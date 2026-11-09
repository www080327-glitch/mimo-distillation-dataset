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

from abc_release import PNG
from audit_abc_releases import audit
from download_abc_bases import fetch_base
from export_replay import export

TOOLS = Path(__file__).parent
ID = "a" * 20


def asset(data, suffix):
    sha = hashlib.sha256(data).hexdigest()
    return {"file": f"assets/{sha}.{suffix}", "sha256": sha}


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
    with tarfile.open(path, "w:gz") as tar:
        for name, data in {"MANIFEST.json": json.dumps(manifest).encode(), **streams, **media}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


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
