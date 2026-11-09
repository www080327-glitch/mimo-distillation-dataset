"""Read the public A/B/C release format without extracting or executing projects."""
from collections import defaultdict
from contextlib import ExitStack
from html import escape
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import tarfile
from tempfile import TemporaryDirectory, TemporaryFile

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

    def open(self, name):
        return self.tar.extractfile(self.members[name])

    def read(self, name):
        with self.open(name) as source:
            return source.read()


def open_needed_bases(stack, paths, unresolved):
    opened, seen = [], set()
    for path in paths:
        if not unresolved:
            break
        path = path.resolve()
        if path not in seen:
            seen.add(path)
            archive = Archive(stack, path)
            opened.append((path, archive))
            unresolved.difference_update(archive.members)
    return opened


class Assets:
    def __init__(self, archives, pngs, base_hint):
        self.archives, self.pngs, self.base_hint = archives, pngs, base_hint
        self.checked = {}

    def member(self, name):
        archive, _ = self.checked[name]
        return archive.tar, archive.members[name]

    def get(self, ref):
        name, digest = ref["file"], ref.get("sha256")
        match = ASSET.fullmatch(name)
        if not match or match[1] != digest:
            raise ValueError(f"Invalid asset reference: {name}")
        if name not in self.checked:
            archive = next((a for a in self.archives if name in a.members), None)
            if archive is None:
                raise ValueError(f"Missing asset: {name}. {self.base_hint}")
            data = archive.read(name)
            if sha(data) != digest:
                raise ValueError(f"Asset SHA-256 mismatch: {name}")
            if self.pngs is not None:
                self.checked[name] = archive, data
        else:
            archive, data = self.checked[name]
        if name.endswith(".png"):
            if (len(data) < 24 or not data.startswith(PNG)
                    or list(struct.unpack(">II", data[16:24])) != ref.get("size")):
                raise ValueError(f"PNG header or dimensions differ: {name}")
            if self.pngs is not None:
                self.pngs["/" + name] = archive.tar, archive.members[name]
        return data


def reused_bases(manifest):
    dependencies = manifest.get("dependencies", [])
    if "assets_reused_from" in manifest:
        reused = manifest["assets_reused_from"]
        return [entry for entry in dependencies if reused.get(entry["version"])]
    return dependencies


def undeclared_reuse(manifest):
    declared = {entry["version"] for entry in manifest.get("dependencies", [])}
    return sorted(version for version, count in manifest.get("assets_reused_from", {}).items()
                  if count and version not in declared)


def base_filename(entry):
    version = entry["version"]
    if entry.get("asset"):
        return entry["asset"]
    if version == "v1.2.0":
        return "mimo-nextgen-abc-v1.tar.gz"
    if version in ("v1.3.0", "v1.4.0"):
        return f"mimo-nextgen-abc-{version}.tar.gz"
    return None


def base_hint(manifest, bases):
    # Older manifests may include predecessor history alongside actual reuse.
    dependencies = reused_bases(manifest)
    supplied = set()
    for archive in bases:
        if "MANIFEST.json" in archive.members:
            try:
                version = json.loads(archive.read("MANIFEST.json")).get("version")
            except (ValueError, AttributeError):
                continue
            if isinstance(version, str):
                supplied.add(version)
    labels = []
    for entry in dependencies:
        version = entry["version"]
        asset = base_filename(entry)
        title = f"{version} ({asset})" if asset else version
        detail = "supplied, but missing this asset" if version in supplied else "supply with --base-tar"
        labels.append(f"{title}: {detail}")
    hint = "Declared base candidates: " + "; ".join(labels) + "." if labels else "No candidate base is declared."
    if supplied:
        hint += " Supplied base versions: " + ", ".join(sorted(supplied)) + "."
    return hint


def index_counts(manifest, selected):
    parts = [f"Selected: {selected:,}"]
    if "sample_of" in manifest:
        parts.append(f"Sample from {manifest['sample_of']}; no new episodes")
    elif manifest.get("incremental") is True:
        parts.append(f"Release increment: {manifest['episodes']:,}")
        if "cumulative_unique_abc_episodes" in manifest:
            parts.append(f"Cumulative unique: {manifest['cumulative_unique_abc_episodes']:,}")
    else:
        parts.append(f"Release episodes: {manifest['episodes']:,}")
    return "<p>" + escape(" · ".join(parts)) + "</p>"


