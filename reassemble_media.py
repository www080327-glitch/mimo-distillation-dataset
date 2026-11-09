#!/usr/bin/env python3
"""Verify and optionally rebuild split GitHub Release assets; does not extract tar files."""
import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path


def name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError("Invalid asset name")
    return value


def verify(entry, folder, target):
    total = hashlib.sha256()
    count = 0
    for part in entry.get("parts") or [entry]:
        digest = hashlib.sha256()
        n = 0
        with (folder / name(part["name"])).open("rb") as src:
            for block in iter(lambda: src.read(1 << 20), b""):
                digest.update(block)
                total.update(block)
                n += len(block)
                if target is not None:
                    target.write(block)
        if digest.hexdigest() != part["sha256"] or n != part["bytes"]:
            raise ValueError(f"Bad chunk: {name(part['name'])}")
        count += n
    if total.hexdigest() != entry["sha256"] or count != entry["bytes"]:
        raise ValueError(f"Bad logical asset: {name(entry['name'])}")


def rebuild(entry, folder, out):
    asset = entry["name"]
    if not out or not entry.get("parts"):
        verify(entry, folder, None)
        return
    result = out / asset
    if result.exists():
        # Recheck a previous run's output without needing to keep its chunks.
        verify({**entry, "parts": []}, out, None)
        return
    out.mkdir(parents=True, exist_ok=True)
    work = None
    try:
        with tempfile.NamedTemporaryFile(dir=out, delete=False) as f:
            work = Path(f.name)
            verify(entry, folder, f)
        work.rename(result)
    finally:
        if work is not None:
            work.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("--asset", action="append", help="A logical asset name; omit to check all")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--out", type=Path, help="Rebuild split files into this directory; default only verifies")
    mode.add_argument("--list-parts", action="store_true", help="List exact download names without reading assets")
    args = p.parse_args()
    catalog = {name(x["name"]): x for x in json.loads(args.manifest.read_text())["files"]}
    for asset in args.asset or catalog:
        if asset not in catalog:
            p.error(f"Unknown logical asset: {asset}")
        entry = catalog[asset]
        if args.list_parts:
            for part in entry.get("parts") or [entry]:
                print(name(part["name"]))
            continue
        try:
            rebuild(entry, args.manifest.parent, args.out)
        except FileNotFoundError as exc:
            missing = [part["name"] for part in entry.get("parts") or [entry]
                       if not (args.manifest.parent / name(part["name"])).is_file()]
            if not missing:
                raise
            raise FileNotFoundError(f"{asset}: missing download(s): {', '.join(missing)}") from exc
        print(f"Verified: {asset}")


if __name__ == "__main__":
    main()
