#!/usr/bin/env python3
"""Verify that a public replay sample preserves the selected evidence in its parent release."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory

from abc_release import Archive, Assets, STREAMS, base_hint, episode, load_groups, open_needed_bases, read_spooled, references, release_version


def verify(source, sample, bases=()):
    with ExitStack() as stack:
        parent, subset = Archive(stack, source), Archive(stack, sample)
        source_manifest, sample_manifest = (json.loads(a.read("MANIFEST.json")) for a in (parent, subset))
        version = release_version(source_manifest)
        if ("sample_of" in source_manifest or release_version(sample_manifest) != version
                or sample_manifest.get("sample_of") != version):
            raise ValueError("Sample does not name the supplied production release")
        parent_spool, sample_spool = (Path(stack.enter_context(TemporaryDirectory())) for _ in range(2))
        selected = load_groups(subset, sample_manifest, None, sample_spool)
        load_groups(parent, source_manifest, selected, parent_spool)
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
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        p.exit(1, f"Verification failed: {exc}\n")
    print(json.dumps(report, indent=2))
    return int(not report["verified"])


if __name__ == "__main__":
    raise SystemExit(main())