def json_text(value):
    return "<pre>" + escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"


def references(value):
    if isinstance(value, dict):
        name = value.get("file")
        if isinstance(name, str) and name.startswith("assets/") and ("sha256" in value or ASSET.fullmatch(name)):
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
        if not label or not ref["file"].endswith(".png") or ref["file"] in seen:
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


def project_path(filename):
    path = PurePosixPath(filename)
    if (path.is_absolute() or not path.parts or ".." in path.parts
            or path.as_posix() != filename or any(c in filename for c in "\\:\0")):
        raise ValueError(f"Unsupported project filename: {filename!r}")
    return path


def diff_text(ref, assets, errors):
    try:
        return assets.get(ref).decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        errors.add(str(exc))
        return None


def episode(ident, rows, assets, zips):
    final = rows["final_task_to_html"][0]
    errors, downloads, projects = set(), [], {}
    render = zips is not None
    for label, field in (("initial", "starting_files"), ("retained", "final_files")):
        try:
            files = {}
            for filename, ref in final[field].items():
                project_path(filename)
                assets.get(ref)
                files[filename] = assets.member(ref["file"]) if render else None
            if not files:
                raise ValueError("No project files recorded")
        except ValueError as exc:
            errors.add(f"{label.title()} project ZIP unavailable: {exc}")
            projects[label] = None
        else:
            route = f"/project/{ident}/{label}.zip"
            projects[label] = list(files)
            if render:
                zips[route] = files
                downloads.append(f'<li><a href="{route}">Download {label} project ZIP</a> ({len(files)} files)</li>')

    body = []
    if render:
        body = [f"<h1>Episode {ident}</h1><p>Status: {escape(final['status'])} · {escape(final['termination'])}</p>",
                "<ul>" + "".join(downloads) + "</ul>", "<h2>Teacher requests and visible responses</h2>"]
    for turn in rows["full_trajectory"][0]["turns"]:
        images = figures(turn["messages"], assets, "Teacher input screenshot" if render else "", errors)
        if render:
            body.append(f"<details><summary>Teacher step {turn['step']}</summary>" + images + json_text(turn) + "</details>")
    if render:
        body.append("<h2>Tool results and preview screenshots</h2>")
    for obs in rows["observations"]:
        detail = obs["observation"]
        images = figures(detail.get("before_views", []), assets, "Tool preview before source change" if render else "", errors)
        images += figures(detail.get("views", []), assets, "Tool preview screenshot" if render else "", errors)
        changes = []
        for change in obs["environment_changes"]:
            figures(change, assets, "", errors)
            diff = diff_text(change["diff"], assets, errors) if change.get("diff") else None
            if render:
                content = "<p>No readable verified diff.</p>" if diff is None else f"<pre>{escape(diff)}</pre>"
                changes.append(f"<section><h3>External source change at step {obs['step']}: "
                               f"{escape(change['file'])}</h3>{content}</section>")
        if render:
            body.append(f"<details><summary>Tool step {obs['step']}: {escape(obs['event'])}</summary>" +
                        images + "".join(changes) + json_text(obs) + "</details>")
    figures(final, assets, "", errors)
    if render:
        body.append("<details><summary>Recorded requirements and files</summary>" + json_text(final) + "</details>")
    for edit in rows["single_edit"]:
        audit = edit["audit_assets"]
        figures(audit, assets, "", errors)
        diff = diff_text(audit["diff"], assets, errors) or ""
        if render:
            body.append(f"<details><summary>Edit at step {edit['step']}: {escape(edit['file'])}</summary>"
                        f"<pre>{escape(diff)}</pre></details>")
    if render and errors:
        body.insert(1, "<h2>Missing or invalid content</h2><ul>" +
                    "".join(f"<li>{escape(e)}</li>" for e in sorted(errors)) + "</ul>")
    return "".join(body), {"id": ident, "focus": final["focus"], "status": final["status"],
                           "projects": projects, "errors": sorted(errors)}


