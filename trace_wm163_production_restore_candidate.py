#!/usr/bin/env python3
"""Generate an OFFLINE candidate WM163 production-restore Session-B trace summary.

This does not open a serial port and does not write firmware. It validates the
exact known production image and Session-A loader, then walks the same
capture-backed Session-B packetization logic used by the service-flash tooling.

The resulting trace is a candidate for comparison/research only. It is NOT
proof that the aircraft accepts production restore through this path.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

import wm163_private_fw as private_fw
import wm163_production_fw as production_fw
import wm163_service_flash_live as live
from wm163_service_flash_protocol import (
    CHUNK,
    CMD_ENTER,
    CMD_FINALIZE,
    CMD_REPORT_SIZE,
    CMD_STREAM_B,
    SESSION_B_DST_RAW,
    SESSION_B_SEQ0,
    session_a_enter_payload,
    session_b_file_data_payload,
    session_b_file_end_payload,
    session_b_file_start_payload,
    session_b_finalize_payload,
    session_b_report_size_payload,
    session_b_total_size,
)


def summarize(package_path: pathlib.Path, loader_path: pathlib.Path) -> dict[str, object]:
    production_fw.validate_production_archive(package_path)

    loader = loader_path.read_bytes()
    if len(loader) != live.KNOWN_LOADER_SIZE:
        raise ValueError("Session-A loader size mismatch")
    if hashlib.md5(loader).hexdigest() != live.KNOWN_LOADER_MD5:
        raise ValueError("Session-A loader MD5 mismatch")

    files = live._package_transfer_files(package_path)
    seq = SESSION_B_SEQ0
    packet_count = 0
    wraps = 0
    sha = hashlib.sha256()
    boundary: list[tuple[int, str, str]] = []

    def emit(cmd_id: int, payload: bytes, label: str) -> None:
        nonlocal seq, packet_count, wraps
        pkt = live.encode_raw(
            dst_raw=SESSION_B_DST_RAW,
            seq=seq,
            cmd_id=cmd_id,
            payload=payload,
        )
        if seq in (0xFFFE, 0xFFFF, 0x0000, 0x0001):
            boundary.append((seq, label, pkt.hex(" ")))
        sha.update(pkt)
        packet_count += 1
        old = seq
        seq = (seq + 1) & 0xFFFF
        if old == 0xFFFF:
            wraps += 1

    emit(CMD_ENTER, session_a_enter_payload(), "ENTER")
    emit(
        CMD_REPORT_SIZE,
        session_b_report_size_payload(session_b_total_size(files)),
        "REPORT_SIZE",
    )

    for name, blob in files:
        emit(CMD_STREAM_B, session_b_file_start_payload(name, blob), f"START {name}")

        # Capture-backed one-sequence gap after each START.
        old = seq
        seq = (seq + 1) & 0xFFFF
        if old == 0xFFFF:
            wraps += 1

        for chunk_index, offset in enumerate(range(0, len(blob), CHUNK)):
            emit(
                CMD_STREAM_B,
                session_b_file_data_payload(
                    chunk_index,
                    blob[offset : offset + CHUNK],
                ),
                f"DATA {name} chunk={chunk_index}",
            )

        emit(CMD_STREAM_B, session_b_file_end_payload(blob), f"END {name}")

    finalize_seq = seq
    emit(CMD_FINALIZE, session_b_finalize_payload(), "FINALIZE")

    return {
        "file_count": len(files),
        "transfer_size": session_b_total_size(files),
        "packet_count_including_finalize": packet_count,
        "sequence_wraps_before_or_at_finalize": wraps,
        "finalize_seq": finalize_seq,
        "stream_sha256": sha.hexdigest(),
        "boundary": tuple(boundary),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline candidate WM163 production-restore Session-B trace"
    )
    parser.add_argument("--package")
    parser.add_argument("--loader")
    args = parser.parse_args()

    package = (
        pathlib.Path(args.package)
        if args.package
        else production_fw.find_repo_production_archive()
    )
    private = private_fw.find_private_service_inputs()
    loader = pathlib.Path(args.loader) if args.loader else private.loader

    if package is None or loader is None:
        print("ERROR: production package or private Session-A loader is missing.", file=sys.stderr)
        return 2

    try:
        result = summarize(package, loader)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 3

    print("WM163 production restore candidate Session-B trace: PASS")
    print(f"file_count={result['file_count']}")
    print(f"transfer_size={result['transfer_size']}")
    print(f"packet_count_including_finalize={result['packet_count_including_finalize']}")
    print(f"sequence_wraps_before_or_at_finalize={result['sequence_wraps_before_or_at_finalize']}")
    print(f"finalize_seq=0x{result['finalize_seq']:04X}")
    print(f"candidate_stream_sha256={result['stream_sha256']}")
    for seq, label, packet_hex in result["boundary"]:
        print(f"boundary seq=0x{seq:04X} label={label}")
        print(f"  packet={packet_hex}")

    print()
    print("NO SERIAL PORT WAS OPENED. NO FIRMWARE WAS WRITTEN.")
    print("Live production restore remains locked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
