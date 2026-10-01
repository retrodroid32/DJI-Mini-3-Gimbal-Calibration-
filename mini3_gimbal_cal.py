#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DJI Mini 3 (WM163) experimental gimbal calibration helper.

This project is a focused derivative of protocol work from o-gs/dji-firmware-tools.
It intentionally supports only DJI Mini 3 / WM163 and only the gimbal calibration
command set used for repair calibration.

GPL-3.0-or-later. NO WARRANTY. Experimental hardware-repair software.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from typing import Iterable, Optional

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    serial = None

VERSION = "0.1.0"
MODEL = "DJI Mini 3"
PLATFORM = "WM163"

SOF = 0x55
COMM_DEV_GIMBAL = 4
COMM_DEV_PC = 10
CMD_SET_ZENMUSE = 4
CMD_ID_GIMBAL_CALIB = 0x08
PACKET_TYPE_REQUEST = 0
PACKET_TYPE_RESPONSE = 1
ACK_BEFORE_EXEC = 1
NO_ENCRYPTION = 0

CALIB_COMMANDS = {
    "joint-coarse": 0x01,
    "linear-hall": 0x02,
}

# Legacy completion values used by o-gs/dji-firmware-tools on older DJI gimbals.
# WM163 may use a different progress format, so these are treated as hints only.
LEGACY_PASS = {
    "joint-coarse": (0x10, 0x01),
    "linear-hall": (0x28, 0x01),
}

# DJI DUMLv1 header CRC8 lookup table, GPL-derived from o-gs/dji-firmware-tools.
CRC8_TABLE = (
    0x00,0x5E,0xBC,0xE2,0x61,0x3F,0xDD,0x83,0xC2,0x9C,0x7E,0x20,0xA3,0xFD,0x1F,0x41,
    0x9D,0xC3,0x21,0x7F,0xFC,0xA2,0x40,0x1E,0x5F,0x01,0xE3,0xBD,0x3E,0x60,0x82,0xDC,
    0x23,0x7D,0x9F,0xC1,0x42,0x1C,0xFE,0xA0,0xE1,0xBF,0x5D,0x03,0x80,0xDE,0x3C,0x62,
    0xBE,0xE0,0x02,0x5C,0xDF,0x81,0x63,0x3D,0x7C,0x22,0xC0,0x9E,0x1D,0x43,0xA1,0xFF,
    0x46,0x18,0xFA,0xA4,0x27,0x79,0x9B,0xC5,0x84,0xDA,0x38,0x66,0xE5,0xBB,0x59,0x07,
    0xDB,0x85,0x67,0x39,0xBA,0xE4,0x06,0x58,0x19,0x47,0xA5,0xFB,0x78,0x26,0xC4,0x9A,
    0x65,0x3B,0xD9,0x87,0x04,0x5A,0xB8,0xE6,0xA7,0xF9,0x1B,0x45,0xC6,0x98,0x7A,0x24,
    0xF8,0xA6,0x44,0x1A,0x99,0xC7,0x25,0x7B,0x3A,0x64,0x86,0xD8,0x5B,0x05,0xE7,0xB9,
    0x8C,0xD2,0x30,0x6E,0xED,0xB3,0x51,0x0F,0x4E,0x10,0xF2,0xAC,0x2F,0x71,0x93,0xCD,
    0x11,0x4F,0xAD,0xF3,0x70,0x2E,0xCC,0x92,0xD3,0x8D,0x6F,0x31,0xB2,0xEC,0x0E,0x50,
    0xAF,0xF1,0x13,0x4D,0xCE,0x90,0x72,0x2C,0x6D,0x33,0xD1,0x8F,0x0C,0x52,0xB0,0xEE,
    0x32,0x6C,0x8E,0xD0,0x53,0x0D,0xEF,0xB1,0xF0,0xAE,0x4C,0x12,0x91,0xCF,0x2D,0x73,
    0xCA,0x94,0x76,0x28,0xAB,0xF5,0x17,0x49,0x08,0x56,0xB4,0xEA,0x69,0x37,0xD5,0x8B,
    0x57,0x09,0xEB,0xB5,0x36,0x68,0x8A,0xD4,0x95,0xCB,0x29,0x77,0xF4,0xAA,0x48,0x16,
    0xE9,0xB7,0x55,0x0B,0x88,0xD6,0x34,0x6A,0x2B,0x75,0x97,0xC9,0x4A,0x14,0xF6,0xA8,
    0x74,0x2A,0xC8,0x96,0x15,0x4B,0xA9,0xF7,0xB6,0xE8,0x0A,0x54,0xD7,0x89,0x6B,0x35,
)


