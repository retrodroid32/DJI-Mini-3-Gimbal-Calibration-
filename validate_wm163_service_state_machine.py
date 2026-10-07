#!/usr/bin/env python3
"""Validate the captured WM163 Dr.Grey service-flash state machine.

Offline only: reads a USBPcap .pcapng file and never opens a serial port.

This validator intentionally focuses on the control/state transitions around:
A/CMD_0B -> temp-loader identity -> Session B -> B/FINALIZE(F7)
-> commit probes -> temp-loader disappearance.
"""

from __future__ import annotations

import argparse
import statistics
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FrameEvent:
    ts: float
    sender: int
    dst: int
    seq: int
    flags: int
    cmdset: int
    cmd: int
    payload: bytes
    raw: bytes


def iter_pcapng_packets(path: Path):
    """Yield (timestamp_seconds, captured_packet_bytes) from EPBs.

    Supports the little-endian USBPcap PCAPNG files produced by Wireshark on
    Windows. Timestamp resolution is taken from IDB if_tsresol when present.
    """
    endian = "<"
    tsresol = {0: 1e-6}

    with path.open("rb") as fh:
        while True:
            hdr = fh.read(8)
            if len(hdr) < 8:
                return

            block_type, block_len = struct.unpack(endian + "II", hdr)
            if block_len < 12:
                raise ValueError(f"invalid PCAPNG block length {block_len}")

            body = fh.read(block_len - 12)
            trailer = fh.read(4)
            if len(body) != block_len - 12 or len(trailer) != 4:
                raise ValueError("truncated PCAPNG block")

            if block_type == 0x0A0D0D0A:
                bom = body[:4]
                if bom == b"\x4d\x3c\x2b\x1a":
                    endian = "<"
                elif bom == b"\x1a\x2b\x3c\x4d":
                    endian = ">"
                else:
                    raise ValueError("unsupported PCAPNG byte-order magic")
                continue

            if block_type == 1:  # Interface Description Block
                if len(body) < 8:
                    continue
                # Parse options after linktype/reserved/snaplen.
                pos = 8
                iface_index = len(tsresol) if tsresol else 0
                # This capture normally has a single interface at index 0.
                iface_index = 0
                while pos + 4 <= len(body):
                    code, length = struct.unpack_from(endian + "HH", body, pos)
                    pos += 4
                    if code == 0:
                        break
                    value = body[pos : pos + length]
                    pos += (length + 3) & ~3
                    if code == 9 and value:
                        v = value[0]
                        if v & 0x80:
                            tsresol[iface_index] = 2.0 ** -(v & 0x7F)
                        else:
                            tsresol[iface_index] = 10.0 ** -v
                continue

            if block_type != 6 or len(body) < 20:  # Enhanced Packet Block
                continue

            iface, ts_hi, ts_lo, cap_len, _orig_len = struct.unpack_from(
                endian + "IIIII", body, 0
            )
            packet = body[20 : 20 + cap_len]
            ticks = (ts_hi << 32) | ts_lo
            ts = ticks * tsresol.get(iface, 1e-6)
            yield ts, packet


def usbpcap_payload(packet: bytes) -> bytes:
    if len(packet) < 2:
        return b""
    header_len = struct.unpack_from("<H", packet, 0)[0]
    if header_len < 2 or header_len > len(packet):
        return b""
    return packet[header_len:]


def iter_duml_frames(path: Path):
    """Find complete DUMLv1 frames contained in USBPcap packet payloads."""
    for ts, packet in iter_pcapng_packets(path):
        data = usbpcap_payload(packet)
        pos = 0
        while pos + 13 <= len(data):
            i = data.find(b"\x55", pos)
            if i < 0 or i + 13 > len(data):
                break
            ver_len = data[i + 1] | (data[i + 2] << 8)
            length = ver_len & 0x03FF
            version = ver_len >> 10
            if version == 1 and 13 <= length <= 0x03FF and i + length <= len(data):
                raw = data[i : i + length]
                yield FrameEvent(
                    ts=ts,
                    sender=raw[4],
                    dst=raw[5],
                    seq=raw[6] | (raw[7] << 8),
                    flags=raw[8],
                    cmdset=raw[9],
                    cmd=raw[10],
                    payload=raw[11:-2],
                    raw=raw,
                )
                pos = i + length
            else:
                pos = i + 1


