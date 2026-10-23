# Contributing

Report reproducible bugs with the command, Python version, and a small synthetic
input. Do not attach private exports, databases, wheels or credentials.

```sh
python -m venv .venv
# Activate it (Windows PowerShell: .venv/Scripts/Activate.ps1).
python -m pip install -r requirements-dev.txt -e .
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m build
```

Changes should include focused regression tests and accurate limits in the
documentation. Python 3.11+ is supported; CI tests Linux, macOS and Windows.
No network service is required at runtime. Runtime dependencies are intentionally
empty. Keep CI read-only; automated code commits and dependency bots are disabled.
This repository currently accepts bug reports and design suggestions through
Issues. External code pull requests are not being accepted during the initial
single-maintainer release phase.
