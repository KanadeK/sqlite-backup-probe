"""Read-only inspection of a scratch copy of a standalone SQLite backup."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import time
import zlib
from contextlib import closing
from pathlib import Path

DEFAULT_MAX_BYTES = 512 * 1024 * 1024
CHUNK = 64 * 1024


class ContractError(ValueError):
    """A malformed or unsupported declarative contract."""


class _Rejected(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate contract key")
        result[key] = value
    return result


def _name(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 255
        and all(ord(c) >= 32 for c in value)
        and "\x7f" not in value
    )


def validate_contract(contract: object) -> dict:
    if not isinstance(contract, dict) or set(contract) - {
        "schema_version",
        "tables",
        "user_version",
        "application_id",
    }:
        raise ContractError("unknown contract fields or invalid object")
    if type(contract.get("schema_version")) is not int or contract["schema_version"] != 1:
        raise ContractError("schema_version must be 1")
    for key in ("user_version", "application_id"):
        if key in contract and (
            type(contract[key]) is not int or not 0 <= contract[key] <= 2147483647
        ):
            raise ContractError("version and application id must be nonnegative 32-bit integers")
    tables = contract.get("tables", {})
    if not isinstance(tables, dict) or len(tables) > 1000:
        raise ContractError("tables must be an object with at most 1000 entries")
    for table, spec in tables.items():
        if (
            not _name(table)
            or not isinstance(spec, dict)
            or set(spec) - {"columns", "min_rows", "max_rows"}
        ):
            raise ContractError("invalid table specification")
        columns = spec.get("columns", [])
        if (
            not isinstance(columns, list)
            or len(columns) > 2000
            or not all(_name(c) for c in columns)
            or len(set(columns)) != len(columns)
        ):
            raise ContractError("columns must be unique names")
        for key in ("min_rows", "max_rows"):
            if key in spec and (
                type(spec[key]) is not int or not 0 <= spec[key] <= 9223372036854775807
            ):
                raise ContractError("row bounds must be nonnegative integers")
        if spec.get("min_rows", 0) > spec.get("max_rows", 9223372036854775807):
            raise ContractError("minimum row count exceeds maximum")
    return contract


def load_contract(path: str | Path) -> dict:
    with Path(path).open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ContractError("contract exceeds 1 MiB")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        return validate_contract(value)
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise ContractError("invalid contract") from error


def _deadline(deadline):
    if time.monotonic() >= deadline:
        raise _Rejected("timeout")


def _sidecars(path):
    return any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


def _stat(stream):
    s = os.fstat(stream.fileno())
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns


def _copy(path, destination, max_bytes, deadline, report, expected_sha256):
    with path.open("rb") as source:
        before = _stat(source)
        if before[2] > max_bytes:
            raise _Rejected("source_size_limit")
        digest = hashlib.sha256()
        source_bytes = 0
        while chunk := source.read(CHUNK):
            _deadline(deadline)
            source_bytes += len(chunk)
            if source_bytes > max_bytes:
                raise _Rejected("source_size_limit")
            digest.update(chunk)
        report["source_bytes"] = source_bytes
        report["sha256"] = digest.hexdigest()
        if expected_sha256 and digest.hexdigest() != expected_sha256.lower():
            raise _Rejected("source_hash_mismatch")
        source.seek(0)
        compressed = source.read(2) == b"\x1f\x8b"
        source.seek(0)
        report["compression"] = "gzip" if compressed else "none"
        restored = 0
        with destination.open("xb") as output:
            reader = gzip.GzipFile(fileobj=source, mode="rb") if compressed else source
            try:
                while chunk := reader.read(CHUNK):
                    _deadline(deadline)
                    restored += len(chunk)
                    if restored > max_bytes:
                        raise _Rejected("restored_size_limit")
                    output.write(chunk)
            except (EOFError, gzip.BadGzipFile, zlib.error) as error:
                raise _Rejected("invalid_gzip") from error
            finally:
                if compressed:
                    reader.close()
        report["restored_bytes"] = restored
        if before != _stat(source) or _sidecars(path):
            raise _Rejected("source_changed_or_live")
    with destination.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise _Rejected("invalid_sqlite_header")


def _quoted(name):
    # All names are SQL identifiers, never expressions. Double embedded quotes.
    return '"' + name.replace('"', '""') + '"'


def _inspect(path, contract, deadline, report):
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as connection:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 64 * 1024 * 1024)
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        issues = report["issues"]
        _deadline(deadline)
        integrity = connection.execute("PRAGMA integrity_check(100)").fetchmany(101)
        report["integrity_check"] = integrity == [("ok",)]
        if not report["integrity_check"]:
            issues.append({"code": "integrity_failed"})
            return
        violations = connection.execute("PRAGMA foreign_key_check").fetchmany(101)
        report["foreign_key_check"] = not violations
        if violations:
            issues.append({"code": "foreign_key_violations", "count_at_least": len(violations)})
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' "
                "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
            )
        }
        report["table_count"] = len(tables)
        report["user_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
        report["application_id"] = connection.execute("PRAGMA application_id").fetchone()[0]
        report["contract_checked"] = contract is not None
        if contract is None:
            return
        for field in ("user_version", "application_id"):
            if field in contract and report[field] != contract[field]:
                issues.append(
                    {
                        "code": field + "_mismatch",
                        "expected": contract[field],
                        "actual": report[field],
                    }
                )
        checked = []
        for table, spec in contract.get("tables", {}).items():
            _deadline(deadline)
            if table not in tables:
                issues.append({"code": "missing_table", "table": table})
                continue
            actual_columns = {
                row[0]
                for row in connection.execute("SELECT name FROM pragma_table_xinfo(?)", (table,))
            }
            missing = [c for c in spec.get("columns", []) if c not in actual_columns]
            if missing:
                issues.append({"code": "missing_columns", "table": table, "columns": missing})
            entry = {"table": table}
            if "min_rows" in spec or "max_rows" in spec:
                query = "SELECT COUNT(*) FROM " + _quoted(table)  # noqa: S608 -- quoted identifier, checked against actual table names
                count = connection.execute(query).fetchone()[0]
                entry["rows"] = count
                if count < spec.get("min_rows", 0) or count > spec.get(
                    "max_rows", 9223372036854775807
                ):
                    issues.append(
                        {"code": "row_count_out_of_range", "table": table, "actual": count}
                    )
            checked.append(entry)
        report["tables_checked"] = checked


def drill(
    path: str | Path,
    *,
    contract: dict | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout_seconds: float = 30,
    expected_sha256: str | None = None,
    temp_dir: str | Path | None = None,
) -> dict:
    """Restore an existing raw/gzip backup to scratch and check it without production access."""
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be positive and finite")
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str)
        or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256)
    ):
        raise ValueError("expected_sha256 must be 64 hex characters")
    if contract is not None:
        contract = validate_contract(contract)
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("input must be a regular file, not a symlink")
    deadline = time.monotonic() + timeout_seconds
    report = {
        "format_version": 1,
        "ok": False,
        "sqlite_version": sqlite3.sqlite_version,
        "issues": [],
    }
    try:
        if _sidecars(path):
            raise _Rejected("live_sidecars_present")
        with tempfile.TemporaryDirectory(prefix="sqlite-restore-drill-", dir=temp_dir) as workspace:
            restored = Path(workspace) / "restored.sqlite"
            _copy(path, restored, max_bytes, deadline, report, expected_sha256)
            _inspect(restored, contract, deadline, report)
            _deadline(deadline)
        report["ok"] = not report["issues"]
    except _Rejected as error:
        report["issues"].append({"code": str(error)})
    except sqlite3.Error:
        code = "timeout" if time.monotonic() >= deadline else "sqlite_error"
        report["issues"].append({"code": code})
    return report
