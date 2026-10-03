import struct

from mini3_gimbal_cal import (
    build_cfg_manifest_read_payload,
    parse_aircraft_cfg_manifest,
    parse_cfg_manifest_reply,
)


def test_cfg_manifest_request_wire_format():
    assert build_cfg_manifest_read_payload(0x11223344, 1000) == bytes.fromhex(
        "01 44 33 22 11 e8 03 00 00"
    )


def test_cfg_manifest_reply_parser():
    payload = (
        b"\x00"
        + struct.pack("<I", 4)
        + struct.pack("<I", 12)
        + b"ABCD"
    )
    status, remaining, chunk = parse_cfg_manifest_reply(payload)
    assert status == 0
    assert remaining == 12
    assert chunk == b"ABCD"


def test_cfg_manifest_reply_rejects_truncated_chunk():
    payload = (
        b"\x00"
        + struct.pack("<I", 10)
        + struct.pack("<I", 0)
        + b"abc"
    )
    try:
        parse_cfg_manifest_reply(payload)
    except ValueError as exc:
        assert "exceeds available" in str(exc)
    else:
        raise AssertionError("expected truncated manifest chunk to fail")


def test_aircraft_cfg_manifest_extracts_formal_and_arb():
    blob = (
        b"IM*H" + b"\x00" * 96
        + b'<?xml version="1.0"?><dji><device id="wm163"><firmware formal="01.00.0600">'
        + b'<release version="01.00.0600" antirollback="3" antirollback_ext="cn:3" '
        + b'enforce="1" enforce_time="2026-01-01T00:00:00+00:00">'
        + b'<module id="0306" version="03.04.11.31">wm163_0306_x.pro.fw.sig</module>'
        + b"</release></firmware></device></dji>"
    )
    info = parse_aircraft_cfg_manifest(blob)
    assert info.device == "wm163"
    assert info.formal == "01.00.0600"
    assert info.release == "01.00.0600"
    assert info.antirollback == "3"
    assert info.antirollback_ext == "cn:3"
    assert info.enforce == "1"
    assert info.modules == (
        ("0306", "03.04.11.31", "wm163_0306_x.pro.fw.sig"),
    )
