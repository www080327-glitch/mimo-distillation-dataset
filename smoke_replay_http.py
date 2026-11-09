#!/usr/bin/env python3
"""Check a local A/B/C replay page and its recorded asset downloads over loopback."""
import argparse
from contextlib import closing
import hashlib
from http.client import HTTPConnection, HTTPException
import io
import json
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from zipfile import BadZipFile, ZipFile

from abc_release import ID


def get(port, route):
    with closing(HTTPConnection("127.0.0.1", port, timeout=10)) as conn:
        conn.request("GET", route)
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError(f"{route}: HTTP {response.status}")
        return response.read()


def smoke(source, bases, ident, expected_pngs=None):
    if not ID.fullmatch(ident):
        raise ValueError("An explicit full lowercase episode ID is required")
    with TemporaryDirectory() as td:
        work = Path(td)
        ids, receipt = work / "ids", work / "receipt.json"
        ids.write_text(ident + "\n")
        command = [sys.executable, "-u", str(Path(__file__).with_name("replay_episode.py")),
                   str(source), "--abc-tar", "--ids", str(ids), "--receipt", str(receipt), "--port", "0"]
        for base in bases:
            command.extend(("--base-tar", str(base)))
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as process:
            try:
                ready = Queue()
                Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
                try:
                    line = ready.get(timeout=35).strip()
                except Empty as exc:
                    raise ValueError("Replay server did not start within 35 seconds") from exc
                addr = re.fullmatch(r"Open http://127\.0\.0\.1:(\d{1,5})/", line)
                if not addr:
                    raise ValueError("Replay server did not publish a loopback address")
                port = int(addr[1])
                data = json.loads(receipt.read_text())["episodes"][0]
                if data["errors"]:
                    raise ValueError("; ".join(data["errors"]))
                route = f"/episode/{ident}"
                if route.encode() not in get(port, "/"):
                    raise ValueError("Selected episode missing from the index")
                body = get(port, route)
                pngs = dict.fromkeys(re.findall(rb'<img src="(/assets/[0-9a-f]{64}\.png)"', body))
                if expected_pngs is not None:
                    rendered = {Path(raw.decode("ascii")).stem for raw in pngs}
                    missing, unexpected = expected_pngs-rendered, rendered-expected_pngs
                    if missing or unexpected:
                        raise ValueError("Rendered PNG set differs: "
                                         f"missing={sorted(missing)}, unexpected={sorted(unexpected)}")
                for raw in pngs:
                    image_path = raw.decode("ascii")
                    if hashlib.sha256(get(port, image_path)).hexdigest() != Path(image_path).stem:
                        raise ValueError(f"{image_path}: incorrect PNG bytes")
                zips = {}
                for label, files in data["projects"].items():
                    if files is None:
                        continue
                    path = f"/project/{ident}/{label}.zip"
                    if path.encode() not in body:
                        raise ValueError(f"{label} project link missing from the episode page")
                    with ZipFile(io.BytesIO(get(port, path))) as archive:
                        if archive.testzip() is not None or sorted(archive.namelist()) != sorted(files):
                            raise ValueError(f"{label} ZIP contents disagree with the receipt")
                    zips[label] = len(files)
                return {"episode_id": ident, "status": data["status"], "verified_pngs": len(pngs),
                        "verified_zip_files": zips}
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--base-tar", type=Path, action="append", default=[])
    p.add_argument("--episode", required=True)
    p.add_argument("--expected-pngs", type=Path, help="Expected distinct rendered PNG hashes, one SHA-256 per line")
    args = p.parse_args()
    try:
        expected = None
        if args.expected_pngs is not None:
            expected = {line.strip() for line in args.expected_pngs.read_text().splitlines() if line.strip()}
            if any(not re.fullmatch(r"[0-9a-f]{64}", sha) for sha in expected):
                raise ValueError("Expected PNG list must contain lowercase SHA-256 values")
        report = smoke(args.archive, args.base_tar, args.episode, expected)
    except (ValueError, OSError, KeyError, IndexError, HTTPException, BadZipFile) as exc:
        p.exit(1, f"Replay smoke failed: {exc}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
