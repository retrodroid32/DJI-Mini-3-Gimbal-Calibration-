#!/usr/bin/env python3
"""Offline comparison of compiled DrGrey gray transport vs recreated transport.

Requires Python 3.14. Does not open a real serial port.
"""

from __future__ import annotations
import argparse, importlib, pathlib, sys, tempfile, zipfile
from wm163_service_flash_live import SerialTransport as RecreatedTransport

class FakeSerial:
    def __init__(self, response: bytes):
        self.response = bytes(response)
        self.buf = bytearray()
        self.calls = []
        self.timeout = None
        self.write_timeout = None
        self.in_waiting = 0
    def reset_input_buffer(self):
        self.calls.append(("reset_input_buffer",))
        self.buf.clear()
        self.in_waiting = 0
    def write(self, data):
        b = bytes(data)
        self.calls.append(("write", b.hex(" ")))
        self.buf.extend(self.response)
        self.in_waiting = len(self.buf)
        return len(b)
    def read(self, n=1):
        self.calls.append(("read", int(n)))
        out = bytes(self.buf[:n])
        del self.buf[:n]
        self.in_waiting = len(self.buf)
        return out

def extract_root(source: pathlib.Path, dest: pathlib.Path) -> pathlib.Path:
    if source.is_dir():
        roots = [source, source/"app_recovery"/"extracted_app", source/"extracted_app"]
    else:
        with zipfile.ZipFile(source, "r") as zf:
            zf.extractall(dest)
        roots = [dest/"app_recovery"/"extracted_app", dest/"extracted_app", dest]
    for root in roots:
        if (root/"drgrey"/"transport.cp314-win_amd64.pyd").exists():
            return root
    raise FileNotFoundError("transport.cp314-win_amd64.pyd not found")

def main() -> int:
    if sys.version_info[:2] != (3, 14):
        print("Run this with Python 3.14", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    args = ap.parse_args()

    packet = bytes.fromhex("55 0d 04 33 2a 28 00 00 40 00 01 00 00")
    response = bytes.fromhex("aa bb cc dd")

    with tempfile.TemporaryDirectory(prefix="drgrey_equiv_", ignore_cleanup_errors=True) as td:
        root = extract_root(pathlib.Path(args.source), pathlib.Path(td))
        sys.path.insert(0, str(root))
        tr = importlib.import_module("drgrey.transport")

        dg = tr.SerialTransport()
        dg_fake = FakeSerial(response)
        dg.ser = dg_fake
        dg_result = dg.send_like_gray_flasher(packet, wait_response=True, window_ms=5)

        rc_fake = FakeSerial(response)
        rc = RecreatedTransport(rc_fake)
        rc.write(packet)
        rc_result = rc.read_raw_window(5)

        print("DrGrey calls:")
        for item in dg_fake.calls:
            print("  ", item)
        print("DrGrey result:", dg_result)

        print("Recreated calls:")
        for item in rc_fake.calls:
            print("  ", item)
        print("Recreated result:", [rc_result] if rc_result else [])

        calls_equal = dg_fake.calls == rc_fake.calls
        result_equal = dg_result == ([rc_result] if rc_result else [])
        print("calls_equal=", calls_equal)
        print("result_equal=", result_equal)

        if calls_equal and result_equal:
            print("EQUIVALENT")
            return 0
        print("NOT EQUIVALENT")
        return 3

if __name__ == "__main__":
    raise SystemExit(main())
