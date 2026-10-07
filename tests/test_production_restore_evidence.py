import hashlib

from wm163_production_restore_evidence import (
    EvidenceLevel,
    MINI2STYLE_ENTER_CMD,
    MINI2STYLE_REPORT_SIZE_CMD,
    MINI2STYLE_TRANSFER_CMD,
    MINI2STYLE_FINALIZE_CMD,
    MINI2STYLE_REQUEST_FLAGS,
    MINI2STYLE_FINALIZE_PAYLOAD,
    MINI2STYLE_INSTALL_PUSH_CMD,
    build_mini2style_chunk,
    build_mini2style_file_end,
    build_mini2style_file_start,
    build_mini2style_report_size,
    EVIDENCE,
)
from wm163_service_flash_protocol import (
    session_b_file_data_payload,
    session_b_file_end_payload,
    session_b_file_start_payload,
    session_b_finalize_payload,
    session_b_report_size_payload,
)


def test_recovered_mini2style_report_size_matches_wm163_session_b_grammar():
    size = 53_315_680
    assert build_mini2style_report_size(size) == session_b_report_size_payload(size)


def test_recovered_mini2style_file_start_matches_wm163_session_b_grammar():
    name = "wm163_0306_v03.04.11.34_20240513.pro.fw.sig"
    size = 1_765_152
    assert build_mini2style_file_start(name, size) == session_b_file_start_payload(
        name, b"x" * size
    )


def test_recovered_mini2style_chunk_matches_captured_wm163_chunk_grammar():
    # For WM163 observed 24-bit-range indices, uint32 LE is byte-identical
    # to uint24 LE followed by the captured zero byte.
    for index in (0, 1, 9547, 9548, 9549, 9550, 0x00FFFFFE):
        data = b"offline-test"
        assert build_mini2style_chunk(index, data) == session_b_file_data_payload(
            index, data
        )


def test_recovered_mini2style_file_end_matches_wm163_session_b_grammar():
    blob = b"signed-module"
    digest = hashlib.md5(blob).digest()
    assert build_mini2style_file_end(digest) == session_b_file_end_payload(blob)


def test_recovered_mini2style_finalize_matches_wm163_session_b_grammar():
    assert MINI2STYLE_FINALIZE_PAYLOAD == b"\x00" * 17
    assert MINI2STYLE_FINALIZE_PAYLOAD == session_b_finalize_payload()


def test_evidence_model_does_not_promote_stock_restore_to_proven():
    stock = next(x for x in EVIDENCE if x.subject == "WM163 stock-restore outer orchestration")
    assert stock.level is EvidenceLevel.UNPROVEN
    assert MINI2STYLE_INSTALL_PUSH_CMD == 0x42


def test_recovered_mini2style_outer_command_mapping():
    assert MINI2STYLE_ENTER_CMD == 0x07
    assert MINI2STYLE_REPORT_SIZE_CMD == 0x08
    assert MINI2STYLE_TRANSFER_CMD == 0x2A
    assert MINI2STYLE_FINALIZE_CMD == 0x0A
    assert MINI2STYLE_REQUEST_FLAGS == 0x40
    assert MINI2STYLE_INSTALL_PUSH_CMD == 0x42

    # Important correction: DrGrey's signed-file stream is its custom 0x2A
    # record transport, not the generic General 0x09 command.
    assert MINI2STYLE_TRANSFER_CMD != 0x09
