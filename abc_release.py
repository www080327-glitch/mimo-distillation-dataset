"""Read the public A/B/C release format without extracting or executing projects."""
from collections import defaultdict
from contextlib import ExitStack
from html import escape
import gzip
import hashlib
import json
from pathlib import PurePosixPath
import re
import shutil
import struct
import tarfile
from tempfile import TemporaryFile

STREAMS = ("full_trajectory", "final_task_to_html", "observations", "single_edit")
ID = re.compile(r"[0-9a-f]{20}")
ASSET = re.compile(r"assets/([0-9a-f]{64})\.(?:png|html|js|css|md|diff)")
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Archive:
    def __init__(self, stack, path):
        # Random lookups on a gzip stream repeatedly decompress everything before the member.
        spool = stack.enter_context(TemporaryFile())
        with gzip.open(path, "rb") as compressed:
            shutil.copyfileobj(compressed, spool, length=1024 * 1024)
        spool.seek(0)
        self.tar = stack.enter_context(tarfile.open(fileobj=spool, mode="r:"))
        self.members = {}
        for member in self.tar:
            if member.name in self.members or not member.isfile():
                raise ValueError(f"{path.name}: invalid or duplicate archive member {member.name!r}")
            self.members[member.name] = member

    def read(self, name):
        with self.tar.extractfile(self.members[name]) as source:
            return source.read()


class Assets:
    def __init__(self, archives, pngs):
        self.archives, self.pngs = archives, pngs
        self.checked = {}

    def get(self, ref):
        name, digest = ref["file"], ref["sha256"]
        match = ASSET.fullmatch(name)
        if not match or match[1] != digest:
            raise ValueError(f"Invalid asset reference: {name}")
        if name not in self.checked:
            archive = next((a for a in self.archives if name in a.members), None)
            if archive is None:
                raise ValueError(f"Missing asset: {name}. Supply its release with --base-tar.")
            data = archive.read(name)
            if sha(data) != digest:
                raise ValueError(f"Asset SHA-256 mismatch: {name}")
            self.checked[name] = archive, data
        archive, data = self.checked[name]
        if name.endswith(".png"):
            if (len(data) < 24 or not data.startswith(PNG)
                    or list(struct.unpack(">II", data[16:24])) != ref.get("size")):
                raise ValueError(f"PNG header or dimensions differ: {name}")
            self.pngs["/" + name] = archive.tar, archive.members[name]
        return data


def json_text(value):
    return "<pre>" + escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"


def references(value):
    if isinstance(value, dict):
        if "sha256" in value and isinstance(value.get("file"), str) and value["file"].startswith("assets/"):
            yield value
        for part in value.values():
            yield from references(part)
    elif isinstance(value, list):
        for part in value:
            yield from references(part)


def figures(value, assets, label, errors):
    html = []
    seen = set()
    for ref in references(value):
        try:
            assets.get(ref)
        except ValueError as exc:
            errors.add(str(exc))
            continue
        if not ref["file"].endswith(".png") or ref["file"] in seen:
            continue
        seen.add(ref["file"])
        html.append(f'<figure><figcaption>{label}</figcaption>'
                    f'<img src="/{ref["file"]}" loading="lazy" alt="{label}"></figure>')
    return "".join(html)


def page(version, body):
    return ("""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MiMo A/B/C replay</title><style>
body{font:1rem/1.5 system-ui;max-width:70rem;margin:auto;padding:1rem}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2f5;padding:1rem}
figure{margin:1rem 0}img{max-width:100%;height:auto}summary{cursor:pointer}
a:focus-visible,summary:focus-visible{outline:3px solid #175f9c;outline-offset:3px}
</style><main><p><a href="/">Episode index</a> · """ + escape(version) +
            " · Recorded evidence only. Project code is shown as text.</p>" + body + "</main></html>").encode()


