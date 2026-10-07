#!/usr/bin/env python3
"""Locate DJI Assistant 2 cached DJI Mini 3 / WM163 production firmware on Windows.

DJI does not document one stable public cache path across Assistant generations.
Older Assistant builds are known to use an install-tree Data/firm_cache folder,
while Consumer Drones builds also keep data in DJI Assistant AppData locations.

This module searches a constrained set of DJI-owned roots only. It never scans
an entire drive and never modifies DJI Assistant files.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import struct
import tarfile
import xml.etree.ElementTree as ET

from wm163_service_fw_inspect import inspect_package


PREFERRED_PRODUCTION_FORMAL = "01.00.0500"


@dataclasses.dataclass(frozen=True)
class CachedFirmware:
    kind: str  # "archive" or "module-set"
    root: pathlib.Path
    formal: str
    release: str
    cfg_path: pathlib.Path | None
    archive_path: pathlib.Path | None
    module_files: tuple[pathlib.Path, ...]
    missing_modules: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_modules

    @property
    def display_path(self) -> pathlib.Path:
        return self.archive_path or self.root


def _candidate_roots() -> list[pathlib.Path]:
    env = os.environ
    roots: list[pathlib.Path] = []

    def add(path: str | pathlib.Path | None) -> None:
        if not path:
            return
        p = pathlib.Path(path)
        if p not in roots:
            roots.append(p)

    pf86 = env.get("ProgramFiles(x86)")
    pf = env.get("ProgramFiles")
    local = env.get("LOCALAPPDATA")
    roaming = env.get("APPDATA")
    programdata = env.get("PROGRAMDATA")

    for base in (pf86, pf):
        if not base:
            continue
        basep = pathlib.Path(base) / "DJI Product"
        for product in (
            "DJI Assistant 2 (Consumer Drones Series)",
            "DJI Assistant 2",
        ):
            product_root = basep / product
            add(product_root / "Assistant" / "Data" / "firm_cache")
            add(product_root / "DJIEngine" / "firm_cache")
            add(product_root / "DJIApp" / "firm_cache")
            add(product_root / "firm_cache")
            # Keep the product root as a fallback because current versions may
            # move the cache while retaining the same installation tree.
            add(product_root)

    for base in (local, roaming):
        if not base:
            continue
        basep = pathlib.Path(base)
        for name in (
            "DJI Assistant 2",
            "DJIAssistant2",
            "DJI Assistant 2 (Consumer Drones Series)",
            "DJI",
        ):
            add(basep / name)

    if programdata:
        add(pathlib.Path(programdata) / "DJI Product")
        add(pathlib.Path(programdata) / "DJI")

    return roots


def candidate_roots() -> tuple[pathlib.Path, ...]:
    """Public read-only list of Windows locations searched by the GUI."""
    return tuple(_candidate_roots())


def _extract_signed_cfg_xml(blob: bytes) -> ET.Element:
    if not blob.startswith(b"IM*H"):
        raise ValueError("not an IM*H signed DJI cfg")
    if len(blob) < 32:
        raise ValueError("signed cfg too short")

    size_a = struct.unpack_from("<I", blob, 8)[0]
    size_b = struct.unpack_from("<I", blob, 28)[0]
    if size_a != len(blob) or size_b != len(blob):
        raise ValueError("signed cfg total-size mismatch")

    start = blob.find(b"<?xml")
    end = blob.rfind(b"</dji>")
    if start < 0 or end < 0:
        raise ValueError("signed cfg contains no DJI XML")
    return ET.fromstring(blob[start : end + len(b"</dji>")])


def _inspect_cfg(path: pathlib.Path) -> CachedFirmware | None:
    try:
        root = _extract_signed_cfg_xml(path.read_bytes())
    except (OSError, ValueError, ET.ParseError):
        return None

    device = root.find("./device")
    if device is None or device.attrib.get("id", "").lower() != "wm163":
        return None

    firmware = device.find("./firmware")
    if firmware is None:
        return None

    formal = firmware.attrib.get("formal", "")
    release = firmware.find("./release")
    if release is None:
        return None
    release_ver = release.attrib.get("version", "")

    filenames: list[str] = []
    for node in release.findall("./module"):
        name = (node.text or "").strip()
        if name:
            filenames.append(name)

    module_paths: list[pathlib.Path] = []
    missing: list[str] = []
    for name in filenames:
        direct = path.parent / name
        if direct.is_file():
            module_paths.append(direct)
            continue

        # Some Assistant versions nest individual module files below a version
        # directory. Restrict fallback lookup to the cfg's cache subtree.
        matches = list(path.parent.rglob(name))
        if matches:
            module_paths.append(matches[0])
        else:
            missing.append(name)

    return CachedFirmware(
        kind="module-set",
        root=path.parent,
        formal=formal,
        release=release_ver,
        cfg_path=path,
        archive_path=None,
        module_files=tuple(module_paths),
        missing_modules=tuple(missing),
    )


def _archive_candidates(root: pathlib.Path):
    patterns = (
        "*wm163*.bin",
        "*WM163*.bin",
        "*dji_system*.bin",
    )
    seen: set[pathlib.Path] = set()
    for pattern in patterns:
        try:
            iterator = root.rglob(pattern)
        except OSError:
            continue
        for path in iterator:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            yield path


def _inspect_archive(path: pathlib.Path) -> CachedFirmware | None:
    try:
        if not tarfile.is_tarfile(path):
            return None
        info = inspect_package(path, require_known_v30=False)
    except (OSError, tarfile.TarError, ValueError, ET.ParseError):
        return None

    if info.device.lower() != "wm163":
        return None

    return CachedFirmware(
        kind="archive",
        root=path.parent,
        formal=info.formal,
        release=info.release,
        cfg_path=None,
        archive_path=path,
        module_files=tuple(),
        missing_modules=tuple(),
    )


def _cfg_candidates(root: pathlib.Path):
    patterns = (
        "wm163.cfg.sig",
        "*wm163*cfg.sig",
        "*WM163*cfg.sig",
    )
    seen: set[pathlib.Path] = set()
    for pattern in patterns:
        try:
            iterator = root.rglob(pattern)
        except OSError:
            continue
        for path in iterator:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            yield path


def _score(item: CachedFirmware, preferred_formal: str) -> tuple:
    exact = int(item.formal == preferred_formal and item.release == preferred_formal)
    complete = int(item.complete)
    archive = int(item.kind == "archive")
    module_count = len(item.module_files)
    # Prefer exact production version first, then complete sets, then a full
    # archive if Assistant happens to retain one.
    return (exact, complete, archive, module_count)


def find_wm163_assistant_firmware(
    *,
    roots: list[pathlib.Path] | tuple[pathlib.Path, ...] | None = None,
    preferred_formal: str = PREFERRED_PRODUCTION_FORMAL,
) -> list[CachedFirmware]:
    """Return WM163 cache candidates ranked best-first."""
    scan_roots = list(roots) if roots is not None else _candidate_roots()
    found: list[CachedFirmware] = []
    seen_identity: set[tuple[str, str]] = set()

    for root in scan_roots:
        root = pathlib.Path(root)
        if not root.exists():
            continue

        for archive in _archive_candidates(root):
            item = _inspect_archive(archive)
            if item is None:
                continue
            ident = (item.kind, str(item.display_path).lower())
            if ident not in seen_identity:
                found.append(item)
                seen_identity.add(ident)

        for cfg in _cfg_candidates(root):
            item = _inspect_cfg(cfg)
            if item is None:
                continue
            ident = (item.kind, str(item.cfg_path).lower())
            if ident not in seen_identity:
                found.append(item)
                seen_identity.add(ident)

    found.sort(key=lambda item: _score(item, preferred_formal), reverse=True)
    return found


def describe_cached_firmware(item: CachedFirmware) -> str:
    if item.kind == "archive":
        return (
            f"WM163 archive formal={item.formal or '?'} release={item.release or '?'} "
            f"path={item.archive_path}"
        )

    status = "complete" if item.complete else f"missing {len(item.missing_modules)} module(s)"
    return (
        f"WM163 module cache formal={item.formal or '?'} release={item.release or '?'} "
        f"modules={len(item.module_files)} ({status}) root={item.root}"
    )


if __name__ == "__main__":
    matches = find_wm163_assistant_firmware()
    if not matches:
        print("No WM163 DJI Assistant firmware cache was found.")
        raise SystemExit(1)
    for item in matches:
        print(describe_cached_firmware(item))
