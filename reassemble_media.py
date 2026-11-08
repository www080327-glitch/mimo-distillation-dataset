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


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("--asset", action="append", help="A logical asset name; omit to check all")
    p.add_argument("--out", type=Path, help="Rebuild split files into this directory; default only verifies")
    args = p.parse_args()
    catalog = {name(x["name"]): x for x in json.loads(args.manifest.read_text())["files"]}
    for asset in args.asset or catalog:
        entry = catalog[asset]
        if args.out and entry.get("parts"):
            args.out.mkdir(parents=True, exist_ok=True)
            result = args.out / asset
            if result.exists():
                raise FileExistsError(result)
            with tempfile.NamedTemporaryFile(dir=args.out, delete=False) as f:
                work = Path(f.name)
                try:
                    verify(entry, args.manifest.parent, f)
                    f.flush()
                    work.rename(result)
                finally:
                    work.unlink(missing_ok=True)
        else:
            verify(entry, args.manifest.parent, None)
        print(f"Verified: {asset}")


if __name__ == "__main__":
    main()
