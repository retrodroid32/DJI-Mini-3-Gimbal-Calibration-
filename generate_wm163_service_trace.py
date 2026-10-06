#!/usr/bin/env python3
"""Generate a complete offline WM163 service-flash TX trace.

This tool never opens a serial port. It validates the exact known WM163
V30.00.0100 package and recovered Session-A loader, then emits the packets
that the current project would transmit for Session A and Session B.

Intended use: compare this trace against a genuine Dr.Grey USB capture before
any live flashing is considered.
"""

from __future__ import annotations

import argparse
import csv
import pathlib

from wm163_service_flash_live import (
    KNOWN_LOADER_SIZE,
    KNOWN_V30_FINALIZE_SEQ,
    _package_transfer_files,
    encode_raw,
    validate_inputs,
)
from wm163_service_flash_protocol import (
    CHUNK,
    CMD_ENTER,
    CMD_FINALIZE,
    CMD_PREPARE_A,
    CMD_REBOOT_A,
    CMD_REPORT_SIZE,
    CMD_STREAM_A,
    CMD_STREAM_B,
    SESSION_A_DST_RAW,
    SESSION_A_SEQ0,
    SESSION_B_DST_RAW,
    SESSION_B_SEQ0,
    session_a_enter_payload,
    session_a_finalize_payload,
    session_a_prepare_payload,
    session_a_reboot_payload,
    session_a_report_size_payload,
    session_a_stream_payload,
    session_b_file_data_payload,
    session_b_file_end_payload,
    session_b_file_start_payload,
    session_b_finalize_payload,
    session_b_finalize_seq,
    session_b_report_size_payload,
    session_b_total_size,
)


def row(phase, kind, seq, dst, cmd, payload, packet, note=""):
    return {
        "phase": phase,
        "kind": kind,
        "seq_hex": f"0x{seq:04X}",
        "dst_hex": f"0x{dst:02X}",
        "cmdset_hex": "0x00",
        "cmd_hex": f"0x{cmd:02X}",
        "payload_len": len(payload),
        "payload_hex": payload.hex(" "),
        "packet_len": len(packet),
        "packet_hex": packet.hex(" "),
        "note": note,
    }


