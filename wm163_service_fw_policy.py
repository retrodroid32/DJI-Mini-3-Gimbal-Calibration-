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
