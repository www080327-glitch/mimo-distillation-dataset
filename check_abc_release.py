#!/usr/bin/env python3
"""Check local public release pins and the matching embedded manifest without downloading."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

from abc_release import release_version
from download_abc_bases import embedded_manifest
from download_release import checksum, digest
from reassemble_media import name


def check(archive, manifest, sums, asset_name=None):
    official_name = archive.name if asset_name is None else name(asset_name)
    archive_pin = checksum(sums, official_name)
    manifest_pin = checksum(sums, "MANIFEST.json")
    if digest(archive) != archive_pin:
        raise ValueError("Archive SHA-256 differs from the release checksums")
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest_pin:
        raise ValueError("Standalone MANIFEST.json SHA-256 differs from the release checksums")
    with archive.open("rb") as source:
        if embedded_manifest(source) != raw:
            raise ValueError("Standalone and embedded MANIFEST.json differ")
    document = json.loads(raw)
    version = release_version(document)
    if "sample_of" in document:
        raise ValueError("A sample is not a production release")
    return {"version": version, "declared_episodes": document["episodes"], "archive_sha256": archive_pin,
            "manifest_sha256": manifest_pin, "verified": True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("manifest", type=Path)
    p.add_argument("sha256sums", type=Path)
    p.add_argument("--asset-name", help="Original release filename if the local archive was renamed")
    args = p.parse_args()
    try:
        report = check(args.archive, args.manifest, args.sha256sums, args.asset_name)
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError, EOFError) as exc:
        p.exit(1, f"Release check failed: {exc}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
