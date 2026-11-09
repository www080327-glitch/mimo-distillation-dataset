#!/usr/bin/env python3
"""Check a production archive's declared episode tallies against its recorded final rows."""
import argparse
from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory

from abc_release import Archive, load_groups, read_spooled, release_version


def verify(path):
    with ExitStack() as stack:
        archive = Archive(stack, path)
        manifest = json.loads(archive.read("MANIFEST.json"))
        version = release_version(manifest)
        if "sample_of" in manifest:
            raise ValueError("A sample is not a production archive")
        spool = Path(stack.enter_context(TemporaryDirectory()))
        ids = load_groups(archive, manifest, None, spool)
        actual = Counter()
        for ident in ids:
            row = read_spooled(spool / ident)["final_task_to_html"][0]
            focus, state = row["focus"], row["status"]
            if not isinstance(focus, str) or not isinstance(state, str) or not focus or not state:
                raise ValueError(f"Invalid focus or status for {ident}")
            actual[f"{focus}/{state}"] += 1
        declared = manifest.get("by_focus_and_state")
        if declared is not None and (
            not isinstance(declared, dict) or any(type(n) is not int or n < 0 for n in declared.values())
        ):
            raise ValueError("Invalid declared by_focus_and_state")
        diff = {label: {"declared": declared.get(label, 0), "recorded": actual[label]}
                for label in sorted(actual.keys() | declared.keys())
                if declared.get(label, 0) != actual[label]} if declared is not None else {}
        return {"version": version, "episodes": len(ids), "recorded": dict(sorted(actual.items())),
                "declared": declared, "differences": diff,
                "verified": None if declared is None else not diff}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    args = p.parse_args()
    try:
        report = verify(args.archive)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        p.exit(1, f"Tally check failed: {exc}\n")
    print(json.dumps(report, indent=2))
    return 2 if report["verified"] is None else int(not report["verified"])


if __name__ == "__main__":
    raise SystemExit(main())
