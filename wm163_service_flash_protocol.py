#!/usr/bin/env python3
"""Recovered WM163 Mini 3 service-flash protocol primitives.

This module is intentionally transport-agnostic. It builds and validates payloads
but does not open a serial port or transmit to an aircraft.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

SESSION_A_DST_RAW = 0xA9
SESSION_B_DST_RAW = 0x01
COMMIT_PROBE_DST_RAW = 0x28

CMDSET_GENERAL = 0x00
FLAG_REQ_ACK = 0x40
CHUNK = 980

CMD_ENTER = 0x07
CMD_REPORT_SIZE = 0x08
CMD_STREAM_A = 0x09
CMD_FINALIZE = 0x0A
CMD_REBOOT_A = 0x0B
CMD_PREPARE_A = 0x0C
CMD_STREAM_B = 0x2A
CMD_COMMIT_PROBE = 0x01

COMMIT_PROBE_SEQ = 0
COMMIT_PROBE_TIMEOUT_MS = 500
COMMIT_HOLD_SLEEP_SECONDS = 0.5
COMMIT_HOLD_DEFAULT_SECONDS = 150

SESSION_A_FINAL_SELECTOR = b"\x01\x00"
SESSION_B_FINAL_SELECTOR = b"\x01\x02"


@dataclass(frozen=True)
class EncodedCommand:
    dst_raw: int
    cmd_set: int
    cmd_id: int
    payload: bytes
    seq: int
    flags: int


def session_a_enter_payload() -> bytes:
    return b"\x00" * 9


def session_a_prepare_payload() -> bytes:
    return b"\x00"


def report_size_payload(size: int, selector: bytes) -> bytes:
    if not 0 <= size <= 0xFFFFFFFF:
        raise ValueError("size out of uint32 range")
    if len(selector) != 2:
        raise ValueError("selector must be exactly two bytes")
    return b"\x00" + struct.pack("<I", size) + b"\x00" * 6 + selector


def session_a_report_size_payload(size: int) -> bytes:
    return report_size_payload(size, SESSION_A_FINAL_SELECTOR)


def session_b_report_size_payload(size: int) -> bytes:
    return report_size_payload(size, SESSION_B_FINAL_SELECTOR)


def session_a_stream_payload(offset: int, chunk: bytes) -> bytes:
    if not 0 <= offset <= 0xFFFFFFFF:
        raise ValueError("offset out of uint32 range")
    if len(chunk) > CHUNK:
        raise ValueError(f"chunk exceeds recovered {CHUNK}-byte limit")
    return b"\x00" + struct.pack("<I", offset) + struct.pack("<H", len(chunk)) + chunk


def session_a_finalize_payload(loader: bytes) -> bytes:
    return b"\x00" + hashlib.md5(loader).digest()


def session_a_reboot_payload() -> bytes:
    return b"\x00\x01" + struct.pack("<I", 1000) + b"DEADBEEF"


def session_b_file_start_payload(filename: str, blob: bytes) -> bytes:
    name = filename.encode("utf-8")
    if len(name) + 1 > 0xFF:
        raise ValueError("filename is too long")
    return b"\x01" + struct.pack("<I", len(blob)) + bytes([len(name) + 1]) + name + b"\x00" * 4


def session_b_file_data_payload(offset: int, chunk: bytes) -> bytes:
    if not 0 <= offset <= 0xFFFFFF:
        raise ValueError("Session-B offset exceeds recovered 24-bit field")
    if len(chunk) > CHUNK:
        raise ValueError(f"chunk exceeds recovered {CHUNK}-byte limit")
    return b"\x02" + struct.pack("<I", offset)[:3] + b"\x00" + chunk


def session_b_file_end_payload(blob: bytes) -> bytes:
    return b"\x03" + hashlib.md5(blob).digest()


def session_b_finalize_payload() -> bytes:
    return b"\x00" * 17


def commit_hold_probe_command() -> EncodedCommand:
    """Exact DrGrey WM163 _hold_for_commit probe recovered from Cython constants."""
    return EncodedCommand(
        dst_raw=COMMIT_PROBE_DST_RAW,
        cmd_set=CMDSET_GENERAL,
        cmd_id=CMD_COMMIT_PROBE,
        payload=b"",
        seq=COMMIT_PROBE_SEQ,
        flags=FLAG_REQ_ACK,
    )
