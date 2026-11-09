import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
import warnings
from zipfile import ZipFile

from abc_release import PNG
from audit_abc_releases import audit
from check_abc_release import check as check_release
from download_abc_bases import fetch_base
from export_replay import export, plan
from restore_replay_step import workspace_at
from replay_episode import zipped
from verify_step_receipt import verify as verify_step
from verify_abc_tallies import verify as verify_tallies
from verify_replay_sample import verify

TOOLS = Path(__file__).parent
ID = "a" * 20


def asset(data, suffix):
    sha = hashlib.sha256(data).hexdigest()
    return {"file": f"assets/{sha}.{suffix}", "sha256": sha}


def write_tar(path, files):
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def sample(path, *, remove_digest):
    html, png = b"<!doctype html><title>Sample</title>", PNG + struct.pack(">II", 1, 1)
    document, image = asset(html, "html"), asset(png, "png") | {"size": [1, 1]}
    media = {document["file"]: html, image["file"]: png}
    if remove_digest:
        del image["sha256"]
    rows = {
        "full_trajectory": [{"episode_id": ID, "turns": [{"messages": [image]}]}],
        "final_task_to_html": [{"episode_id": ID, "focus": "C", "status": "completed",
                               "starting_files": {"index.html": document}, "final_files": {"index.html": document}}],
        "observations": [], "single_edit": [],
    }
    streams = {k + ".jsonl": b"".join(json.dumps(x).encode() + b"\n" for x in v) for k, v in rows.items()}
    manifest = {"version": "v1.9.0", "episodes": 1, "episode_ids": [ID],
                "files": {k: {"bytes": len(v), "sha256": hashlib.sha256(v).hexdigest()}
                          for k, v in streams.items()}}
    write_tar(path, {"MANIFEST.json": json.dumps(manifest).encode(), **streams, **media})


