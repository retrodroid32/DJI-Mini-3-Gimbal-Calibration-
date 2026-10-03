#!/usr/bin/env python3
"""WM163 persistent 40011 service-calibration runner.

Uses the packet/parser primitives in mini3_gimbal_cal.py. This does NOT flash
service firmware; run it only while WM163 calibration/service firmware is active.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

import mini3_gimbal_cal as m


# Safety interlock: DrGrey's bench-confirmed WM163 40011 sequence requires
# service-session keepalives during Joint Coarse -> Linear Hall -> validation.
# Keep live execution blocked until both exact keepalive packet builders are
# recovered and covered by offline tests.
KEEPALIVE_IMPLEMENTATION_READY = False


def send_stage(ser_obj, reader: m.FrameReader, name: str, payload: bytes,
               timeout: float, verbose: int) -> bool:
    seq = m.next_sequence()
    packet = m.build_packet(
        seq=seq,
        payload=payload,
        receiver=m.COMM_DEV_GIMBAL,
        ack_type=m.ACK_BEFORE_EXEC,
        cmd_set=m.CMD_SET_ZENMUSE,
        cmd_id=m.CMD_ID_GIMBAL_CALIB,
    )
    if verbose:
        print(f"{name} TX: {packet.hex(' ')}")
    ser_obj.write(packet)
    ser_obj.flush()

    deadline = time.monotonic() + timeout
    got_ack = False
    last_status: Optional[bytes] = None

    while time.monotonic() < deadline:
        for frame in m.read_frames(ser_obj, reader, min(deadline, time.monotonic() + 0.5)):
            if verbose > 1:
                print(f"{name} RX: {frame.hex}")

            if m.is_reply_to(
                frame,
                sender=m.COMM_DEV_GIMBAL,
                seq=seq,
                cmd_set=m.CMD_SET_ZENMUSE,
                cmd_id=m.CMD_ID_GIMBAL_CALIB,
            ):
                got_ack = True

            if (
                frame.sender == m.COMM_DEV_GIMBAL
                and frame.cmd_set == m.CMD_SET_ZENMUSE
                and frame.cmd_id == m.CMD_ID_GIMBAL_AUTO_CAL_STATUS
                and len(frame.payload) >= 2
            ):
                last_status = frame.payload[:2]
                print(f"{name}: {m.describe_auto_cal_status_payload(last_status)}")
                if last_status == b"\x64\x00":
                    return True

    if not got_ack:
        print(f"{name}: no sequence-matched 04/08 ACK.", file=sys.stderr)
    if last_status is None:
        print(f"{name}: no 04/30 status push.", file=sys.stderr)
    else:
        print(f"{name}: timed out; last 04/30={last_status.hex(' ')}.", file=sys.stderr)
    return False


def run(port: str, baudrate: int, precheck: float, stage_timeout: float,
        verify: float, verbose: int) -> int:
    if not KEEPALIVE_IMPLEMENTATION_READY:
        print(
            "REFUSED: exact WM163 service keepalives are not implemented yet; "
            "the recovered 40011 sequence must not run without them.",
            file=sys.stderr,
        )
        return 12

    if m.serial is None:
        print("ERROR: pyserial is required: python -m pip install pyserial", file=sys.stderr)
        return 2

    print("DJI Mini 3 / WM163 persistent 40011 service calibration")
    print(f"Port: {port} @ {baudrate}")
    print("Sequence: Joint Coarse -> 64 00 -> Linear Hall -> 64 00 -> verify 00/F1")
    print("This command does not flash firmware. WM163 service/calibration firmware must already be active.")

    reader = m.FrameReader()
    try:
        with m.serial.Serial(port, baudrate=baudrate, timeout=0.05) as ser_obj:
            ser_obj.reset_input_buffer()
            deadline = time.monotonic() + precheck
            saw_status = False
            active_40011 = False
            active_40021 = False
            last_status: Optional[bytes] = None

            for frame in m.read_frames(ser_obj, reader, deadline):
                if (
                    frame.sender == m.COMM_DEV_GIMBAL
                    and frame.cmd_set == m.CMD_SET_GENERAL
                    and frame.cmd_id == m.CMD_ID_GENERAL_PUSH_CHECK_STATUS
                    and len(frame.payload) >= 4
                ):
                    saw_status = True
                    last_status = frame.payload
                    value, _ = m.decode_gimbal_check_status(frame.payload)
                    active_40011 = bool(value & (1 << 24))
                    active_40021 = bool(value & (1 << 7))
                    if verbose:
                        print("Precheck:", m.describe_gimbal_check_status_payload(frame.payload))

            if not saw_status:
                print("REFUSED: no gimbal 00/F1 status observed; nothing sent.", file=sys.stderr)
                return 6
            if active_40021:
                print("REFUSED: 40021 is active again. Run the confirmed 40021 repair first.", file=sys.stderr)
                return 7
            if not active_40011:
                print("40011 is already clear.")
                return 0

            print("40011 confirmed active and 40021 clear.")
            if not send_stage(ser_obj, reader, "Joint Coarse", b"\x01", stage_timeout, verbose):
                print("STOPPED: Joint Coarse did not reach 100% SUCCESS.", file=sys.stderr)
                return 8

            print("Joint Coarse complete; keeping the same COM/service session open.")
            if not send_stage(ser_obj, reader, "Linear Hall", b"\x02", stage_timeout, verbose):
                print("STOPPED: Linear Hall did not reach 100% SUCCESS.", file=sys.stderr)
                return 9

            print("Linear Hall complete; checking persistent diagnostic state.")
            deadline = time.monotonic() + verify
            saw_verify = False
            last_value: Optional[int] = None
            for frame in m.read_frames(ser_obj, reader, deadline):
                if (
                    frame.sender == m.COMM_DEV_GIMBAL
                    and frame.cmd_set == m.CMD_SET_GENERAL
                    and frame.cmd_id == m.CMD_ID_GENERAL_PUSH_CHECK_STATUS
                    and len(frame.payload) >= 4
                ):
                    saw_verify = True
                    value, _ = m.decode_gimbal_check_status(frame.payload)
                    last_value = value
                    print("Verify:", m.describe_gimbal_check_status_payload(frame.payload))
                    if not (value & (1 << 24)):
                        print("SUCCESS: 40011 CALIBRATE_ERROR cleared.")
                        return 0

            if not saw_verify:
                print("Stages succeeded, but no 00/F1 verification push was observed.", file=sys.stderr)
                return 10

            print(
                f"40011 remains active (flags=0x{(last_value or 0):08x}). "
                "The calibration/service firmware is probably not active or did not remain in service state.",
                file=sys.stderr,
            )
            return 11

    except Exception as exc:
        if m.serial is not None and isinstance(exc, m.serial.SerialException):
            print(f"ERROR: serial failure on {port}: {exc}", file=sys.stderr)
            return 5
        raise


def main() -> int:
    p = argparse.ArgumentParser(description="WM163 service-mode repair sequence for persistent DJI gimbal error 40011.")
    p.add_argument("--port", required=True, help="Aircraft COM port, e.g. COM23")
    p.add_argument("--baudrate", type=int, default=9600)
    p.add_argument("--precheck-seconds", type=float, default=5.0)
    p.add_argument("--stage-timeout-seconds", type=float, default=90.0)
    p.add_argument("--verify-seconds", type=float, default=30.0)
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument("--yes", action="store_true", help="Confirm props are removed and WM163 service firmware is active")
    args = p.parse_args()

    if not args.yes:
        p.error("refusing to run without --yes; remove props and verify WM163 service/calibration firmware is active")

    return run(
        args.port,
        args.baudrate,
        args.precheck_seconds,
        args.stage_timeout_seconds,
        args.verify_seconds,
        args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(main())
