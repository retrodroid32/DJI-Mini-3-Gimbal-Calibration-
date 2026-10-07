#!/usr/bin/env python3
"""Offline validator for genuine WM163 Dr.Grey Advanced Calibration.

Reads a USBPcap .pcapng file only. It never opens a serial port.

Validates the capture-backed 40011 service-calibration sequence:
  04/08 01 -> 04/30 ... -> 64 00
  04/08 02 -> 04/30 ... -> 64 00
plus the genuine 04/12 keepalive and the gimbal 00/F1 transition to
00 00 00 00.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

from validate_wm163_service_state_machine import iter_duml_frames


HOST_RAW = 0x0A
GIMBAL_RAW = 0x04
STATUS_DST_RAW = 0x8A

CMDSET_GENERAL = 0x00
CMD_GENERAL_PUSH_CHECK_STATUS = 0xF1

CMDSET_GIMBAL = 0x04
CMD_GIMBAL_CALIB = 0x08
CMD_GIMBAL_KEEPALIVE = 0x12
CMD_GIMBAL_CAL_STATUS = 0x30

JOINT_COARSE = b"\x01"
LINEAR_HALL = b"\x02"
CAL_COMPLETE = b"\x64\x00"
GIMBAL_KEEPALIVE = bytes.fromhex("e6 01 43 00 00 00 00 00 00 00 00 08")

F1_ERROR = b"\x00\x00\x00\x01"
F1_CLEAR = b"\x00\x00\x00\x00"


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

    joint = require(
        first(
            events,
            lambda e: (
                e.sender == HOST_RAW
                and e.dst == GIMBAL_RAW
                and e.cmdset == CMDSET_GIMBAL
                and e.cmd == CMD_GIMBAL_CALIB
                and e.payload == JOINT_COARSE
            ),
        ),
        "Joint Coarse 04/08 payload 01 not found",
    )

    joint_complete = require(
        first(
            events,
            lambda e: (
                e.sender == GIMBAL_RAW
                and e.dst == HOST_RAW
                and e.cmdset == CMDSET_GIMBAL
                and e.cmd == CMD_GIMBAL_CAL_STATUS
                and e.payload == CAL_COMPLETE
            ),
            after=joint.ts,
        ),
        "Joint Coarse 04/30 64 00 completion not found",
    )

    linear = require(
        first(
            events,
            lambda e: (
                e.sender == HOST_RAW
                and e.dst == GIMBAL_RAW
                and e.cmdset == CMDSET_GIMBAL
                and e.cmd == CMD_GIMBAL_CALIB
                and e.payload == LINEAR_HALL
            ),
            after=joint_complete.ts,
        ),
        "Linear Hall 04/08 payload 02 not found after Joint Coarse completion",
    )

    linear_complete = require(
        first(
            events,
            lambda e: (
                e.sender == GIMBAL_RAW
                and e.dst == HOST_RAW
                and e.cmdset == CMDSET_GIMBAL
                and e.cmd == CMD_GIMBAL_CAL_STATUS
                and e.payload == CAL_COMPLETE
            ),
            after=linear.ts,
        ),
        "Linear Hall 04/30 64 00 completion not found",
    )

    keepalives = [
        e
        for e in events
        if joint.ts <= e.ts <= linear_complete.ts
        and e.sender == HOST_RAW
        and e.dst == GIMBAL_RAW
        and e.cmdset == CMDSET_GIMBAL
        and e.cmd == CMD_GIMBAL_KEEPALIVE
        and e.payload == GIMBAL_KEEPALIVE
    ]
    if len(keepalives) < 10:
        raise RuntimeError(
            f"too few capture-confirmed 04/12 keepalives: {len(keepalives)}"
        )

    intervals = [
        keepalives[i + 1].ts - keepalives[i].ts
        for i in range(len(keepalives) - 1)
    ]
    median_keepalive = statistics.median(intervals) if intervals else 0.0

    # Check-status frames are pushed by gimbal toward the aircraft application
    # node (raw 0x8A) roughly once per second.
    pre_error = [
        e
        for e in events
        if joint.ts - 15.0 <= e.ts < joint.ts
        and e.sender == GIMBAL_RAW
        and e.dst == STATUS_DST_RAW
        and e.cmdset == CMDSET_GENERAL
        and e.cmd == CMD_GENERAL_PUSH_CHECK_STATUS
        and e.payload == F1_ERROR
    ]
    if not pre_error:
        raise RuntimeError("pre-calibration 00/F1 00 00 00 01 state not found")

    second_phase_error = [
        e
        for e in events
        if linear.ts <= e.ts <= linear_complete.ts
        and e.sender == GIMBAL_RAW
        and e.dst == STATUS_DST_RAW
        and e.cmdset == CMDSET_GENERAL
        and e.cmd == CMD_GENERAL_PUSH_CHECK_STATUS
        and e.payload == F1_ERROR
    ]
    if not second_phase_error:
        raise RuntimeError("00/F1 error state was not observed during Linear Hall")

    final_clear = require(
        first(
            events,
            lambda e: (
                e.sender == GIMBAL_RAW
                and e.dst == STATUS_DST_RAW
                and e.cmdset == CMDSET_GENERAL
                and e.cmd == CMD_GENERAL_PUSH_CHECK_STATUS
                and e.payload == F1_CLEAR
            ),
            after=linear.ts,
        ),
        "post-Linear-Hall 00/F1 00 00 00 00 validation state not found",
    )

    # Require a clear sample at or after the final 64/00 completion as stronger
    # proof that validation remained clear at phase completion.
    clear_after_complete = require(
        first(
            events,
            lambda e: (
                e.sender == GIMBAL_RAW
                and e.dst == STATUS_DST_RAW
                and e.cmdset == CMDSET_GENERAL
                and e.cmd == CMD_GENERAL_PUSH_CHECK_STATUS
                and e.payload == F1_CLEAR
            ),
            after=linear_complete.ts,
        ),
        "00/F1 clear state not found after Linear Hall completion",
    )

    # Genuine capture uses fixed calibration request sequences 0x0062 and 0x0063.
    if joint.seq != 0x0062:
        raise RuntimeError(f"unexpected Joint Coarse seq 0x{joint.seq:04X}")
    if linear.seq != 0x0063:
        raise RuntimeError(f"unexpected Linear Hall seq 0x{linear.seq:04X}")

    if not 2.5 <= median_keepalive <= 4.0:
        raise RuntimeError(
            f"unexpected 04/12 keepalive median interval {median_keepalive:.3f}s"
        )

    return {
        "frames": len(events),
        "joint_seq": joint.seq,
        "linear_seq": linear.seq,
        "joint_seconds": joint_complete.ts - joint.ts,
        "interphase_seconds": linear.ts - joint_complete.ts,
        "linear_seconds": linear_complete.ts - linear.ts,
        "keepalive_count": len(keepalives),
        "keepalive_median": median_keepalive,
        "first_clear_from_linear": final_clear.ts - linear.ts,
        "clear_after_complete": clear_after_complete.ts - linear_complete.ts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Offline validator for genuine WM163 Dr.Grey Advanced Calibration"
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

    print("WM163 Dr.Grey Advanced Calibration: PASS")
    print(f"DUML frames found: {r['frames']}")
    print(f"Joint Coarse request seq: 0x{r['joint_seq']:04X}")
    print(f"Joint Coarse -> 64 00: {r['joint_seconds']:.3f} s")
    print(f"64 00 -> Linear Hall request: {r['interphase_seconds']:.3f} s")
    print(f"Linear Hall request seq: 0x{r['linear_seq']:04X}")
    print(f"Linear Hall -> 64 00: {r['linear_seconds']:.3f} s")
    print(f"04/12 keepalives: {r['keepalive_count']}")
    print(f"04/12 median interval: {r['keepalive_median']:.3f} s")
    print(
        "Linear Hall -> first 00/F1 clear: "
        f"{r['first_clear_from_linear']:.3f} s"
    )
    print(
        "Final 64 00 -> confirmed 00/F1 clear: "
        f"{r['clear_after_complete']:.3f} s"
    )
    print("OFFLINE ONLY: no serial port was opened.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
