#!/usr/bin/env python3
"""Guarded WM163 V30.00.0100 service-firmware activation tool.

This is intentionally restricted to the one validated DJI Mini 3 / WM163
service package and the recovered Session-A loader.  It refuses arbitrary
firmware and defaults to dry-run validation unless --yes is supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import tarfile
import time

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover
    serial = None

from mini3_gimbal_cal import (
    FrameReader,
    PACKET_TYPE_RESPONSE,
    crc8_header,
    crc16_duML,
)
from wm163_service_fw_inspect import (
    EXPECTED_ARCHIVE_MD5,
    EXPECTED_ARCHIVE_SHA256,
    inspect_package,
)
from wm163_service_flash_protocol import (
    ACK_COLLECT_DRAIN_MS,
    CHUNK,
    CMDSET_GENERAL,
    CMD_COMMIT_PROBE,
    CMD_ENTER,
    CMD_FINALIZE,
    CMD_PREPARE_A,
    CMD_REBOOT_A,
    CMD_REPORT_SIZE,
    CMD_STREAM_A,
    CMD_STREAM_B,
    COMMIT_HOLD_DEFAULT_SECONDS,
    COMMIT_HOLD_SLEEP_SECONDS,
    COMMIT_PROBE_DST_RAW,
    COMMIT_PROBE_SEQ,
    COMMIT_PROBE_TIMEOUT_MS,
    CTRL_ACK_DEADLINE_SECONDS,
    FLAG_REQ_ACK,
    SESSION_A_DST_RAW,
    SESSION_A_SEQ0,
    SESSION_B_DRAIN_EVERY_RECORDS,
    SESSION_B_DST_RAW,
    SESSION_B_FINAL_DRAIN_MS,
    SESSION_B_LOADER_IDENTITY_MARKER,
    SESSION_B_LOADER_PROBE_DRAIN_MS,
    SESSION_B_LOADER_PROBE_SEQ0,
    SESSION_B_LOADER_PROBE_SLEEP_SECONDS,
    SESSION_B_LOADER_PROBE_XFER_TIMEOUT_MS,
    SESSION_B_LOADER_WAIT_SECONDS,
    SESSION_B_PERIODIC_DRAIN_MS,
    SESSION_B_SEQ0,
    STREAM_ACK_DEADLINE_SECONDS,
    ctrl_ack_payload_accepted,
    gray_order,
    session_a_enter_payload,
    session_a_finalize_payload,
    session_a_next_seq_after_loader,
    session_a_prepare_payload,
    session_a_reboot_payload,
    session_a_report_size_payload,
    session_a_stream_payload,
    session_b_file_data_payload,
    session_b_file_end_payload,
    session_b_file_start_payload,
    session_b_finalize_payload,
    session_b_finalize_seq,
    session_b_report_size_payload,
    session_b_total_size,
)

HOST_RAW = 0x2A
KNOWN_LOADER_MD5 = "72f7a3d3f40648c9e6c02583360c16b3"
KNOWN_LOADER_SIZE = 743_120
KNOWN_V30_TOTAL_SIZE = 52_009_440
KNOWN_V30_FINALIZE_SEQ = 0xFF83


class FlashError(RuntimeError):
    pass


def _md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def encode_raw(*, dst_raw: int, seq: int, cmd_id: int, payload: bytes, flags: int = FLAG_REQ_ACK) -> bytes:
    """Encode the recovered DUMLv1 frame using raw source/destination node bytes."""
    length = 11 + len(payload) + 2
    if not 13 <= length <= 0x3FF:
        raise ValueError("DUML packet length out of range")
    ver_length = (1 << 10) | length

    out = bytearray()
    out.append(0x55)
    out += ver_length.to_bytes(2, "little")
    out.append(crc8_header(bytes(out[:3])))
    out.append(HOST_RAW)
    out.append(dst_raw & 0xFF)
    out += (seq & 0xFFFF).to_bytes(2, "little")
    out.append(flags & 0xFF)
    out.append(CMDSET_GENERAL)
    out.append(cmd_id & 0xFF)
    out += payload
    out += crc16_duML(bytes(out)).to_bytes(2, "little")
    return bytes(out)


def _package_transfer_files(path: pathlib.Path) -> list[tuple[str, bytes]]:
    with tarfile.open(path, "r:*") as tf:
        found: dict[str, bytes] = {}
        for member in tf.getmembers():
            if not member.isfile():
                continue
            if not (member.name.endswith(".cfg.sig") or member.name.endswith(".pro.fw.sig")):
                continue
            fh = tf.extractfile(member)
            if fh is None:
                raise FlashError(f"cannot read package member {member.name}")
            found[member.name] = fh.read()

    names = gray_order(found.keys())
    return [(name, found[name]) for name in names]


def validate_inputs(package_path: pathlib.Path, loader_path: pathlib.Path) -> tuple[bytes, list[tuple[str, bytes]]]:
    pkg = inspect_package(package_path, require_known_v30=True)
    if pkg.md5 != EXPECTED_ARCHIVE_MD5 or pkg.sha256 != EXPECTED_ARCHIVE_SHA256:
        raise FlashError("service package hash mismatch")

    loader = loader_path.read_bytes()
    if len(loader) != KNOWN_LOADER_SIZE:
        raise FlashError(
            f"Session-A loader size mismatch: expected {KNOWN_LOADER_SIZE}, got {len(loader)}"
        )
    loader_md5 = _md5_bytes(loader)
    if loader_md5 != KNOWN_LOADER_MD5:
        raise FlashError(
            f"Session-A loader MD5 mismatch: expected {KNOWN_LOADER_MD5}, got {loader_md5}"
        )

    files = _package_transfer_files(package_path)
    total = session_b_total_size(files)
    if total != KNOWN_V30_TOTAL_SIZE:
        raise FlashError(
            f"Session-B total-size invariant failed: expected {KNOWN_V30_TOTAL_SIZE}, got {total}"
        )
    final_seq = session_b_finalize_seq(files)
    if final_seq != KNOWN_V30_FINALIZE_SEQ:
        raise FlashError(
            f"Session-B final-sequence invariant failed: expected 0x{KNOWN_V30_FINALIZE_SEQ:04x}, "
            f"got 0x{final_seq:04x}"
        )
    if session_a_next_seq_after_loader(len(loader)) != 0x4BFC:
        raise FlashError("Session-A sequence invariant failed")

    return loader, files


class SerialTransport:
    def __init__(self, ser_obj):
        self.ser = ser_obj
        self.reader = FrameReader()

    def write(self, packet: bytes) -> None:
        self.ser.write(packet)
        self.ser.flush()

    def read_raw_window(self, budget_ms: int) -> bytes:
        deadline = time.monotonic() + budget_ms / 1000.0
        out = bytearray()
        while time.monotonic() < deadline:
            waiting = getattr(self.ser, "in_waiting", 0)
            data = self.ser.read(waiting or 1)
            if data:
                out.extend(data)
        return bytes(out)

    def _find_ack(self, raw: bytes, *, want_seq: int, want_cmd: int):
        for frame in self.reader.feed(raw):
            if (
                frame.packet_type == PACKET_TYPE_RESPONSE
                and frame.seq == (want_seq & 0xFFFF)
                and frame.cmd_id == want_cmd
            ):
                return frame
        return None

    def command(
        self,
        *,
        dst_raw: int,
        seq: int,
        cmd_id: int,
        payload: bytes,
        what: str,
        deadline_seconds: int,
        check_status: bool,
    ):
        packet = encode_raw(dst_raw=dst_raw, seq=seq, cmd_id=cmd_id, payload=payload)
        self.write(packet)

        deadline = time.monotonic() + deadline_seconds
        while True:
            frame = self._find_ack(
                self.read_raw_window(ACK_COLLECT_DRAIN_MS),
                want_seq=seq,
                want_cmd=cmd_id,
            )
            if frame is not None:
                if check_status and not ctrl_ack_payload_accepted(frame.payload):
                    raise FlashError(f"{what}: device rejected request ({frame.payload.hex(' ')})")
                return frame
            if time.monotonic() >= deadline:
                raise FlashError(f"{what}: no matching response from aircraft")

    def ctrl(self, **kwargs):
        return self.command(
            deadline_seconds=CTRL_ACK_DEADLINE_SECONDS,
            check_status=True,
            **kwargs,
        )

    def stream(self, **kwargs):
        return self.command(
            deadline_seconds=STREAM_ACK_DEADLINE_SECONDS,
            check_status=False,
            **kwargs,
        )


def run_session_a(tp: SerialTransport, loader: bytes, *, verbose: bool = False) -> None:
    seq = SESSION_A_SEQ0

    def ctrl(cmd_id: int, payload: bytes, what: str):
        nonlocal seq
        if verbose:
            print(f"{what}: seq=0x{seq:04x}")
        tp.ctrl(
            dst_raw=SESSION_A_DST_RAW,
            seq=seq,
            cmd_id=cmd_id,
            payload=payload,
            what=what,
        )
        seq = (seq + 1) & 0xFFFF

    ctrl(CMD_ENTER, session_a_enter_payload(), "A/ENTER")
    ctrl(CMD_PREPARE_A, session_a_prepare_payload(), "A/PREPARE")
    ctrl(CMD_REPORT_SIZE, session_a_report_size_payload(len(loader)), "A/REPORT_SIZE")

    for offset in range(0, len(loader), CHUNK):
        chunk = loader[offset : offset + CHUNK]
        if verbose and (offset == 0 or offset % (CHUNK * 64) == 0):
            print(f"A/DATA: {offset}/{len(loader)} seq=0x{seq:04x}")
        tp.stream(
            dst_raw=SESSION_A_DST_RAW,
            seq=seq,
            cmd_id=CMD_STREAM_A,
            payload=session_a_stream_payload(offset, chunk),
            what=f"A/DATA offset={offset}",
        )
        seq = (seq + 1) & 0xFFFF

    ctrl(CMD_FINALIZE, session_a_finalize_payload(loader), "A/VERIFY")
    ctrl(CMD_REBOOT_A, session_a_reboot_payload(), "A/CMD_0B")

    if seq != 0x4BFC:
        raise FlashError(f"Session-A ended on unexpected next seq 0x{seq:04x}")


def wait_for_temp_loader(tp: SerialTransport, *, verbose: bool = False) -> None:
    seq = SESSION_B_LOADER_PROBE_SEQ0
    deadline = time.monotonic() + SESSION_B_LOADER_WAIT_SECONDS

    while time.monotonic() < deadline:
        pkt = encode_raw(
            dst_raw=COMMIT_PROBE_DST_RAW,
            seq=seq,
            cmd_id=CMD_COMMIT_PROBE,
            payload=b"",
        )
        tp.write(pkt)
        raw = tp.read_raw_window(SESSION_B_LOADER_PROBE_XFER_TIMEOUT_MS)
        raw += tp.read_raw_window(SESSION_B_LOADER_PROBE_DRAIN_MS)
        if SESSION_B_LOADER_IDENTITY_MARKER in raw:
            if verbose:
                print(f"Temporary loader detected on probe seq=0x{seq:04x}")
            return
        seq = (seq + 1) & 0xFFFF
        time.sleep(SESSION_B_LOADER_PROBE_SLEEP_SECONDS)

    raise FlashError("Session B: temporary WM163 loader was not detected within 180 seconds")


def run_session_b(
    tp: SerialTransport,
    files: list[tuple[str, bytes]],
    *,
    verbose: bool = False,
) -> None:
    seq = SESSION_B_SEQ0
    total_size = session_b_total_size(files)

    def ctrl(cmd_id: int, payload: bytes, what: str):
        nonlocal seq
        if verbose:
            print(f"{what}: seq=0x{seq:04x}")
        tp.ctrl(
            dst_raw=SESSION_B_DST_RAW,
            seq=seq,
            cmd_id=cmd_id,
            payload=payload,
            what=what,
        )
        seq = (seq + 1) & 0xFFFF

    ctrl(CMD_ENTER, session_a_enter_payload(), "B/ENTER")
    ctrl(CMD_REPORT_SIZE, session_b_report_size_payload(total_size), "B/REPORT_SIZE")

    record_count = 0

    def send_record(payload: bytes):
        nonlocal seq, record_count
        pkt = encode_raw(
            dst_raw=SESSION_B_DST_RAW,
            seq=seq,
            cmd_id=CMD_STREAM_B,
            payload=payload,
        )
        tp.write(pkt)
        seq = (seq + 1) & 0xFFFF
        record_count += 1
        if record_count % SESSION_B_DRAIN_EVERY_RECORDS == 0:
            tp.read_raw_window(SESSION_B_PERIODIC_DRAIN_MS)

    for name, blob in files:
        if verbose:
            print(f"B/START {name} size={len(blob)} seq=0x{seq:04x}")
        send_record(session_b_file_start_payload(name, blob))

        for offset in range(0, len(blob), CHUNK):
            send_record(session_b_file_data_payload(offset, blob[offset : offset + CHUNK]))

        send_record(session_b_file_end_payload(blob))
        if verbose:
            print(f"B/END   {name} seq_next=0x{seq:04x}")

    tp.read_raw_window(SESSION_B_FINAL_DRAIN_MS)

    if seq != KNOWN_V30_FINALIZE_SEQ:
        raise FlashError(
            f"refusing B/FINALIZE: seq invariant expected 0x{KNOWN_V30_FINALIZE_SEQ:04x}, "
            f"got 0x{seq:04x}"
        )

    ctrl(CMD_FINALIZE, session_b_finalize_payload(), "B/FINALIZE")


def hold_for_commit(tp: SerialTransport, *, verbose: bool = False) -> bool:
    """Return True only when post-finalize transport loss/reboot transition is observed."""
    deadline = time.monotonic() + COMMIT_HOLD_DEFAULT_SECONDS
    next_status = time.monotonic() + 15

    while time.monotonic() < deadline:
        try:
            pkt = encode_raw(
                dst_raw=COMMIT_PROBE_DST_RAW,
                seq=COMMIT_PROBE_SEQ,
                cmd_id=CMD_COMMIT_PROBE,
                payload=b"",
            )
            tp.write(pkt)
            tp.read_raw_window(COMMIT_PROBE_TIMEOUT_MS)
        except Exception as exc:
            if verbose:
                print(f"Post-finalize transport transition observed: {exc}")
            return True

        if verbose and time.monotonic() >= next_status:
            print("Waiting for firmware verify/commit transition...")
            next_status = time.monotonic() + 15
        time.sleep(COMMIT_HOLD_SLEEP_SECONDS)

    return False


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Guarded WM163-only V30.00.0100 service-firmware activation"
    )
    ap.add_argument("--package", required=True, help="validated V30.00.0100 WM163 service .bin")
    ap.add_argument("--loader", required=True, help="recovered session_a_loader.bin")
    ap.add_argument("--port", default="COM23")
    ap.add_argument("--baudrate", type=int, default=9600)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument(
        "--yes",
        action="store_true",
        help="perform the live Session-A/Session-B firmware transfer",
    )
    args = ap.parse_args()

    package_path = pathlib.Path(args.package)
    loader_path = pathlib.Path(args.loader)

    try:
        loader, files = validate_inputs(package_path, loader_path)
    except Exception as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    print("Validated exact WM163 V30.00.0100 service package.")
    print(f"Package MD5: {EXPECTED_ARCHIVE_MD5}")
    print(f"Package SHA256: {EXPECTED_ARCHIVE_SHA256}")
    print(f"Session-A loader MD5: {KNOWN_LOADER_MD5}")
    print(f"Session-B total_size: {session_b_total_size(files)}")
    print(f"Expected B/FINALIZE seq: 0x{session_b_finalize_seq(files):04x}")

    if not args.yes:
        print("DRY RUN ONLY: no serial port opened and no firmware was written.")
        print("Re-run with --yes only after the aircraft read-only preflight has passed.")
        return 0

    if serial is None:
        print("ERROR: pyserial is required", file=sys.stderr)
        return 2

    print("LIVE MODE: WM163 service firmware transfer will begin.")
    print("Do not disconnect USB or power during Session A/B.")
    print(f"Opening {args.port} @ {args.baudrate}...")

    try:
        with serial.Serial(args.port, baudrate=args.baudrate, timeout=0.04) as ser_obj:
            ser_obj.reset_input_buffer()
            tp = SerialTransport(ser_obj)

            run_session_a(tp, loader, verbose=args.verbose)
            print("Session A completed; waiting for temporary WM163 loader...")

            wait_for_temp_loader(tp, verbose=args.verbose)
            print("Temporary loader detected; beginning Session B...")

            run_session_b(tp, files, verbose=args.verbose)
            print("B/FINALIZE acknowledged; waiting for verify/commit transition...")

            transitioned = hold_for_commit(tp, verbose=args.verbose)

    except FlashError as exc:
        print(f"FLASH BLOCKED/ABORTED: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"TRANSPORT ERROR: {exc}", file=sys.stderr)
        return 4

    if transitioned:
        print("Post-finalize transport-loss/reboot transition observed.")
        print("Do not assume calibration is complete; reconnect and verify service firmware state.")
        return 0

    print(
        "WARNING: B/FINALIZE was acknowledged but no automatic transport-loss/reboot "
        "transition was observed within 150 seconds.",
        file=sys.stderr,
    )
    print("Do not start 40011 calibration until the aircraft state is verified.", file=sys.stderr)
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