def first(events, predicate, after=float("-inf")):
    for event in events:
        if event.ts >= after and predicate(event):
            return event
    return None


def require(event, message):
    if event is None:
        raise RuntimeError(message)
    return event


def ms(seconds: float) -> float:
    return seconds * 1000.0


def validate(path: Path) -> dict:
    events = list(iter_duml_frames(path))
    if not events:
        raise RuntimeError("no DUML frames found in capture")

    a_cmd0b = require(
        first(
            events,
            lambda e: (
                e.sender == 0x2A
                and e.dst == 0xA9
                and e.seq == 0x4BFB
                and e.cmdset == 0x00
                and e.cmd == 0x0B
                and e.payload == b"\x00\x01\xE8\x03\x00\x00DEADBEEF"
            ),
        ),
        "A/CMD_0B TX not found",
    )

    a_ack = require(
        first(
            events,
            lambda e: (
                e.sender == 0xA9
                and e.dst == 0x2A
                and e.seq == 0x4BFB
                and (e.flags & 0x80)
                and e.cmdset == 0x00
                and e.cmd == 0x0B
                and e.payload[:1] == b"\x00"
            ),
            after=a_cmd0b.ts,
        ),
        "A/CMD_0B success ACK not found",
    )

    loader_probe = require(
        first(
            events,
            lambda e: (
                e.sender == 0x2A
                and e.dst == 0x28
                and e.cmdset == 0x00
                and e.cmd == 0x01
                and e.payload == b""
            ),
            after=a_ack.ts,
        ),
        "temporary-loader probe not found after A/CMD_0B",
    )

    loader_identity = require(
        first(
            events,
            lambda e: (
                e.sender == 0x28
                and e.dst == 0x2A
                and e.cmdset == 0x00
                and e.cmd == 0x01
                and b"WM163 UAV" in e.payload
            ),
            after=loader_probe.ts,
        ),
        "WM163 UAV temporary-loader identity response not found",
    )

    b_enter = require(
        first(
            events,
            lambda e: (
                e.sender == 0x2A
                and e.dst == 0x01
                and e.seq == 0x3022
                and e.cmdset == 0x00
                and e.cmd == 0x07
                and e.payload == b"\x00" * 9
            ),
            after=loader_identity.ts,
        ),
        "B/ENTER not found",
    )

    b_report = require(
        first(
            events,
            lambda e: (
                e.sender == 0x2A
                and e.dst == 0x01
                and e.seq == 0x3023
                and e.cmdset == 0x00
                and e.cmd == 0x08
            ),
            after=b_enter.ts,
        ),
        "B/REPORT_SIZE not found",
    )

    b_finalize = require(
        first(
            events,
            lambda e: (
                e.sender == 0x2A
                and e.dst == 0x01
                and e.seq == 0xFF8A
                and e.cmdset == 0x00
                and e.cmd == 0x0A
                and e.payload == b"\x00" * 17
            ),
            after=b_report.ts,
        ),
        "captured B/FINALIZE seq 0xFF8A not found",
    )

    finalize_ack = require(
        first(
            events,
            lambda e: (
                e.sender == 0x01
                and e.dst == 0x2A
                and e.seq == 0xFF8A
                and (e.flags & 0x80)
                and e.cmdset == 0x00
                and e.cmd == 0x0A
                and e.payload[:1] == b"\xF7"
            ),
            after=b_finalize.ts,
        ),
        "captured B/FINALIZE F7 response not found",
    )

    commit_probes = [
        e
        for e in events
        if e.ts >= finalize_ack.ts
        and e.sender == 0x2A
        and e.dst == 0x28
        and e.seq == 0
        and e.cmdset == 0x00
        and e.cmd == 0x01
        and e.payload == b""
    ]
    if len(commit_probes) < 10:
        raise RuntimeError(
            f"too few post-finalize commit probes: {len(commit_probes)}"
        )

    commit_identity = [
        e
        for e in events
        if e.ts >= finalize_ack.ts
        and e.sender == 0x28
        and e.dst == 0x2A
        and e.seq == 0
        and e.cmdset == 0x00
        and e.cmd == 0x01
        and b"WM163 UAV" in e.payload
    ]
    if not commit_identity:
        raise RuntimeError("no post-finalize WM163 UAV identity responses found")

    first_probe = commit_probes[0]
    last_probe = commit_probes[-1]
    last_identity = commit_identity[-1]

    intervals = [
        commit_probes[i + 1].ts - commit_probes[i].ts
        for i in range(len(commit_probes) - 1)
    ]
    median_probe_interval = statistics.median(intervals) if intervals else 0.0

    # Broad capture-backed sanity bounds; these are not hard protocol constants.
    timing_checks = {
        "A ACK after CMD_0B < 100 ms": 0 <= a_ack.ts - a_cmd0b.ts < 0.100,
        "loader probe after A ACK < 100 ms": 0 <= loader_probe.ts - a_ack.ts < 0.100,
        "loader identity after probe < 1 s": 0 <= loader_identity.ts - loader_probe.ts < 1.0,
        "B/ENTER after loader identity < 1 s": 0 <= b_enter.ts - loader_identity.ts < 1.0,
        "B/FINALIZE F7 ACK < 1 s": 0 <= finalize_ack.ts - b_finalize.ts < 1.0,
        "first commit probe < 1 s": 0 <= first_probe.ts - b_finalize.ts < 1.0,
        "commit probe median 0.4..0.7 s": 0.4 <= median_probe_interval <= 0.7,
        "last probe follows last good loader response": last_probe.ts > last_identity.ts,
    }

    failed = [name for name, ok in timing_checks.items() if not ok]
    if failed:
        raise RuntimeError("state timing check(s) failed: " + "; ".join(failed))

    return {
        "duML_frames": len(events),
        "a_cmd0b_ack_ms": ms(a_ack.ts - a_cmd0b.ts),
        "loader_probe_from_cmd0b_ms": ms(loader_probe.ts - a_cmd0b.ts),
        "loader_identity_from_cmd0b_ms": ms(loader_identity.ts - a_cmd0b.ts),
        "b_enter_from_cmd0b_ms": ms(b_enter.ts - a_cmd0b.ts),
        "b_session_seconds": b_finalize.ts - b_enter.ts,
        "b_finalize_f7_ack_ms": ms(finalize_ack.ts - b_finalize.ts),
        "first_commit_probe_ms": ms(first_probe.ts - b_finalize.ts),
        "commit_probe_count": len(commit_probes),
        "commit_identity_count": len(commit_identity),
        "commit_probe_median_seconds": median_probe_interval,
        "last_good_identity_seconds": last_identity.ts - b_finalize.ts,
        "last_probe_seconds": last_probe.ts - b_finalize.ts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Offline validator for genuine WM163 Dr.Grey service-flash PCAP"
    )
    ap.add_argument("capture", help="USBPcap .pcapng capture")
    args = ap.parse_args()

    path = Path(args.capture)
    if not path.is_file():
        print(f"ERROR: capture not found: {path}", file=sys.stderr)
        return 2

    try:
        result = validate(path)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 3

    print("WM163 Dr.Grey service-flash state machine: PASS")
    print(f"DUML frames found: {result['duML_frames']}")
    print(f"A/CMD_0B -> ACK: {result['a_cmd0b_ack_ms']:.3f} ms")
    print(
        "A/CMD_0B -> loader probe: "
        f"{result['loader_probe_from_cmd0b_ms']:.3f} ms"
    )
    print(
        "A/CMD_0B -> WM163 UAV response: "
        f"{result['loader_identity_from_cmd0b_ms']:.3f} ms"
    )
    print(f"A/CMD_0B -> B/ENTER: {result['b_enter_from_cmd0b_ms']:.3f} ms")
    print(f"Session B ENTER -> FINALIZE: {result['b_session_seconds']:.3f} s")
    print(
        "B/FINALIZE -> F7 ACK: "
        f"{result['b_finalize_f7_ack_ms']:.3f} ms"
    )
    print(
        "B/FINALIZE -> first commit probe: "
        f"{result['first_commit_probe_ms']:.3f} ms"
    )
    print(
        "Commit probes / loader responses: "
        f"{result['commit_probe_count']} / {result['commit_identity_count']}"
    )
    print(
        "Commit-probe median interval: "
        f"{result['commit_probe_median_seconds']:.3f} s"
    )
    print(
        "Last good WM163 UAV response: "
        f"+{result['last_good_identity_seconds']:.3f} s"
    )
    print(f"Last probe: +{result['last_probe_seconds']:.3f} s")
    print("OFFLINE ONLY: no serial port was opened.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
