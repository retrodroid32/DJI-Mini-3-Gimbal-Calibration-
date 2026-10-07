#!/usr/bin/env python3
"""Offline structural analysis for a future WM163 production-firmware restore.

This tool validates the exact known WM163 v01.00.0500 production archive and
the exact recovered Session-A loader, then asks the already capture-backed
Session-B packetization helpers how that production archive would be laid out.

It NEVER opens a serial port and NEVER writes firmware. The calculated
Session-B values are analysis data only; they do not prove that the service
loader accepts a production restore. Live restore remains locked.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

import wm163_private_fw as private_fw
import wm163_production_fw as production_fw
import wm163_service_flash_live as service_fw


KNOWN_PRODUCTION_SESSION_B_FILES = (
    ("wm163.cfg.sig", 2_336),
    ("wm163_0100_v01.64.01.52_20231130.pro.fw.sig", 40_760_352),
    ("wm163_0105_v12.07.00.12_20221213.pro.fw.sig", 245_856),
    ("wm163_0306_v03.04.11.34_20240513.pro.fw.sig", 1_765_152),
    ("wm163_0905_v01.00.01.27_20220919.pro.fw.sig", 10_390_912),
    ("wm163_1100_v10.75.00.17_20221108.pro.fw.sig", 94_720),
    ("wm163_1200_v01.10.02.15_20221010.pro.fw.sig", 56_352),
)
KNOWN_PRODUCTION_SESSION_B_TOTAL_SIZE = 53_315_680
KNOWN_PRODUCTION_SESSION_B_FINALIZE_SEQ = 0x04C0


def validate_loader(loader_path: pathlib.Path) -> bytes:
    loader = loader_path.read_bytes()
    if len(loader) != service_fw.KNOWN_LOADER_SIZE:
        raise ValueError(
            f"Session-A loader size mismatch: expected "
            f"{service_fw.KNOWN_LOADER_SIZE}, got {len(loader)}"
        )
    md5 = hashlib.md5(loader).hexdigest()
    if md5 != service_fw.KNOWN_LOADER_MD5:
        raise ValueError(
            f"Session-A loader MD5 mismatch: expected "
            f"{service_fw.KNOWN_LOADER_MD5}, got {md5}"
        )
    return loader


def transfer_summary(files: list[tuple[str, bytes]]) -> dict[str, object]:
    return {
        "file_count": len(files),
        "files": tuple((name, len(blob)) for name, blob in files),
        "total_size": service_fw.session_b_total_size(files),
        "finalize_seq": service_fw.session_b_finalize_seq(files),
    }


def analyze(package_path: pathlib.Path, loader_path: pathlib.Path) -> dict[str, object]:
    info = production_fw.validate_production_archive(package_path)
    loader = validate_loader(loader_path)
    files = service_fw._package_transfer_files(package_path)
    if not files:
        raise ValueError("production archive contains no transferable signed package members")

    summary = transfer_summary(files)

    actual_files = tuple((name, len(blob)) for name, blob in files)
    if actual_files != KNOWN_PRODUCTION_SESSION_B_FILES:
        raise ValueError(
            "production Session-B member layout mismatch: "
            f"expected {KNOWN_PRODUCTION_SESSION_B_FILES!r}, got {actual_files!r}"
        )
    if summary["total_size"] != KNOWN_PRODUCTION_SESSION_B_TOTAL_SIZE:
        raise ValueError(
            "production Session-B total-size mismatch: "
            f"expected {KNOWN_PRODUCTION_SESSION_B_TOTAL_SIZE}, "
            f"got {summary['total_size']}"
        )
    if summary["finalize_seq"] != KNOWN_PRODUCTION_SESSION_B_FINALIZE_SEQ:
        raise ValueError(
            "production Session-B final-sequence mismatch: "
            f"expected 0x{KNOWN_PRODUCTION_SESSION_B_FINALIZE_SEQ:04X}, "
            f"got 0x{summary['finalize_seq']:04X}"
        )

    return {
        "device": info.device,
        "formal": info.formal,
        "release": info.release,
        "package_size": package_path.stat().st_size,
        "package_md5": info.md5,
        "package_sha256": info.sha256,
        "loader_size": len(loader),
        "loader_md5": hashlib.md5(loader).hexdigest(),
        **summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline WM163 v01.00.0500 production-restore structural analysis"
    )
    parser.add_argument(
        "--package",
        help="Exact WM163 v01.00.0500 production archive; defaults to repo firmware/",
    )
    parser.add_argument(
        "--loader",
        help="Exact Session-A loader; defaults to private_firmware/session_a_loader.bin",
    )
    args = parser.parse_args()

    package = pathlib.Path(args.package) if args.package else production_fw.find_repo_production_archive()
    private = private_fw.find_private_service_inputs()
    loader = pathlib.Path(args.loader) if args.loader else private.loader

    if package is None:
        print(
            "ERROR: exact production archive not found. Expected "
            f"firmware/{production_fw.DEFAULT_PRODUCTION_FILENAME}",
            file=sys.stderr,
        )
        return 2
    if loader is None:
        print(
            "ERROR: exact Session-A loader not found. Expected "
            f"{private_fw.PRIVATE_FIRMWARE_DIR}/{private_fw.SESSION_A_LOADER_FILENAME}",
            file=sys.stderr,
        )
        return 2

    try:
        result = analyze(package, loader)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 3

    print("WM163 production-restore OFFLINE structural analysis: PASS")
    print(f"device={result['device']}")
    print(f"formal={result['formal']}")
    print(f"release={result['release']}")
    print(f"package_size={result['package_size']}")
    print(f"package_md5={result['package_md5']}")
    print(f"package_sha256={result['package_sha256']}")
    print(f"loader_size={result['loader_size']}")
    print(f"loader_md5={result['loader_md5']}")
    print(f"session_b_file_count={result['file_count']}")
    for name, size in result["files"]:
        print(f"session_b_file={name} size={size}")
    print(f"session_b_total_size={result['total_size']}")
    print(f"predicted_session_b_finalize_seq=0x{result['finalize_seq']:04X}")
    print("session_b_sequence_rollover=REQUIRED (16-bit wrap past 0xFFFF)")
    print()
    print("NO SERIAL PORT WAS OPENED. NO FIRMWARE WAS WRITTEN.")
    print(
        "IMPORTANT: these values only show that the exact production archive can "
        "be represented by the capture-backed Session-B packetization. They do "
        "NOT prove that a live production restore uses or accepts this sequence."
    )
    print("Live production restore remains locked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
