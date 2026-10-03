import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mini3_gimbal_cal import (
    ACK_AFTER_EXEC,
    CALIB_COMMANDS,
    CMD_ID_GENERAL_REBOOT,
    CMD_ID_GIMBAL_WRITE_IMU,
    CMD_ID_GIMBAL_READ_IMU,
    CMD_SET_GENERAL,
    CMD_SET_ZENMUSE,
    COMM_DEV_BATTERY,
    COMM_DEV_GIMBAL,
    IMU_FIX_SHORT_PAYLOAD,
    FrameReader,
    build_packet,
    crc16_duML,
    crc64_jones,
    crc8_header,
    describe_active_status_payload,
    decode_gimbal_check_status,
    describe_auto_cal_status_payload,
    describe_ccode_payload,
    describe_gimbal_check_status_payload,
    describe_camera_sensor_id_payload,
    describe_common_device_id_payload,
    describe_fc_device_info_payload,
    describe_gimbal_serial_payload,
    describe_general_serial_payload,
    describe_payload,
    parse_flightlog_identity,
    parse_frame,
)

# Public packet from o-gs/dji-firmware-tools issue #483.
JOINT_COARSE_REQ = bytes.fromhex("55 0e 04 66 0a 04 39 d8 20 04 08 01 ee 6c")
MINI3_ACK_1 = bytes.fromhex("55 0e 04 66 04 0a 39 d8 80 04 08 01 ff 78")
MINI3_ACK_2 = bytes.fromhex("55 0e 04 66 04 0a b5 89 80 04 08 01 8f 32")


def test_builds_observed_joint_coarse_packet():
    pkt = build_packet(seq=0xD839, payload=bytes([CALIB_COMMANDS["joint-coarse"]]))
    assert pkt == JOINT_COARSE_REQ


def test_crc_fields_match_observed_request():
    assert crc8_header(JOINT_COARSE_REQ[:3]) == JOINT_COARSE_REQ[3]
    assert crc16_duML(JOINT_COARSE_REQ[:-2]) == int.from_bytes(JOINT_COARSE_REQ[-2:], "little")


def test_parses_wm163_one_byte_ack():
    frame = parse_frame(MINI3_ACK_1)
    assert frame.sender == 4
    assert frame.receiver == 10
    assert frame.seq == 0xD839
    assert frame.packet_type == 1
    assert frame.cmd_set == 4
    assert frame.cmd_id == 8
    assert frame.payload == b"\x01"
    assert "one-byte" in describe_payload("joint-coarse", frame.payload)


def test_second_public_ack_is_valid_too():
    frame = parse_frame(MINI3_ACK_2)
    assert frame.payload == b"\x01"
    assert frame.seq == 0x89B5


def test_stream_parser_handles_noise_and_split_frames():
    reader = FrameReader()
    out = list(reader.feed(b"noise\x00" + MINI3_ACK_1[:5]))
    assert out == []
    out = list(reader.feed(MINI3_ACK_1[5:] + MINI3_ACK_2))
    assert len(out) == 2
    assert out[0].seq == 0xD839
    assert out[1].seq == 0x89B5


def test_describes_general_serial_length_prefixed_payload():
    serial_text = b"1581F5FJC254J0"
    payload = len(serial_text).to_bytes(2, "little") + serial_text
    desc = describe_general_serial_payload(payload)
    assert "1581F5FJC254J0" in desc
    assert "declared_len=14" in desc


def test_describes_fc_device_info_payload():
    payload = b"\x00" + b"1581F5FJC254J0\x00D"
    desc = describe_fc_device_info_payload(payload)
    assert "status=0x00" in desc
    assert "1581F5FJC254J0" in desc
    assert "extra=44" in desc


def test_describes_wm163_fc_serial_with_leading_status():
    serial_text = b"EXAMPLE1234567"
    payload = b"\x00" + len(serial_text).to_bytes(2, "little") + serial_text + b"\x00\xf9"
    desc = describe_general_serial_payload(payload)
    assert "status=0x00" in desc
    assert "EXAMPLE1234567" in desc
    assert "declared_len=14" in desc


def test_describes_active_status_v11_serial():
    serial_text = b"GIMBAL123456"
    payload = b"\x01" + b"\x00" * 7 + bytes([len(serial_text)]) + serial_text
    desc = describe_active_status_payload(payload, "v1.1")
    assert "GIMBAL123456" in desc
    assert "sn_len=12" in desc


