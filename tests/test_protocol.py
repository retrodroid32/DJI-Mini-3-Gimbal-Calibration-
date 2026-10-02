import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mini3_gimbal_cal import (
    CALIB_COMMANDS,
    FrameReader,
    build_packet,
    crc16_duML,
    crc8_header,
    describe_active_status_payload,
    describe_ccode_payload,
    describe_camera_sensor_id_payload,
    describe_fc_device_info_payload,
    describe_gimbal_serial_payload,
    describe_general_serial_payload,
    describe_payload,
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


def test_decodes_e3_as_get_param_failed():
    assert describe_ccode_payload(b"\xe3") == "ccode=0xe3 (GET_PARAM_FAILED)"
    desc = describe_active_status_payload(b"\xe3" + b"\x00" * 5, "v1.1")
    assert "GET_PARAM_FAILED" in desc


def test_describes_gimbal_direct_serial_response():
    payload = b"\x00\x00GIMBAL123456\x00"
    desc = describe_gimbal_serial_payload(payload)
    assert "GIMBAL123456" in desc
    assert "prefix=00 00" in desc


def test_describes_camera_sensor_id_ascii():
    payload = b"\x02\x0eCAMERA12345678"
    desc = describe_camera_sensor_id_payload(payload)
    assert "sensor_type=0x02" in desc
    assert "CAMERA12345678" in desc


def test_describes_binary_gimbal_fingerprint():
    payload = bytes.fromhex("00 02 9e fc 71 b0 9f 26 97 40 c4 f8 b4 b7 e9 20 b7")
    desc = describe_gimbal_serial_payload(payload)
    assert "binary_fingerprint=9efc71b09f269740c4f8b4b7e920b7" in desc
    assert "15 bytes" in desc
