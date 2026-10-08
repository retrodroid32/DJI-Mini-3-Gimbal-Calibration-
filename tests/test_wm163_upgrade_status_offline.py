"""Read-only public-protocol fixture tests; NOT WM163 hardware validations."""
import pytest

from wm163_upgrade_status_offline import parse_upgrade_status

def test_verify_and_confirmation():
    assert parse_upgrade_status(b"\x01").label == "verify"
    status = parse_upgrade_status(bytes.fromhex("02 0c 7f"))
    assert (status.label, status.user_time, status.user_reserve) == ("user_confirm", 12, 127)
    assert not status.reports_success

def test_upgrade_progress_bitfield():
    status = parse_upgrade_status(bytes.fromhex("03 64 a7"))
    assert (status.progress, status.current_upgrade_index, status.upgrade_times) == (100, 5, 7)
    assert not status.reports_success

def test_only_complete_success_reports_success():
    ok = parse_upgrade_status(bytes.fromhex("04 01 02"))
    fail = parse_upgrade_status(bytes.fromhex("04 09 02"))
    other = parse_upgrade_status(bytes.fromhex("04 ff 02"))
    assert ok.reports_success and ok.complete_reason_label == "success"
    assert not fail.reports_success and fail.complete_reason_label == "illegal_downgrade"
    assert not other.reports_success and other.complete_reason_label == "unknown"

@pytest.mark.parametrize(
    "payload", [b"", b"\x00", b"\x03", b"\x04\x01", b"\x01\x02", b"\x02\x01\x00\x00"]
)
def test_malformed_or_unknown_status_rejected(payload):
    with pytest.raises(ValueError):
        parse_upgrade_status(payload)
