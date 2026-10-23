# Third-party inventory

No third-party runtime Python packages, copied source code, binary assets or
vendored resources are distributed. Python's standard library is provided by
the user's interpreter (PSF license; bundled SQLite is public domain).

Development/build tools are not bundled: Ruff 0.17.2 (MIT), build 1.6.1 (MIT),
setuptools 84.2.1 (MIT). Build may install their dependencies under their own
licenses: packaging (Apache-2.0 OR BSD-2-Clause), pyproject-hooks (MIT), and
colorama on Windows (BSD-3-Clause). GitHub Actions checkout/setup-python are MIT
and pinned by commit. These permissive licenses are compatible with this MIT
project. Specifications and competitor documentation are linked in DESIGN.md;
no competitor implementation or test fixture was copied.
