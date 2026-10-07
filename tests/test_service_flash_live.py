from wm163_service_flash_live import encode_raw, HOST_RAW
from wm163_service_flash_protocol import (
    CMD_ENTER,
    FLAG_REQ_ACK,
    SESSION_A_DST_RAW,
    SESSION_A_SEQ0,
    session_a_enter_payload,
)
from mini3_gimbal_cal import parse_frame


def test_encode_raw_session_a_enter_roundtrip():
    pkt = encode_raw(
        dst_raw=SESSION_A_DST_RAW,
        seq=SESSION_A_SEQ0,
        cmd_id=CMD_ENTER,
        payload=session_a_enter_payload(),
    )
    frame = parse_frame(pkt)
    assert pkt[4] == HOST_RAW
    assert pkt[5] == SESSION_A_DST_RAW
    assert frame.seq == SESSION_A_SEQ0
    assert frame.cmd_set == 0
    assert frame.cmd_id == CMD_ENTER
    assert frame.payload == b"\x00" * 9
    assert pkt[8] == FLAG_REQ_ACK


def test_raw_node_bytes_are_not_rewritten():
    pkt = encode_raw(
        dst_raw=0x28,
        seq=0,
        cmd_id=0x01,
        payload=b"",
    )
    assert pkt[4] == 0x2A
    assert pkt[5] == 0x28


class _FakeSer:
    def __init__(self):
        self.calls = []
        self.in_waiting = 0
    def reset_input_buffer(self):
        self.calls.append(("reset_input_buffer",))
    def write(self, data):
        self.calls.append(("write", bytes(data)))
        return len(data)
    def read(self, n):
        self.calls.append(("read", n))
        return b""


def test_gray_transport_write_resets_before_write():
    from wm163_service_flash_live import SerialTransport

    fake = _FakeSer()
    tp = SerialTransport(fake)
    tp.gray_write(b"abc")
    assert fake.calls == [
        ("reset_input_buffer",),
        ("write", b"abc"),
    ]


class _ImmediateBurstSer:
    def __init__(self):
        self._data = bytearray(b"\xaa\xbb\xcc\xdd")
        self.calls = []
    @property
    def in_waiting(self):
        return len(self._data)
    def read(self, n):
        self.calls.append(("read", n))
        out = bytes(self._data[:n])
        del self._data[:n]
        return out


def test_read_raw_window_returns_on_first_available_burst():
    from wm163_service_flash_live import SerialTransport

    fake = _ImmediateBurstSer()
    tp = SerialTransport(fake)
    got = tp.read_raw_window(400)
    assert got == b"\xaa\xbb\xcc\xdd"
    assert fake.calls == [("read", 4)]


class _SessionBWriteSer:
    def __init__(self):
        self.calls = []
        self.timeout = 0.04
    def write(self, data):
        self.calls.append(("write", bytes(data)))
        return len(data)
    def flush(self):
        self.calls.append(("flush",))
    def reset_input_buffer(self):
        self.calls.append(("reset_input_buffer",))
    def read(self, n):
        self.calls.append(("read", n, self.timeout))
        return b""


def test_session_b_write_is_write_flush_only():
    from wm163_service_flash_live import SerialTransport

    fake = _SessionBWriteSer()
    tp = SerialTransport(fake)
    tp.session_b_write(b"abc")
    assert fake.calls == [
        ("write", b"abc"),
        ("flush",),
    ]


class _ReadBurstSer:
    def __init__(self):
        self.calls = []
        self.timeout = 9.0
        self.responses = [b"\xaa\xbb\xcc\xdd", b""]
    def read(self, n):
        self.calls.append(("read", n, self.timeout))
        return self.responses.pop(0)


def test_read_burst_reads_until_first_empty_and_restores_timeout():
    from wm163_service_flash_live import SerialTransport

    fake = _ReadBurstSer()
    tp = SerialTransport(fake)
    got = tp.read_burst(budget_ms=120, read_timeout_ms=40)
    assert got == b"\xaa\xbb\xcc\xdd"
    assert fake.calls == [
        ("read", 4096, 0.04),
        ("read", 4096, 0.04),
    ]
    assert fake.timeout == 9.0
