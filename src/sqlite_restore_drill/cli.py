"""Run an isolated validation drill against an existing SQLite backup artifact."""

import argparse
import json
import sys

from . import __version__
from .core import DEFAULT_MAX_BYTES, ContractError, drill, load_contract


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("backup", help="standalone raw or gzip SQLite backup file")
    p.add_argument("--contract", help="optional declarative JSON expectations")
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    p.add_argument("--timeout-seconds", type=float, default=30)
    p.add_argument("--expected-sha256", help="expected hash of the original artifact")
    p.add_argument("--temp-dir", help="existing parent for the private temporary workspace")
    args = p.parse_args(argv)
    try:
        contract = load_contract(args.contract) if args.contract else None
        report = drill(
            args.backup,
            contract=contract,
            max_bytes=args.max_bytes,
            timeout_seconds=args.timeout_seconds,
            expected_sha256=args.expected_sha256,
            temp_dir=args.temp_dir,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1
    except ContractError:
        print('{"error":"invalid_contract"}', file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print(
            '{"error":"invalid_input_or_options","hint":"Check the file, limits and permissions."}',
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print('{"error":"interrupted"}', file=sys.stderr)
        return 130
