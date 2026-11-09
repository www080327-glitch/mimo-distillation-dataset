import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest

from abc_release import STREAMS

REPLAY = Path(__file__).with_name("replay_episode.py")


class SelectedReceiptTest(unittest.TestCase):
    def test_rejects_duplicate_unselected_primary_row_with_valid_hash(self):
        selected, other = "a" * 20, "b" * 20
        with TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "test.tar.gz"
            ids = root / "ids"
            ids.write_text(selected + "\n")
            manifest = {"version": "v1.5.0", "episodes": 2,
                        "episode_ids": [selected, other], "files": {}}
            with tarfile.open(archive, "w:gz") as tar:
                def add(name, data):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))

                for stream in STREAMS:
                    stream_ids = ([selected, other, other] if stream == "full_trajectory"
                                  else [selected, other] if stream == "final_task_to_html" else [])
                    data = b"".join(json.dumps({"episode_id": ident}).encode() + b"\n"
                                    for ident in stream_ids)
                    name = stream + ".jsonl"
                    manifest["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                    add(name, data)
                add("MANIFEST.json", json.dumps(manifest).encode())
            receipt = root / "receipt.json"
            proc = subprocess.run([sys.executable, str(REPLAY), str(archive), "--abc-tar",
                                   "--ids", str(ids), "--receipt", str(receipt), "--strict"],
                                  capture_output=True, text=True, check=False, timeout=15)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("Episode index differs from the recorded streams", proc.stderr)
            self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
