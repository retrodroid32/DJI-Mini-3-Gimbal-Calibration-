import mini3_gimbal_cal as m


def test_recovered_airforge_flyc_keepalive_fields():
    raw = m.build_airforge_flyc_keepalive_packet()
    f = m.parse_frame(raw)
    assert (f.sender, f.sender_index) == (m.COMM_DEV_PC, 1)
    assert (f.receiver, f.receiver_index) == (m.COMM_DEV_FLYCONTROLLER, 0)
    assert f.seq == 0x3896 == m.AIRFORGE_FLYC_KEEPALIVE_SEQ
    assert f.packet_type == m.PACKET_TYPE_REQUEST
    assert f.ack_type == m.ACK_AFTER_EXEC
    assert (f.cmd_set, f.cmd_id) == (0x00, 0x01)
    assert f.payload == b""


def test_recovered_wm163_gimbal_keepalive_fields():
    expected = bytes.fromhex("e60143000000000000000008")
    assert m.WM163_GIMBAL_KEEPALIVE_PAYLOAD == expected

    raw = m.build_wm163_gimbal_keepalive_packet()
    f = m.parse_frame(raw)
    assert (f.sender, f.sender_index) == (m.COMM_DEV_PC, 0)
    assert (f.receiver, f.receiver_index) == (m.COMM_DEV_GIMBAL, 0)
    assert f.seq == 0x1249 == m.WM163_GIMBAL_KEEPALIVE_SEQ
    assert f.packet_type == m.PACKET_TYPE_REQUEST
    assert f.ack_type == m.ACK_AFTER_EXEC
    assert (f.cmd_set, f.cmd_id) == (0x04, 0x12)
    assert f.payload == expected


def test_40011_runner_remains_interlocked_without_keepalive_orchestration():
    import wm163_service_cal_40011 as r

    assert r.KEEPALIVE_IMPLEMENTATION_READY is False
    assert r.run("COM_DO_NOT_OPEN", 9600, 0.1, 0.1, 0.1, 0) == 12


def test_recovered_keepalive_intervals():
    assert m.AIRFORGE_FLYC_KEEPALIVE_INTERVAL_MS == 2000
    assert m.WM163_GIMBAL_KEEPALIVE_INTERVAL_MS == 3000


def test_recovered_keepalive_scheduler_due_edges():
    assert m.service_keepalives_due(
        1999, last_flyc_ms=0, last_gimbal_ms=0
    ) == (False, False)

    assert m.service_keepalives_due(
        2000, last_flyc_ms=0, last_gimbal_ms=0
    ) == (True, False)

    assert m.service_keepalives_due(
        3000, last_flyc_ms=2000, last_gimbal_ms=0
    ) == (False, True)

    assert m.service_keepalives_due(
        4000, last_flyc_ms=2000, last_gimbal_ms=3000
    ) == (True, False)


def test_recovered_gimbal_keepalive_can_be_disabled_by_missing_payload():
    assert m.service_keepalives_due(
        6000,
        last_flyc_ms=6000,
        last_gimbal_ms=0,
        gimbal_payload=None,
    ) == (False, False)