def build_trace(package_path: pathlib.Path, loader_path: pathlib.Path):
    loader, files = validate_inputs(package_path, loader_path)
    out = []

    # Session A
    seq = SESSION_A_SEQ0

    for kind, cmd, payload in (
        ("ENTER", CMD_ENTER, session_a_enter_payload()),
        ("PREPARE", CMD_PREPARE_A, session_a_prepare_payload()),
        ("REPORT_SIZE", CMD_REPORT_SIZE, session_a_report_size_payload(len(loader))),
    ):
        pkt = encode_raw(dst_raw=SESSION_A_DST_RAW, seq=seq, cmd_id=cmd, payload=payload)
        out.append(row("A", kind, seq, SESSION_A_DST_RAW, cmd, payload, pkt))
        seq = (seq + 1) & 0xFFFF

    for chunk_index, offset in enumerate(range(0, len(loader), CHUNK)):
        chunk = loader[offset : offset + CHUNK]
        payload = session_a_stream_payload(chunk_index, chunk)
        pkt = encode_raw(
            dst_raw=SESSION_A_DST_RAW,
            seq=seq,
            cmd_id=CMD_STREAM_A,
            payload=payload,
        )
        out.append(
            row(
                "A",
                "DATA",
                seq,
                SESSION_A_DST_RAW,
                CMD_STREAM_A,
                payload,
                pkt,
                note=f"chunk_index={chunk_index};byte_offset={offset};chunk_len={len(chunk)}",
            )
        )
        seq = (seq + 1) & 0xFFFF

    payload = session_a_finalize_payload(loader)
    pkt = encode_raw(dst_raw=SESSION_A_DST_RAW, seq=seq, cmd_id=CMD_FINALIZE, payload=payload)
    out.append(row("A", "VERIFY", seq, SESSION_A_DST_RAW, CMD_FINALIZE, payload, pkt))
    seq = (seq + 1) & 0xFFFF

    payload = session_a_reboot_payload()
    pkt = encode_raw(dst_raw=SESSION_A_DST_RAW, seq=seq, cmd_id=CMD_REBOOT_A, payload=payload)
    out.append(row("A", "CMD_0B", seq, SESSION_A_DST_RAW, CMD_REBOOT_A, payload, pkt))

    # Session B
    seq = SESSION_B_SEQ0

    payload = session_a_enter_payload()
    pkt = encode_raw(dst_raw=SESSION_B_DST_RAW, seq=seq, cmd_id=CMD_ENTER, payload=payload)
    out.append(row("B", "ENTER", seq, SESSION_B_DST_RAW, CMD_ENTER, payload, pkt))
    seq = (seq + 1) & 0xFFFF

    payload = session_b_report_size_payload(session_b_total_size(files))
    pkt = encode_raw(dst_raw=SESSION_B_DST_RAW, seq=seq, cmd_id=CMD_REPORT_SIZE, payload=payload)
    out.append(row("B", "REPORT_SIZE", seq, SESSION_B_DST_RAW, CMD_REPORT_SIZE, payload, pkt))
    seq = (seq + 1) & 0xFFFF

    for filename, blob in files:
        payload = session_b_file_start_payload(filename, blob)
        pkt = encode_raw(dst_raw=SESSION_B_DST_RAW, seq=seq, cmd_id=CMD_STREAM_B, payload=payload)
        out.append(row("B", "START", seq, SESSION_B_DST_RAW, CMD_STREAM_B, payload, pkt, filename))
        seq = (seq + 1) & 0xFFFF

        # Captured Dr.Grey behavior: one sequence value unused after START.
        skipped = seq
        out.append({
            "phase": "B",
            "kind": "SEQ_GAP",
            "seq_hex": f"0x{skipped:04X}",
            "dst_hex": "",
            "cmdset_hex": "",
            "cmd_hex": "",
            "payload_len": 0,
            "payload_hex": "",
            "packet_len": 0,
            "packet_hex": "",
            "note": f"captured unused sequence after START for {filename}",
        })
        seq = (seq + 1) & 0xFFFF

        for chunk_index, offset in enumerate(range(0, len(blob), CHUNK)):
            chunk = blob[offset : offset + CHUNK]
            payload = session_b_file_data_payload(chunk_index, chunk)
            pkt = encode_raw(dst_raw=SESSION_B_DST_RAW, seq=seq, cmd_id=CMD_STREAM_B, payload=payload)
            out.append(
                row(
                    "B",
                    "DATA",
                    seq,
                    SESSION_B_DST_RAW,
                    CMD_STREAM_B,
                    payload,
                    pkt,
                    note=(
                        f"{filename};chunk_index={chunk_index};"
                        f"byte_offset={offset};chunk_len={len(chunk)}"
                    ),
                )
            )
            seq = (seq + 1) & 0xFFFF

        payload = session_b_file_end_payload(blob)
        pkt = encode_raw(dst_raw=SESSION_B_DST_RAW, seq=seq, cmd_id=CMD_STREAM_B, payload=payload)
        out.append(row("B", "END", seq, SESSION_B_DST_RAW, CMD_STREAM_B, payload, pkt, filename))
        seq = (seq + 1) & 0xFFFF

    if seq != KNOWN_V30_FINALIZE_SEQ:
        raise RuntimeError(
            f"trace invariant failed: expected B/FINALIZE 0x{KNOWN_V30_FINALIZE_SEQ:04X}, "
            f"got 0x{seq:04X}"
        )

    payload = session_b_finalize_payload()
    pkt = encode_raw(dst_raw=SESSION_B_DST_RAW, seq=seq, cmd_id=CMD_FINALIZE, payload=payload)
    out.append(row("B", "FINALIZE", seq, SESSION_B_DST_RAW, CMD_FINALIZE, payload, pkt))

    if session_b_finalize_seq(files) != KNOWN_V30_FINALIZE_SEQ:
        raise RuntimeError("session_b_finalize_seq invariant disagrees with trace")

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate offline WM163 service-flash packet trace")
    ap.add_argument("--package", required=True)
    ap.add_argument("--loader", required=True)
    ap.add_argument("--output", default="wm163_service_flash_trace.csv")
    args = ap.parse_args()

    rows = build_trace(pathlib.Path(args.package), pathlib.Path(args.loader))

    fields = [
        "phase",
        "kind",
        "seq_hex",
        "dst_hex",
        "cmdset_hex",
        "cmd_hex",
        "payload_len",
        "payload_hex",
        "packet_len",
        "packet_hex",
        "note",
    ]

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    a_rows = sum(1 for r in rows if r["phase"] == "A")
    b_rows = sum(1 for r in rows if r["phase"] == "B")
    print(f"WROTE: {args.output}")
    print(f"Session-A trace rows: {a_rows}")
    print(f"Session-B trace rows: {b_rows}")
    print(f"Session-A loader size: {KNOWN_LOADER_SIZE}")
    print(f"Expected B/FINALIZE seq: 0x{KNOWN_V30_FINALIZE_SEQ:04X}")
    print("OFFLINE ONLY: no serial port was opened.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
