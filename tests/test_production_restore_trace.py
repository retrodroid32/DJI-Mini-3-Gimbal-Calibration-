from trace_wm163_production_restore_candidate import (
    KNOWN_PRODUCTION_CANDIDATE_FINALIZE_SEQ,
    KNOWN_PRODUCTION_CANDIDATE_PACKET_COUNT,
    KNOWN_PRODUCTION_CANDIDATE_SEQUENCE_WRAPS,
    KNOWN_PRODUCTION_CANDIDATE_STREAM_SHA256,
    KNOWN_PRODUCTION_ROLLOVER_PACKETS,
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


def test_locked_rollover_packet_fingerprints():
    assert KNOWN_PRODUCTION_ROLLOVER_PACKETS == (
        (
            0xFFFE,
            "DATA wm163_0905_v01.00.01.27_20220919.pro.fw.sig chunk=9547",
            "4cbf654ee6083043450cf4faac511dd07ced347548ad5a88d201bbf805b23d00",
        ),
        (
            0xFFFF,
            "DATA wm163_0905_v01.00.01.27_20220919.pro.fw.sig chunk=9548",
            "8177cf57f5307c3827dae9e8bf813d9cf1326e75d3731a42f0b12326d634d4c0",
        ),
        (
            0x0000,
            "DATA wm163_0905_v01.00.01.27_20220919.pro.fw.sig chunk=9549",
            "45e150d3799947769a066ae0592409b64b70e538b27f465a45f619be281655b9",
        ),
        (
            0x0001,
            "DATA wm163_0905_v01.00.01.27_20220919.pro.fw.sig chunk=9550",
            "6c6355cbfa3431c78d8514b9442eba357a1bbab9c710dd078836683a9e0e179f",
        ),
    )