def test_describes_active_status_v10_serial():
    payload = b"\x01" + b"\x00" * 7 + b"CAMERA1234"
    desc = describe_active_status_payload(payload, "v1.0")
    assert "CAMERA1234" in desc


def test_decodes_e3_as_invalid_param():
    assert describe_ccode_payload(b"\xe3") == "ccode=0xe3 (INVALID_PARAM)"
    desc = describe_active_status_payload(b"\xe3" + b"\x00" * 5, "v1.1")
    assert "INVALID_PARAM" in desc


def test_describes_gimbal_direct_serial_response():
    payload = b"\x00\x02\x00GIMBAL123456\x00"
    desc = describe_gimbal_serial_payload(payload)
    assert "GIMBAL123456" in desc
    assert "header=02 00" in desc


def test_describes_camera_sensor_id_ascii():
    # Raw DUML response payload includes ccode=0 before camera response data.
    payload = b"\x00\x03\x0eSYNTHCAM123456"
    desc = describe_camera_sensor_id_payload(payload)
    assert "ccode=0x00" in desc
    assert "sensor_type=0x03" in desc
    assert "SYNTHCAM123456" in desc


def test_describes_binary_gimbal_serial_bytes():
    # Synthetic fixture only; do not commit device-specific captured identifiers.
    payload = bytes.fromhex("00 02 aa 10 20 30 40 50 60 70 80 90 a0 b0 c0 d0 e0")
    desc = describe_gimbal_serial_payload(payload)
    assert "ccode=0x00" in desc
    assert "header=02 aa" in desc
    assert "binary_serial_bytes=102030405060708090a0b0c0d0e0" in desc
    assert "14 bytes" in desc


def test_describes_common_fc_identifier_ascii():
    ident = b"SYNTHBOARD1234"
    payload = b"\x00" + len(ident).to_bytes(2, "little") + ident + b"\x00\xf9"
    desc = describe_common_device_id_payload(payload)
    assert "ccode=0x00" in desc
    assert "SYNTHBOARD1234" in desc
    assert "declared_len=14" in desc
    assert "extra=00 f9" in desc


def test_describes_common_fc_identifier_binary():
    ident = bytes.fromhex("10 20 30 40 50 60")
    payload = b"\x00" + len(ident).to_bytes(2, "little") + ident
    desc = describe_common_device_id_payload(payload)
    assert "binary_id=102030405060" in desc
    assert "6 bytes" in desc


