#!/usr/bin/env python3
"""Locate/extract the exact recovered WM163 Session-A loader from a local archive.

This tool does not contain or distribute the loader. It only finds a local file
whose size and MD5 match the already-recovered DrGrey loader fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import sys
import zipfile

EXPECTED_SIZE = 743_120
EXPECTED_MD5 = "72f7a3d3f40648c9e6c02583360c16b3"


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def scan_zip(path: pathlib.Path):
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir() or info.file_size != EXPECTED_SIZE:
                continue
            data = zf.read(info)
            if md5_bytes(data) == EXPECTED_MD5:
                return info.filename, data
    return None


def scan_dir(path: pathlib.Path):
    for p in path.rglob("*"):
        if not p.is_file():
            continue
        try:
            if p.stat().st_size != EXPECTED_SIZE:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if md5_bytes(data) == EXPECTED_MD5:
            return str(p), data
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Find the exact WM163 Session-A loader in a local DrGrey ZIP/folder"
    )
    ap.add_argument("source", help="DrGrey recovery ZIP or extracted directory")
    ap.add_argument(
        "--output",
        default="session_a_loader.bin",
        help="output filename (default: session_a_loader.bin)",
    )
    args = ap.parse_args()

    src = pathlib.Path(args.source)
    if not src.exists():
        print(f"ERROR: source does not exist: {src}", file=sys.stderr)
        return 2

    try:
        found = scan_zip(src) if src.is_file() and zipfile.is_zipfile(src) else scan_dir(src)
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if found is None:
        print(
            f"NOT FOUND: no {EXPECTED_SIZE}-byte file with MD5 {EXPECTED_MD5}",
            file=sys.stderr,
        )
        return 3

    name, data = found
    out = pathlib.Path(args.output)
    out.write_bytes(data)

    print(f"FOUND: {name}")
    print(f"SIZE:  {len(data)}")
    print(f"MD5:   {md5_bytes(data)}")
    print(f"WROTE: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
