# Design and acceptance

Audience: maintainers who already have a SQLite backup produced by another system.
The core workflow is artifact → bounded scratch copy → structural/FK checks →
declarative application expectations → JSON result → scratch cleanup.

SQLite never opens the original artifact. The file is hashed and copied with normal
binary I/O, then the scratch file is opened immutable/read-only with trusted-schema
off and query-only on. Opening immutable is appropriate only because the scratch
file is private and stable; using this flag on a live production DB would be unsafe.
The connection is explicitly closed before removing the temporary directory.

The input and restored byte limits are independent. A monotonic deadline is checked
in read loops and the SQLite VM progress callback. It cannot preempt arbitrary OS
I/O. Input stat/sidecar checks are best-effort consistency detection, not a snapshot.
No arbitrary SQL, extension loading, shell commands or network access exists in the
runtime. Identifier-based COUNT queries quote double quotes and only use names found
in the inspected database. PRAGMA column discovery uses a bound parameter.

Contracts deliberately check only required tables, column presence, inclusive row
bounds, user_version and application_id. They do not infer invariants, compare live
data or decide whether a backup is recent enough. The first physical integrity
failure stops further SQL. Native SQLite remains a trust boundary.

Acceptance includes raw/gzip end-to-end cases, real live-WAL refusal, FK violations
that pass integrity_check, malformed contracts, unusual identifiers, missing schema,
bounded decompression, truncated backups, deadlines, unchanged inputs and cleanup.
Examples use synthetic databases built with SQLite's backup API.

References: [SQLite PRAGMA](https://www.sqlite.org/pragma.html),
[immutable URI option](https://www.sqlite.org/uri.html#uriimmutable),
[Python sqlite3](https://docs.python.org/3/library/sqlite3.html).
Alternatives: [Litestream](https://litestream.io/) for backup replication;
[db-backup-verifier](https://github.com/ciuramichal2000/db-backup-verifier) for a small
backup/checksum/row-count example. No implementation was copied from these projects.
