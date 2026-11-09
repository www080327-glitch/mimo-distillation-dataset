#!/usr/bin/env python3
"""Verify a recovered ZIP against its local step receipt without extracting files."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

from abc_release import ID, project_path, release_version
from download_release import digest

SHA256 = re.compile(r"[0-9a-f]{64}")


def verify(archive, receipt):
    version = release_version({"version": receipt["release"]})
    ident, step, files = receipt["episode_id"], receipt["step"], receipt["files"]
    if not ID.fullmatch(ident) or type(step) is not int or step < 0 or not isinstance(files, dict):
        raise ValueError("Invalid episode, step or file index")
    for name, sha in files.items():
        project_path(name)
        if not SHA256.fullmatch(sha):
            raise ValueError(f"Invalid file SHA-256 for {name}")
    if digest(archive) != receipt["zip_sha256"]:
        raise ValueError("ZIP SHA-256 differs from the supplied receipt")
    with ZipFile(archive) as z:
        entries = z.infolist()
        if (len(entries) != len(files) or {item.filename for item in entries} != files.keys()
                or any(item.is_dir() for item in entries)):
            raise ValueError("ZIP entries differ from the supplied receipt")
        for item in entries:
            actual = hashlib.sha256()
            with z.open(item) as f:
                for block in iter(lambda: f.read(256 * 1024), b""):
                    actual.update(block)
            if actual.hexdigest() != files[item.filename]:
                raise ValueError(f"Incorrect file SHA-256: {item.filename}")
    return {"release": version, "episode_id": ident, "step": step, "files_verified": len(files),
            "scope": "ZIP and members match this receipt; the original source release was not checked."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("zip", type=Path)
    p.add_argument("receipt", type=Path)
    args = p.parse_args()
    try:
        report = verify(args.zip, json.loads(args.receipt.read_text()))
    except (OSError, ValueError, TypeError, KeyError, BadZipFile, RuntimeError) as exc:
        p.exit(1, f"Step receipt check failed: {exc}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
