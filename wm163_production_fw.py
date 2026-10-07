#!/usr/bin/env python3
"""Exact offline validator for the verified DJI Mini 3 / WM163 v01.00.0500 production firmware.

This module contains no transport or flashing code.  It exists so a future
production-firmware restore path can refuse any image that is not the exact
known-good WM163 archive recovered and verified for this project.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tarfile
import xml.etree.ElementTree as ET

from wm163_service_fw_inspect import PackageInfo, inspect_package


EXPECTED_DEVICE = "wm163"
EXPECTED_FORMAL = "01.00.0500"
DEFAULT_PRODUCTION_FILENAME = "V01.00.0500_wm163_dji_system.bin"
EXPECTED_ARCHIVE_SIZE = 53_329_920
EXPECTED_ARCHIVE_MD5 = "1ab6fa851af2afb3a9faeddd0ff093b3"
EXPECTED_ARCHIVE_SHA256 = "38f654fb8b60c4c7c2d28afccddfd131228dc8a2a42df65b54a4cd2d65666a0e"
EXPECTED_ANTIROLLBACK = "0"
EXPECTED_ANTIROLLBACK_EXT = "cn:0"
EXPECTED_ENFORCE = "0"
EXPECTED_MODULE_VERSIONS = (
    ("0905", "01.00.01.27"),
    ("0306", "03.04.11.34"),
    ("1200", "01.10.02.15"),
    ("1100", "10.75.00.17"),
    ("0105", "12.07.00.12"),
    ("0100", "01.64.01.52"),
)


def validate_production_info(
    info: PackageInfo,
    *,
    archive_size: int,
) -> PackageInfo:
    """Validate parsed metadata against the exact known WM163 v01.00.0500 image."""

    if info.device.lower() != EXPECTED_DEVICE:
        raise ValueError(f"wrong device: expected {EXPECTED_DEVICE}, got {info.device!r}")

    if info.formal != EXPECTED_FORMAL or info.release != EXPECTED_FORMAL:
        raise ValueError(
            "wrong production formal/release: "
            f"expected {EXPECTED_FORMAL}/{EXPECTED_FORMAL}, "
            f"got {info.formal}/{info.release}"
        )

    if archive_size != EXPECTED_ARCHIVE_SIZE:
        raise ValueError(
            f"wrong archive size: expected {EXPECTED_ARCHIVE_SIZE}, got {archive_size}"
        )

    if info.md5.lower() != EXPECTED_ARCHIVE_MD5:
        raise ValueError(
            "archive MD5 does not match the verified WM163 v01.00.0500 image"
        )

    if info.sha256.lower() != EXPECTED_ARCHIVE_SHA256:
        raise ValueError(
            "archive SHA256 does not match the verified WM163 v01.00.0500 image"
        )

    if info.antirollback != EXPECTED_ANTIROLLBACK:
        raise ValueError(
            f"unexpected antirollback={info.antirollback!r}; expected {EXPECTED_ANTIROLLBACK!r}"
        )
    if info.antirollback_ext != EXPECTED_ANTIROLLBACK_EXT:
        raise ValueError(
            "unexpected antirollback_ext="
            f"{info.antirollback_ext!r}; expected {EXPECTED_ANTIROLLBACK_EXT!r}"
        )
    if info.enforce != EXPECTED_ENFORCE:
        raise ValueError(
            f"unexpected enforce={info.enforce!r}; expected {EXPECTED_ENFORCE!r}"
        )

    actual_modules = tuple((mod.module_id, mod.version) for mod in info.modules)
    if actual_modules != EXPECTED_MODULE_VERSIONS:
        expected = " -> ".join(f"{mid}:{ver}" for mid, ver in EXPECTED_MODULE_VERSIONS)
        actual = " -> ".join(f"{mid}:{ver}" for mid, ver in actual_modules)
        raise ValueError(
            f"production module set mismatch: expected [{expected}], got [{actual}]"
        )

    return info


def find_repo_production_archive(
    base_dir: str | pathlib.Path | None = None,
) -> pathlib.Path | None:
    """Return the repo-local verified-production candidate when present.

    This only locates the canonical firmware path; callers must still run
    validate_production_archive() before treating the file as verified.
    """

    root = pathlib.Path(base_dir) if base_dir is not None else pathlib.Path(__file__).resolve().parent
    candidate = root / "firmware" / DEFAULT_PRODUCTION_FILENAME
    return candidate if candidate.is_file() else None


def validate_production_archive(path: str | pathlib.Path) -> PackageInfo:
    """Inspect and positively identify the exact verified production archive."""

    path = pathlib.Path(path)
    size = path.stat().st_size
    info = inspect_package(path, require_known_v30=False)
    return validate_production_info(info, archive_size=size)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate exact DJI Mini 3 / WM163 v01.00.0500 production firmware"
    )
    parser.add_argument("path", help="path to V01.00.0500_wm163_dji_system.bin")
    args = parser.parse_args()

    path = pathlib.Path(args.path)
    try:
        info = validate_production_archive(path)
    except (OSError, tarfile.TarError, ET.ParseError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2

    print("VALID exact WM163 production firmware")
    print(f"path={path}")
    print(f"device={info.device}")
    print(f"formal={info.formal}")
    print(f"release={info.release}")
    print(f"size={path.stat().st_size}")
    print(f"md5={info.md5}")
    print(f"sha256={info.sha256}")
    print(
        f"antirollback={info.antirollback} "
        f"antirollback_ext={info.antirollback_ext} enforce={info.enforce}"
    )
    for mod in info.modules:
        print(f"{mod.module_id} {mod.version}")
    print("No serial port was opened and no firmware was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
