#!/usr/bin/env python3
"""Offline end-to-end replay of the WM163 live Service-FW path.

This script NEVER opens a serial port.

It runs the project's actual orchestration functions:

    run_session_a()
    wait_for_temp_loader()
    run_session_b()
    hold_for_commit()

against request/response data extracted from a genuine Dr.Grey USBPcap capture.
Outgoing packets are compared byte-for-byte with the captured Dr.Grey requests.
The two known 13-packet USBPcap omissions in Session B are tolerated only at
their exact captured sequence ranges.

The final post-FINALIZE loader disappearance is replayed as a synthetic
transport disconnect after all 112 captured WM163-UAV identity responses have
been consumed.
"""

from __future__ import annotations

import argparse
import contextlib
import pathlib
import sys

import wm163_service_flash_live as live
from validate_wm163_service_state_machine import iter_duml_frames


class ReplayError(RuntimeError):
    pass


class ReplayDisconnect(OSError):
    pass


def _is_service_request(e) -> bool:
    if e.sender != 0x2A or e.cmdset != 0x00:
        return False
    if e.dst == 0xA9 and e.cmd in {0x07, 0x0C, 0x08, 0x09, 0x0A, 0x0B}:
        return True
    if e.dst == 0x28 and e.cmd == 0x01:
        return True
    if e.dst == 0x01 and e.cmd in {0x07, 0x08, 0x2A, 0x0A}:
        return True
    return False


def _is_a_enter(e) -> bool:
    return (
        e.sender == 0x2A
        and e.dst == 0xA9
        and e.seq == 0x4900
        and e.cmdset == 0x00
        and e.cmd == 0x07
        and e.payload == b"\x00" * 9
    )


def _is_b_finalize(e) -> bool:
    return (
        e.sender == 0x2A
        and e.dst == 0x01
        and e.seq == 0xFF8A
        and e.cmdset == 0x00
        and e.cmd == 0x0A
        and e.payload == b"\x00" * 17
    )


def _matching_response(events, req_index: int, *, max_delay: float):
    req = events[req_index]
    deadline = req.ts + max_delay
    for e in events[req_index + 1 :]:
        if e.ts > deadline:
            return None
        if (
            e.sender == req.dst
            and e.dst == 0x2A
            and e.seq == req.seq
            and (e.flags & 0x80)
            and e.cmdset == req.cmdset
            and e.cmd == req.cmd
        ):
            return e
    return None


def _parse_request(raw: bytes):
    if len(raw) < 13 or raw[0] != 0x55:
        raise ReplayError("write was not a complete DUML frame")
    return {
        "sender": raw[4],
        "dst": raw[5],
        "seq": raw[6] | (raw[7] << 8),
        "flags": raw[8],
        "cmdset": raw[9],
        "cmd": raw[10],
        "payload": raw[11:-2],
    }


def _ranges(values: list[int]) -> list[tuple[int, int]]:
    if not values:
        return []
    vals = sorted(values)
    out = []
    start = prev = vals[0]
    for value in vals[1:]:
        if value == prev + 1:
            prev = value
            continue
        out.append((start, prev))
        start = prev = value
    out.append((start, prev))
    return out


