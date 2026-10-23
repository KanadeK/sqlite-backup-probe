"""Create a consistent synthetic backup and exercise a successful and failed drill."""

import gzip
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from sqlite_restore_drill.core import drill

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    source_path, backup_path = root / "live.sqlite", root / "backup.sqlite"
    with closing(sqlite3.connect(source_path)) as source:
        source.executescript(
            "PRAGMA user_version=7; CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT);"
            "INSERT INTO users VALUES(1,'example@example.invalid');"
        )
        with closing(sqlite3.connect(backup_path)) as backup:
            source.backup(backup)
    compressed = root / "backup.sqlite.gz"
    compressed.write_bytes(gzip.compress(backup_path.read_bytes()))
    contract = {
        "schema_version": 1,
        "user_version": 7,
        "tables": {"users": {"columns": ["id", "email"], "min_rows": 1}},
    }
    passed = drill(compressed, contract=contract)
    failed = drill(compressed, contract={"schema_version": 1, "tables": {"missing": {}}})
    if not passed["ok"] or failed["ok"] or not backup_path.exists():
        raise RuntimeError("unexpected drill result")
    print(
        json.dumps(
            {
                "valid_backup_passed": passed["ok"],
                "missing_table_rejected": not failed["ok"],
                "original_retained": True,
            }
        )
    )
