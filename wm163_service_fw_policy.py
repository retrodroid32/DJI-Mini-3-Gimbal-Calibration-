#!/usr/bin/env python3
"""Recovered DrGrey service-firmware selection/ARB policy.

This module contains no transport code and cannot flash an aircraft.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class ServiceFw:
    version: str
    filename: str
    note: str = ""

    def full_path(self, base_dir: str) -> str:
        import os
        if os.path.isabs(self.filename):
            return self.filename
        return os.path.join(base_dir, self.filename)


SERVICE_FW_LIBRARY: dict[str, tuple[ServiceFw, ...]] = {
    "WM162": (
        ServiceFw("20.00.0800", "mini3pro_service.bin", "wetransfer 2026-04-27"),
    ),
    "WM163": (
        ServiceFw("30.00.0100", "mini3_service.bin", "wetransfer 2026-04-27"),
    ),
    "WA1617": (
        ServiceFw("20.07.0700", "mini4k_service.bin", "wetransfer 2026-04-27"),
    ),
}


def parse_version(s: object) -> tuple[int, ...]:
    """Reproduce DrGrey's recovered version normalization.

    False/empty input yields (). Underscores and hyphens are normalized to
    periods; only dot-separated tokens consisting entirely of digits are kept.
    """
    if not s:
        return ()
    text = str(s).replace("_", ".").replace("-", ".")
    parts = text.split(".")
    return tuple(int(tok) for tok in parts if tok.isdigit())


def arb_allows(service_version: object, drone_public_version: object) -> bool:
    """Recovered DrGrey ARB predicate: parsed service version >= public version."""
    return parse_version(service_version) >= parse_version(drone_public_version)


def select_service_fw(
    model_code: object,
    drone_public_version: object,
    library: Mapping[str, Sequence[ServiceFw]] | None = None,
) -> tuple[ServiceFw | None, str]:
    """Reproduce DrGrey's service-image selector.

    Model codes are stripped/uppercased. Candidates that fail arb_allows() are
    excluded. The newest eligible image is selected by parsed version.
    """
    lib = SERVICE_FW_LIBRARY if library is None else library
    model = ("" if model_code is None else str(model_code)).strip().upper()
    cands = tuple(lib.get(model, ()))

    if not cands:
        return None, (
            f"No hay FW de servicio en la biblioteca para {model or '(modelo?)'}. "
            f"Agregalo a SERVICE_FW_LIBRARY[{model or '(modelo?)'}]."
        )

    eligible = [
        fw for fw in cands
        if arb_allows(fw.version, drone_public_version)
    ]

    if not eligible:
        newest = max(cands, key=lambda f: parse_version(f.version))
        return None, (
            f"ARB bloquea: el dron está en versión pública {drone_public_version}; "
            f"el FW de servicio más nuevo disponible es {newest.version} (más viejo). "
            "Necesitás el FW de servicio para el ARB actual del dron."
        )

    selected = max(eligible, key=lambda f: parse_version(f.version))
    return selected, (
        f"OK: FW de servicio {selected.version} para {model} "
        f"en versión pública {drone_public_version} (ARB compatible)."
    )


def has_service_fw(
    model_code: object,
    library: Mapping[str, Sequence[ServiceFw]] | None = None,
) -> bool:
    """Recovered DrGrey catalog-availability predicate.

    This intentionally performs no ARB/public-version check. Use
    select_service_fw() for the ARB-aware selection gate.
    """
    lib = SERVICE_FW_LIBRARY if library is None else library
    model = ("" if model_code is None else str(model_code)).strip().upper()
    return bool(lib.get(model, ()))


def select_service_fw_from_aircraft_manifest(
    model_code: object,
    aircraft_manifest: Mapping[str, object] | None,
    library: Mapping[str, Sequence[ServiceFw]] | None = None,
) -> tuple[ServiceFw | None, str]:
    """ARB-aware selection using the aircraft's own cfg.sig FORMAL version.

    The recovered DrGrey diagnostics path can read the installed aircraft
    firmware manifest read-only.  This helper intentionally requires the
    aircraft-level FORMAL release string from that manifest instead of using
    per-module loader/app versions.

    It contains no transport code and cannot flash an aircraft.
    """
    if not aircraft_manifest:
        return None, (
            "ARB guard blocked: no aircraft firmware manifest was supplied. "
            "A read-only cfg.sig FORMAL version is required."
        )

    formal = aircraft_manifest.get("formal")
    if formal is None:
        # Permit a nested shape matching common parsed-manifest structures
        # without guessing a version from module entries.
        firmware = aircraft_manifest.get("firmware")
        if isinstance(firmware, Mapping):
            formal = firmware.get("formal")

    if not formal:
        return None, (
            "ARB guard blocked: aircraft cfg.sig has no FORMAL firmware "
            "version. Module app/loader versions are not valid substitutes."
        )

    return select_service_fw(model_code, formal, library)


def evaluate_wm163_v30_preflight(
    *,
    aircraft_device: object,
    aircraft_formal: object,
    aircraft_antirollback: object,
    diagnostic_40011_active: bool,
    diagnostic_40021_active: bool,
) -> tuple[bool, tuple[str, ...]]:
    """Offline go/no-go evaluator for the known WM163 V30.00.0100 40011 path.

    This contains no transport or flashing code. It evaluates only the live
    read-only state already obtained from the aircraft.

    40021 is deliberately not a blocking condition. A WM163 with both 40011
    and 40021 follows the validated repair order: Service FW -> Advanced
    Calibration (40011) -> short 40021 repair -> reboot/verify.
    """
    reasons: list[str] = []

    device = ("" if aircraft_device is None else str(aircraft_device)).strip().lower()
    if device != "wm163":
        reasons.append(f"wrong aircraft device: expected wm163, got {aircraft_device!r}")

    if not aircraft_formal:
        reasons.append("missing aircraft cfg.sig FORMAL version")
    elif not arb_allows("30.00.0100", aircraft_formal):
        reasons.append(
            f"ARB blocks V30.00.0100 against aircraft FORMAL {aircraft_formal}"
        )

    if str(aircraft_antirollback).strip() != "0":
        reasons.append(
            f"unexpected aircraft antirollback={aircraft_antirollback!r}; expected '0'"
        )

    if not diagnostic_40011_active:
        reasons.append("40011 is not currently active; no 40011 service repair is indicated")

    if reasons:
        return False, tuple(reasons)

    return True, (
        "WM163 identity confirmed",
        f"aircraft FORMAL {aircraft_formal} is compatible with service 30.00.0100",
        "aircraft antirollback is 0",
        (
            "40021 is active; combined repair is allowed and 40021 must be repaired "
            "after Advanced Calibration"
            if diagnostic_40021_active
            else "40021 is clear; 40011-only service path is allowed"
        ),
        "40011 is active",
    )
