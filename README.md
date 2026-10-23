# sqlite-restore-drill

[中文说明](README.zh-CN.md) · [Design](DESIGN.md) · [Security](SECURITY.md)

Validate an **existing standalone SQLite backup** by restoring its bytes into a
temporary workspace, checking integrity and foreign keys, and testing an optional
application contract. Your production database is never opened by SQLite, and
the backup artifact is read only. Python 3.11+, no runtime dependencies or servers.

A checksum detects changed bytes, not a missing application table. SQLite's
`integrity_check` does not detect foreign-key violations. This tool combines the
checks into a repeatable, local drill with machine-readable results. It works with
backup files produced by other tools; it does not require access to the live database.

## Install and run

```sh
git clone https://github.com/KanadeK/sqlite-restore-drill.git
cd sqlite-restore-drill
python -m venv .venv
# Activate: source .venv/bin/activate
# Windows PowerShell: .venv/Scripts/Activate.ps1
python -m pip install .
python examples/demo.py
```

The demo creates a synthetic database, makes a consistent backup with SQLite's
backup API, compresses it, checks it against a contract, demonstrates a failed
expectation, and cleans up. It fails explicitly if any expected outcome is wrong.

```sh
sqlite-restore-drill backups/app.sqlite
sqlite-restore-drill backups/app.sqlite.gz --contract expectations.json
sqlite-restore-drill backups/app.sqlite --max-bytes 1073741824 --timeout-seconds 60
```

`python -m sqlite_restore_drill` is equivalent. JSON is written to stdout. No row
payloads, SQL error text or absolute input paths are included. Counts, schema names
from your contract and integer version fields may still be sensitive.

## Application expectations

Save this as `expectations.json` and adjust it to your actual backup:

```json
{
  "schema_version": 1,
  "user_version": 7,
  "application_id": 42,
  "tables": {
    "users": {
      "columns": ["id", "email"],
      "min_rows": 1,
      "max_rows": 1000000
    }
  }
}
```

Only `schema_version` is required. The other keys are optional; `tables` maps
required user-table names to optional column lists and inclusive row bounds.
Extra tables and columns are permitted. Set the same minimum and maximum for an
exact row count. Views are not counted as tables. Column checks include generated
columns. Names are matched exactly and safely quoted; contracts cannot contain SQL.
Unknown fields, duplicate JSON keys, booleans in numeric fields and contradictory
bounds are rejected. Contracts are limited to 1 MiB, 1,000 tables and 2,000 listed
columns per table. Integer version fields support 0–2,147,483,647.

Without a contract, `ok: true` means the structural and foreign-key checks passed;
it makes **no assertion about expected content**. A valid empty database can pass.

## What happens during a drill

1. Refuse symlinks and artifacts with `-wal`, `-shm` or `-journal` sidecars.
2. Hash the original artifact. If supplied, compare `--expected-sha256 HEX` with
   this hash (for gzip, the hash is of the compressed file).
3. Copy or decompress into a private temporary directory. Gzip is detected by
   magic bytes, independent of filename. Enforce source and restored size limits.
4. Open the scratch file with `mode=ro&immutable=1`, query-only and trusted-schema
   protections. Run full `integrity_check`, then the separate `foreign_key_check`.
5. Check the contract. Close the SQLite connection explicitly and remove scratch
   files, including when validation fails. Nothing is restored over your application.

Example result fields include `ok`, `sha256`, `source_bytes`, `restored_bytes`,
`compression`, `integrity_check`, `foreign_key_check`, `table_count`,
`contract_checked`, `tables_checked` and `issues`. Some fields are absent when an
earlier stage fails. Issue codes include `live_sidecars_present`,
`invalid_sqlite_header`, `sqlite_error`, `foreign_key_violations`, `missing_table`,
`missing_columns`, `row_count_out_of_range`, `source_hash_mismatch` and `timeout`.
Foreign-key diagnostics report at most 101 observed violations as a lower bound,
not the actual rows or their values. Structural errors stop application checks.

| Exit | Meaning |
|---:|---|
| 0 | Requested checks passed |
| 1 | Backup failed validation, a resource limit, or the cooperative deadline |
| 2 | Invalid contract/options, unavailable input, permissions or other I/O error |
| 130 | Interrupted |

## Safety boundaries and current limits

- Feed it a **closed, standalone backup**, created using SQLite's backup API,
  `VACUUM INTO`, or an equivalent consistent snapshot. Copying a live main file
  can lose uncheckpointed data. Refusal of sidecars is conservative: it includes
  empty sidecars. If a required WAL was already lost, this tool cannot detect the
  missing committed data merely from the remaining main file.
- Default byte limit is 512 MiB, applied independently to original and restored
  file sizes. Copying/hashing uses 64 KiB chunks. Temporary disk space up to the
  restored size is required. Use `--temp-dir EXISTING_DIRECTORY` to select its parent.
  Decoded SQLite schema and query memory are not hard bounded by this byte limit.
- Default deadline is 30 seconds. Python loops and SQLite's progress handler
  enforce it cooperatively; this is not a process sandbox or hard I/O timeout.
- Stat and sidecar checks detect ordinary concurrent changes, not adversarial
  same-stat rewrites. Do not modify an input while checking it. Gzip CRC/truncation
  is checked, including concatenated members; no zip/tar/SQL dump support.
- No backup creation, scheduling, pruning, live database access, SQLCipher,
  custom extensions or application startup tests. Virtual tables/custom SQL
  functions may fail if the interpreter lacks the necessary built-in support.
- Success does not prove recency, business correctness, completeness relative to
  production, authenticity, or a complete disaster-recovery plan. Native SQLite
  still parses the file: use an up-to-date interpreter and an OS sandbox for
  deliberately hostile database files. Input artifacts never execute Python code.
- Reports are not signed. Temporary storage inherits OS protections; abrupt
  process termination can leave a scratch directory for later manual cleanup.

See [SQLite's integrity-check documentation](https://www.sqlite.org/pragma.html#pragma_integrity_check)
and [backup API guidance](https://www.sqlite.org/backup.html). For replication and
backup production, consider [Litestream](https://litestream.io/); this project
provides a small independent verification step.

## Development and cleanup

```sh
python -m pip install -r requirements-dev.txt -e .
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m build
```

Read-only CI tests Python 3.11/3.14 on Linux, macOS and Windows.
[VALIDATION.md](VALIDATION.md) records local release checks; Actions records remote
results. Uninstall with `python -m pip uninstall sqlite-restore-drill`, then remove
the virtual environment if desired. No global configuration or persistent output
is created by the tool. Do not delete your backup as part of uninstalling.

MIT license. [Contributing](CONTRIBUTING.md) · [Third-party inventory](THIRD_PARTY.md).
