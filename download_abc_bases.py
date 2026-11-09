#!/usr/bin/env python3
"""Plan or explicitly download the direct bases declared by a public A/B/C manifest."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError

from abc_release import base_filename, release_version, reused_bases, undeclared_reuse
from download_release import REPO, digest, download
from reassemble_media import name


def base_plan(manifest):
    missing = undeclared_reuse(manifest)
    if missing:
        raise ValueError("Reused base archives are not declared: " + ", ".join(missing))
    by_name = {}
    for entry in reused_bases(manifest):
        version, checksum = entry["version"], entry["sha256"]
        if not re.fullmatch(r"v\d+\.\d+\.\d+", version) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("Invalid base version or SHA-256")
        asset = base_filename(entry)
        if not asset:
            raise ValueError(f"Base archive filename is not declared for {version}")
        asset = name(asset)
        request = (version, asset, checksum)
        if asset in by_name and by_name[asset] != request:
            raise ValueError(f"Conflicting base archive entries: {asset}")
        by_name[asset] = request
    return list(by_name.values())


def fetch_base(url, checksum, target):
    try:
        download(url, checksum, target)
    except HTTPError as exc:
        if exc.code not in (502, 503, 504):
            raise
        exc.close()
    else:
        return
    time.sleep(1)
    download(url, checksum, target)


def check(entry, directory, fetch):
    version, asset, checksum = entry
    target = directory / asset
    row = {"version": version, "asset": asset}
    try:
        if target.exists():
            if digest(target) != checksum:
                raise ValueError("Existing file has the wrong SHA-256")
        elif fetch:
            url = f"https://github.com/{REPO}/releases/download/{version}/{asset}?download=1"
            fetch_base(url, checksum, target)
        else:
            return {**row, "status": "missing"}
    except HTTPError as exc:
        return {**row, "status": "failed", "error": f"HTTP {exc.code}"}
    except ValueError as exc:
        return {**row, "status": "failed", "error": str(exc)}
    except (OSError, HTTPException) as exc:
        return {**row, "status": "failed", "error": type(exc).__name__}
    return {**row, "status": "ready"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("directory", type=Path)
    p.add_argument("--fetch", action="store_true", help="Download missing declared bases anonymously")
    args = p.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        version = release_version(manifest)
        plan = base_plan(manifest)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        p.error(str(exc))
    if args.fetch:
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda entry: check(entry, args.directory, True), plan))
    else:
        rows = [check(entry, args.directory, False) for entry in plan]
    print(json.dumps({"release": version, "bases": rows}, indent=2))
    return int(any(row["status"] != "ready" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
