#!/usr/bin/env python3
"""Recover recorded project files at a public replay step without executing anything."""
import argparse
import os
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory

from abc_release import project_path, read_spooled
from export_replay import verified_selection
from replay_episode import zipped


def workspace_at(rows, step):
    last = max((row["step"] for row in rows["full_trajectory"][0]["turns"]), default=0)
    if not 0 <= step <= last:
        raise ValueError(f"Step must be between 0 and {last}")
    final = rows["final_task_to_html"][0]
    state = dict(final["starting_files"])
    transitions = [(row["step"], row["file"], row["audit_assets"]) for row in rows["single_edit"]]
    transitions.extend((obs["step"], change["file"], change)
                       for obs in rows["observations"] for change in obs["environment_changes"])
    for at, name, edit in sorted(transitions, key=lambda x: x[0]):
        if at > step:
            break
        project_path(name)
        old, before, after = state.get(name), edit["before"], edit["after"]
        if (old is None) != (before is None) or (old is not None and old["sha256"] != before["sha256"]):
            raise ValueError(f"Recorded version gap at step {at}: {name}")
        if after is None:
            state.pop(name, None)
        else:
            state[name] = after
    for name, item in final.get("runtime_requirements", {}).items():
        if item["released_after_step"] <= step:
            project_path(name)
            ref = item["asset"]
            if name in state and state[name]["sha256"] != ref["sha256"]:
                raise ValueError(f"Conflicting runtime version: {name}")
            state[name] = ref
    return state


def restore(source, bases, ident, step, output):
    if output.exists():
        raise ValueError("Output already exists")
    with verified_selection(source, bases, {ident: None}) as (_, spool, _, _, assets, _):
        refs = workspace_at(read_spooled(spool / ident), step)
        content = zipped({name: assets.get(ref) for name, ref in refs.items()})
    with TemporaryDirectory(dir=output.parent) as tmp:
        archive = Path(tmp) / "recorded.zip"
        archive.write_bytes(content)
        os.link(archive, output)
    return len(refs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--base-tar", type=Path, action="append", default=[])
    p.add_argument("--episode", required=True)
    p.add_argument("--step", type=int, required=True, help="After this recorded step, inclusive; 0 is initial")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        n = restore(args.archive, args.base_tar, args.episode, args.step, args.output)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        p.exit(1, f"Recovery failed: {exc}\n")
    print(f"Recovered {n} recorded files at step {args.step}; project code was not executed.")


if __name__ == "__main__":
    raise SystemExit(main())