def crc8_header(data: bytes, seed: int = 0x77) -> int:
    value = seed
    for byte in data:
        value = CRC8_TABLE[(byte ^ value) & 0xFF]
    return value


def crc16_duML(data: bytes, seed: int = 0x3692) -> int:
    """DJI DUMLv1 CRC16 (reflected 0x1021 polynomial / 0x8408 form)."""
    value = seed
    for byte in data:
        value ^= byte
        for _ in range(8):
            if value & 1:
                value = (value >> 1) ^ 0x8408
            else:
                value >>= 1
        value &= 0xFFFF
    return value


def build_packet(
    *,
    seq: int,
    payload: bytes,
    sender: int = COMM_DEV_PC,
    receiver: int = COMM_DEV_GIMBAL,
    packet_type: int = PACKET_TYPE_REQUEST,
    ack_type: int = ACK_BEFORE_EXEC,
    encrypt_type: int = NO_ENCRYPTION,
    cmd_set: int = CMD_SET_ZENMUSE,
    cmd_id: int = CMD_ID_GIMBAL_CALIB,
) -> bytes:
    length = 11 + len(payload) + 2
    if not 13 <= length <= 0x3FF:
        raise ValueError("DUML packet length out of range")

    ver_length = (1 << 10) | length
    cmd_type_data = ((packet_type & 1) << 7) | ((ack_type & 3) << 5) | (encrypt_type & 7)

    out = bytearray()
    out.append(SOF)
    out += ver_length.to_bytes(2, "little")
    out.append(crc8_header(bytes(out[:3])))
    out.append(sender & 0x1F)
    out.append(receiver & 0x1F)
    out += (seq & 0xFFFF).to_bytes(2, "little")
    out.append(cmd_type_data)
    out.append(cmd_set & 0xFF)
    out.append(cmd_id & 0xFF)
    out += payload
    out += crc16_duML(bytes(out)).to_bytes(2, "little")
    return bytes(out)


@dataclasses.dataclass(frozen=True)
class DumlFrame:
    raw: bytes
    sender: int
    receiver: int
    seq: int
    packet_type: int
    ack_type: int
    encrypt_type: int
    cmd_set: int
    cmd_id: int
    payload: bytes

    @property
    def hex(self) -> str:
        return self.raw.hex(" ")


def parse_frame(raw: bytes) -> DumlFrame:
    if len(raw) < 13:
        raise ValueError("frame too short")
    if raw[0] != SOF:
        raise ValueError("not a DUML 0x55 frame")

    advertised_len = int.from_bytes(raw[1:3], "little") & 0x03FF
    version = (int.from_bytes(raw[1:3], "little") >> 10) & 0x3F
    if version != 1:
        raise ValueError(f"unexpected DUML version {version}")
    if advertised_len != len(raw):
        raise ValueError(f"length mismatch: header={advertised_len}, actual={len(raw)}")
    if crc8_header(raw[:3]) != raw[3]:
        raise ValueError("header CRC8 mismatch")

    expected_crc = int.from_bytes(raw[-2:], "little")
    actual_crc = crc16_duML(raw[:-2])
    if actual_crc != expected_crc:
        raise ValueError(f"CRC16 mismatch: expected 0x{expected_crc:04x}, computed 0x{actual_crc:04x}")

    cmd_type_data = raw[8]
    return DumlFrame(
        raw=raw,
        sender=raw[4] & 0x1F,
        receiver=raw[5] & 0x1F,
        seq=int.from_bytes(raw[6:8], "little"),
        packet_type=(cmd_type_data >> 7) & 1,
        ack_type=(cmd_type_data >> 5) & 3,
        encrypt_type=cmd_type_data & 7,
        cmd_set=raw[9],
        cmd_id=raw[10],
        payload=raw[11:-2],
    )