def episode(ident, rows, assets, zips):
    final = rows["final_task_to_html"][0]
    errors, downloads, projects = set(), [], {}
    for label, field in (("initial", "starting_files"), ("retained", "final_files")):
        try:
            files = {}
            for filename, ref in final[field].items():
                path = PurePosixPath(filename)
                if (path.is_absolute() or not path.parts or ".." in path.parts
                        or path.as_posix() != filename or any(c in filename for c in "\\:\0")):
                    raise ValueError(f"Unsupported project filename: {filename!r}")
                files[filename] = assets.get(ref)
            if not files:
                raise ValueError("No project files recorded")
        except ValueError as exc:
            errors.add(f"{label.title()} project ZIP unavailable: {exc}")
            projects[label] = None
        else:
            route = f"/project/{ident}/{label}.zip"
            zips[route] = files
            projects[label] = list(files)
            downloads.append(f'<li><a href="{route}">Download {label} project ZIP</a> ({len(files)} files)</li>')

    body = [f"<h1>Episode {ident}</h1><p>Status: {escape(final['status'])} · {escape(final['termination'])}</p>",
            "<ul>" + "".join(downloads) + "</ul>"]
    sections = []
    for turn in rows["full_trajectory"][0]["turns"]:
        images = figures(turn["messages"], assets, "Teacher input screenshot", errors)
        sections.append(f"<details><summary>Teacher step {turn['step']}</summary>" + images + json_text(turn) + "</details>")
    body.append("<h2>Teacher requests and visible responses</h2>" + "".join(sections))
    sections = []
    for obs in rows["observations"]:
        detail = obs["observation"]
        images = figures(detail.get("before_views", []), assets, "Tool preview before source change", errors)
        images += figures(detail.get("views", []), assets, "Tool preview screenshot", errors)
        for change in obs["environment_changes"]:
            figures(change, assets, "", errors)
        sections.append(f"<details><summary>Tool step {obs['step']}: {escape(obs['event'])}</summary>" +
                        images + json_text(obs) + "</details>")
    body.append("<h2>Tool results and preview screenshots</h2>" + "".join(sections))
    figures(final, assets, "", errors)
    body.append("<details><summary>Recorded requirements and files</summary>" + json_text(final) + "</details>")
    for edit in rows["single_edit"]:
        audit = edit["audit_assets"]
        figures(audit, assets, "", errors)
        try:
            diff = assets.get(audit["diff"]).decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            errors.add(str(exc))
            diff = ""
        body.append(f"<details><summary>Edit at step {edit['step']}: {escape(edit['file'])}</summary>"
                    f"<pre>{escape(diff)}</pre></details>")
    if errors:
        body.insert(1, "<h2>Missing or invalid content</h2><ul>" +
                    "".join(f"<li>{escape(e)}</li>" for e in sorted(errors)) + "</ul>")
    return "".join(body), {"id": ident, "focus": final["focus"], "status": final["status"],
                           "projects": projects, "errors": sorted(errors)}


def run(args, serve):
    with ExitStack() as stack:
        primary = Archive(stack, args.manifest)
        raw = primary.read("MANIFEST.json")
        manifest = json.loads(raw)
        version = manifest["version"]
        if not re.fullmatch(r"v1\.(?:[2-9]|[1-9][0-9]+)\.\d+", version) or manifest.get("schema_version", 1) != 1:
            raise ValueError(f"Unsupported A/B/C release format: {version}")
        groups = defaultdict(lambda: {name: [] for name in STREAMS})
        for stream in STREAMS:
            name = stream + ".jsonl"
            data = primary.read(name)
            expected = manifest["files"][name]
            if len(data) != expected["bytes"] or sha(data) != expected["sha256"]:
                raise ValueError(f"{name}: size or SHA-256 differs from MANIFEST.json")
            for line in data.splitlines():
                row = json.loads(line)
                ident = row["episode_id"]
                if not ID.fullmatch(ident):
                    raise ValueError(f"{name}: invalid episode ID")
                groups[ident][stream].append(row)
        if (not groups or len(groups) != manifest["episodes"] or
                any(len(row["full_trajectory"]) != 1 or len(row["final_task_to_html"]) != 1 for row in groups.values()) or
                ("episode_ids" in manifest and set(manifest["episode_ids"]) != groups.keys())):
            raise ValueError("Episode index differs from the recorded streams")
        selected = dict.fromkeys(args.ids.read_text().split()) if args.ids else groups
        if not selected or selected.keys() - groups.keys():
            raise ValueError("--ids must select episode IDs in this A/B/C archive")
        pages, pngs, zips, receipts, links = {}, {}, {}, [], []
        assets = Assets([primary, *(Archive(stack, path) for path in args.base_tar)], pngs)
        for ident in selected:
            body, receipt = episode(ident, groups[ident], assets, zips)
            route = "/episode/" + ident
            pages[route] = page(version, body)
            links.append(f'<li><a href="{route}">{ident}</a> · {escape(receipt["focus"])} · {escape(receipt["status"])}</li>')
            receipts.append(receipt)
        pages["/"] = page(version, "<h1>MiMo A/B/C episodes</h1><ol>" + "".join(links) + "</ol>")
        if args.receipt:
            args.receipt.write_text(json.dumps({"release": version, "manifest_sha256": sha(raw),
                "dependencies": manifest.get("dependencies", []), "episodes": receipts}, ensure_ascii=False, indent=2) + "\n")
        if args.port is not None:
            serve(args.port, pages, pngs, zips)
        if args.strict and any(item["errors"] for item in receipts):
            return 1
