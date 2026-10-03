#!/usr/bin/env python3
"""Offline validator for DJI Mini 3 / WM163 service-calibration firmware packages."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import io
import pathlib
import re
import struct
import sys
import tarfile
import xml.etree.ElementTree as ET

EXPECTED_DEVICE = "wm163"
EXPECTED_FORMAL = "30.00.0100"
EXPECTED_MODULE_ORDER = ("0905", "0306", "1200", "1100", "0105", "0100")
EXPECTED_ARCHIVE_MD5 = "7895303d687618766cc06efe405cf082"
EXPECTED_ARCHIVE_SHA256 = "c6c88d49c6da0026a9498d07f04a3db41ef8a8d650a5bbaf22de574dc8e60b26"

@dataclasses.dataclass(frozen=True)
class ModuleInfo:
    module_id: str
    version: str
    order: int
    wait: int
    size: int
    md5: str
    filename: str

@dataclasses.dataclass(frozen=True)
class PackageInfo:
    device: str
    formal: str
    release: str
    antirollback: str
    antirollback_ext: str
    enforce: str
    modules: tuple[ModuleInfo, ...]
    md5: str
    sha256: str


def _hashes(path: pathlib.Path) -> tuple[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def _extract_xml(signed_cfg: bytes) -> bytes:
    if not signed_cfg.startswith(b"IM*H"):
        raise ValueError("wm163.cfg.sig does not start with IM*H")
    if len(signed_cfg) < 32:
        raise ValueError("wm163.cfg.sig is too short")
    total_a = struct.unpack_from("<I", signed_cfg, 8)[0]
    total_b = struct.unpack_from("<I", signed_cfg, 28)[0]
    if total_a != len(signed_cfg) or total_b != len(signed_cfg):
        raise ValueError(
            f"wm163.cfg.sig IM*H total-size mismatch: hdr={total_a}/{total_b}, actual={len(signed_cfg)}"
        )
    start = signed_cfg.find(b"<?xml")
    end = signed_cfg.rfind(b"</dji>")
    if start < 0 or end < 0:
        raise ValueError("signed config contains no DJI XML manifest")
    return signed_cfg[start : end + len(b"</dji>")]


def _validate_imah(name: str, blob: bytes) -> None:
    if not blob.startswith(b"IM*H"):
        raise ValueError(f"{name}: missing IM*H header")
    if len(blob) < 32:
        raise ValueError(f"{name}: truncated IM*H header")
    size_a = struct.unpack_from("<I", blob, 8)[0]
    size_b = struct.unpack_from("<I", blob, 28)[0]
    if size_a != len(blob) or size_b != len(blob):
        raise ValueError(
            f"{name}: IM*H size mismatch hdr={size_a}/{size_b}, actual={len(blob)}"
        )


def inspect_package(path: str | pathlib.Path, *, require_known_v30: bool = False) -> PackageInfo:
    path = pathlib.Path(path)
    md5_hex, sha256_hex = _hashes(path)

    with tarfile.open(path, "r:*") as tf:
        names = {m.name for m in tf.getmembers() if m.isfile()}
        if "wm163.cfg.sig" not in names:
            raise ValueError("archive does not contain wm163.cfg.sig")

        cfg = tf.extractfile("wm163.cfg.sig")
        if cfg is None:
            raise ValueError("could not read wm163.cfg.sig")
        cfg_blob = cfg.read()
        _validate_imah("wm163.cfg.sig", cfg_blob)
        xml_blob = _extract_xml(cfg_blob)
        root = ET.fromstring(xml_blob)

        device = root.find("./device")
        if device is None:
            raise ValueError("manifest has no <device>")
        device_id = device.attrib.get("id", "")
        firmware = device.find("./firmware")
        if firmware is None:
            raise ValueError("manifest has no <firmware>")
        formal = firmware.attrib.get("formal", "")
        release = firmware.find("./release")
        if release is None:
            raise ValueError("manifest has no <release>")

        release_ver = release.attrib.get("version", "")
        antirollback = release.attrib.get("antirollback", "")
        antirollback_ext = release.attrib.get("antirollback_ext", "")
        enforce = release.attrib.get("enforce", "")

        modules: list[ModuleInfo] = []
        seen_filenames: set[str] = set()
        for node in release.findall("./module"):
            info = ModuleInfo(
                module_id=node.attrib["id"],
                version=node.attrib["version"],
                order=int(node.attrib["order"]),
                wait=int(node.attrib.get("wait", "0")),
                size=int(node.attrib["size"]),
                md5=node.attrib["md5"].lower(),
                filename=(node.text or "").strip(),
            )
            if not info.filename:
                raise ValueError(f"module {info.module_id}: missing filename")
            if info.filename in seen_filenames:
                raise ValueError(f"duplicate module filename: {info.filename}")
            seen_filenames.add(info.filename)
            if info.filename not in names:
                raise ValueError(f"module {info.module_id}: missing archive member {info.filename}")

            fh = tf.extractfile(info.filename)
            if fh is None:
                raise ValueError(f"module {info.module_id}: cannot read {info.filename}")
            blob = fh.read()
            if len(blob) != info.size:
                raise ValueError(
                    f"module {info.module_id}: size mismatch manifest={info.size}, actual={len(blob)}"
                )
            digest = hashlib.md5(blob).hexdigest()
            if digest != info.md5:
                raise ValueError(
                    f"module {info.module_id}: MD5 mismatch manifest={info.md5}, actual={digest}"
                )
            _validate_imah(info.filename, blob)
            modules.append(info)

    modules.sort(key=lambda m: m.order)
    orders = tuple(m.order for m in modules)
    if orders != tuple(range(1, len(modules) + 1)):
        raise ValueError(f"manifest module order is not contiguous: {orders}")

    if device_id.lower() != EXPECTED_DEVICE:
        raise ValueError(f"wrong device: expected {EXPECTED_DEVICE}, got {device_id!r}")

    if require_known_v30:
        if formal != EXPECTED_FORMAL or release_ver != EXPECTED_FORMAL:
            raise ValueError(
                f"wrong formal/release version for validated V30 package: {formal}/{release_ver}"
            )
        module_order = tuple(m.module_id for m in modules)
        if module_order != EXPECTED_MODULE_ORDER:
            raise ValueError(
                f"unexpected V30 module order: {' -> '.join(module_order)}"
            )
        if md5_hex != EXPECTED_ARCHIVE_MD5 or sha256_hex != EXPECTED_ARCHIVE_SHA256:
            raise ValueError(
                "archive bytes do not match the bench-validated WM163 V30.00.0100 package"
            )

    return PackageInfo(
        device=device_id,
        formal=formal,
        release=release_ver,
        antirollback=antirollback,
        antirollback_ext=antirollback_ext,
        enforce=enforce,
        modules=tuple(modules),
        md5=md5_hex,
        sha256=sha256_hex,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Offline integrity/manifest validator for WM163 service firmware.")
    p.add_argument("path", help="path to the DJI WM163 .bin package")
    p.add_argument(
        "--require-known-v30",
        action="store_true",
        help="require byte-for-byte match to the validated V30.00.0100 WM163 package",
    )
    args = p.parse_args()

    try:
        info = inspect_package(args.path, require_known_v30=args.require_known_v30)
    except (OSError, tarfile.TarError, ET.ParseError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2

    print(f"VALID WM163 package: {args.path}")
    print(f"device={info.device} formal={info.formal} release={info.release}")
    print(
        f"antirollback={info.antirollback!r} antirollback_ext={info.antirollback_ext!r} "
        f"enforce={info.enforce!r}"
    )
    for mod in info.modules:
        print(
            f"{mod.order}: {mod.module_id} v{mod.version} wait={mod.wait} "
            f"size={mod.size} md5={mod.md5} {mod.filename}"
        )
    print(f"archive MD5:    {info.md5}")
    print(f"archive SHA256: {info.sha256}")
    if args.require_known_v30:
        print("MATCH: exact bench-validated WM163 V30.00.0100 archive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
