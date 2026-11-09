#!/usr/bin/env python3
"""Read episodes and PNGs from verified MiMo Release assets."""
import argparse
from collections import defaultdict
import gzip
import hashlib
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import struct
import tarfile
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from reassemble_media import name, verify

ROWS = "mimo-episodes-v1.jsonl.gz"
NOTICE = "https://github.com/www080327-glitch/mimo-distillation-dataset/blob/main/NOTICE"
PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def open_shard(shard, catalog, folders):
    if not re.fullmatch(r"mimo-episode-media-v1-\d+\.tar", shard) or shard not in catalog:
        raise ValueError(f"Unknown episode shard: {shard}")
    for folder in folders:
        path = folder / shard
        if path.is_file():
            verify({**catalog[shard], "parts": []}, folder, None)
            return tarfile.open(path, "r:")
    raise FileNotFoundError(f"{shard}: download or rebuild this logical archive")


class Media:
    def __init__(self, catalog, folders):
        self.catalog, self.folders = catalog, folders
        self.archives, self.checks = {}, {}

    def inspect(self, ref):
        shard, path, digest = (ref[k] for k in ("shard", "path", "sha256"))
        key = (shard, path, digest, tuple(ref["size"]))
        if key not in self.checks:
            try:
                if not re.fullmatch(r"[0-9a-f]{64}", digest) or path != f"images/{digest}.png":
                    raise ValueError(f"Invalid PNG reference: {path}")
                if shard not in self.archives:
                    try:
                        self.archives[shard] = open_shard(shard, self.catalog, self.folders)
                    except (OSError, ValueError, tarfile.TarError) as exc:
                        self.archives[shard] = str(exc)
                archive = self.archives[shard]
                if isinstance(archive, str):
                    raise ValueError(archive)
                member = archive.getmember(path)
                if not member.isfile():
                    raise ValueError(f"Not a regular PNG member: {path}")
                with archive.extractfile(member) as file:
                    data = file.read()
                if (sha(data) != digest or not data.startswith(PNG_HEADER)
                        or list(struct.unpack(">II", data[16:24])) != ref["size"]):
                    raise ValueError(f"PNG hash or dimensions differ: {path}")
                self.checks[key] = (archive, member)
            except (OSError, KeyError, ValueError, tarfile.TarError, struct.error) as exc:
                self.checks[key] = str(exc)
        return self.checks[key]

    def close(self):
        for archive in self.archives.values():
            if isinstance(archive, tarfile.TarFile):
                archive.close()


def read_episodes(manifest, catalog, ids):
    verify(catalog[ROWS], manifest.parent, None)
    with gzip.open(manifest.parent / ROWS, "rt", encoding="utf-8") as source:
        selected = {}
        for line in source:
            row = json.loads(line)
            if row["id"] in ids:
                selected[row["id"]] = row
                if len(selected) == len(ids):
                    break
    missing = ids.keys() - selected.keys()
    if missing:
        raise ValueError(f"Episode not in {ROWS}: {', '.join(sorted(missing))}")
    return [selected[ident] for ident in ids]


def project_versions(row):
    initial = row.get("case", {}).get("files", {})
    archived = row.get("versions", {})
    if "starting-index.html" in archived:
        initial = {**initial, "index.html": archived["starting-index.html"]}
    versions = {"initial": initial}
    workspace = dict(initial)
    issues, announced, recovered = [], set(), {}
    edits = row.get("edits", [])
    at_step = defaultdict(list)
    for edit in edits:
        at_step[edit["step"]].append(edit)
    observations = defaultdict(list)
    for item in row.get("requests", []) + row.get("events", []):
        if isinstance(item.get("observation"), dict):
            observations[item.get("step")].append(item["observation"])
    for step in sorted((at_step.keys() | observations.keys()) - {None}):
        for edit in at_step[step]:
            before, after = edit.get("before"), edit["after"]
            if after not in archived or (before and before not in archived):
                issues.append(f"Step {step}: missing version {before} → {after}")
            if after in archived:
                workspace["index.html"] = archived[after]
                versions[after] = dict(workspace)
        for obs in observations[step]:
            if obs.get("new_file"):
                announced.add(obs["new_file"])
            filename = obs.get("name")
            if filename in announced and "line_range" not in obs and isinstance(obs.get("text"), str):
                workspace[filename] = obs["text"]
                recovered.setdefault(filename, step)
    for filename in sorted(announced - recovered.keys()):
        issues.append(f"Missing runtime file: {filename} was announced but no full tool read is archived.")
    versions["last-retained"] = workspace
    if not workspace:
        issues.append("No recoverable project snapshot at the last retained version.")
    return versions, issues, recovered


def observation_timeline(row):
    events = defaultdict(list)
    edits = {edit["after"]: edit["step"] for edit in row.get("edits", [])}
    for position, event in enumerate(row.get("events", []), 1):
        doc = event.get("document")
        step = event.get("step", 0 if doc == "starting-index.html" else edits.get(doc))
        events[step].append((position, event))
    return events


