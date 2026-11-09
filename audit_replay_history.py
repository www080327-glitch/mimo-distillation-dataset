#!/usr/bin/env python3
"""Check recorded workspace version chains without reading assets or re-executing code."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory

from abc_release import Archive, Assets, base_hint, load_groups, open_needed_bases, read_spooled, release_version
from restore_replay_step import workspace_at


def workspace_refs(rows):
    final = rows["final_task_to_html"][0]
    yield from final["starting_files"].values()
    yield from final["final_files"].values()
    for item in final.get("runtime_requirements", {}).values():
        yield item["asset"]
    edits = [row["audit_assets"] for row in rows["single_edit"]]
    edits.extend(change for row in rows["observations"] for change in row["environment_changes"])
    for edit in edits:
        for side in ("before", "after"):
            if edit[side] is not None:
                yield edit[side]


def verify_workspace_files(stack, archive, manifest, spool, ids, bases):
    refs = {ident: list(workspace_refs(read_spooled(spool / ident))) for ident in ids}
    unresolved = {ref["file"] for group in refs.values() for ref in group} - archive.members.keys()
    opened = [base for _, base in open_needed_bases(stack, bases, unresolved)]
    assets = Assets([archive, *opened], None, base_hint(manifest, opened))
    checked, failures = {}, []
    for ident, group in refs.items():
        for ref in group:
            key = json.dumps(ref, sort_keys=True)
            if key not in checked:
                try:
                    assets.get(ref)
                except ValueError as exc:
                    checked[key] = str(exc)
                else:
                    checked[key] = None
            if checked[key] is not None:
                failure = {"id": ident, "asset": ref["file"], "error": checked[key]}
                if failure not in failures:
                    failures.append(failure)
    return {"distinct_references": len(checked), "failures": failures, "verified": not failures}


def audit(path, bases=(), verify_files=False):
    with ExitStack() as stack:
        archive = Archive(stack, path)
        manifest = json.loads(archive.read("MANIFEST.json"))
        version = release_version(manifest)
        spool = Path(stack.enter_context(TemporaryDirectory()))
        ids = load_groups(archive, manifest, None, spool)
        gaps, differences = [], []
        matched = 0
        for ident in ids:
            rows = read_spooled(spool / ident)
            last = max((turn["step"] for turn in rows["full_trajectory"][0]["turns"]), default=0)
            try:
                recovered = workspace_at(rows, last)
            except (ValueError, KeyError, TypeError) as exc:
                gaps.append({"id": ident, "reason": str(exc)})
                continue
            retained = rows["final_task_to_html"][0]["final_files"]
            changed = sorted(name for name in recovered.keys() | retained.keys()
                             if recovered.get(name, {}).get("sha256") != retained.get(name, {}).get("sha256"))
            if changed:
                differences.append({"id": ident, "files": changed})
            else:
                matched += 1
        file_check = verify_workspace_files(stack, archive, manifest, spool, ids, bases) if verify_files else None
        return {"version": version, "checked": len(ids), "matching_retained_hashes": matched,
                "version_gaps": gaps, "retained_differences": differences, "file_verification": file_check,
                "scope": ("Recorded version-chain metadata and workspace file bytes; screenshot bytes not checked."
                          if verify_files else "Recorded SHA-256 references only; file bytes were not checked.")}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--verify-files", action="store_true", help="Also verify the bytes of recorded workspace assets")
    p.add_argument("--base-tar", type=Path, action="append", default=[])
    args = p.parse_args()
    if args.base_tar and not args.verify_files:
        p.error("--base-tar requires --verify-files")
    try:
        report = audit(args.archive, args.base_tar, args.verify_files)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        p.exit(1, f"History audit failed: {exc}\n")
    print(json.dumps(report, indent=2))
    return int(bool(report["version_gaps"] or report["retained_differences"] or
                    (report["file_verification"] and not report["file_verification"]["verified"])))


if __name__ == "__main__":
    raise SystemExit(main())