class FrameReader:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> Iterable[DumlFrame]:
        self.buffer.extend(data)
        while True:
            try:
                sof_idx = self.buffer.index(SOF)
            except ValueError:
                self.buffer.clear()
                return

            if sof_idx:
                del self.buffer[:sof_idx]
            if len(self.buffer) < 4:
                return

            length = int.from_bytes(self.buffer[1:3], "little") & 0x03FF
            if length < 13 or length > 0x03FF:
                del self.buffer[0]
                continue
            if len(self.buffer) < length:
                return

            raw = bytes(self.buffer[:length])
            del self.buffer[:length]
            try:
                yield parse_frame(raw)
            except ValueError:
                # A bad 0x55 candidate may have consumed bytes. Put everything except
                # the first byte back so framing can resynchronize on a later 0x55.
                self.buffer = bytearray(raw[1:]) + self.buffer


def is_gimbal_calib_frame(frame: DumlFrame) -> bool:
    return (
        frame.sender == COMM_DEV_GIMBAL
        and frame.receiver == COMM_DEV_PC
        and frame.cmd_set == CMD_SET_ZENMUSE
        and frame.cmd_id == CMD_ID_GIMBAL_CALIB
    )


def describe_payload(command_name: str, payload: bytes) -> str:
    if len(payload) == 0:
        return "empty payload"
    if len(payload) == 1:
        # WM163 field observation from public repair testing. Meaning is not yet
        # claimed; treating it as opaque avoids a false success/failure result.
        return f"WM163 one-byte reply 0x{payload[0]:02x} (meaning not yet confirmed)"
    if len(payload) == 2:
        legacy_pass = LEGACY_PASS.get(command_name)
        pair = (payload[0], payload[1])
        if legacy_pass and pair == legacy_pass:
            return f"two-byte progress 0x{pair[0]:02x} 0x{pair[1]:02x} (matches legacy completion marker)"
        return f"two-byte progress/status 0x{pair[0]:02x} 0x{pair[1]:02x}"
    return f"{len(payload)}-byte payload: {payload.hex(' ')}"


def next_sequence() -> int:
    # Same basic approach as upstream: centiseconds modulo 16 bits.
    return int(time.time() * 100) & 0xFFFF


def read_frames(ser_obj, reader: FrameReader, deadline: float) -> Iterable[DumlFrame]:
    while time.monotonic() < deadline:
        waiting = getattr(ser_obj, "in_waiting", 0) or 0
        chunk = ser_obj.read(waiting if waiting > 0 else 1)
        if chunk:
            yield from reader.feed(chunk)
        else:
            time.sleep(0.01)