def _encode_aux_info(decoded: bytes, first: int = 0x42) -> bytes:
    seed = first
    key_input = ((0x123456789ABCDEF0 * first) & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
    key = crc64_jones(seed, key_input).to_bytes(8, "little")
    return bytes([first]) + bytes(decoded[i] ^ key[i % 8] for i in range(len(decoded)))


def test_parses_v14_flightlog_identity_without_api_key(tmp_path):
    info = bytearray(436)
    info[271] = 112
    info[280:280 + len(b"DJI Mini 3")] = b"DJI Mini 3"
    info[312:312 + len(b"SYNTHAIR123456")] = b"SYNTHAIR123456"
    info[328:328 + len(b"SYNTHCAM123456")] = b"SYNTHCAM123456"
    info[344:344 + len(b"SYNTHRC1234567")] = b"SYNTHRC1234567"
    info[360:360 + len(b"SYNTHBAT123456")] = b"SYNTHBAT123456"
    info[376] = 6
    info[377:380] = bytes([1, 14, 2])

    decoded = b"\x00" + len(info).to_bytes(2, "little") + bytes(info) + b"\x00\x00"
    raw_aux = _encode_aux_info(decoded)

    prefix = bytearray(100)
    prefix[0:8] = (809).to_bytes(8, "little")
    prefix[8:10] = (436).to_bytes(2, "little")
    prefix[10] = 14

    blob = bytes(prefix) + b"\x00" + len(raw_aux).to_bytes(2, "little") + raw_aux
    path = tmp_path / "DJIFlightRecord_synthetic.txt"
    path.write_bytes(blob)

    ident = parse_flightlog_identity(path)
    assert ident.version == 14
    assert ident.product_type == 112
    assert ident.aircraft_name == "DJI Mini 3"
    assert ident.aircraft_sn == "SYNTHAIR123456"
    assert ident.camera_sn == "SYNTHCAM123456"
    assert ident.rc_sn == "SYNTHRC1234567"
    assert ident.battery_sn == "SYNTHBAT123456"
    assert ident.app_platform == 6
    assert ident.app_version == "1.14.2"


def test_decodes_fd_as_flash_flushing():
    assert describe_ccode_payload(b"\xfd") == "ccode=0xfd (FLASH_FLUSHING)"


def test_builds_normal_auto_calibration_packet_with_empty_payload():
    pkt = build_packet(
        seq=0x1234,
        payload=b"",
        receiver=4,
        cmd_set=4,
        cmd_id=8,
    )
    frame = parse_frame(pkt)
    assert frame.sender == 10
    assert frame.receiver == 4
    assert frame.seq == 0x1234
    assert frame.packet_type == 0
    assert frame.cmd_set == 4
    assert frame.cmd_id == 8
    assert frame.payload == b""


def test_decodes_auto_calibration_status():
    assert describe_auto_cal_status_payload(bytes.fromhex("64 00")) == "progress=100% status=0 (SUCCESS)"
    assert describe_auto_cal_status_payload(bytes.fromhex("42 01")) == "progress=66% status=1 (CALIBRATING)"
    assert "FAILED_OR_OTHER_2" in describe_auto_cal_status_payload(bytes.fromhex("19 02"))


def test_decodes_wm163_gimbal_check_status_40011_40021():
    value, active = decode_gimbal_check_status(bytes.fromhex("80 00 00 01"))
    assert value == 0x01000080
    assert (40011, "CALIBRATE_ERROR") in active
    assert (40021, "IMU_DATA_DISMATCH") in active
    desc = describe_gimbal_check_status_payload(bytes.fromhex("80 00 00 01"))
    assert "40011 CALIBRATE_ERROR" in desc
    assert "40021 IMU_DATA_DISMATCH" in desc


def test_builds_recovered_wm163_40021_short_fix_packet():
    pkt = build_packet(
        seq=0x4000,
        payload=IMU_FIX_SHORT_PAYLOAD,
        receiver=COMM_DEV_GIMBAL,
        ack_type=ACK_AFTER_EXEC,
        cmd_set=CMD_SET_ZENMUSE,
        cmd_id=CMD_ID_GIMBAL_WRITE_IMU,
    )
    frame = parse_frame(pkt)
    assert frame.sender == 10
    assert frame.receiver == 4
    assert frame.seq == 0x4000
    assert frame.packet_type == 0
    assert frame.ack_type == ACK_AFTER_EXEC
    assert frame.encrypt_type == 0
    assert frame.cmd_set == 0x04
    assert frame.cmd_id == 0x36
    assert frame.payload == bytes.fromhex("42 e9 7f 3f")


def test_builds_recovered_wm163_40021_reboot_packet():
    pkt = build_packet(
        seq=0x4001,
        payload=b"",
        receiver=COMM_DEV_BATTERY,
        ack_type=ACK_AFTER_EXEC,
        cmd_set=CMD_SET_GENERAL,
        cmd_id=CMD_ID_GENERAL_REBOOT,
    )
    frame = parse_frame(pkt)
    assert frame.sender == 10
    assert frame.receiver == 11
    assert frame.seq == 0x4001
    assert frame.packet_type == 0
    assert frame.ack_type == ACK_AFTER_EXEC
    assert frame.encrypt_type == 0
    assert frame.cmd_set == 0x00
    assert frame.cmd_id == 0x0B
    assert frame.payload == b""


def test_builds_read_only_wm163_gimbal_imu_probe_packet():
    pkt = build_packet(
        seq=0x5151,
        payload=b"",
        receiver=COMM_DEV_GIMBAL,
        ack_type=ACK_AFTER_EXEC,
        cmd_set=CMD_SET_ZENMUSE,
        cmd_id=CMD_ID_GIMBAL_READ_IMU,
    )
    frame = parse_frame(pkt)
    assert frame.sender == 10
    assert frame.receiver == 4
    assert frame.seq == 0x5151
    assert frame.packet_type == 0
    assert frame.ack_type == ACK_AFTER_EXEC
    assert frame.cmd_set == 0x04
    assert frame.cmd_id == 0x51
    assert frame.payload == b""