def details(label, value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, indent=2)
    return f"<details><summary>{escape(label)}</summary><pre>{escape(value)}</pre></details>"


def images(media, pictures, role, urls):
    html, receipts = [], []
    for ordinal, ref in enumerate(pictures, 1):
        result = media.inspect(ref)
        error = result if isinstance(result, str) else None
        receipts.append({**ref, "role": role, "ordinal": ordinal, "status": error or "verified"})
        if error:
            html.append(f"<p>{escape(role)} {ordinal}: {escape(error)}</p>")
        else:
            key = f"/media/{quote(ref['shard'])}/{ref['sha256']}.png"
            urls[key] = result
            html.append(f'<figure><img loading="lazy" src="{key}" alt="{escape(role)} {ordinal}">'
                        f"<figcaption>{escape(role)} {ordinal} · {ref['size'][0]} × {ref['size'][1]}</figcaption></figure>")
    return "".join(html), receipts


def episode_page(row, media, urls, zips):
    ident = row["id"]
    result = row.get("result", {})
    state = result.get("state", "unrecorded")
    teachers = sorted({r["teacher"] for r in row.get("requests", [])} |
                      ({row["teacher"]} if row.get("teacher") else set()))
    versions, issues, recovered = project_versions(row)
    version_html = []
    for label, files in versions.items():
        if not files:
            continue
        route = f"/episode/{ident}/{quote(label, safe='')}.zip"
        zips[route] = files
        files_html = "".join(details(filename, source) for filename, source in files.items())
        version_html.append(f"<h3>{escape(label)} · {len(files)} file(s)</h3>"
                            f'<a href="{route}">Download retained files (.zip)</a>{files_html}')
    timeline = observation_timeline(row)
    turns = {r["step"]: r for r in row.get("requests", [])}
    edits = defaultdict(list)
    for edit in row.get("edits", []):
        edits[edit["step"]].append(edit)
    receipts, steps = [], []
    for step in sorted(set(turns) | set(edits) | (timeline.keys() - {None})) + ([None] if None in timeline else []):
        parts = [f"<h3>{'Before request 1' if step == 0 else 'Unpaired events' if step is None else f'Step {step}'}</h3>"]
        if step in turns:
            turn = turns[step]
            role = "Recorded teacher input" if "input" in turn else "Archived request image (role unconfirmed)"
            html, checks = images(media, turn.get("images", []), role, urls)
            receipts.extend({"step": step, **c} for c in checks)
            parts.extend(details(k, turn[k]) for k in ("system", "input", "answer", "action", "observation", "executed", "finish_reason") if k in turn)
            parts.append(html)
        for edit in edits[step]:
            parts.append(details("Edit · before → after", {k: edit[k] for k in ("before", "after", "change_requirement") if k in edit}))
        for position, event in timeline.get(step, []):
            html, checks = images(media, event.get("images", []), "Archived tool preview", urls)
            receipts.extend({"step": step, "event": position, **c} for c in checks)
            parts.extend((details(f"Event {position} · recorded action and tool result",
                                  {k: v for k, v in event.items() if k != "images"}), html))
        steps.extend(parts)
    if row.get("final_answer") is not None:
        steps.append(details("Recorded final answer", row["final_answer"]))
    provenance = ("Release NOTICE applies to the compilation. Episode-specific source/license "
                  "is not recorded in this v1.1.0 schema.")
    case = row.get("case", {})
    brief = details("Archived initial brief", case["prompt"]) if "prompt" in case else ""
    title = f" · {escape(case['title'])}" if case.get("title") else ""
    body = (f'<h1>{escape(row["task"])} · {escape(state)}{title}</h1><p><code>{ident}</code></p>'
            f"<p>Teacher: {escape(', '.join(teachers) or 'unrecorded')} · split: {escape(row['split'])}</p>"
            f'<p><a href="{NOTICE}">Release NOTICE</a>. {provenance}</p>'
            + details("Recorded outcome", result) + brief
            + "<h2>Historical replay</h2>" + "".join(steps)
            + "<h2>Retained project files</h2>"
              "<p>Initial files, archived index.html versions and complete reads of announced runtime files. Last retained does not certify the whole final workspace.</p>"
            + "".join(f"<p>{escape(filename)}: recovered from the full tool return at step {step}.</p>"
                      for filename, step in recovered.items())
            + "".join(f"<p>{escape(issue)}</p>" for issue in issues) + "".join(version_html))
    receipt = {"id": ident, "task": row["task"], "split": row["split"], "result": result, "teachers": teachers,
               "requests": len(turns), "events": len(row.get("events", [])),
               "tool_returns": sum("observation" in x for x in row.get("events", []) + row.get("requests", [])),
               "edits": [{"step": e["step"], "before": e["before"], "after": e["after"]} for e in row.get("edits", [])],
               "media": receipts, "versions": {k: {n: sha(t.encode()) for n, t in files.items()} for k, files in versions.items()},
               "project_limits": issues, "runtime_files_recovered_at_step": recovered, "episode_source_license": None, "rerun": "NOT_RUN"}
    return body, receipt


