from analyze_wm163_production_restore import (
    KNOWN_PRODUCTION_SESSION_B_FILES,
    KNOWN_PRODUCTION_SESSION_B_FINALIZE_SEQ,
    KNOWN_PRODUCTION_SESSION_B_TOTAL_SIZE,
    transfer_summary,
)
import wm163_service_flash_live as service_fw


def test_production_restore_transfer_summary_uses_capture_backed_packetization():
    files = [
        ("0905.cfg.sig", b"abc"),
        ("0905.pro.fw.sig", b"12345"),
    ]

    summary = transfer_summary(files)

    assert summary["file_count"] == 2
    assert summary["files"] == (
        ("0905.cfg.sig", 3),
        ("0905.pro.fw.sig", 5),
    )
    assert summary["total_size"] == service_fw.session_b_total_size(files)
    assert summary["finalize_seq"] == service_fw.session_b_finalize_seq(files)


def test_exact_production_transfer_invariants_require_uint16_rollover():
    files = [(name, b"x" * size) for name, size in KNOWN_PRODUCTION_SESSION_B_FILES]

    summary = transfer_summary(files)

    assert summary["file_count"] == 7
    assert summary["total_size"] == KNOWN_PRODUCTION_SESSION_B_TOTAL_SIZE
    assert summary["finalize_seq"] == KNOWN_PRODUCTION_SESSION_B_FINALIZE_SEQ == 0x04C0

    # Without uint16 rollover this would be greater than 0xFFFF.
    from wm163_service_flash_protocol import (
        SESSION_B_SEQ0,
        session_b_record_count,
    )

    unwrapped_finalize = (
        SESSION_B_SEQ0
        + 2
        + session_b_record_count(files)
        + len(files)
    )
    assert unwrapped_finalize > 0xFFFF
    assert (unwrapped_finalize & 0xFFFF) == 0x04C0


def test_uint16_rollover_matches_wire_encoding():
    from wm163_service_flash_live import encode_raw
    from wm163_service_flash_protocol import CMD_STREAM_B, SESSION_B_DST_RAW, seq_after

    assert seq_after(0xFFFE, 1) == 0xFFFF
    assert seq_after(0xFFFF, 1) == 0x0000
    assert seq_after(0xFFFF, 2) == 0x0001

    packets = [
        encode_raw(
            dst_raw=SESSION_B_DST_RAW,
            seq=seq,
            cmd_id=CMD_STREAM_B,
            payload=b"\x02\x00\x00\x00\x00",
        )
        for seq in (0xFFFE, 0xFFFF, 0x0000, 0x0001)
    ]

    # DUML sequence is little-endian at bytes 6..7.
    assert [packet[6:8] for packet in packets] == [
        b"\xfe\xff",
        b"\xff\xff",
        b"\x00\x00",
        b"\x01\x00",
    ]
