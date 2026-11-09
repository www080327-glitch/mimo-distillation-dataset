#!/usr/bin/env python3
"""Create a portable, self-contained sample from explicitly selected public A/B/C episodes."""
import argparse
from contextlib import ExitStack
import gzip
import io
import json
import os
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory

from abc_release import Archive, Assets, STREAMS, base_hint, episode, load_groups, read_spooled, references, release_version
from download_release import digest


def tar_bytes(tar, name, data):
    item = tarfile.TarInfo(name)
    item.size = len(data)
    tar.addfile(item, io.BytesIO(data))


def export(source, bases, ids, output):
    if output.exists():
        raise ValueError("Output already exists")
    if not ids:
        raise ValueError("At least one episode ID is required")
    with ExitStack() as stack:
        primary = Archive(stack, source)
        manifest = json.loads(primary.read("MANIFEST.json"))
        version = release_version(manifest)
        spool = Path(stack.enter_context(TemporaryDirectory()))
        chosen = load_groups(primary, manifest, ids, spool)
        unresolved = {ref["file"] for ident in chosen for ref in references(read_spooled(spool / ident))}
        unresolved.difference_update(primary.members)
        base_archives, seen = [], set()
        for path in bases:
            if not unresolved:
                break
            path = path.resolve()
            if path not in seen:
                seen.add(path)
                base = Archive(stack, path)
                base_archives.append(base)
                unresolved.difference_update(base.members)
        assets = Assets([primary, *base_archives], None, base_hint(manifest, base_archives))
        staged = Path(stack.enter_context(TemporaryDirectory(dir=output.parent)))
        archive = staged / "sample.tar.gz"
        refs = {}
        stream_paths = {k: staged / (k + ".jsonl") for k in STREAMS}
        with ExitStack() as streams:
            files = {k.encode("ascii"): streams.enter_context(p.open("wb")) for k, p in stream_paths.items()}
            for ident in chosen:
                path = spool / ident
                rows = read_spooled(path)
                _, receipt = episode(ident, rows, assets, None)
                if receipt["errors"]:
                    raise ValueError(f"{ident}: " + "; ".join(receipt["errors"]))
                for ref in references(rows):
                    # Check every occurrence, including repeated PNG dimensions, before deduplicating.
                    assets.get(ref)
                    refs.setdefault(ref["file"], ref)
                with path.open("rb") as f:
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
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        sample = export(args.archive, args.base_tar, dict.fromkeys(args.ids.read_text().split()), args.output)
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError) as exc:
        p.exit(1, f"Export failed: {exc}\n")
    print(f"Exported {sample['episodes']} selected episodes and {sample['content_addressed_assets']} assets to {args.output}.")


if __name__ == "__main__":
    raise SystemExit(main())
