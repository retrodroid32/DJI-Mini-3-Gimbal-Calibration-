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


def test_gray_order_matches_recovered_logic():
    from wm163_service_flash_protocol import gray_order

    files = [
        "wm163_1100_x.sig",
        "wm163_0306_x.sig",
        "wm163.cfg.sig",
        "wm163_0100_x.sig",
        "wm163_1200_x.sig",
        "wm163_0905_x.sig",
        "wm163_0105_x.sig",
    ]
    assert gray_order(files) == [
        "wm163.cfg.sig",
        "wm163_0100_x.sig",
        "wm163_0105_x.sig",
        "wm163_0306_x.sig",
        "wm163_0905_x.sig",
        "wm163_1100_x.sig",
        "wm163_1200_x.sig",
    ]


def test_gray_order_non_module_names_sort_before_module_names_stably():
    from wm163_service_flash_protocol import gray_order

    files = ["z.cfg", "wm163_0306_x.sig", "a.cfg", "wm163_0100_x.sig"]
    assert gray_order(files) == ["z.cfg", "a.cfg", "wm163_0100_x.sig", "wm163_0306_x.sig"]


def test_session_b_total_size_counts_only_transferred_blob_bytes():
    from wm163_service_flash_protocol import session_b_total_size

    files = [
        ("wm163.cfg.sig", b"x" * 5),
        ("wm163_0100_test.pro.fw.sig", b"y" * 7),
    ]
    assert session_b_total_size(files) == 12


def test_known_v30_session_b_total_size():
    from wm163_service_flash_protocol import session_b_total_size

    # Signed member sizes from the validated WM163 V30.00.0100 archive:
    # cfg + 0100 + 0105 + 0306 + 0905 + 1100 + 1200.
    files = [
        ("wm163.cfg.sig", b"x" * 2336),
        ("0100", b"x" * 39459264),
        ("0105", b"x" * 245824),
        ("0306", b"x" * 1760032),
        ("0905", b"x" * 10390912),
        ("1100", b"x" * 94720),
        ("1200", b"x" * 56352),
    ]
    assert session_b_total_size(files) == 52009440


def test_known_loader_record_and_sequence_invariants():
    from wm163_service_flash_protocol import chunk_count, seq_after

    loader_size = 743120
    assert chunk_count(loader_size) == 759
    assert loader_size - (758 * CHUNK) == 280
    # ENTER + PREPARE + REPORT_SIZE + 759 DATA + VERIFY + CMD_0B
    assert seq_after(0x4900, 764) == 0x4BFC


def test_known_v30_session_b_record_and_finalize_sequence_invariants():
    from wm163_service_flash_protocol import session_b_record_count, seq_after

    files = [
        ("wm163.cfg.sig", b"x" * 2336),
        ("0100", b"x" * 39459264),
        ("0105", b"x" * 245824),
        ("0306", b"x" * 1760032),
        ("0905", b"x" * 10390912),
        ("1100", b"x" * 94720),
        ("1200", b"x" * 56352),
    ]
    assert session_b_record_count(files) == 53087
    # ENTER and REPORT_SIZE consume 0x3022 and 0x3023; first 0x2A record is 0x3024.
    assert seq_after(0x3024, 53087) == 0xFF83


def test_recovered_sequence_defaults_and_drain_cadence():
    from wm163_service_flash_protocol import (
        SESSION_A_SEQ0,
        SESSION_B_SEQ0,
        SESSION_B_TIMEOUT_SECONDS,
        SESSION_B_DRAIN_EVERY_RECORDS,
        SESSION_B_PERIODIC_DRAIN_MS,
        SESSION_B_FINAL_DRAIN_MS,
        SESSION_B_WRITE_WINDOW_MS,
        SESSION_B_WRITE_READ_TIMEOUT_MS,
        ENGINE_DRAIN_READ_TIMEOUT_MS,
    )

    assert SESSION_A_SEQ0 == 0x4900
    assert SESSION_B_SEQ0 == 0x3022
    assert SESSION_B_TIMEOUT_SECONDS == 180
    assert SESSION_B_DRAIN_EVERY_RECORDS == 64
    assert SESSION_B_PERIODIC_DRAIN_MS == 15
    assert SESSION_B_FINAL_DRAIN_MS == 300
    assert SESSION_B_WRITE_WINDOW_MS == 0
    assert SESSION_B_WRITE_READ_TIMEOUT_MS == 1
    assert ENGINE_DRAIN_READ_TIMEOUT_MS == 40


def test_recovered_sequence_helpers_match_known_transfers():
    from wm163_service_flash_protocol import (
        session_a_next_seq_after_loader,
        session_b_finalize_seq,
    )

    assert session_a_next_seq_after_loader(743120) == 0x4BFC

    files = [
        ("wm163.cfg.sig", b"x" * 2336),
        ("0100", b"x" * 39459264),
        ("0105", b"x" * 245824),
        ("0306", b"x" * 1760032),
        ("0905", b"x" * 10390912),
        ("1100", b"x" * 94720),
        ("1200", b"x" * 56352),
    ]
    assert session_b_finalize_seq(files) == 0xFF83


def test_recovered_session_b_loader_probe():
    from wm163_service_flash_protocol import (
        COMMIT_PROBE_DST_RAW,
        CMDSET_GENERAL,
        CMD_COMMIT_PROBE,
        FLAG_REQ_ACK,
        SESSION_B_LOADER_WAIT_SECONDS,
        SESSION_B_LOADER_PROBE_SEQ0,
        SESSION_B_LOADER_PROBE_XFER_TIMEOUT_MS,
        SESSION_B_LOADER_PROBE_DRAIN_MS,
        SESSION_B_LOADER_PROBE_SLEEP_SECONDS,
        SESSION_B_LOADER_IDENTITY_MARKER,
        session_b_loader_probe_command,
        loader_probe_identity_seen,
    )

    assert SESSION_B_LOADER_WAIT_SECONDS == 180
    assert SESSION_B_LOADER_PROBE_SEQ0 == 0
    assert SESSION_B_LOADER_PROBE_XFER_TIMEOUT_MS == 4000
    assert SESSION_B_LOADER_PROBE_DRAIN_MS == 200
    assert SESSION_B_LOADER_PROBE_SLEEP_SECONDS == 2
    assert SESSION_B_LOADER_IDENTITY_MARKER == b"UAV"

    cmd = session_b_loader_probe_command(0)
    assert cmd.dst_raw == COMMIT_PROBE_DST_RAW == 0x28
    assert cmd.cmd_set == CMDSET_GENERAL == 0x00
    assert cmd.cmd_id == CMD_COMMIT_PROBE == 0x01
    assert cmd.payload == b""
    assert cmd.seq == 0
    assert cmd.flags == FLAG_REQ_ACK == 0x40

    assert loader_probe_identity_seen(b"prefix WM163 ", b"UAV suffix")
    assert loader_probe_identity_seen(b"UAV", b"")
    assert not loader_probe_identity_seen(b"WM163", b"")


def test_loader_probe_first_packet_matches_commit_probe_fields():
    from wm163_service_flash_protocol import (
        session_b_loader_probe_command,
        commit_hold_probe_command,
    )

    assert session_b_loader_probe_command(0) == commit_hold_probe_command()