class CaptureReplaySerial:
    def __init__(self, capture: pathlib.Path):
        self.timeout = 0.04
        self._rx = bytearray()
        self._disconnect_pending = False

        self.events = list(iter_duml_frames(capture))
        if not self.events:
            raise ReplayError("no DUML frames found in capture")

        try:
            self.a_start_index = next(
                i for i, e in enumerate(self.events) if _is_a_enter(e)
            )
        except StopIteration as exc:
            raise ReplayError("captured A/ENTER was not found") from exc

        try:
            self.b_finalize_index = next(
                i
                for i in range(self.a_start_index, len(self.events))
                if _is_b_finalize(self.events[i])
            )
        except StopIteration as exc:
            raise ReplayError("captured B/FINALIZE 0xFF8A was not found") from exc

        b_finalize_ts = self.events[self.b_finalize_index].ts
        end_ts = b_finalize_ts + 70.0

        self.expected = [
            (i, e)
            for i, e in enumerate(self.events)
            if self.a_start_index <= i
            and e.ts <= end_ts
            and _is_service_request(e)
        ]
        self.expected_pos = 0

        # Capture-backed response map for Session A and B control requests.
        self.response_by_index = {}
        for i, e in self.expected:
            if e.dst == 0xA9:
                reply = _matching_response(self.events, i, max_delay=1.0)
                if reply is None:
                    raise ReplayError(
                        f"missing captured Session-A reply seq=0x{e.seq:04X}"
                    )
                self.response_by_index[i] = reply.raw
            elif e.dst == 0x01 and e.cmd in {0x07, 0x08, 0x0A}:
                reply = _matching_response(self.events, i, max_delay=2.0)
                if reply is None:
                    raise ReplayError(
                        f"missing captured Session-B control reply "
                        f"cmd=0x{e.cmd:02X} seq=0x{e.seq:04X}"
                    )
                self.response_by_index[i] = reply.raw

        # One pre-B loader response.
        self.pre_b_loader_response = next(
            (
                e.raw
                for e in self.events
                if self.events[self.a_start_index].ts <= e.ts < b_finalize_ts
                and e.sender == 0x28
                and e.dst == 0x2A
                and e.seq == 0
                and (e.flags & 0x80)
                and e.cmdset == 0x00
                and e.cmd == 0x01
                and b"WM163 UAV" in e.payload
            ),
            None,
        )
        if self.pre_b_loader_response is None:
            raise ReplayError("captured pre-B WM163 UAV identity response not found")

        # Genuine post-finalize loader responses. Replay these in capture order
        # across the successful commit probes, then disconnect on the final
        # unanswered probe.
        self.commit_responses = [
            e.raw
            for e in self.events
            if b_finalize_ts <= e.ts <= end_ts
            and e.sender == 0x28
            and e.dst == 0x2A
            and e.seq == 0
            and (e.flags & 0x80)
            and e.cmdset == 0x00
            and e.cmd == 0x01
            and b"WM163 UAV" in e.payload
        ]
        if len(self.commit_responses) != 112:
            raise ReplayError(
                f"expected 112 captured post-finalize WM163 UAV responses, "
                f"found {len(self.commit_responses)}"
            )

        self.finalized = False
        self.loader_probe_seen = False
        self.commit_response_pos = 0
        self.omitted_capture_seqs: list[int] = []
        self.write_count = 0
        self.flush_count = 0
        self.reset_count = 0

    @property
    def in_waiting(self):
        if self._disconnect_pending:
            raise ReplayDisconnect("captured temporary-loader disappearance")
        return len(self._rx)

    def reset_input_buffer(self):
        self.reset_count += 1
        self._rx.clear()

    def flush(self):
        self.flush_count += 1

    def read(self, n=1):
        if self._disconnect_pending:
            raise ReplayDisconnect("captured temporary-loader disappearance")
        if not self._rx:
            return b""
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def _queue(self, raw: bytes | None):
        if raw:
            self._rx.extend(raw)

    def write(self, data):
        raw = bytes(data)
        fields = _parse_request(raw)
        self.write_count += 1

        if self.expected_pos >= len(self.expected):
            raise ReplayError(
                f"unexpected extra TX after capture exhausted: "
                f"dst=0x{fields['dst']:02X} seq=0x{fields['seq']:04X} "
                f"cmd=0x{fields['cmd']:02X}"
            )

        exp_index, exp = self.expected[self.expected_pos]

        if raw != exp.raw:
            # The genuine USBPcap has two known contiguous holes, each 13 DATA
            # records long. Only permit a generated Session-B DATA record whose
            # sequence is earlier than the next captured Session-B DATA seq.
            is_generated_b_data = (
                fields["sender"] == 0x2A
                and fields["dst"] == 0x01
                and fields["cmdset"] == 0x00
                and fields["cmd"] == 0x2A
                and fields["payload"][:1] == b"\x02"
            )
            is_expected_b_data = (
                exp.sender == 0x2A
                and exp.dst == 0x01
                and exp.cmdset == 0x00
                and exp.cmd == 0x2A
                and exp.payload[:1] == b"\x02"
            )
            if (
                is_generated_b_data
                and is_expected_b_data
                and fields["seq"] < exp.seq
            ):
                self.omitted_capture_seqs.append(fields["seq"])
                return len(raw)

            raise ReplayError(
                "TX mismatch against genuine capture:\n"
                f"  generated dst=0x{fields['dst']:02X} "
                f"seq=0x{fields['seq']:04X} cmd=0x{fields['cmd']:02X}\n"
                f"  captured  dst=0x{exp.dst:02X} "
                f"seq=0x{exp.seq:04X} cmd=0x{exp.cmd:02X}"
            )

        self.expected_pos += 1

        # Session-A replies.
        if exp.dst == 0xA9:
            self._queue(self.response_by_index[exp_index])

        # Temporary-loader / commit probes.
        elif exp.dst == 0x28 and exp.cmd == 0x01:
            if not self.finalized:
                if self.loader_probe_seen:
                    raise ReplayError("more than one pre-B loader probe was generated")
                self.loader_probe_seen = True
                self._queue(self.pre_b_loader_response)
            else:
                if self.commit_response_pos < len(self.commit_responses):
                    self._queue(self.commit_responses[self.commit_response_pos])
                    self.commit_response_pos += 1
                else:
                    # The final captured probe has no normal loader response;
                    # model the transport loss that Dr.Grey treats as commit.
                    self._disconnect_pending = True

        # B/ENTER, B/REPORT_SIZE and B/FINALIZE.
        elif exp.dst == 0x01 and exp.cmd in {0x07, 0x08, 0x0A}:
            self._queue(self.response_by_index[exp_index])
            if exp.cmd == 0x0A and exp.seq == 0xFF8A:
                self.finalized = True

        return len(raw)

    def assert_complete(self):
        if self.expected_pos != len(self.expected):
            _idx, exp = self.expected[self.expected_pos]
            raise ReplayError(
                f"capture replay stopped early at expected TX "
                f"dst=0x{exp.dst:02X} seq=0x{exp.seq:04X} cmd=0x{exp.cmd:02X}"
            )

        omitted_ranges = _ranges(self.omitted_capture_seqs)
        expected_ranges = [(0x7660, 0x766C), (0xB960, 0xB96C)]
        if omitted_ranges != expected_ranges:
            raise ReplayError(
                f"unexpected USBPcap omission ranges: {omitted_ranges}; "
                f"expected {expected_ranges}"
            )

        if self.commit_response_pos != 112:
            raise ReplayError(
                f"only replayed {self.commit_response_pos}/112 commit responses"
            )

        if not self._disconnect_pending:
            raise ReplayError("post-finalize disconnect was not reached")

        return omitted_ranges


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Offline replay of actual WM163 live Service-FW orchestration"
    )
    ap.add_argument("--capture", required=True, help="genuine Dr.Grey USBPcap .pcapng")
    ap.add_argument("--package", required=True, help="exact known WM163 V30 service package")
    ap.add_argument("--loader", required=True, help="exact recovered session_a_loader.bin")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    capture = pathlib.Path(args.capture)
    package = pathlib.Path(args.package)
    loader_path = pathlib.Path(args.loader)
    for path in (capture, package, loader_path):
        if not path.is_file():
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            return 2

    try:
        loader, files = live.validate_inputs(package, loader_path)
        fake = CaptureReplaySerial(capture)
        tp = live.SerialTransport(fake)

        live.run_session_a(tp, loader, verbose=args.verbose)
        live.wait_for_temp_loader(tp, verbose=args.verbose)
        live.run_session_b(tp, files, verbose=args.verbose)

        # Remove real-time waiting only; response and disconnect behavior still
        # comes from the captured replay script.
        old_sleep = live.COMMIT_HOLD_SLEEP_SECONDS
        live.COMMIT_HOLD_SLEEP_SECONDS = 0.0
        try:
            transitioned = live.hold_for_commit(tp, verbose=args.verbose)
        finally:
            live.COMMIT_HOLD_SLEEP_SECONDS = old_sleep

        if not transitioned:
            raise ReplayError("hold_for_commit did not observe captured disconnect")

        omission_ranges = fake.assert_complete()

    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 3

    print("WM163 actual live-path replay: PASS")
    print("Executed project functions:")
    print("  run_session_a")
    print("  wait_for_temp_loader")
    print("  run_session_b")
    print("  hold_for_commit")
    print(f"Total generated writes: {fake.write_count}")
    print(f"Captured service requests matched: {len(fake.expected)}")
    print(
        "Known USBPcap omission ranges replayed: "
        + ", ".join(f"0x{a:04X}-0x{b:04X}" for a, b in omission_ranges)
    )
    print(f"Captured post-finalize WM163 UAV responses replayed: {fake.commit_response_pos}")
    print("Final unanswered commit probe -> synthetic transport disconnect: PASS")
    print("OFFLINE ONLY: no serial port was opened.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
