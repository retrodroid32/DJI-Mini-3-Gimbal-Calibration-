#!/usr/bin/env python3
"""Offline probe for DrGrey's compiled SerialTransport.send_like_gray_flasher.

This script MUST NOT open a real COM port. It extracts/imports the recovered
CPython 3.14 extension and replaces the module-level serial constructor with a
fake recorder before exercising the gray-flasher helper.

It is a reverse-engineering probe only; it sends nothing to an aircraft.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import inspect
import os
import pathlib
import sys
import tempfile
import time
import types
import zipfile


class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.timeout = kwargs.get("timeout", None)
        self.write_timeout = kwargs.get("write_timeout", None)
        self.is_open = True
        self.in_waiting = 0
        self.log: list[tuple] = []
        self._rx = bytearray()
        self.response_on_write = b""

    def open(self):
        self.log.append(("open",))
        self.is_open = True

    def close(self):
        self.log.append(("close",))
        self.is_open = False

    def write(self, data):
        b = bytes(data)
        self.log.append(("write", len(b), b.hex(" ")))
        if self.response_on_write:
            self._rx.extend(self.response_on_write)
            self.in_waiting = len(self._rx)
        return len(b)

    def flush(self):
        self.log.append(("flush",))

    def reset_input_buffer(self):
        self.log.append(("reset_input_buffer",))
        self._rx.clear()
        self.in_waiting = 0

    def read(self, n=1):
        self.log.append(("read", int(n), self.timeout))
        if not self._rx:
            return b""
        out = bytes(self._rx[:n])
        del self._rx[:n]
        self.in_waiting = len(self._rx)
        return out

    def __getattr__(self, name):
        def recorder(*args, **kwargs):
            self.log.append((name, args, kwargs))
            return None
        return recorder


class FakeSerialFactory:
    def __init__(self):
        self.instances: list[FakeSerial] = []

    def __call__(self, *args, **kwargs):
        obj = FakeSerial(*args, **kwargs)
        self.instances.append(obj)
        return obj


def find_extracted_root(root: pathlib.Path) -> pathlib.Path:
    candidates = [
        root / "app_recovery" / "extracted_app",
        root / "extracted_app",
        root,
    ]
    for c in candidates:
        if (c / "drgrey" / "transport.cp314-win_amd64.pyd").exists():
            return c
    raise FileNotFoundError("drgrey/transport.cp314-win_amd64.pyd not found")


def extract_if_needed(source: pathlib.Path, temp_root: pathlib.Path) -> pathlib.Path:
    if source.is_dir():
        return find_extracted_root(source)
    if not zipfile.is_zipfile(source):
        raise ValueError("source must be the recovered DrGrey ZIP or extracted directory")
    with zipfile.ZipFile(source, "r") as zf:
        zf.extractall(temp_root)
    return find_extracted_root(temp_root)


def print_signature(label: str, obj) -> None:
    try:
        print(f"{label}: {inspect.signature(obj)}")
    except Exception as exc:
        print(f"{label}: <signature unavailable: {exc}>")


def construct_transport(cls, fake_factory: FakeSerialFactory):
    # Constructor is allowed to call the module-level Serial symbol because it
    # has already been replaced with our fake factory.
    attempts = [
        (),
        ("FAKE",),
        ("FAKE", 9600),
    ]
    errors = []
    for args in attempts:
        try:
            obj = cls(*args)
            return obj, args
        except Exception as exc:
            errors.append((args, repr(exc)))
    raise RuntimeError(f"could not construct SerialTransport safely: {errors}")


def attach_fake_if_needed(obj, factory: FakeSerialFactory) -> FakeSerial:
    if factory.instances:
        return factory.instances[-1]

    fake = FakeSerial(port="FAKE", baudrate=9600)
    for attr in ("ser", "serial", "_ser"):
        try:
            setattr(obj, attr, fake)
            print(f"attached fake serial via attribute {attr!r}")
            return fake
        except Exception:
            pass

    # Some Cython classes expose the underlying field through open(); with the
    # module-level Serial constructor already replaced, this is still offline.
    for open_args in ((), ("FAKE",), ("FAKE", 9600)):
        try:
            obj.open(*open_args)
            if factory.instances:
                return factory.instances[-1]
        except Exception:
            continue

    raise RuntimeError("could not attach fake serial object")


def run_case(obj, fake: FakeSerial, *, reset_after: str | None, wait_response: bool, window_ms: int):
    fake.log.clear()
    if reset_after is None:
        os.environ.pop("DRGREY_GRAY_RESET_AFTER", None)
    else:
        os.environ["DRGREY_GRAY_RESET_AFTER"] = reset_after

    packet = bytes.fromhex("55 0d 04 33 2a 28 00 00 40 00 01 00 00")
    print()
    print(
        f"CASE reset_after={reset_after!r} "
        f"wait_response={wait_response!r} window_ms={window_ms}"
    )

    t0 = time.monotonic()
    try:
        result = obj.send_like_gray_flasher(
            packet,
            wait_response=wait_response,
            window_ms=window_ms,
        )
        print(f"return={result!r}")
    except Exception as exc:
        print(f"exception={type(exc).__name__}: {exc}")
    elapsed = (time.monotonic() - t0) * 1000.0
    print(f"elapsed_ms={elapsed:.3f}")
    print("fake-serial calls:")
    for item in fake.log:
        print("  ", item)


def run_response_case(obj, fake: FakeSerial) -> None:
    fake.log.clear()
    os.environ.pop("DRGREY_GRAY_RESET_AFTER", None)
    fake.response_on_write = bytes.fromhex("aa bb cc dd")
    packet = bytes.fromhex("55 0d 04 33 2a 28 00 00 40 00 01 00 00")
    print()
    print("RESPONSE CASE default reset-before-write, 4 response bytes injected on write")
    t0 = time.monotonic()
    try:
        result = obj.send_like_gray_flasher(packet, wait_response=True, window_ms=5)
        print(f"return={result!r}")
    except Exception as exc:
        print(f"exception={type(exc).__name__}: {exc}")
    print(f"elapsed_ms={(time.monotonic()-t0)*1000.0:.3f}")
    print("fake-serial calls:")
    for item in fake.log:
        print("  ", item)
    fake.response_on_write = b""


def run_repeat_case(obj, fake: FakeSerial, *, reset_after: str, count: int) -> None:
    fake.log.clear()
    os.environ["DRGREY_GRAY_RESET_AFTER"] = reset_after
    packet = bytes.fromhex("55 0d 04 33 2a 28 00 00 40 00 01 00 00")

    print()
    print(f"REPEAT CASE reset_after={reset_after!r} count={count}")
    for _ in range(count):
        obj.send_like_gray_flasher(packet, wait_response=False, window_ms=0)

    resets = [i for i, item in enumerate(fake.log) if item and item[0] == "reset_input_buffer"]
    writes = [i for i, item in enumerate(fake.log) if item and item[0] == "write"]
    print(f"resets={len(resets)} writes={len(writes)}")
    print("first 12 calls:")
    for item in fake.log[:12]:
        print("  ", item)
    print("last 12 calls:")
    for item in fake.log[-12:]:
        print("  ", item)



def run_send_and_collect_cases(obj, fake: FakeSerial) -> None:
    packet = bytes.fromhex("55 0d 04 33 2a 28 00 00 40 00 01 00 00")

    print()
    print("SEND_AND_COLLECT CASE immediate 4-byte response, window_ms=0 read_timeout_ms=1")
    fake.log.clear()
    fake.response_on_write = bytes.fromhex("aa bb cc dd")
    t0 = time.monotonic()
    try:
        result = obj.send_and_collect(packet, window_ms=0, read_timeout_ms=1)
        print(f"return={result!r}")
    except Exception as exc:
        print(f"exception={type(exc).__name__}: {exc}")
    print(f"elapsed_ms={(time.monotonic()-t0)*1000.0:.3f}")
    print("fake-serial calls:")
    for item in fake.log:
        print("  ", item)

    print()
    print("SEND_AND_COLLECT CASE no response, window_ms=0 read_timeout_ms=1")
    fake.log.clear()
    fake.response_on_write = b""
    t0 = time.monotonic()
    try:
        result = obj.send_and_collect(packet, window_ms=0, read_timeout_ms=1)
        print(f"return={result!r}")
    except Exception as exc:
        print(f"exception={type(exc).__name__}: {exc}")
    print(f"elapsed_ms={(time.monotonic()-t0)*1000.0:.3f}")
    print("fake-serial calls:")
    for item in fake.log:
        print("  ", item)


def run_read_burst_cases(obj, fake: FakeSerial) -> None:
    print()
    print("READ_BURST CASE preloaded 4 bytes, budget_ms=120 read_timeout_ms=40")
    fake.log.clear()
    fake.response_on_write = b""
    fake._rx[:] = bytes.fromhex("aa bb cc dd")
    fake.in_waiting = len(fake._rx)
    t0 = time.monotonic()
    try:
        result = obj.read_burst(budget_ms=120, read_timeout_ms=40)
        print(f"return={result!r}")
    except Exception as exc:
        print(f"exception={type(exc).__name__}: {exc}")
    print(f"elapsed_ms={(time.monotonic()-t0)*1000.0:.3f}")
    print("fake-serial calls:")
    for item in fake.log:
        print("  ", item)

    print()
    print("READ_BURST CASE empty, budget_ms=5 read_timeout_ms=1")
    fake.log.clear()
    fake._rx.clear()
    fake.in_waiting = 0
    t0 = time.monotonic()
    try:
        result = obj.read_burst(budget_ms=5, read_timeout_ms=1)
        print(f"return={result!r}")
    except Exception as exc:
        print(f"exception={type(exc).__name__}: {exc}")
    print(f"elapsed_ms={(time.monotonic()-t0)*1000.0:.3f}")
    print("fake-serial calls:")
    for item in fake.log:
        print("  ", item)


def main() -> int:
    if sys.version_info[:2] != (3, 14):
        print(
            f"ERROR: this recovered extension is cp314; run with Python 3.14 "
            f"(current {sys.version.split()[0]}).",
            file=sys.stderr,
        )
        return 2

    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="DrGrey full recovery ZIP or extracted_app directory")
    args = ap.parse_args()
    source = pathlib.Path(args.source)

    if not source.exists():
        print(f"ERROR: source not found: {source}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="drgrey_transport_probe_", ignore_cleanup_errors=True) as td:
        root = extract_if_needed(source, pathlib.Path(td))
        sys.path.insert(0, str(root))

        # Import pyserial normally if available, but replace the exact Serial
        # constructor symbol used by the Cython module before constructing any
        # SerialTransport instance.
        tr = importlib.import_module("drgrey.transport")

        print(f"loaded: {tr.__file__}")
        print_signature("SerialTransport", tr.SerialTransport)
        print_signature(
            "SerialTransport.send_like_gray_flasher",
            tr.SerialTransport.send_like_gray_flasher,
        )
        print_signature("SerialTransport.send_and_collect", tr.SerialTransport.send_and_collect)
        print_signature("SerialTransport.read_burst", tr.SerialTransport.read_burst)

        factory = FakeSerialFactory()

        original_serial_symbol = getattr(tr, "Serial", None)
        setattr(tr, "Serial", factory)
        try:
            obj, ctor_args = construct_transport(tr.SerialTransport, factory)
            print(f"constructed SerialTransport with args={ctor_args!r}")
            fake = attach_fake_if_needed(obj, factory)

            # No real serial object exists anywhere below this point.
            run_case(obj, fake, reset_after=None, wait_response=False, window_ms=0)
            run_case(obj, fake, reset_after=None, wait_response=True, window_ms=1)
            run_case(obj, fake, reset_after="1", wait_response=False, window_ms=0)
            run_case(obj, fake, reset_after="1", wait_response=True, window_ms=1)
            run_case(obj, fake, reset_after="64", wait_response=False, window_ms=0)
            run_repeat_case(obj, fake, reset_after="64", count=66)
            run_response_case(obj, fake)
            run_send_and_collect_cases(obj, fake)
            run_read_burst_cases(obj, fake)
        finally:
            setattr(tr, "Serial", original_serial_symbol)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
