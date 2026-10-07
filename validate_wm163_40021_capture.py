#!/usr/bin/env python3
"""Offline validator for genuine WM163 Dr.Grey 40021 repair.

Reads a USBPcap .pcapng file only. It never opens a serial port.

Validates:
  04/36 payload 42 E9 7F 3F
  -> empty matching ACK
  -> battery/PMU 00/0B reboot command
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from validate_wm163_service_state_machine import iter_duml_frames


FIX_PAYLOAD = bytes.fromhex("42 e9 7f 3f")
REBOOT_PAYLOAD = bytes.fromhex(
    "00 01 00 00 00 00 00 00 00 00 00 00 00 00"
)


def first(events, predicate, after=float("-inf")):
    for event in events:
        if event.ts >= after and predicate(event):
            return event
    return None


def require(event, message):
    if event is None:
        raise RuntimeError(message)
    return event


def validate(path: Path) -> dict:
    events = list(iter_duml_frames(path))
    if not events:
        raise RuntimeError("no DUML frames found in capture")

    fix = require(
        first(
            events,
            lambda e: (
                e.sender == 0x0A
                and e.dst == 0x04
                and e.cmdset == 0x04
                and e.cmd == 0x36
                and e.payload == FIX_PAYLOAD
            ),
        ),
        "WM163 04/36 short 40021 request not found",
    )

    ack = require(
        first(
            events,
            lambda e: (
                e.sender == 0x04
                and e.dst == 0x0A
                and e.seq == fix.seq
                and (e.flags & 0x80)
                and e.cmdset == 0x04
                and e.cmd == 0x36
                and e.payload == b""
            ),
            after=fix.ts,
        ),
        "matching empty 04/36 ACK not found",
    )

    reboot = require(
        first(
            events,
            lambda e: (
                e.sender == 0x2A
                and e.dst == 0x0B
                and e.cmdset == 0x00
                and e.cmd == 0x0B
                and e.payload == REBOOT_PAYLOAD
            ),
            after=ack.ts,
        ),
        "battery/PMU 00/0B reboot command not found after 04/36 ACK",
    )

    reboot_ack = require(
        first(
            events,
            lambda e: (
                e.sender == 0x0B
                and e.dst == 0x2A
                and e.seq == reboot.seq
                and (e.flags & 0x80)
                and e.cmdset == 0x00
                and e.cmd == 0x0B
                and e.payload[:1] == b"\x00"
            ),
            after=reboot.ts,
        ),
        "battery/PMU reboot success ACK not found",
    )

    if fix.seq != 0x0064:
        raise RuntimeError(f"unexpected captured 04/36 seq 0x{fix.seq:04X}")
    if reboot.seq != 0x0065:
        raise RuntimeError(f"unexpected captured reboot seq 0x{reboot.seq:04X}")

    return {
        "frames": len(events),
        "fix_seq": fix.seq,
        "ack_ms": (ack.ts - fix.ts) * 1000.0,
        "reboot_ms": (reboot.ts - fix.ts) * 1000.0,
        "reboot_ack_ms": (reboot_ack.ts - reboot.ts) * 1000.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Offline validator for genuine WM163 Dr.Grey 40021 repair"
    )
    ap.add_argument("capture", help="USBPcap .pcapng capture")
    args = ap.parse_args()

    path = Path(args.capture)
    if not path.is_file():
        print(f"ERROR: capture not found: {path}", file=sys.stderr)
        return 2

    try:
        r = validate(path)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 3

    print("WM163 Dr.Grey 40021 short repair: PASS")
    print(f"DUML frames found: {r['frames']}")
    print(f"04/36 request seq: 0x{r['fix_seq']:04X}")
    print(f"04/36 -> empty ACK: {r['ack_ms']:.3f} ms")
    print(f"04/36 -> battery/PMU reboot TX: {r['reboot_ms']:.3f} ms")
    print(f"reboot TX -> status-00 ACK: {r['reboot_ack_ms']:.3f} ms")
    print("OFFLINE ONLY: no serial port was opened.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
