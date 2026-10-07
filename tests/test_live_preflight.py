from wm163_live_preflight import (
    parse_diagnostics_output,
    parse_manifest_probe_output,
)


def test_parse_manifest_probe_output():
    parsed = parse_manifest_probe_output(
        "device=wm163\n"
        "formal=01.00.0500\n"
        "release=01.00.0500\n"
        "antirollback=0 antirollback_ext=cn:0\n"
    )
    assert parsed.device == "wm163"
    assert parsed.formal == "01.00.0500"
    assert parsed.release == "01.00.0500"
    assert parsed.antirollback == "0"


def test_parse_combined_40011_40021_diagnostics():
    parsed = parse_diagnostics_output(
        "payload=80 00 00 01 flags=0x01000080, "
        "diagnostics=40021 IMU_DATA_DISMATCH, 40011 CALIBRATE_ERROR"
    )
    assert parsed.diagnostic_40011_active
    assert parsed.diagnostic_40021_active


def test_parse_40011_only_diagnostics():
    parsed = parse_diagnostics_output(
        "diagnostics=40011 CALIBRATE_ERROR"
    )
    assert parsed.diagnostic_40011_active
    assert not parsed.diagnostic_40021_active


def test_parse_clear_diagnostics():
    parsed = parse_diagnostics_output("flags=0x00000000, diagnostics=none")
    assert not parsed.diagnostic_40011_active
    assert not parsed.diagnostic_40021_active
