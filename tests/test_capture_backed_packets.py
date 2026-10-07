from mini3_gimbal_cal import (
    build_wm163_service_calibration_packet,
    build_wm163_gimbal_keepalive_packet,
    build_wm163_40021_fix_packet,
    build_wm163_40021_reboot_packet,
)


def test_joint_coarse_matches_genuine_capture_byte_for_byte():
    assert build_wm163_service_calibration_packet("joint-coarse") == bytes.fromhex(
        "55 0e 04 66 0a 04 62 00 40 04 08 01 59 3d"
    )


def test_linear_hall_matches_genuine_capture_byte_for_byte():
    assert build_wm163_service_calibration_packet("linear-hall") == bytes.fromhex(
        "55 0e 04 66 0a 04 63 00 40 04 08 02 e9 0b"
    )


def test_gimbal_keepalive_matches_genuine_capture_byte_for_byte():
    assert build_wm163_gimbal_keepalive_packet() == bytes.fromhex(
        "55 19 04 e4 0a 04 49 12 40 04 12 "
        "e6 01 43 00 00 00 00 00 00 00 00 08 76 e2"
    )


def test_40021_short_fix_matches_genuine_capture_byte_for_byte():
    assert build_wm163_40021_fix_packet() == bytes.fromhex(
        "55 11 04 92 0a 04 64 00 40 04 36 42 e9 7f 3f 61 9f"
    )


def test_40021_reboot_matches_genuine_capture_byte_for_byte():
    assert build_wm163_40021_reboot_packet() == bytes.fromhex(
        "55 1b 04 75 2a 0b 65 00 40 00 0b "
        "00 01 00 00 00 00 00 00 00 00 00 00 00 00 18 41"
    )
