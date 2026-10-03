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

SESSION_A_SEQ0 = 0x4900
SESSION_B_LOADER_WAIT_SECONDS = 180
SESSION_B_LOADER_PROBE_SEQ0 = 0
SESSION_B_LOADER_PROBE_XFER_TIMEOUT_MS = 4000
SESSION_B_LOADER_PROBE_DRAIN_MS = 200
SESSION_B_LOADER_PROBE_SLEEP_SECONDS = 2
SESSION_B_LOADER_IDENTITY_MARKER = b"UAV"
SESSION_B_SEQ0 = 0x3022
SESSION_B_TIMEOUT_SECONDS = 180
SESSION_B_DRAIN_EVERY_RECORDS = 64
SESSION_B_PERIODIC_DRAIN_MS = 15
SESSION_B_FINAL_DRAIN_MS = 300
SESSION_B_WRITE_WINDOW_MS = 0
SESSION_B_WRITE_READ_TIMEOUT_MS = 1
ENGINE_DRAIN_READ_TIMEOUT_MS = 40
CTRL_ACK_DEADLINE_SECONDS = 15
STREAM_ACK_DEADLINE_SECONDS = 20
ACK_COLLECT_DRAIN_MS = 400

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


def session_b_loader_probe_command(seq: int) -> EncodedCommand:
    """Recovered Session-B preflight probe used while waiting for the temp loader."""
    if not 0 <= seq <= 0xFFFF:
        raise ValueError("seq must fit uint16")
    return EncodedCommand(
        dst_raw=COMMIT_PROBE_DST_RAW,
        cmd_set=CMDSET_GENERAL,
        cmd_id=CMD_COMMIT_PROBE,
        payload=b"",
        seq=seq,
        flags=FLAG_REQ_ACK,
    )


def loader_probe_identity_seen(xfer_bytes: bytes, drain_bytes: bytes) -> bool:
    """DrGrey accepts the loader when raw xfer+drain bytes contain b'UAV'."""
    return SESSION_B_LOADER_IDENTITY_MARKER in (bytes(xfer_bytes) + bytes(drain_bytes))


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


def gray_order(files):
    """Recovered DrGrey Session-B ordering helper.

    Names without a _NNNN_ module marker sort first. Module-bearing names then
    sort numerically by that four-digit module id.
    """
    import re

    def key(name):
        m = re.search(r"_(\d{4})_", name)
        if m:
            return (1, int(m.group(1)))
        return (0, 0)

    return sorted(files, key=key)


def session_b_total_size(files):
    """Recovered DrGrey Session-B total_size calculation.

    files is the sequence of (filename, blob) pairs actually transferred.
    Protocol/name overhead and tar metadata are not counted.
    """
    return sum(len(blob) for _name, blob in files)


def chunk_count(size: int, chunk_size: int = CHUNK) -> int:
    """Offline record-count helper for a byte stream split into fixed chunks."""
    if size < 0:
        raise ValueError("size must be non-negative")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return (size + chunk_size - 1) // chunk_size


def session_b_record_count(files) -> int:
    """Count START/DATA/END records for an already-selected Session-B file set."""
    return sum(2 + chunk_count(len(blob)) for _name, blob in files)


def seq_after(start_seq: int, operations: int) -> int:
    """Offline 16-bit sequence arithmetic used for recovered transfer invariants."""
    if not 0 <= start_seq <= 0xFFFF:
        raise ValueError("start_seq must fit uint16")
    if operations < 0:
        raise ValueError("operations must be non-negative")
    return (start_seq + operations) & 0xFFFF


def session_a_next_seq_after_loader(loader_size: int) -> int:
    """Expected next-unused Session-A sequence after a complete loader transfer."""
    # ENTER + PREPARE + REPORT_SIZE + DATA records + CMD_0A + CMD_0B.
    operations = 5 + chunk_count(loader_size)
    return seq_after(SESSION_A_SEQ0, operations)


def session_b_finalize_seq(files) -> int:
    """Expected B/FINALIZE sequence for an already-selected Session-B file set."""
    # ENTER and REPORT_SIZE consume the first two sequence values.
    first_record_seq = seq_after(SESSION_B_SEQ0, 2)
    return seq_after(first_record_seq, session_b_record_count(files))


def ctrl_ack_payload_accepted(payload: bytes) -> bool:
    """Recovered DrGrey _ctrl ACK payload acceptance rule.

    After match_ack() has already confirmed response flag, command id and
    sequence, _ctrl examines payload[:1].  An empty payload or a leading
    0x00 status is accepted.  Any other leading status is a device-side
    rejection.

    This helper is offline/transport-agnostic; it does not transmit anything.
    """
    status = bytes(payload)[:1]
    return status in (b"", b"\x00")


def session_b_finalize_gate(*, stream_exhausted: bool, final_drain_completed: bool) -> bool:
    """Offline invariant for the recovered Session-B -> FINALIZE boundary.

    DrGrey only reaches B/FINALIZE after the Session-B file iterator is
    exhausted and the terminal drain(300) call returns normally. Exceptions
    from a 0x2A write, a periodic drain(15), or the terminal drain(300)
    propagate out of session_b and therefore prevent FINALIZE.

    A normal drain return may contain b""; payload content is not inspected at
    this boundary.
    """
    return bool(stream_exhausted and final_drain_completed)
