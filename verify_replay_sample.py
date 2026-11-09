#!/usr/bin/env python3
"""Verify that a public replay sample preserves the selected evidence in its parent release."""
import argparse
from collections import defaultdict
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory

from abc_release import (
    Archive, Assets, STREAMS, base_hint, episode, load_groups, open_needed_bases,
    read_spooled, references, release_version, spool_row, validate_index,
)
from download_abc_bases import read_manifest


def stream_parent_rows(path, manifest, requested, spool):
    streams = {name + ".jsonl": name for name in STREAMS}
    counts = defaultdict(lambda: dict.fromkeys(STREAMS, 0))
    seen = set()
    with tarfile.open(path, "r|gz") as parent:
        for member in parent:
            name = member.name
            if name != "MANIFEST.json" and name not in streams:
                continue
            if name in seen or not member.isfile():
                raise ValueError(f"Invalid or duplicate parent member: {name}")
            seen.add(name)
            with parent.extractfile(member) as source:
                if name == "MANIFEST.json":
                    if json.load(source) != manifest:
                        raise ValueError("Embedded parent manifest changed")
                    continue
                expected = manifest["files"][name]
                checksum = hashlib.sha256()
                size = 0
                for line in source:
                    size += len(line)
                    checksum.update(line)
                    spool_row(line, streams[name], counts, requested, spool)
                if size != expected["bytes"] or checksum.hexdigest() != expected["sha256"]:
                    raise ValueError(f"{name}: size or SHA-256 differs from parent MANIFEST.json")
    if seen != {"MANIFEST.json", *streams}:
        raise ValueError("Parent manifest or recorded stream missing")
    validate_index(manifest, counts, requested)


def verify(source, sample, bases=()):
    with ExitStack() as stack:
        subset = Archive(stack, sample)
        source_manifest = read_manifest(source)
        sample_manifest = json.loads(subset.read("MANIFEST.json"))
        version = release_version(source_manifest)
        if ("sample_of" in source_manifest or release_version(sample_manifest) != version
                or sample_manifest.get("sample_of") != version):
            raise ValueError("Sample does not name the supplied production release")
        parent_spool, sample_spool = (Path(stack.enter_context(TemporaryDirectory())) for _ in range(2))
        selected = load_groups(subset, sample_manifest, None, sample_spool)
        stream_parent_rows(source, source_manifest, selected, parent_spool)
        unresolved = {ref["file"] for ident in selected for ref in references(read_spooled(sample_spool / ident))}
        unresolved.difference_update(subset.members)
        opened = [archive for _, archive in open_needed_bases(stack, bases, unresolved)]
        assets = Assets([subset, *opened], None, base_hint(sample_manifest, opened))
        issues, self_contained = [], True
        for ident in selected:
            original, actual = (read_spooled(d / ident) for d in (parent_spool, sample_spool))
            for stream in STREAMS:
                if json.dumps(original[stream], sort_keys=True) != json.dumps(actual[stream], sort_keys=True):
                    issues.append({"id": ident, "stream": stream, "error": "Recorded rows differ"})
            _, receipt = episode(ident, actual, assets, None)
            issues.extend({"id": ident, "error": message} for message in receipt["errors"])
            for ref in references(actual):
                self_contained &= ref["file"] in subset.members
                try:
                    assets.get(ref)
                except ValueError as exc:
                    issue = {"id": ident, "error": str(exc)}
                    if issue not in issues:
                        issues.append(issue)
        return {"source": version, "sample_episodes": len(selected), "self_contained": self_contained,
                "verified": not issues, "issues": issues}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("sample", type=Path)
    p.add_argument("--base-tar", type=Path, action="append", default=[])
    args = p.parse_args()
    try:
        report = verify(args.source, args.sample, args.base_tar)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as exc:
        p.exit(1, f"Verification failed: {exc}\n")
    print(json.dumps(report, indent=2))
    return int(not report["verified"])


if __name__ == "__main__":
    raise SystemExit(main())
