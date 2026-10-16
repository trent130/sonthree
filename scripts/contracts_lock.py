"""Create or verify the pinned SHA-256 inventory for the frozen contracts tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
LOCK = ROOT / "contracts.lock"
IGNORED_DIRS = {".venv", "venv", "__pycache__", ".pytest_cache", "htmlcov"}
IGNORED_NAMES = {".DS_Store", ".coverage"}


def contract_hashes() -> dict[str, str]:
    inventory = {}
    for current, dirs, files in os.walk(CONTRACTS):
        dirs[:] = sorted(name for name in dirs if name not in IGNORED_DIRS)
        for filename in sorted(files):
            if filename in IGNORED_NAMES or filename.endswith((".pyc", ".pyo")):
                continue
            path = Path(current) / filename
            relative = path.relative_to(ROOT).as_posix()
            inventory[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args()
    actual = contract_hashes()
    if args.write:
        LOCK.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote {len(actual)} contract checksums to {LOCK.relative_to(ROOT)}")
        return 0
    try:
        expected = json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read contracts.lock: {exc}", file=sys.stderr)
        return 1
    missing = sorted(expected.keys() - actual.keys())
    added = sorted(actual.keys() - expected.keys())
    changed = sorted(
        path for path in expected.keys() & actual.keys() if expected[path] != actual[path]
    )
    if missing or added or changed:
        for label, paths in (("missing", missing), ("unlocked", added), ("changed", changed)):
            for path in paths:
                print(f"{label}: {path}", file=sys.stderr)
        return 1
    print(f"Verified {len(expected)} frozen contract files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