def page(body):
    return ("""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MiMo Release episode replay</title>
<style>
body{font:1rem/1.55 system-ui,sans-serif;max-width:68rem;margin:auto;padding:1rem;color:#18222a;background:#f7f9fb}
h2{border-top:1px solid #bac9d6;padding-top:1rem} details{margin:.35rem 0}
summary{cursor:pointer} pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eaf0f5;padding:1rem}
code{overflow-wrap:anywhere} figure{margin:.8rem 0} img{max-width:100%;height:auto} a{color:#124c89}
</style><main><p><a href="/">Sample index</a> · v1.1.0 · local historical record. No code is executed.</p>"""
            + body + "</main></html>").encode()


def zipped(files):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for filename, text in files.items():
            path = PurePosixPath(filename)
            if (path.is_absolute() or ".." in path.parts or not path.parts
                    or "\\" in filename or ":" in filename):
                raise ValueError(f"Unsupported project filename: {filename}")
            if isinstance(text, tuple):
                source_archive, member = text
                with source_archive.extractfile(member) as source:
                    text = source.read()
            archive.writestr(path.as_posix(), text)
    return buffer.getvalue()


def serve(port, pages, pngs, zips):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = self.path
            if route in pages:
                data = pages[route]
                if isinstance(data, Path):
                    data = data.read_bytes()
                mime = "text/html; charset=utf-8"
            elif route in pngs:
                archive, member = pngs[route]
                with archive.extractfile(member) as file:
                    data, mime = file.read(), "image/png"
            elif route in zips:
                try:
                    data, mime = zipped(zips[route]), "application/zip"
                except ValueError as exc:
                    self.send_error(422, str(exc))
                    return
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'")
            if route in zips:
                self.send_header("Content-Disposition", 'attachment; filename="retained-project.zip"')
            self.end_headers()
            self.wfile.write(data)

    with HTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Open http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--ids", type=Path)
    parser.add_argument("--abc-tar", action="store_true", help="Read a v1.2.0 or later A/B/C release tar")
    parser.add_argument("--base-tar", type=Path, action="append", default=[], help="Local prior A/B/C tar with shared assets")
    parser.add_argument("--media-dir", type=Path, action="append", default=[], help="Additional folders with rebuilt archives")
    parser.add_argument("--receipt", type=Path, help="Write recovery checks as JSON")
    parser.add_argument("--strict", action="store_true", help="Return 1 after writing an A/B/C receipt with missing or invalid evidence")
    parser.add_argument("--port", type=int, help="Serve the selected episodes on loopback")
    args = parser.parse_args()
    if args.receipt is None and args.port is None:
        parser.error("Choose --receipt, --port, or both")
    if args.strict and (not args.abc_tar or args.receipt is None or args.port is not None):
        parser.error("--strict requires --abc-tar and --receipt, without --port")
    if args.abc_tar:
        import abc_release
        if args.media_dir:
            parser.error("--media-dir is only for the v1.1.0 reader")
        try:
            return abc_release.run(args, serve)
        except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
            parser.error(f"A/B/C release: {exc}")
    if args.base_tar:
        parser.error("--base-tar requires --abc-tar")
    ids_file = args.ids or Path(__file__).with_name("examples") / "v1.1.0-ids.txt"
    ids = dict.fromkeys(ids_file.read_text().split())
    if not ids or any(not re.fullmatch(r"[0-9a-f]{64}", ident) for ident in ids):
        parser.error("--ids must list full lowercase Release episode IDs")
    manifest = json.loads(args.manifest.read_text())
    if manifest["snapshot"] != "v1.1.0":
        parser.error("This reader supports Release v1.1.0")
    catalog = {name(x["name"]): x for x in manifest["files"]}
    media = Media(catalog, [args.manifest.parent, *args.media_dir])
    pages, urls, zips, receipts = {}, {}, {}, []
    try:
        links = []
        for row in read_episodes(args.manifest, catalog, ids):
            body, receipt = episode_page(row, media, urls, zips)
            ident = receipt["id"]
            route = f"/episode/{ident}"
            pages[route] = page(body)
            links.append(f'<li><a href="{route}">{escape(receipt["task"])} · '
                         f'{escape(receipt["result"].get("state", "unrecorded"))} · {ident[:12]}</a></li>')
            receipts.append(receipt)
        pages["/"] = page("<h1>MiMo episode samples</h1><p>Open a recorded episode to see teacher inputs, "
                          "tool results and retained files. No rerendering or teacher calls.</p><ol>"
                          + "".join(links) + "</ol>")
        if args.receipt:
            payload = {"release": manifest["snapshot"], "manifest_sha256": sha(args.manifest.read_bytes()), "episodes": receipts}
            args.receipt.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        if args.port is not None:
            serve(args.port, pages, urls, zips)
    finally:
        media.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
