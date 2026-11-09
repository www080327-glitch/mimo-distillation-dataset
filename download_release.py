#!/usr/bin/env python3
"""Resume one anonymous MiMo Release asset and verify it before giving it its final name."""
import argparse
import hashlib
from http.client import HTTPException
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from reassemble_media import name

REPO = "www080327-glitch/mimo-distillation-dataset"
BLOCK = 256 * 1024


def checksum(sums, asset):
    matches = [m[1].lower() for line in sums.read_text().splitlines()
               if (m := re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)) and m[2] == asset]
    if len(matches) != 1:
        raise ValueError("SHA256SUMS must contain exactly one entry for the named asset")
    return matches[0]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(BLOCK), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, expected, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    if target.exists():
        if digest(target) != expected:
            raise ValueError("Existing download has the wrong SHA-256")
        return
    if part.exists() and digest(part) == expected:
        part.replace(target)
        return
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("Unexpected content encoding; no bytes appended")
        if response.status == 206:
            m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
            if not m or int(m[1]) != offset or not offset <= int(m[2]) < int(m[3]):
                raise ValueError("Content-Range does not match the saved offset; no bytes appended")
            limit = int(m[2]) - offset + 1
            mode = "ab"
        elif response.status == 200:
            length = response.headers.get("Content-Length")
            limit = int(length) if length else None
            mode = "wb"
        else:
            raise ValueError(f"Unexpected HTTP status {response.status}")
        # Don't truncate an earlier partial file when a fresh response has no body.
        chunk = response.read1(BLOCK)
        if not chunk:
            raise ValueError("Empty response; previous partial file kept")
        count = 0
        with part.open(mode) as out:
            while chunk:
                count += len(chunk)
                if limit is not None and count > limit:
                    raise ValueError("Response exceeds its declared byte range")
                out.write(chunk)
                chunk = response.read1(BLOCK)
    if limit is not None and count != limit:
        raise ValueError("Transfer interrupted; retry to resume the partial file")
    if digest(part) != expected:
        raise ValueError("SHA-256 has not matched; partial file kept")
    part.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("asset")
    parser.add_argument("sha256sums", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        tag, asset = name(args.tag), name(args.asset)
        url = f"https://github.com/{REPO}/releases/download/{tag}/{asset}?download=1"
        target = args.output / asset
        download(url, checksum(args.sha256sums, asset), target)
    except HTTPError as exc:
        print(f"HTTP {exc.code}; partial file kept if present. Retry or check the release name.", file=sys.stderr)
        return 1
    except (OSError, HTTPException) as exc:
        print(f"{type(exc).__name__}; check the download connection or output directory and retry.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Verified: {target}")


if __name__ == "__main__":
    raise SystemExit(main())