class ReleaseToolsTest(unittest.TestCase):
    def test_export_rejects_corrupted_selected_reference_before_install(self):
        with TemporaryDirectory() as tmp:
            t = Path(tmp)
            source, out = t / "source.tar.gz", t / "sample.tar.gz"
            sample(source, remove_digest=True)
            with self.assertRaisesRegex(ValueError, "Invalid asset reference"):
                export(source, (), {ID: None}, out)
            self.assertFalse(out.exists())
            sample(source, remove_digest=False)
            result = export(source, (t / "unused-base.tar.gz",), {ID: None}, out)
            self.assertEqual(result["content_addressed_assets"], 2)
            self.assertTrue(out.is_file())
            second = t / "same-selection.tar.gz"
            export(source, (), {ID: None}, second)
            self.assertEqual(out.read_bytes(), second.read_bytes())
            self.assertEqual(out.read_bytes()[4:8], b"\0" * 4)

    def test_fetch_rejects_incomplete_plan_before_downloading(self):
        with TemporaryDirectory() as tmp:
            t = Path(tmp)
            manifest = t / "MANIFEST.json"
            manifest.write_text(json.dumps({"version": "v1.9.0", "assets_reused_from": {"v1.3.0": 1},
                                            "dependencies": []}))
            out = t / "download"
            p = subprocess.run([sys.executable, str(TOOLS / "download_abc_bases.py"), str(manifest), str(out), "--fetch"],
                               capture_output=True, text=True, timeout=10)
            self.assertEqual(p.returncode, 2)
            self.assertIn("v1.3.0", p.stderr)
            self.assertFalse(out.exists())

    def test_partial_production_chain_does_not_verify_cumulative_claim(self):
        report = audit([{"version": "v1.9.0", "previous_release": "v1.8.0",
                         "episodes": 1, "episode_ids": [ID], "cumulative_unique_abc_episodes": 1332}])
        self.assertEqual(report["known_unique"], 1)
        self.assertFalse(report["unique_complete"])
        self.assertIsNone(report["cumulative_unique"])
        self.assertEqual(report["issues"], ["v1.9.0: missing production manifest for v1.8.0"])

    def test_sample_verifier_detects_edited_evidence_with_valid_stream_hash(self):
        with TemporaryDirectory() as tmp:
            t = Path(tmp)
            source, exported, changed = (t / name for name in ("source.tar.gz", "sample.tar.gz", "changed.tar.gz"))
            sample(source, remove_digest=False)
            export(source, (), {ID: None}, exported)
            self.assertTrue(verify(source, exported)["verified"])
            with tarfile.open(exported) as archive:
                files = {member.name: archive.extractfile(member).read() for member in archive}
            stream = "final_task_to_html.jsonl"
            row = json.loads(files[stream])
            row["status"] = "failed"
            files[stream] = (json.dumps(row) + "\n").encode()
            manifest = json.loads(files["MANIFEST.json"])
            manifest["files"][stream] = {"bytes": len(files[stream]), "sha256": hashlib.sha256(files[stream]).hexdigest()}
            files["MANIFEST.json"] = json.dumps(manifest).encode()
            with tarfile.open(changed, "w:gz") as archive:
                for name, data in files.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            result = verify(source, changed)
            self.assertFalse(result["verified"])
            self.assertEqual(result["issues"], [{"id": ID, "stream": "final_task_to_html", "error": "Recorded rows differ"}])

    def test_embedded_manifest_plan_and_selected_archive_plan(self):
        with TemporaryDirectory() as tmp:
            t = Path(tmp)
            archive = t / "source.tar.gz"
            sample(archive, remove_digest=False)
            p = subprocess.run([sys.executable, str(TOOLS / "download_abc_bases.py"), str(archive), str(t)],
                               capture_output=True, text=True, timeout=10)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)["replay_args"], [])
            selected = plan(archive, [t / "unused.tar.gz"], {ID: None})
            self.assertEqual(selected["archives"], [{"path": str(archive), "assets": 2}])
            self.assertEqual(selected["selected_ids"], [ID])

    def test_recorded_workspace_does_not_unlock_future_files(self):
        initial = asset(b"initial", "html")
        edited = asset(b"edited", "html")
        requirement = asset(b"new requirement", "md")
        rows = {
            "full_trajectory": [{"turns": [{"step": 1}, {"step": 2}]}],
            "final_task_to_html": [{"starting_files": {"index.html": initial},
                                    "runtime_requirements": {"release-01.md": {"released_after_step": 2, "asset": requirement}}}],
            "single_edit": [{"step": 1, "file": "index.html", "audit_assets": {"before": initial, "after": edited}}],
            "observations": [],
        }
        self.assertEqual(workspace_at(rows, 1), {"index.html": edited})
        self.assertEqual(workspace_at(rows, 2), {"index.html": edited, "release-01.md": requirement})
        rows["single_edit"][0]["audit_assets"]["before"] = edited
        with self.assertRaisesRegex(ValueError, "version gap"):
            workspace_at(rows, 1)

    def test_step_receipt_checks_each_file_after_zip_digest(self):
        with TemporaryDirectory() as tmp:
            archive = Path(tmp) / "step.zip"
            content = b"recorded file"
            raw = zipped({"index.html": content}, reproducible=True)
            archive.write_bytes(raw)
            receipt = {"release": "v1.9.0", "episode_id": ID, "step": 0,
                       "zip_sha256": hashlib.sha256(raw).hexdigest(),
                       "files": {"index.html": hashlib.sha256(content).hexdigest()}}
            self.assertEqual(verify_step(archive, receipt)["files_verified"], 1)
            receipt["files"]["index.html"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "Incorrect file SHA-256"):
                verify_step(archive, receipt)

    def test_step_receipt_rejects_repeated_member_with_matching_zip_digest(self):
        with TemporaryDirectory() as tmp:
            archive = Path(tmp) / "duplicated.zip"
            content = b"recorded bytes"
            with ZipFile(archive, "w") as z, warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=r"Duplicate name:.*", category=UserWarning)
                z.writestr("index.html", content)
                z.writestr("index.html", content)
            receipt = {"release": "v1.9.0", "episode_id": ID, "step": 0,
                       "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                       "files": {name: hashlib.sha256(content).hexdigest()
                                 for name in ("index.html", "panel.css")}}
            with self.assertRaisesRegex(ValueError, "ZIP entries differ"):
                verify_step(archive, receipt)

    def test_tally_verifier_does_not_trust_manifest_counts(self):
        with TemporaryDirectory() as tmp:
            t = Path(tmp)
            source, altered = t / "source.tar.gz", t / "altered.tar.gz"
            sample(source, remove_digest=False)
            with tarfile.open(source) as archive:
                files = {member.name: archive.extractfile(member).read() for member in archive}
            manifest = json.loads(files["MANIFEST.json"])
            manifest["by_focus_and_state"] = {"C/completed": 2}
            files["MANIFEST.json"] = json.dumps(manifest).encode()
            with tarfile.open(altered, "w:gz") as archive:
                for name, data in files.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            result = verify_tallies(altered)
            self.assertFalse(result["verified"])
            self.assertEqual(result["differences"], {"C/completed": {"declared": 2, "recorded": 1}})

    def test_streamed_parent_rejects_corruption_outside_selection(self):
        with TemporaryDirectory() as tmp:
            t = Path(tmp)
            source, exported, altered = (t / n for n in ("source.tar.gz", "sample.tar.gz", "altered.tar.gz"))
            sample(source, remove_digest=False)
            with tarfile.open(source) as archive:
                files = {member.name: archive.extractfile(member).read() for member in archive}
            manifest = json.loads(files["MANIFEST.json"])
            other = "b" * 20
            manifest["episodes"] = 2
            manifest["episode_ids"].append(other)
            for name in ("final_task_to_html.jsonl", "full_trajectory.jsonl"):
                row = json.loads(files[name])
                row["episode_id"] = other
                files[name] += (json.dumps(row) + "\n").encode()
                manifest["files"][name] = {"bytes": len(files[name]), "sha256": hashlib.sha256(files[name]).hexdigest()}
            files["MANIFEST.json"] = json.dumps(manifest).encode()
            write_tar(source, files)
            export(source, (), {ID: None}, exported)
            self.assertTrue(verify(source, exported)["verified"])
            name = "final_task_to_html.jsonl"
            first, second = files[name].splitlines()
            files[name] = first + b"\n" + second.replace(b"completed", b"incomplete", 1) + b"\n"
            write_tar(altered, files)
            with self.assertRaisesRegex(ValueError, "SHA-256 differs from parent"):
                verify(altered, exported)

    def test_release_pin_preflight_requires_identical_embedded_metadata(self):
        with TemporaryDirectory() as tmp:
            t = Path(tmp)
            source, manifest, sums = t / "source.tar.gz", t / "MANIFEST.json", t / "SHA256SUMS"
            sample(source, remove_digest=False)
            with tarfile.open(source) as archive:
                manifest.write_bytes(archive.extractfile("MANIFEST.json").read())
            def write_sums():
                sums.write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                                        for path in (source, manifest)))
            write_sums()
            self.assertTrue(check_release(source, manifest, sums)["verified"])
            renamed = t / "renamed archive.tar.gz"
            renamed.write_bytes(source.read_bytes())
            with self.assertRaisesRegex(ValueError, "named asset"):
                check_release(renamed, manifest, sums)
            self.assertTrue(check_release(renamed, manifest, sums, source.name)["verified"])
            manifest.write_bytes(manifest.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "Standalone MANIFEST.json SHA-256"):
                check_release(source, manifest, sums)
            write_sums()
            with self.assertRaisesRegex(ValueError, "Standalone and embedded MANIFEST.json differ"):
                check_release(source, manifest, sums)

    def test_base_planner_requires_primary_release_version(self):
        with TemporaryDirectory() as tmp:
            t = Path(tmp)
            manifest = t / "MANIFEST.json"
            manifest.write_text('{"dependencies":[]}')
            out = t / "download"
            p = subprocess.run([sys.executable, str(TOOLS / "download_abc_bases.py"), str(manifest), str(out), "--fetch"],
                               capture_output=True, text=True, timeout=10)
            self.assertEqual(p.returncode, 2)
            self.assertIn("version", p.stderr)
            self.assertNotIn("Traceback", p.stderr)
            self.assertFalse(out.exists())

    def test_base_plan_emits_replay_args_only_for_verified_bases(self):
        with TemporaryDirectory(prefix="bases with spaces ") as tmp:
            t = Path(tmp)
            manifest = t / "MANIFEST.json"
            base = t / "mimo-nextgen-abc-v1.tar.gz"
            content = b"example verified base bytes"
            sha = hashlib.sha256(content).hexdigest()
            manifest.write_text(json.dumps({"version": "v1.3.0", "dependencies": [
                {"version": "v1.2.0", "sha256": sha},
            ]}))
            cmd = [sys.executable, str(TOOLS / "download_abc_bases.py"), str(manifest), str(t)]
            missing = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            self.assertEqual(missing.returncode, 1)
            self.assertIsNone(json.loads(missing.stdout)["replay_args"])
            base.write_bytes(content)
            ready = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            self.assertEqual(ready.returncode, 0, ready.stderr)
            output = json.loads(ready.stdout)
            self.assertEqual(output["bases"][0]["sha256"], sha)
            self.assertEqual(output["replay_args"], ["--base-tar", str(base)])

    def test_transient_gateway_failure_retries_one_resumed_range(self):
        content = b"verified range data" * 1500
        prefix = 11111
        ranges = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                ranges.append(self.headers.get("Range"))
                if len(ranges) == 1:
                    self.send_response(504)
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {prefix}-{len(content)-1}/{len(content)}")
                self.send_header("Content-Length", str(len(content)-prefix))
                self.end_headers()
                self.wfile.write(content[prefix:])

        with HTTPServer(("127.0.0.1", 0), Handler) as server, TemporaryDirectory() as tmp:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                target = Path(tmp) / "base.tar.gz"
                target.with_suffix(".gz.part").write_bytes(content[:prefix])
                fetch_base(f"http://127.0.0.1:{server.server_port}/archive",
                           hashlib.sha256(content).hexdigest(), target)
                self.assertEqual(ranges, [f"bytes={prefix}-"] * 2)
                self.assertEqual(target.read_bytes(), content)
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
