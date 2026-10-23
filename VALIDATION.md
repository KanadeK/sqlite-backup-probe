# Release validation

Local release checks use Windows and CPython 3.13.16:

- 22 unit, integration, boundary and failure-injection tests pass, including a real
  open WAL database, malformed/truncated gzip, concatenated gzip members, foreign
  keys that pass integrity_check, unusual quoted identifiers and generated columns.
- Raw and gzip backup drills preserve input bytes. Successful, failed, timed-out
  and source-change cases leave the selected scratch parent empty.
- Ruff 0.17.2 lint/security rules and formatting checks pass.
- The release gate builds an sdist and a wheel from it, installs the wheel with
  `--no-index --no-deps` into a fresh environment, then reruns all tests, the demo,
  the console entry point and `pip check`. Publication requires every step to pass.
- No third-party runtime dependency or vendored implementation is present.

Review improvements made before publication: explicitly close SQLite connections
before scratch cleanup, use bound column-discovery parameters, quote/count only
known table identifiers, reject boolean numeric expectations, cap foreign-key
diagnostics at 101 observations, and bound gzip expansion independently of its
compressed size. Native SQLite and cooperative timeout limitations are explicit.

The publishing gate also scans tracked files for secret/private-key patterns and
machine-specific paths, audits complete Git history, checks remote SHA and linked
identities, and requires successful CI and a sole API-listed KanadeK contributor.
Actual remote test results are recorded on the repository's Actions page.
