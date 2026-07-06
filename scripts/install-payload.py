#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "contract" / "dudley-payload.v1.json"


def load_contract(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"contract not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid contract JSON in {path}: {exc}") from None


def profile_selectors(contract: dict, profile: str) -> set[str]:
    profiles = contract.get("profiles", {})
    try:
        selectors = profiles[profile]
    except KeyError:
        available = ", ".join(sorted(profiles))
        raise SystemExit(f"unknown profile {profile!r}; expected one of: {available}") from None
    return set(selectors)


def selected_entries(contract: dict, profile: str) -> list[dict]:
    selectors = profile_selectors(contract, profile)
    selected = []
    for entry in contract.get("files", []):
        entry_selectors = set(entry.get("selectors", []))
        if entry_selectors & selectors:
            selected.append(entry)
    return selected


def install_entry(entry: dict, dest: Path) -> None:
    source = ROOT / entry["source"]
    if not source.is_file():
        raise SystemExit(f"payload source missing: {entry['source']}")

    target = dest / entry["target"].lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install dsb-common Dudley payload by profile.")
    parser.add_argument("--profile", required=True, choices=["bluefin", "ubuntu"])
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    contract = load_contract(args.contract)
    entries = selected_entries(contract, args.profile)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "profile": args.profile,
                    "selected_count": len(entries),
                    "files": [
                        {
                            "source": entry["source"],
                            "target": entry["target"],
                            "selectors": entry["selectors"],
                        }
                        for entry in entries
                    ],
                },
                indent=2,
            )
        )
        return 0

    for entry in entries:
        install_entry(entry, args.dest)

    return 0


if __name__ == "__main__":
    sys.exit(main())