def run_calibration(port: str, baudrate: int, command_name: str, monitor_seconds: float, verbose: int) -> int:
    if serial is None:
        print("ERROR: pyserial is required. Install with: python -m pip install pyserial", file=sys.stderr)
        return 2

    command_byte = CALIB_COMMANDS[command_name]
    seq = next_sequence()
    packet = build_packet(seq=seq, payload=bytes([command_byte]))

    print(f"Model: {MODEL} ({PLATFORM})")
    print(f"Command: {command_name} (0x{command_byte:02x})")
    print(f"Port: {port} @ {baudrate}")
    if verbose:
        print(f"TX: {packet.hex(' ')}")

    with serial.Serial(port, baudrate=baudrate, timeout=0.05) as ser_obj:
        ser_obj.reset_input_buffer()
        ser_obj.write(packet)
        ser_obj.flush()

        reader = FrameReader()
        first_deadline = time.monotonic() + 3.0
        got_reply = False

        for frame in read_frames(ser_obj, reader, first_deadline):
            if verbose > 1:
                print(f"RX: {frame.hex}")
            if not is_gimbal_calib_frame(frame):
                continue
            got_reply = True
            print(f"Reply: {describe_payload(command_name, frame.payload)}")
            break

        if not got_reply:
            print("No matching gimbal-calibration reply was received within 3 seconds.")
            print("The command may not have reached the gimbal; no calibration result is assumed.")
            return 3

        print("Calibration command was acknowledged at the DUML transport level.")
        print("Do not move the aircraft while the gimbal is calibrating.")

        end = time.monotonic() + monitor_seconds
        packet_count = 0
        legacy_complete = False
        last_payload: Optional[bytes] = None

        for frame in read_frames(ser_obj, reader, end):
            if verbose > 1:
                print(f"RX: {frame.hex}")
            if not is_gimbal_calib_frame(frame):
                continue
            packet_count += 1
            last_payload = frame.payload
            desc = describe_payload(command_name, frame.payload)
            if verbose:
                print(f"Progress {packet_count}: {desc}")
            if len(frame.payload) == 2 and tuple(frame.payload) == LEGACY_PASS.get(command_name):
                legacy_complete = True
                break

        print(f"Observed {packet_count} additional gimbal-calibration packet(s).")
        if legacy_complete:
            print("Result: calibration reached the legacy completion marker.")
            return 0

        if last_payload is not None:
            print(f"Last observed WM163 payload: {last_payload.hex(' ')}")
        print("Result: command was accepted, but WM163 completion semantics are not yet fully decoded.")
        print("Judge the repair by the gimbal's physical centering and a subsequent DJI Fly auto-calibration.")
        return 0


def replay_frames(command_name: str, frames: list[str]) -> int:
    reader = FrameReader()
    for item in frames:
        raw = bytes.fromhex(item)
        parsed = list(reader.feed(raw))
        if not parsed:
            print(f"No valid frame decoded from: {item}")
            continue
        for frame in parsed:
            print(frame.hex)
            print(f"  sender={frame.sender} receiver={frame.receiver} seq=0x{frame.seq:04x}")
            print(f"  packet_type={frame.packet_type} cmd_set=0x{frame.cmd_set:02x} cmd_id=0x{frame.cmd_id:02x}")
            print(f"  {describe_payload(command_name, frame.payload)}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Experimental repair-calibration helper for DJI Mini 3 (WM163) gimbals."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("-v", "--verbose", action="count", default=0)

    sub = parser.add_subparsers(dest="action", required=True)

    for name in ("joint-coarse", "linear-hall"):
        p = sub.add_parser(name, help=f"send the WM163 {name} gimbal calibration command")
        p.add_argument("--port", required=True, help="serial port exposed by the aircraft, e.g. COM3")
        p.add_argument("--baudrate", type=int, default=9600, help="serial baud rate (default: 9600)")
        p.add_argument(
            "--monitor-seconds",
            type=float,
            default=45.0 if name == "linear-hall" else 25.0,
            help="how long to collect calibration status packets",
        )
        p.add_argument(
            "--yes",
            action="store_true",
            help="required acknowledgement that this is experimental repair software",
        )

    dry = sub.add_parser("dry-run", help="build a known request packet without touching hardware")
    dry.add_argument("command", choices=tuple(CALIB_COMMANDS))
    dry.add_argument("--seq", type=lambda s: int(s, 0), default=0xD839)

    replay = sub.add_parser("replay", help="decode one or more captured DUML hex frames")
    replay.add_argument("command", choices=tuple(CALIB_COMMANDS))
    replay.add_argument("frames", nargs="+")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.action == "dry-run":
        packet = build_packet(seq=args.seq, payload=bytes([CALIB_COMMANDS[args.command]]))
        print(packet.hex(" "))
        return 0

    if args.action == "replay":
        return replay_frames(args.command, args.frames)

    if not args.yes:
        parser.error(
            "refusing to send a hardware calibration command without --yes; "
            "verify the aircraft is a DJI Mini 3 / WM163, remove propellers, and place it on a level surface"
        )

    print("WARNING: Experimental WM163 repair calibration. This is not DJI-authorized service software.")
    print("Remove propellers and keep the aircraft stationary on a level surface.")
    return run_calibration(args.port, args.baudrate, args.action, args.monitor_seconds, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
