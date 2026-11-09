import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from download_release import download

DATA = bytes(range(256)) * 1024
CUT = 65536 + 17


class DownloadTest(unittest.TestCase):
    def test_interrupted_http_response_resumes_at_verified_offset(self):
        ranges = []
        replies = iter(("cut", "bad", "finish"))

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                mode = next(replies)
                ranges.append(self.headers.get("Range"))
                self.send_response(200 if mode == "cut" else 206)
                self.send_header("Content-Length", str(len(DATA) if mode == "cut" else len(DATA) - CUT))
                if mode != "cut":
                    start = CUT + (mode == "bad")
                    self.send_header("Content-Range", f"bytes {start}-{len(DATA)-1}/{len(DATA)}")
                self.end_headers()
                if mode != "bad":
                    self.wfile.write(DATA[:CUT] if mode == "cut" else DATA[CUT:])

        with HTTPServer(("127.0.0.1", 0), Handler) as server, TemporaryDirectory() as folder:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/asset"
                target = Path(folder) / "asset.tar.gz"
                part = Path(folder) / "asset.tar.gz.part"
                sha = hashlib.sha256(DATA).hexdigest()
                with self.assertRaisesRegex(ValueError, "interrupted"):
                    download(url, sha, target)
                self.assertFalse(target.exists())
                self.assertEqual(part.read_bytes(), DATA[:CUT])
                with self.assertRaisesRegex(ValueError, "Content-Range"):
                    download(url, sha, target)
                self.assertEqual(part.read_bytes(), DATA[:CUT])
                download(url, sha, target)
                self.assertEqual(ranges, [None, f"bytes={CUT}-", f"bytes={CUT}-"])
                self.assertFalse(part.exists())
                self.assertEqual(target.read_bytes(), DATA)
            finally:
                server.shutdown()
                thread.join()

    def test_ignored_range_only_replaces_saved_part_after_verification(self):
        ranges = []
        replies = iter((DATA[:8192], b"x" * len(DATA), DATA))

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                ranges.append(self.headers.get("Range"))
                self.send_response(200)
                self.send_header("Content-Length", str(len(DATA)))
                self.end_headers()
                self.wfile.write(next(replies))

        with HTTPServer(("127.0.0.1", 0), Handler) as server, TemporaryDirectory() as folder:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/asset"
                target = Path(folder) / "asset.tar.gz"
                part = Path(folder) / "asset.tar.gz.part"
                part.write_bytes(DATA[:CUT])
                sha = hashlib.sha256(DATA).hexdigest()
                for reason in ("interrupted", "SHA-256"):
                    with self.assertRaisesRegex(ValueError, reason):
                        download(url, sha, target)
                    self.assertEqual(part.read_bytes(), DATA[:CUT])
                    self.assertEqual(list(target.parent.iterdir()), [part])
                download(url, sha, target)
                self.assertEqual(ranges, [f"bytes={CUT}-"] * 3)
                self.assertFalse(part.exists())
                self.assertEqual(target.read_bytes(), DATA)
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
