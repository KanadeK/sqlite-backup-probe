# v0.1.0

Initial release of an independent verification drill for standalone SQLite backups.

- Restore raw/gzip artifacts into temporary scratch storage without SQLite opening
  the original file, then run integrity and separate foreign-key checks.
- Optional strict JSON contracts check required tables, columns, row-count bounds,
  user_version and application_id. No arbitrary contract SQL is executed.
- Source SHA-256 checking, live-sidecar refusal, bounded decompression, cooperative
  deadlines, structured issue codes and cleanup on ordinary failures.
- Synthetic backup-API demo, English/Chinese documentation, 22 tests and read-only CI.

Python 3.11+; zero runtime dependencies. Default source/restored limit: 512 MiB;
default cooperative deadline: 30 seconds. This is not a backup producer, live
restore tool, SQLCipher/extension runner or proof of recency/business correctness.
Use a closed standalone snapshot and keep the interpreter's SQLite patched.

See VALIDATION.md and the Actions matrix for validation details.
