#!/usr/bin/env python3
"""Offline evidence model for WM163 production-firmware restore research.

This module contains no serial or transport code.

Recovered from DrGrey's compiled mini2style_flash implementation:
- report-size uses selector 01 02;
- signed-file records use 01 START / 02 DATA / 03 END;
- DATA carries a little-endian uint32 chunk index;
- END carries the supplied 16-byte MD5 digest;
- file START/DATA/END records are carried under command 0x2A;
- surrounding control commands are 0x07 ENTER, 0x08 REPORT SIZE and 0x0A FINALIZE;
- request flags include 0x40;
- FINALIZE is 17 zero bytes;
- the normal updater monitors install-state push 0x42 after verification.

Those payload builders are byte-equivalent to the capture-backed WM163
Service-FW Session-B grammar for the production image's observed chunk range.

This does NOT prove which outer transport/orchestration a WM163 uses when
returning from Service FW to stock production firmware. In particular, it does
not prove destination node, transfer command id, FINALIZE response semantics,
or post-finalize commit/reboot behavior for a stock restore.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import struct


class EvidenceLevel(str, Enum):
    CAPTURE_PROVEN = "capture-proven"
    BINARY_RECOVERED = "binary-recovered"
    STRUCTURALLY_VALID = "structurally-valid"
    UNPROVEN = "unproven"


MINI2STYLE_ENTER_CMD = 0x07
MINI2STYLE_REPORT_SIZE_CMD = 0x08
MINI2STYLE_TRANSFER_CMD = 0x2A
MINI2STYLE_FINALIZE_CMD = 0x0A
MINI2STYLE_REQUEST_FLAGS = 0x40
MINI2STYLE_INSTALL_PUSH_CMD = 0x42
MINI2STYLE_REPORT_SELECTOR = b"\x01\x02"
MINI2STYLE_FINALIZE_PAYLOAD = b"\x00" * 17


def build_mini2style_report_size(total_size: int) -> bytes:
    if not 0 <= total_size <= 0xFFFFFFFF:
        raise ValueError("total_size out of uint32 range")
    return (
        b"\x00"
        + struct.pack("<I", total_size)
        + bytes.fromhex("00 00 00 00 00 00 01 02")
    )


def build_mini2style_file_start(name: str, size: int) -> bytes:
    if not 0 <= size <= 0xFFFFFFFF:
        raise ValueError("size out of uint32 range")
    encoded = name.encode("utf-8")
    if len(encoded) + 1 > 0xFF:
        raise ValueError("encoded filename is too long")
    # Recovered native expression is equivalent to:
    # 01 + <I size> + bytes([len(name)+1]) + name + 00 + bytes(3)
    return (
        b"\x01"
        + struct.pack("<I", size)
        + bytes([len(encoded) + 1])
        + encoded
        + b"\x00"
        + bytes(3)
    )


def build_mini2style_chunk(chunk_index: int, data: bytes) -> bytes:
    if not 0 <= chunk_index <= 0xFFFFFFFF:
        raise ValueError("chunk_index out of uint32 range")
    return b"\x02" + struct.pack("<I", chunk_index) + bytes(data)


def build_mini2style_file_end(md5_digest: bytes) -> bytes:
    digest = bytes(md5_digest)
    if len(digest) != 16:
        raise ValueError("MD5 digest must be exactly 16 bytes")
    return b"\x03" + digest


@dataclass(frozen=True)
class RestoreEvidence:
    subject: str
    level: EvidenceLevel
    finding: str


EVIDENCE = (
    RestoreEvidence(
        "WM163 Service-FW Session A/B",
        EvidenceLevel.CAPTURE_PROVEN,
        "Genuine DrGrey USB capture plus byte-for-byte offline replay.",
    ),
    RestoreEvidence(
        "Generic DJI signed-file payload grammar",
        EvidenceLevel.BINARY_RECOVERED,
        (
            "DrGrey mini2style_flash independently uses command 0x2A with the "
            "same 01/02/03 file-record grammar, 01 02 report selector, and "
            "17-zero FINALIZE; surrounding controls are 0x07/0x08/0x0A."
        ),
    ),
    RestoreEvidence(
        "WM163 v01.00.0500 production archive in that grammar",
        EvidenceLevel.STRUCTURALLY_VALID,
        (
            "Exact production archive packetizes cleanly; payload ordering, "
            "sizes, MD5 records and uint16 DUML rollover are deterministic."
        ),
    ),
    RestoreEvidence(
        "WM163 stock-restore outer orchestration",
        EvidenceLevel.UNPROVEN,
        (
            "Destination/transfer command, FINALIZE reply semantics and "
            "post-finalize install/reboot behavior lack WM163 stock-restore evidence."
        ),
    ),
)


def render_evidence_matrix() -> str:
    return "\n".join(
        f"{item.level.value:20s} | {item.subject} | {item.finding}"
        for item in EVIDENCE
    )