def spool_row(line, stream, counts, requested, spool):
    row = json.loads(line)
    ident = row["episode_id"]
    if not ID.fullmatch(ident):
        raise ValueError(f"{stream}.jsonl: invalid episode ID")
    counts[ident][stream] += 1
    if requested is None or ident in requested:
        with (spool / ident).open("ab") as output:
            output.write(stream.encode("ascii") + b"\t" + line.rstrip(b"\r\n") + b"\n")


def validate_index(manifest, counts, requested):
    if (not counts or len(counts) != manifest["episodes"] or
            any(row["full_trajectory"] != 1 or row["final_task_to_html"] != 1 for row in counts.values()) or
            ("episode_ids" in manifest and set(manifest["episode_ids"]) != counts.keys())):
        raise ValueError("Episode index differs from the recorded streams")
    selected = counts if requested is None else requested
    if not selected or selected.keys() - counts.keys():
        raise ValueError("--ids must select episode IDs in this A/B/C archive")
    return selected


def load_groups(primary, manifest, requested, spool):
    counts = defaultdict(lambda: dict.fromkeys(STREAMS, 0))
    for stream in STREAMS:
        name = stream + ".jsonl"
        expected = manifest["files"][name]
        checksum = hashlib.sha256()
        with primary.open(name) as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                checksum.update(chunk)
        if primary.members[name].size != expected["bytes"] or checksum.hexdigest() != expected["sha256"]:
            raise ValueError(f"{name}: size or SHA-256 differs from MANIFEST.json")
        with primary.open(name) as source:
            for line in source:
                spool_row(line, stream, counts, requested, spool)
    return validate_index(manifest, counts, requested)


def read_spooled(path):
    rows = {stream: [] for stream in STREAMS}
    with path.open("rb") as source:
        for line in source:
            stream, payload = line.split(b"\t", 1)
            rows[stream.decode("ascii")].append(json.loads(payload))
    return rows


def release_version(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("Manifest must contain a non-empty string version")
    if not re.fullmatch(r"v1\.(?:[2-9]|[1-9][0-9]+)\.\d+", version) or manifest.get("schema_version", 1) != 1:
        raise ValueError(f"Unsupported A/B/C release format: {version}")
    return version


def run(args, serve):
    with ExitStack() as stack:
        primary = Archive(stack, args.manifest)
        raw = primary.read("MANIFEST.json")
        manifest = json.loads(raw)
        version = release_version(manifest)
        render = args.port is not None
        spool = Path(stack.enter_context(TemporaryDirectory()))
        requested = dict.fromkeys(args.ids.read_text().split()) if args.ids else None
        selected = load_groups(primary, manifest, requested, spool)
        pages, receipts, links = {}, [], []
        pngs = {} if render else None
        zips = {} if render else None
        bases = [Archive(stack, path) for path in dict.fromkeys(p.resolve() for p in args.base_tar)]
        assets = Assets([primary, *bases], pngs, base_hint(manifest, bases))
        for ident in selected:
            row_path = spool / ident
            rows = read_spooled(row_path)
            row_path.unlink()
            body, receipt = episode(ident, rows, assets, zips)
            assets.checked.clear()
            del rows
            if render:
                route = "/episode/" + ident
                row_path.write_bytes(page(version, body))
                pages[route] = row_path
                links.append(f'<li><a href="{route}">{ident}</a> · {escape(receipt["focus"])} · {escape(receipt["status"])}</li>')
            receipts.append(receipt)
        if render:
            index = spool / "index.html"
            index.write_bytes(page(version, "<h1>MiMo A/B/C episodes</h1>" +
                index_counts(manifest, len(selected)) + "<ol>" + "".join(links) + "</ol>"))
            pages["/"] = index
        if args.receipt:
            args.receipt.write_text(json.dumps({"release": version, "manifest_sha256": sha(raw),
                "dependencies": manifest.get("dependencies", []), "episodes": receipts}, ensure_ascii=False, indent=2) + "\n")
        if args.port is not None:
            serve(args.port, pages, pngs, zips)
        if args.strict and any(item["errors"] for item in receipts):
            return 1
