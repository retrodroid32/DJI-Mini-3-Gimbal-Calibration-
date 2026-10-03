import io
import hashlib
import pathlib
import struct
import tarfile

import pytest

from wm163_service_fw_inspect import (
    EXPECTED_MODULE_ORDER,
    _extract_xml,
    _validate_imah,
)


def _imah(payload: bytes) -> bytes:
    total = 32 + len(payload)
    hdr = bytearray(32)
    hdr[:4] = b"IM*H"
    struct.pack_into("<I", hdr, 4, 2)
    struct.pack_into("<I", hdr, 8, total)
    struct.pack_into("<I", hdr, 16, 224)
    struct.pack_into("<I", hdr, 20, 256)
    struct.pack_into("<I", hdr, 24, len(payload))
    struct.pack_into("<I", hdr, 28, total)
    return bytes(hdr) + payload


def test_validate_imah_accepts_matching_size():
    blob = _imah(b"abc")
    _validate_imah("x", blob)


def test_validate_imah_rejects_bad_size():
    blob = bytearray(_imah(b"abc"))
    struct.pack_into("<I", blob, 8, 999)
    with pytest.raises(ValueError, match="size mismatch"):
        _validate_imah("x", bytes(blob))


def test_extract_xml_from_signed_cfg():
    xml = b'<?xml version="1.0"?><dji><device id="wm163"/></dji>'
    blob = _imah(b"prefix" + xml + b"\x00\x00")
    assert _extract_xml(blob) == xml


def test_expected_v30_order_is_fixed():
    assert EXPECTED_MODULE_ORDER == ("0905", "0306", "1200", "1100", "0105", "0100")
