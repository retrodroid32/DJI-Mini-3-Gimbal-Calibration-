import mini3_gimbal_cal as m
from wm163_service_cal_40011 import (
    AIRFORGE_FLYC_KEEPALIVE_INTERVAL_MS,
    AIRFORGE_FLYC_KEEPALIVE_SEQ,
    GIMBAL_KEEPALIVE_INTERVAL_MS,
    GIMBAL_KEEPALIVE_MINI3,
    GIMBAL_KEEPALIVE_SEQ,
    KEEPALIVE_IMPLEMENTATION_READY,
    build_airforge_flyc_keepalive_packet,
    build_mini3_gimbal_keepalive_packet,
)


def test_airforge_flyc_keepalive_exact_fields():
    frame = m.parse_frame(build_airforge_flyc_keepalive_packet())
    assert frame.sender == m.COMM_DEV_PC
    assert frame.sender_index == 1
    assert frame.receiver == m.COMM_DEV_FLYCONTROLLER
    assert frame.receiver_index == 0
    assert frame.seq == 0x3896 == AIRFORGE_FLYC_KEEPALIVE_SEQ
    assert frame.packet_type == m.PACKET_TYPE_REQUEST
    assert frame.ack_type == m.ACK_AFTER_EXEC == 2
    assert frame.cmd_set == 0x00
    assert frame.cmd_id == 0x01
    assert frame.payload == b""
    assert AIRFORGE_FLYC_KEEPALIVE_INTERVAL_MS == 2000


def test_mini3_gimbal_keepalive_exact_builder_defaults():
    frame = m.parse_frame(build_mini3_gimbal_keepalive_packet())
    assert frame.sender == m.COMM_DEV_PC
    assert frame.sender_index == 0
    assert frame.receiver == m.COMM_DEV_GIMBAL
    assert frame.receiver_index == 0
    assert frame.seq == 0x1249 == GIMBAL_KEEPALIVE_SEQ
    assert frame.packet_type == m.PACKET_TYPE_REQUEST
    assert frame.ack_type == m.ACK_AFTER_EXEC == 2
    assert frame.cmd_set == 0x04
    assert frame.cmd_id == 0x12
    assert frame.payload == bytes.fromhex(
        "e6 01 43 00 00 00 00 00 00 00 00 08"
    ) == GIMBAL_KEEPALIVE_MINI3
    assert GIMBAL_KEEPALIVE_INTERVAL_MS == 3000


def test_gimbal_keepalive_builder_allows_recovered_engine_sender_override():
    frame = m.parse_frame(
        build_mini3_gimbal_keepalive_packet(sender=(m.COMM_DEV_PC, 1), seq=0x2222)
    )
    assert frame.sender == m.COMM_DEV_PC
    assert frame.sender_index == 1
    assert frame.seq == 0x2222
    assert frame.cmd_set == 0x04
    assert frame.cmd_id == 0x12
    assert frame.payload == GIMBAL_KEEPALIVE_MINI3


def test_live_service_keepalives_remain_blocked():
    # Exact packet builders are now recovered, but the live runner stays gated
    # until CalibEngine's orchestration/sender selection is fully reconstructed.
    assert KEEPALIVE_IMPLEMENTATION_READY is False


def test_recovered_keepalive_wire_vectors():
    assert build_airforge_flyc_keepalive_packet() == bytes.fromhex(
        "55 0d 04 33 2a 03 96 38 40 00 01 13 f9"
    )
    assert build_mini3_gimbal_keepalive_packet() == bytes.fromhex(
        "55 19 04 e4 0a 04 49 12 40 04 12 "
        "e6 01 43 00 00 00 00 00 00 00 00 08 76 e2"
    )
