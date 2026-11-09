#!/usr/bin/env python3
"""Create a portable, self-contained sample from explicitly selected public A/B/C episodes."""
import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
import gzip
import io
import json
import os
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory

from abc_release import Archive, Assets, STREAMS, base_hint, episode, load_groups, open_needed_bases, read_spooled, references, release_version
from download_release import digest


def tar_bytes(tar, name, data):
    item = tarfile.TarInfo(name)
    item.size = len(data)
    tar.addfile(item, io.BytesIO(data))


@contextmanager
def verified_selection(source, bases, ids):
    if not ids:
        raise ValueError("At least one episode ID is required")
    with ExitStack() as stack:
        primary = Archive(stack, source)
        manifest = json.loads(primary.read("MANIFEST.json"))
        release_version(manifest)
        spool = Path(stack.enter_context(TemporaryDirectory()))
        chosen = load_groups(primary, manifest, ids, spool)
        unresolved = {ref["file"] for ident in chosen for ref in references(read_spooled(spool / ident))}
        unresolved.difference_update(primary.members)
        opened = [(source.absolute(), primary), *open_needed_bases(stack, bases, unresolved)]
        archives = [arc for _, arc in opened]
        assets = Assets(archives, None, base_hint(manifest, archives[1:]))
        refs = {}
        for ident in chosen:
            rows = read_spooled(spool / ident)
            _, receipt = episode(ident, rows, assets, None)
            if receipt["errors"]:
                raise ValueError(f"{ident}: " + "; ".join(receipt["errors"]))
            for ref in references(rows):
                # Check every occurrence, including repeated PNG dimensions, before deduplicating.
                assets.get(ref)
                refs.setdefault(ref["file"], ref)
        yield manifest, spool, chosen, refs, assets, opened


def plan(source, bases, ids):
    with verified_selection(source, bases, ids) as (manifest, _, chosen, refs, _, opened):
        counts = Counter(next(path for path, archive in opened if name in archive.members) for name in refs)
        return {"source": manifest["version"], "selected_ids": list(chosen), "assets": len(refs),
                "archives": [{"path": str(path), "assets": counts[path]} for path, _ in opened if counts[path]]}


def export(source, bases, ids, output):
    if output.exists():
        raise ValueError("Output already exists")
    with (verified_selection(source, bases, ids) as (manifest, spool, chosen, refs, assets, opened),
          TemporaryDirectory(dir=output.parent) as directory):
        primary = opened[0][1]
        version = manifest["version"]
        staged = Path(directory)
        archive = staged / "sample.tar.gz"
        stream_paths = {k: staged / (k + ".jsonl") for k in STREAMS}
        with ExitStack() as streams:
            files = {k.encode("ascii"): streams.enter_context(p.open("wb")) for k, p in stream_paths.items()}
            for ident in chosen:
                with (spool / ident).open("rb") as f:
                    for line in f:
                        stream, payload = line.split(b"\t", 1)
                        files[stream].write(payload)
        sample = {"version": version, "schema_version": 1,
                  "sample_of": manifest.get("sample_of", manifest["version"]),
                  "episodes": len(chosen), "episode_ids": list(chosen),
                  "files": {p.name: {"bytes": p.stat().st_size, "sha256": digest(p)}
                            for p in stream_paths.values()},
                  "content_addressed_assets": len(refs), "dependencies": []}
        with (
            archive.open("wb") as raw,
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=3) as compressed,
            tarfile.open(fileobj=compressed, mode="w|") as tar,
        ):
            tar_bytes(tar, "MANIFEST.json", (json.dumps(sample, indent=2) + "\n").encode())
            for path in stream_paths.values():
                info = tarfile.TarInfo(path.name)
                info.size = path.stat().st_size
                with path.open("rb") as f:
                    tar.addfile(info, f)
            for name, ref in sorted(refs.items()):
                tar_bytes(tar, name, assets.get(ref))
            for name in ("LICENSE", "NOTICE"):
                if name in primary.members:
                    tar_bytes(tar, name, primary.read(name))
        os.link(archive, output)
    return sample


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--base-tar", type=Path, action="append", default=[])
    p.add_argument("--ids", type=Path, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--plan", action="store_true", help="Verify selected assets and list their contributing archives")
    args = p.parse_args()
    try:
        ids = dict.fromkeys(args.ids.read_text().split())
        if args.plan:
            print(json.dumps(plan(args.archive, args.base_tar, ids), indent=2))
            return
        sample = export(args.archive, args.base_tar, ids, args.output)
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError) as exc:
        p.exit(1, f"Export failed: {exc}\n")
    print(f"Exported {sample['episodes']} selected episodes and {sample['content_addressed_assets']} assets to {args.output}.")


if __name__ == "__main__":
    raise SystemExit(main())
