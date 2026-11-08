# test_reassemble.py
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import reassemble_media as sut


def record(filename, data):
    return {
        "name": filename,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


class ReassemblyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.out = self.root / "out"
        self.manifest = self.root / "manifest.json"

        # Cross the reader's 1 MiB boundary and include binary data.
        blocks = [b"A" * ((1 << 20) + 3), b"\x00\xffsecond part\n"]
        parts = []
        for index, data in enumerate(blocks, 1):
            filename = f"bundle.bin.part{index:02}"
            (self.root / filename).write_bytes(data)
            parts.append(record(filename, data))

        self.joined = b"".join(blocks)
        self.split = record("bundle.bin", self.joined)
        self.split["parts"] = parts

        self.plain_data = b"ordinary asset\n"
        self.plain = record("ordinary.txt", self.plain_data)
        (self.root / self.plain["name"]).write_bytes(self.plain_data)

    def cli(self, entries=None, rebuild=True):
        if entries is None:
            entries = [self.split, self.plain]
        self.manifest.write_text(
            json.dumps({"files": entries}), encoding="utf-8"
        )
        argv = ["reassemble", str(self.manifest)]
        if rebuild:
            argv += ["--out", str(self.out)]

        self.stdout = io.StringIO()
        with patch.object(sys, "argv", argv):
            with contextlib.redirect_stdout(self.stdout):
                sut.main()
        return self.stdout.getvalue()

    def assert_no_publication(self):
        contents = list(self.out.iterdir()) if self.out.exists() else []
        self.assertEqual(contents, [], "Final or temporary output remains")
        self.assertEqual(self.stdout.getvalue(), "", "Reported false success")

    def test_verify_only_checks_both_assets_without_output(self):
        text = self.cli(rebuild=False)
        self.assertEqual(
            text, "Verified: bundle.bin\nVerified: ordinary.txt\n"
        )
        self.assertFalse(self.out.exists())

    def test_reassemble_multipart(self):
        self.assertEqual(
            self.cli([self.split]), "Verified: bundle.bin\n"
        )
        result = self.out / self.split["name"]
        self.assertEqual(result.read_bytes(), self.joined)
        self.assertEqual(list(self.out.iterdir()), [result])

    def test_ordinary_asset_with_out_is_verified_not_copied(self):
        self.assertEqual(
            self.cli([self.plain]), "Verified: ordinary.txt\n"
        )
        self.assertFalse(self.out.exists())
        self.assertEqual(
            (self.root / self.plain["name"]).read_bytes(), self.plain_data
        )

    def test_missing_later_part_removes_partial_work(self):
        (self.root / self.split["parts"][1]["name"]).unlink()
        with self.assertRaises(FileNotFoundError):
            self.cli([self.split])
        self.assert_no_publication()

    def test_reversed_parts_fail_logical_hash(self):
        entry = copy.deepcopy(self.split)
        entry["parts"].reverse()
        with self.assertRaisesRegex(ValueError, "Bad logical asset"):
            self.cli([entry])
        self.assert_no_publication()

    def test_incorrect_sizes_and_hashes(self):
        for scope in ("chunk", "logical", "ordinary"):
            for field in ("bytes", "sha256"):
                with self.subTest(scope=scope, field=field):
                    entry = copy.deepcopy(
                        self.plain if scope == "ordinary" else self.split
                    )
                    item = entry["parts"][0] if scope == "chunk" else entry
                    item[field] = (
                        item[field] + 1 if field == "bytes" else "0" * 64
                    )
                    message = (
                        "Bad logical asset" if scope == "logical"
                        else "Bad chunk"
                    )
                    with self.assertRaisesRegex(ValueError, message):
                        self.cli([entry])
                    self.assert_no_publication()

    def test_keyboard_interrupt_removes_partial_work(self):
        original_open = Path.open
        second_part = self.root / self.split["parts"][1]["name"]

        def interrupt_open(path, mode="r", *args, **kwargs):
            if path == second_part and mode == "rb":
                # The first part has already passed through real verify().
                self.assertFalse((self.out / self.split["name"]).exists())
                raise KeyboardInterrupt("deliberate test abort")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", interrupt_open):
            with self.assertRaises(KeyboardInterrupt):
                self.cli([self.split])
        self.assert_no_publication()

    def test_existing_output_is_preserved(self):
        self.out.mkdir()
        result = self.out / self.split["name"]
        result.write_bytes(b"keep existing output")

        with self.assertRaises(FileExistsError):
            self.cli([self.split])

        self.assertEqual(result.read_bytes(), b"keep existing output")
        self.assertEqual(list(self.out.iterdir()), [result])
        self.assertEqual(self.stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
