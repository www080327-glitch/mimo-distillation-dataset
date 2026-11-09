#!/usr/bin/env python3
"""Verify a recovered ZIP against its local step receipt without extracting files."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
from zipfile import BadZipFile, ZipFile

from abc_release import ID, project_path, read_spooled, release_version
from download_release import digest
from export_replay import verified_selection
from restore_replay_step import workspace_at

SHA256 = re.compile(r"[0-9a-f]{64}")


def verify(archive, receipt, source=None, bases=(), source_pin=None):
    if source_pin is not None:
        if source is None or not SHA256.fullmatch(source_pin):
            raise ValueError("A lowercase source SHA-256 requires a source archive")
        if digest(source) != source_pin:
            raise ValueError("Source archive SHA-256 differs from the supplied pin")
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
    scope = "ZIP and members match this receipt; the original source release was not checked."
    if source is not None:
        with verified_selection(source, bases, {ident: None}) as (manifest, spool, _, _, _, _):
            if manifest["version"] != version:
                raise ValueError("Receipt release differs from the supplied source version")
            recorded = workspace_at(read_spooled(spool / ident), step)
            if files != {name: ref["sha256"] for name, ref in recorded.items()}:
                raise ValueError("Receipt file hashes differ from the recorded workspace at the stated step")
        scope = ("ZIP matches the recorded step in the source, and source bytes match the supplied SHA-256 pin."
                 if source_pin is not None else
                 "ZIP matches the recorded step in the supplied source; source release identity was not authenticated.")
    return {"release": version, "episode_id": ident, "step": step, "files_verified": len(files),
            "scope": scope}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("zip", type=Path)
    p.add_argument("receipt", type=Path)
    p.add_argument("--source-archive", type=Path, help="Also compare to the recorded step in this supplied release")
    p.add_argument("--base-tar", type=Path, action="append", default=[])
    p.add_argument("--source-sha256", help="Expected source archive SHA-256 from a trusted release checksum")
    args = p.parse_args()
    if (args.base_tar or args.source_sha256 is not None) and args.source_archive is None:
        p.error("--base-tar and --source-sha256 require --source-archive")
    try:
        report = verify(args.zip, json.loads(args.receipt.read_text()), args.source_archive,
                        args.base_tar, args.source_sha256)
    except (OSError, ValueError, TypeError, KeyError, BadZipFile, RuntimeError, tarfile.TarError) as exc:
        p.exit(1, f"Step receipt check failed: {exc}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
