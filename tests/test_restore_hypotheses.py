import hashlib

from analyze_wm163_restore_hypotheses import (
    KNOWN_PRODUCTION_DATA_RECORDS,
    KNOWN_PRODUCTION_PAYLOAD_RECORDS,
    KNOWN_PRODUCTION_PAYLOAD_STREAM_SHA256,
    compare_payload_grammars,
)


def test_hypothesis_comparison_accepts_identical_recovered_payload_grammars():
    files = [
        ("wm163.cfg.sig", b"A" * 2336),
        ("wm163_0100_test.pro.fw.sig", b"B" * 2500),
    ]
    result = compare_payload_grammars(files)
    assert result["file_count"] == 2
    assert result["data_records"] == 6
    # report + (start/data/end) records + finalize
    assert result["payload_records_including_report_and_finalize"] == 12
    assert len(result["payload_stream_sha256"]) == 64


def test_hypothesis_payload_fingerprint_is_deterministic():
    files = [("x.pro.fw.sig", b"abc" * 400)]
    one = compare_payload_grammars(files)
    two = compare_payload_grammars(files)
    assert one == two


def test_locked_exact_production_payload_fingerprint():
    assert KNOWN_PRODUCTION_DATA_RECORDS == 54_407
    assert KNOWN_PRODUCTION_PAYLOAD_RECORDS == 54_423
    assert (
        KNOWN_PRODUCTION_PAYLOAD_STREAM_SHA256
        == "2ffd428473db42d75e0c7ee581cbeec964f21874992c5f3c974eed2911564fc0"
    )
