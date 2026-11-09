#!/usr/bin/env python3
"""Audit public A/B/C release counts and direct base declarations from local manifests."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import re
import tarfile
from tempfile import TemporaryDirectory

from abc_release import Archive, ID, load_groups, reused_bases, undeclared_reuse

VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def version_key(value):
    match = VERSION.fullmatch(value)
    if match is None:
        raise ValueError(f"Invalid release version: {value}")
    return tuple(map(int, match.groups()))


def legacy_ids(path, manifest):
    with ExitStack() as stack:
        archive = Archive(stack, path)
        if json.loads(archive.read("MANIFEST.json")) != manifest:
            raise ValueError("Legacy archive does not match the supplied v1.2.0 manifest")
        spool = Path(stack.enter_context(TemporaryDirectory()))
        return list(load_groups(archive, manifest, None, spool))


def audit(manifests, legacy=None):
    production, samples = {}, []
    for manifest in manifests:
        version = manifest["version"]
        version_key(version)
        count = manifest["episodes"]
        if type(count) is not int or count < 1:
            raise ValueError(f"{version}: invalid episode count")
        ids = manifest.get("episode_ids")
        if ids is not None and (not isinstance(ids, list) or len(ids) != count
                                or any(not isinstance(x, str) or not ID.fullmatch(x) for x in ids)):
            raise ValueError(f"{version}: invalid episode IDs or count")
        if "sample_of" in manifest:
            version_key(manifest["sample_of"])
            samples.append(manifest)
        else:
            if version in production:
                raise ValueError(f"Duplicate production manifest: {version}")
            production[version] = manifest

    if not production:
        raise ValueError("Supply at least one production manifest")
    if legacy is not None:
        manifest = production.get("v1.2.0")
        if manifest is None:
            raise ValueError("Supply the v1.2.0 manifest with --legacy-archive")
        production["v1.2.0"] = {**manifest, "episode_ids": legacy_ids(legacy, manifest)}

    seen, rows, issues = set(), [], []
    complete = True
    for version, manifest in sorted(production.items(), key=lambda x: version_key(x[0])):
        ids = manifest.get("episode_ids")
        if ids is None:
            complete = False
        else:
            overlap = seen.intersection(ids)
            if len(set(ids)) != len(ids) or overlap:
                issues.append(f"{version}: duplicate episode ID in or across production increments")
            seen.update(ids)
        predecessors = []
        if manifest.get("previous_release"):
            predecessors.append(manifest["previous_release"])
        dependencies = [x["version"] for x in reused_bases(manifest)]
        for undeclared in undeclared_reuse(manifest):
            issues.append(f"{version}: reused base {undeclared} has no archive declaration")
        for related in dict.fromkeys(predecessors + dependencies):
            if version_key(related) >= version_key(version):
                issues.append(f"{version}: invalid forward reference to {related}")
            elif related not in production:
                issues.append(f"{version}: missing production manifest for {related}")
        declared = manifest.get("cumulative_unique_abc_episodes")
        if complete and declared is not None and declared != len(seen):
            issues.append(f"{version}: cumulative unique count differs from {len(seen)}")
        rows.append({"version": version, "episodes": manifest["episodes"], "direct_bases": dependencies,
                     "declared_cumulative_unique": declared, "verified_cumulative_unique": len(seen) if complete else None})
    for sample in samples:
        parent = production.get(sample["sample_of"])
        if parent is not None and sample.get("episode_ids") is not None and parent.get("episode_ids") is not None:
            if set(sample["episode_ids"]) - set(parent["episode_ids"]):
                issues.append(f"{sample['version']}: sample contains IDs outside {sample['sample_of']}")
    return {"production": rows, "samples": len(samples), "known_unique": len(seen),
            "unique_complete": complete, "cumulative_unique": len(seen) if complete else None, "issues": issues}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path, nargs="+")
    p.add_argument("--legacy-archive", type=Path)
    args = p.parse_args()
    try:
        result = audit([json.loads(path.read_text()) for path in args.manifest], args.legacy_archive)
    except (ValueError, OSError, TypeError, KeyError, tarfile.TarError) as exc:
        p.error(str(exc))
    print(json.dumps(result, indent=2))
    return int(bool(result["issues"]))


if __name__ == "__main__":
    raise SystemExit(main())
