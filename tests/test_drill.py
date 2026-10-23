import gzip
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from sqlite_backup_probe.core import ContractError, drill, load_contract, validate_contract


class DrillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / "backup # ü.sqlite"
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript("""
                PRAGMA user_version=7;
                PRAGMA application_id=42;
                CREATE TABLE parent(id INTEGER PRIMARY KEY, secret TEXT);
                CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id));
                INSERT INTO parent VALUES(1,'PRIVATE_SENTINEL_DO_NOT_LOG');
                INSERT INTO child VALUES(1,1);
            """)
        self.contract = {
            "schema_version": 1,
            "user_version": 7,
            "application_id": 42,
            "tables": {
                "parent": {"columns": ["id", "secret"], "min_rows": 1, "max_rows": 1},
                "child": {"columns": ["parent_id"], "min_rows": 1},
            },
        }

    def codes(self, report):
        return {i["code"] for i in report["issues"]}

    def test_raw_backup_end_to_end_unchanged(self):
        before = self.db.read_bytes()
        files = set(self.root.iterdir())
        report = drill(self.db, contract=self.contract, temp_dir=self.scratch)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["integrity_check"])
        self.assertTrue(report["foreign_key_check"])
        self.assertEqual(report["table_count"], 2)
        self.assertEqual(report["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(set(self.root.iterdir()), files)
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report))

    def test_gzip_magic_detected_without_suffix(self):
        compressed = self.root / "artifact"
        compressed.write_bytes(gzip.compress(self.db.read_bytes()))
        report = drill(compressed, contract=self.contract)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["compression"], "gzip")
        self.assertEqual(report["restored_bytes"], self.db.stat().st_size)
        self.assertEqual(report["sha256"], hashlib.sha256(compressed.read_bytes()).hexdigest())

    def test_foreign_keys_checked_separately(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("INSERT INTO child VALUES(2,999)")
        report = drill(self.db)
        self.assertTrue(report["integrity_check"])
        self.assertIn("foreign_key_violations", self.codes(report))
        self.assertFalse(report["ok"])

    def test_wrong_application_contract(self):
        contract = {
            "schema_version": 1,
            "user_version": 8,
            "application_id": 99,
            "tables": {"parent": {"columns": ["missing"], "min_rows": 10}, "absent": {}},
        }
        self.assertEqual(
            self.codes(drill(self.db, contract=contract)),
            {
                "user_version_mismatch",
                "application_id_mismatch",
                "missing_columns",
                "row_count_out_of_range",
                "missing_table",
            },
        )

    def test_maximum_rows(self):
        report = drill(
            self.db, contract={"schema_version": 1, "tables": {"parent": {"max_rows": 0}}}
        )
        self.assertIn("row_count_out_of_range", self.codes(report))

    def test_table_identifier_is_not_executable_sql(self):
        name = 'a"; DROP TABLE parent; --'
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute('CREATE TABLE "a""; DROP TABLE parent; --"(id INTEGER)')
        report = drill(self.db, contract={"schema_version": 1, "tables": {name: {"min_rows": 0}}})
        self.assertTrue(report["ok"], report)
        self.assertTrue(drill(self.db, contract=self.contract)["ok"])

    def test_generated_columns_are_visible_to_contract(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute(
                "CREATE TABLE generated(a INTEGER, b INTEGER GENERATED ALWAYS AS (a+1))"
            )
        report = drill(
            self.db, contract={"schema_version": 1, "tables": {"generated": {"columns": ["b"]}}}
        )
        self.assertTrue(report["ok"], report)

    def test_live_sidecars_are_refused_and_untouched(self):
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(self.db) + suffix)
            sidecar.write_bytes(b"sentinel")
            before = self.db.read_bytes()
            self.assertIn("live_sidecars_present", self.codes(drill(self.db)))
            self.assertEqual(self.db.read_bytes(), before)
            self.assertEqual(sidecar.read_bytes(), b"sentinel")
            sidecar.unlink()

    def test_actual_live_wal_is_not_ignored(self):
        connection = sqlite3.connect(self.db)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO parent VALUES(2,'another')")
        connection.commit()
        self.assertIn("live_sidecars_present", self.codes(drill(self.db)))
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM parent").fetchone()[0], 2)

    def test_invalid_and_truncated_databases(self):
        for data in (b"", b"not a database", self.db.read_bytes()[:100]):
            target = self.root / "bad.sqlite"
            target.write_bytes(data)
            report = drill(target, temp_dir=self.scratch)
            self.assertFalse(report["ok"])
            self.assertEqual(list(self.scratch.iterdir()), [])

    def test_gzip_corruption_and_truncation(self):
        raw = gzip.compress(self.db.read_bytes())
        for payload in (raw[:-6], raw[:-1] + bytes([raw[-1] ^ 1])):
            target = self.root / "bad.gz"
            target.write_bytes(payload)
            self.assertIn("invalid_gzip", self.codes(drill(target)))

    def test_size_limits_raw_and_decompressed(self):
        self.assertIn("source_size_limit", self.codes(drill(self.db, max_bytes=10)))
        target = self.root / "compressed.gz"
        target.write_bytes(gzip.compress(self.db.read_bytes()))
        report = drill(target, max_bytes=1024, temp_dir=self.scratch)
        self.assertIn("restored_size_limit", self.codes(report))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_expected_digest(self):
        good = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.assertTrue(drill(self.db, expected_sha256=good.upper())["ok"])
        self.assertIn("source_hash_mismatch", self.codes(drill(self.db, expected_sha256="0" * 64)))
        with self.assertRaises(ValueError):
            drill(self.db, expected_sha256="not a hash")

    def test_cooperative_timeout_and_cleanup(self):
        with patch("sqlite_backup_probe.core.time.monotonic", side_effect=[0, 2]):
            report = drill(self.db, timeout_seconds=1, temp_dir=self.scratch)
        self.assertIn("timeout", self.codes(report))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_changed_input_fails_and_cleans_scratch(self):
        size = self.db.stat().st_size
        with patch(
            "sqlite_backup_probe.core._stat", side_effect=[(1, 1, size, 1), (1, 1, size, 2)]
        ):
            report = drill(self.db, temp_dir=self.scratch)
        self.assertIn("source_changed_or_live", self.codes(report))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_foreign_key_count_is_a_bounded_lower_limit(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.executemany("INSERT INTO child VALUES(?,999)", [(i,) for i in range(2, 202)])
        report = drill(self.db)
        issue = next(i for i in report["issues"] if i["code"] == "foreign_key_violations")
        self.assertEqual(issue["count_at_least"], 101)
        self.assertNotIn("rowid", json.dumps(report))

    def test_concatenated_gzip_members_restore_one_database(self):
        raw = self.db.read_bytes()
        compressed = self.root / "members.gz"
        middle = len(raw) // 2
        compressed.write_bytes(gzip.compress(raw[:middle]) + gzip.compress(raw[middle:]))
        report = drill(compressed, contract=self.contract)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["restored_bytes"], len(raw))

    def test_invalid_options(self):
        for seconds in (0, -1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                drill(self.db, timeout_seconds=seconds)
        for value in (0, -1, True):
            with self.assertRaises(ValueError):
                drill(self.db, max_bytes=value)
        with self.assertRaises(ValueError):
            drill(self.root)

    def test_contract_fails_closed(self):
        bad = [
            [],
            {},
            {"schema_version": True},
            {"schema_version": 1, "typo": 1},
            {"schema_version": 1, "user_version": True},
            {"schema_version": 1, "tables": {"x": {"min_rows": True}}},
            {"schema_version": 1, "tables": {"x": {"columns": ["a", "a"]}}},
            {"schema_version": 1, "tables": {"x": {"min_rows": 3, "max_rows": 2}}},
            {"schema_version": 1, "tables": {"x\x00": {}}},
        ]
        for document in bad:
            with self.subTest(document=document), self.assertRaises(ContractError):
                validate_contract(document)

    def test_contract_file_duplicates_and_deep_input(self):
        target = self.root / "contract.json"
        for text in (
            '{"schema_version":1,"schema_version":1}',
            "[" * 2000 + "0" + "]" * 2000,
            "{bad",
            "x" * 1048577,
        ):
            target.write_text(text)
            with self.assertRaises(ContractError):
                load_contract(target)

    def test_empty_database_is_structurally_valid_without_contract(self):
        path = self.root / "empty.sqlite"
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("VACUUM")
        report = drill(path)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["table_count"], 0)
        self.assertFalse(report["contract_checked"])

    def test_cli_workflow_exit_codes_and_privacy(self):
        contract = self.root / "contract.json"
        contract.write_text(json.dumps(self.contract))
        command = [sys.executable, "-m", "sqlite_backup_probe", str(self.db)]
        good = subprocess.run(
            command + ["--contract", str(contract)], capture_output=True, check=False
        )
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertNotIn(b"PRIVATE_SENTINEL", good.stdout + good.stderr)
        self.assertNotIn(str(self.db).encode(), good.stdout + good.stderr)
        rejected = subprocess.run(
            command + ["--expected-sha256", "0" * 64], capture_output=True, check=False
        )
        self.assertEqual(rejected.returncode, 1)
        error = subprocess.run(command + ["--max-bytes", "0"], capture_output=True, check=False)
        self.assertEqual(error.returncode, 2)


if __name__ == "__main__":
    unittest.main()
