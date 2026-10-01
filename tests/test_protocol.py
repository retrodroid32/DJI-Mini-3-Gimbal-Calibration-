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
