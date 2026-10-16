from __future__ import annotations

import argparse
import json
import sys

from meshapi_contract.diff import public_subset
from meshapi_contract.surface import (
    SurfaceVersionError,
    diff_surface,
    expected_surface,
    load_actual,
)

# 2 is left to argparse usage errors.
EXIT_OK, EXIT_DRIFT, EXIT_VERSION, EXIT_ERROR = 0, 1, 3, 4


def _load_allow(path: str) -> set[str]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    allow = data.get("allow") if isinstance(data, dict) else None
    if not isinstance(allow, list) or not all(isinstance(r, str) for r in allow):
        raise ValueError("--baseline must be a JSON object with an 'allow' list of strings")
    return set(allow)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meshapi_contract.gate")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--spec-version", required=True)
    parser.add_argument("--baseline")
    args = parser.parse_args(argv)

    try:
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        with open(args.actual, encoding="utf-8") as fh:
            envelope = json.load(fh)
        if not isinstance(spec, dict) or not isinstance(envelope, dict):
            raise ValueError("--spec and --actual must each be a JSON object")
        if "schema_version" not in envelope:
            raise ValueError("--actual is missing schema_version")
        # public_subset is idempotent, so a full spec and a published subset both work.
        expected = expected_surface(public_subset(spec))
        if len(expected.model_fields) + len(expected.params) == 0:
            raise ValueError("spec produced an empty surface (wrong or empty --spec?)")
        actual = load_actual(args.actual, args.spec_version)
        allow = _load_allow(args.baseline) if args.baseline else None
    except SurfaceVersionError as exc:
        print(f"contract-check: {exc}")
        return EXIT_VERSION
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        print(f"contract-check: error: {exc}")
        return EXIT_ERROR

    rows = diff_surface(expected, actual)
    total = len(expected.model_fields) + len(expected.params)
    if allow is None:
        if not rows:
            print(f"contract-check: OK ({total} surface members)")
            return EXIT_OK
        print(f"contract-check: DRIFT — SDK is missing {len(rows)} spec surface member(s):")
        for row in rows:
            print(row)
        return EXIT_DRIFT

    stale = sorted(allow - set(rows))
    if stale:
        print(
            f"contract-check: note: {len(stale)} stale baseline entries (no longer missing):",
            file=sys.stderr,
        )
        for row in stale:
            print(row, file=sys.stderr)
    effective = [r for r in rows if r not in allow]
    if not effective:
        print(f"contract-check: OK ({total} members; {len(rows)} baselined)")
        return EXIT_OK
    print(f"contract-check: DRIFT — {len(effective)} new member(s) beyond baseline:")
    for row in effective:
        print(row)
    return EXIT_DRIFT


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
