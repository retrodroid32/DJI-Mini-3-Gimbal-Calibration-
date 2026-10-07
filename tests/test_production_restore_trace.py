from trace_wm163_production_restore_candidate import (
    KNOWN_PRODUCTION_CANDIDATE_FINALIZE_SEQ,
    KNOWN_PRODUCTION_CANDIDATE_PACKET_COUNT,
    KNOWN_PRODUCTION_CANDIDATE_SEQUENCE_WRAPS,
    KNOWN_PRODUCTION_CANDIDATE_STREAM_SHA256,
    summarize,
)


def test_module_import_does_not_open_hardware():
    # The production trace module must remain import-safe and hardware-free.
    assert callable(summarize)


def test_locked_production_candidate_fingerprint():
    assert KNOWN_PRODUCTION_CANDIDATE_PACKET_COUNT == 54_424
    assert KNOWN_PRODUCTION_CANDIDATE_SEQUENCE_WRAPS == 1
    assert KNOWN_PRODUCTION_CANDIDATE_FINALIZE_SEQ == 0x04C0
    assert (
        KNOWN_PRODUCTION_CANDIDATE_STREAM_SHA256
        == "6da89763feb71e837d066ad176b041a9e510c69c49525d2a4cd17863800ce6b8"
    )
