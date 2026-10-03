import hashlib
import struct

from wm163_service_flash_protocol import (
    CHUNK,
    CMDSET_GENERAL,
    CMD_COMMIT_PROBE,
    COMMIT_HOLD_DEFAULT_SECONDS,
    COMMIT_HOLD_SLEEP_SECONDS,
    COMMIT_PROBE_DST_RAW,
    COMMIT_PROBE_SEQ,
    COMMIT_PROBE_TIMEOUT_MS,
    FLAG_REQ_ACK,
    commit_hold_probe_command,
    session_a_enter_payload,
    session_a_finalize_payload,
    session_a_prepare_payload,
    session_a_reboot_payload,
    session_a_report_size_payload,
    session_a_stream_payload,
    session_b_file_data_payload,
    session_b_file_end_payload,
    session_b_file_start_payload,
    session_b_finalize_payload,
    session_b_report_size_payload,
)


def test_session_a_control_payloads():
    assert session_a_enter_payload() == b"\x00" * 9
    assert session_a_prepare_payload() == b"\x00"
    assert session_a_report_size_payload(0x12345678) == (
        b"\x00\x78\x56\x34\x12" + b"\x00" * 6 + b"\x01\x00"
    )
    assert session_a_reboot_payload() == bytes.fromhex(
        "00 01 e8 03 00 00 44 45 41 44 42 45 45 46"
    )


def test_session_a_stream_and_md5():
    chunk = b"abc"
    assert session_a_stream_payload(0x11223344, chunk) == (
        b"\x00\x44\x33\x22\x11\x03\x00abc"
    )
    loader = b"loader"
    assert session_a_finalize_payload(loader) == b"\x00" + hashlib.md5(loader).digest()


def test_session_b_payloads():
    assert session_b_report_size_payload(0x12345678) == (
        b"\x00\x78\x56\x34\x12" + b"\x00" * 6 + b"\x01\x02"
    )
    assert session_b_file_start_payload("abc", b"12345") == (
        b"\x01\x05\x00\x00\x00\x04abc" + b"\x00" * 4
    )
    assert session_b_file_data_payload(0x123456, b"xyz") == bytes.fromhex(
        "02 56 34 12 00"
    ) + b"xyz"
    data = b"module"
    assert session_b_file_end_payload(data) == b"\x03" + hashlib.md5(data).digest()
    assert session_b_finalize_payload() == b"\x00" * 17


def test_recovered_commit_hold_probe_exact():
    cmd = commit_hold_probe_command()
    assert cmd.dst_raw == 0x28 == COMMIT_PROBE_DST_RAW
    assert cmd.cmd_set == 0x00 == CMDSET_GENERAL
    assert cmd.cmd_id == 0x01 == CMD_COMMIT_PROBE
    assert cmd.payload == b""
    assert cmd.seq == 0 == COMMIT_PROBE_SEQ
    assert cmd.flags == 0x40 == FLAG_REQ_ACK
    assert COMMIT_PROBE_TIMEOUT_MS == 500
    assert COMMIT_HOLD_SLEEP_SECONDS == 0.5
    assert COMMIT_HOLD_DEFAULT_SECONDS == 150


def test_chunk_limit_is_980():
    session_a_stream_payload(0, b"x" * CHUNK)
    session_b_file_data_payload(0, b"x" * CHUNK)
