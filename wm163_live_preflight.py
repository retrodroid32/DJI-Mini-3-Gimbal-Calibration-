#!/usr/bin/env python3
"""Single read-only WM163 live preflight before any Service-FW hardware test.

This module deliberately reuses existing project probes and validators:
- installed aircraft cfg.sig: existing read-only General 0x00/0x4F probe;
- gimbal diagnostics: existing passive General 0x00/0xF1 listener;
- exact private Service FW + Session-A loader validation;
- exact production v01.00.0500 validation;
- recovered WM163 V30 ARB/diagnostic policy.

It contains no firmware-transfer, calibration, IMU-write, factory-state, or
reboot operation.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import pathlib
import re
import sys
from dataclasses import dataclass

import mini3_gimbal_cal as cal
import wm163_private_fw as private_fw
import wm163_production_fw as production_fw
import wm163_service_flash_live as service_fw
from wm163_service_fw_policy import evaluate_wm163_v30_preflight


@dataclass(frozen=True)
class ParsedManifestProbe:
    device: str
    formal: str
    release: str
    antirollback: str


@dataclass(frozen=True)
class ParsedDiagnostics:
    diagnostic_40011_active: bool
    diagnostic_40021_active: bool


def parse_manifest_probe_output(output: str) -> ParsedManifestProbe:
    def value(name: str) -> str:
        match = re.search(rf"^{re.escape(name)}=(.+)$", output, re.MULTILINE)
        if not match:
            return ""
        return match.group(1).strip()

    anti_line = re.search(r"^antirollback=(\S+)", output, re.MULTILINE)
    return ParsedManifestProbe(
        device=value("device"),
        formal=value("formal"),
        release=value("release"),
        antirollback=anti_line.group(1) if anti_line else "",
    )


def parse_diagnostics_output(output: str) -> ParsedDiagnostics:
    return ParsedDiagnostics(
        diagnostic_40011_active=bool(
            re.search(r"\b40011\s+CALIBRATE_ERROR\b", output)
        ),
        diagnostic_40021_active=bool(
            re.search(r"\b40021\s+IMU_DATA_DISMATCH\b", output)
        ),
    )


def capture_call(fn) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = int(fn() or 0)
    return rc, buf.getvalue()


def validate_local_inputs(base_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    private = private_fw.find_private_service_inputs(base_dir)
    if not private.complete:
        missing = []
        if private.package is None:
            missing.append(private_fw.SERVICE_PACKAGE_FILENAME)
        if private.loader is None:
            missing.append(private_fw.SESSION_A_LOADER_FILENAME)
        raise RuntimeError(
            "private Service-FW inputs missing: " + ", ".join(missing)
        )

    production = production_fw.find_repo_production_archive(base_dir)
    if production is None:
        raise RuntimeError(
            "exact production firmware missing: "
            f"firmware/{production_fw.DEFAULT_PRODUCTION_FILENAME}"
        )

    service_fw.validate_inputs(private.package, private.loader)
    production_fw.validate_production_archive(production)
    return private.package, private.loader, production


def run(
    port: str,
    *,
    baudrate: int = 9600,
    manifest_timeout_seconds: float = 3.0,
    diagnostic_seconds: float = 5.0,
    base_dir: pathlib.Path | None = None,
) -> int:
    root = base_dir or pathlib.Path(__file__).resolve().parent

    print("WM163 LIVE PREFLIGHT — READ ONLY")
    print(f"Port: {port} @ {baudrate}")
    print(
        "No firmware transfer, calibration, IMU write, factory-state change, "
        "or reboot command is permitted by this preflight."
    )

    try:
        service_package, loader, production = validate_local_inputs(root)
    except Exception as exc:
        print(f"BLOCKED: local firmware validation failed: {exc}", file=sys.stderr)
        return 2

    print("Local exact-file validation: PASS")
    print(f"  Service FW: {service_package}")
    print(f"  Session-A loader: {loader}")
    print(f"  Production FW: {production}")

    manifest_rc, manifest_output = capture_call(
        lambda: cal.run_fw_manifest_probe(
            port,
            baudrate,
            manifest_timeout_seconds,
            0,
        )
    )
    print("\n--- Installed firmware manifest probe ---")
    print(manifest_output.rstrip())
    if manifest_rc != 0:
        print(
            f"BLOCKED: installed firmware manifest probe ended rc={manifest_rc}.",
            file=sys.stderr,
        )
        return 3

    manifest = parse_manifest_probe_output(manifest_output)
    if not manifest.device or not manifest.formal or not manifest.antirollback:
        print("BLOCKED: required manifest fields were not parsed.", file=sys.stderr)
        return 4

    diag_rc, diag_output = capture_call(
        lambda: cal.run_gimbal_diagnostics(
            port,
            baudrate,
            diagnostic_seconds,
            0,
        )
    )
    print("\n--- Passive gimbal diagnostics ---")
    print(diag_output.rstrip())
    if diag_rc != 0:
        print(
            f"BLOCKED: passive gimbal diagnostics ended rc={diag_rc}.",
            file=sys.stderr,
        )
        return 5

    diagnostics = parse_diagnostics_output(diag_output)

    allowed, reasons = evaluate_wm163_v30_preflight(
        aircraft_device=manifest.device,
        aircraft_formal=manifest.formal,
        aircraft_antirollback=manifest.antirollback,
        diagnostic_40011_active=diagnostics.diagnostic_40011_active,
        diagnostic_40021_active=diagnostics.diagnostic_40021_active,
    )

    print("\n--- V30 repair-policy evaluation ---")
    for reason in reasons:
        print(f"  - {reason}")

    if not allowed:
        print("PREFLIGHT: BLOCKED", file=sys.stderr)
        return 6

    print("PREFLIGHT: PASS")
    print(
        "This PASS authorizes only consideration of a deliberate first "
        "hardware-validation run. It does NOT unlock Service-FW flashing."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only WM163 live preflight for the V30 repair path"
    )
    parser.add_argument("--port", required=True, help="DJI USB Virtual COM port, e.g. COM23")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--manifest-timeout-seconds", type=float, default=3.0)
    parser.add_argument("--diagnostic-seconds", type=float, default=5.0)
    args = parser.parse_args()
    return run(
        args.port,
        baudrate=args.baudrate,
        manifest_timeout_seconds=args.manifest_timeout_seconds,
        diagnostic_seconds=args.diagnostic_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
