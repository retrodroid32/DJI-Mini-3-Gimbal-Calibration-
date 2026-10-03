#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DJI Mini 3 (WM163) experimental gimbal calibration helper.

This project is a focused derivative of protocol work from o-gs/dji-firmware-tools.
It intentionally supports only DJI Mini 3 / WM163 and only the gimbal calibration
command set used for repair calibration.

GPL-3.0-or-later. NO WARRANTY. Experimental hardware-repair software.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import struct
import sys
import time
from typing import Iterable, Optional

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    serial = None

VERSION = "0.12.1"
MODEL = "DJI Mini 3"
PLATFORM = "WM163"

DJI_PRODUCT_NAMES = {
    112: "DJI Mini 3",
}

SOF = 0x55
COMM_DEV_CAMERA = 1
COMM_DEV_FLYCONTROLLER = 3
COMM_DEV_GIMBAL = 4
COMM_DEV_PC = 10
COMM_DEV_BATTERY = 11

CMD_SET_GENERAL = 0
CMD_SET_FLYCONTROLLER = 3
CMD_SET_ZENMUSE = 4

CMD_ID_GENERAL_REBOOT = 0x0B
CMD_ID_GENERAL_ACTIVE_STATUS = 0x32
CMD_ID_GENERAL_GET_SN = 0x51
CMD_ID_GENERAL_PUSH_CHECK_STATUS = 0xF1
CMD_ID_FC_GET_DEVICE_INFO = 0x74
CMD_ID_GIMBAL_CALIB = 0x08
CMD_ID_GIMBAL_GET_SERIAL_PARAMS = 0x1F
CMD_ID_GIMBAL_AUTO_CAL_STATUS = 0x30
CMD_ID_GIMBAL_WRITE_IMU = 0x36
CMD_ID_CAMERA_GET_SENSOR_ID = 0xB5

PACKET_TYPE_REQUEST = 0
PACKET_TYPE_RESPONSE = 1
ACK_BEFORE_EXEC = 1
ACK_AFTER_EXEC = 2
NO_ENCRYPTION = 0

IDENTITY_TARGETS = (
    ("camera", COMM_DEV_CAMERA),
    ("gimbal", COMM_DEV_GIMBAL),
    ("flight-controller", COMM_DEV_FLYCONTROLLER),
)

# DJI DataCommonGetDeviceSerialNumber selectors. The public app implementation
# names these BoardNum, ChipId, ModuleNum, and DeviceNum and sends the selector
# as the one-byte payload of General/GetSerialNum (0x00/0x51).
FC_DEVICE_ID_PROBES = (
    ("fc board-number", 0x01, "BoardNum"),
    ("fc chip-id", 0x02, "ChipId"),
    ("fc module-number", 0x03, "ModuleNum"),
    ("fc device-number", 0x04, "DeviceNum"),
)

# Legacy DJI ActiveStatus GET selectors from decompiled app code.
# Camera defaults to Ver1_0 GET=0x01; gimbal explicitly selects Ver1_1 GET=0x11.
ACTIVE_STATUS_PROBES = (
    ("camera active-status", COMM_DEV_CAMERA, b"\x01", "v1.0"),
    ("gimbal active-status", COMM_DEV_GIMBAL, b"\x11", "v1.1"),
)

DJI_CCODES = {
    0x00: "OK",
    0x01: "SUCCEED",
    0xD9: "NOT_SUPPORT_FEATURE",
    0xE0: "INVALID_CMD",
    0xE1: "TIMEOUT_REMOTE",
    0xE2: "OUT_OF_MEMORY",
    0xE3: "INVALID_PARAM",
    0xE4: "NOT_SUPPORT_CURRENT_STATE",
    0xE5: "TIME_NOT_SYNC",
    0xE6: "SET_PARAM_FAILED",
    0xE7: "GET_PARAM_FAILED",
    0xE8: "SDCARD_NOT_INSERTED",
    0xE9: "SDCARD_FULL",
    0xEA: "SDCARD_ERR",
    0xEB: "SENSOR_ERR",
    0xEC: "CAMERA_CRITICAL_ERR",
    0xED: "PARAM_NOT_AVAILABLE",
    0xFB: "DEVICE_LOW_POWER",
    0xFD: "FLASH_FLUSHING",
    0xFE: "UPDATE_NOCONNECT_CAMERA",
    0xFF: "UNDEFINED",
}

CALIB_COMMANDS = {
    "joint-coarse": 0x01,
    "linear-hall": 0x02,
}

# Recovered from DrGrey 1.5.2 static constants. Its embedded documentation
# identifies this exact four-byte form as bank-confirmed on WM163 with active
# 40021. Do not substitute the unrelated 168-byte/model-specific 0x36 payload.
IMU_FIX_SHORT_PAYLOAD = bytes.fromhex("42 e9 7f 3f")

# Legacy completion values used by o-gs/dji-firmware-tools on older DJI gimbals.
# WM163 may use a different progress format, so these are treated as hints only.
LEGACY_PASS = {
    "joint-coarse": (0x10, 0x01),
    "linear-hall": (0x28, 0x01),
}

# DJI DUMLv1 header CRC8 lookup table, GPL-derived from o-gs/dji-firmware-tools.
CRC8_TABLE = (
    0x00,0x5E,0xBC,0xE2,0x61,0x3F,0xDD,0x83,0xC2,0x9C,0x7E,0x20,0xA3,0xFD,0x1F,0x41,
    0x9D,0xC3,0x21,0x7F,0xFC,0xA2,0x40,0x1E,0x5F,0x01,0xE3,0xBD,0x3E,0x60,0x82,0xDC,
    0x23,0x7D,0x9F,0xC1,0x42,0x1C,0xFE,0xA0,0xE1,0xBF,0x5D,0x03,0x80,0xDE,0x3C,0x62,
    0xBE,0xE0,0x02,0x5C,0xDF,0x81,0x63,0x3D,0x7C,0x22,0xC0,0x9E,0x1D,0x43,0xA1,0xFF,
    0x46,0x18,0xFA,0xA4,0x27,0x79,0x9B,0xC5,0x84,0xDA,0x38,0x66,0xE5,0xBB,0x59,0x07,
    0xDB,0x85,0x67,0x39,0xBA,0xE4,0x06,0x58,0x19,0x47,0xA5,0xFB,0x78,0x26,0xC4,0x9A,
    0x65,0x3B,0xD9,0x87,0x04,0x5A,0xB8,0xE6,0xA7,0xF9,0x1B,0x45,0xC6,0x98,0x7A,0x24,
    0xF8,0xA6,0x44,0x1A,0x99,0xC7,0x25,0x7B,0x3A,0x64,0x86,0xD8,0x5B,0x05,0xE7,0xB9,
    0x8C,0xD2,0x30,0x6E,0xED,0xB3,0x51,0x0F,0x4E,0x10,0xF2,0xAC,0x2F,0x71,0x93,0xCD,
    0x11,0x4F,0xAD,0xF3,0x70,0x2E,0xCC,0x92,0xD3,0x8D,0x6F,0x31,0xB2,0xEC,0x0E,0x50,
    0xAF,0xF1,0x13,0x4D,0xCE,0x90,0x72,0x2C,0x6D,0x33,0xD1,0x8F,0x0C,0x52,0xB0,0xEE,
    0x32,0x6C,0x8E,0xD0,0x53,0x0D,0xEF,0xB1,0xF0,0xAE,0x4C,0x12,0x91,0xCF,0x2D,0x73,
    0xCA,0x94,0x76,0x28,0xAB,0xF5,0x17,0x49,0x08,0x56,0xB4,0xEA,0x69,0x37,0xD5,0x8B,
    0x57,0x09,0xEB,0xB5,0x36,0x68,0x8A,0xD4,0x95,0xCB,0x29,0x77,0xF4,0xAA,0x48,0x16,
    0xE9,0xB7,0x55,0x0B,0x88,0xD6,0x34,0x6A,0x2B,0x75,0x97,0xC9,0x4A,0x14,0xF6,0xA8,
    0x74,0x2A,0xC8,0x96,0x15,0x4B,0xA9,0xF7,0xB6,0xE8,0x0A,0x54,0xD7,0x89,0x6B,0x35,
)



CRC64_JONES_POLY = 0x95AC9329AC4BC9B5
MASK64 = 0xFFFFFFFFFFFFFFFF


def crc64_jones(seed: int, data: bytes) -> int:
    crc = seed & MASK64
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ CRC64_JONES_POLY if (crc & 1) else (crc >> 1)
        crc &= MASK64
    return crc


def dji_xor_decode(data: bytes, record_type: int) -> bytes:
    """DJI flight-record XOR decode used for v13+ auxiliary Info blocks."""
    if not data:
        return data
    first = data[0]
    seed = (first + record_type) & 0xFF
    key_input = ((0x123456789ABCDEF0 * first) & MASK64).to_bytes(8, "little")
    key = crc64_jones(seed, key_input).to_bytes(8, "little")
    return bytes(data[i + 1] ^ key[i % 8] for i in range(len(data) - 1))


@dataclasses.dataclass(frozen=True)
class FlightLogIdentity:
    version: int
    product_type: int
    aircraft_name: str
    aircraft_sn: str
    camera_sn: str
    rc_sn: str
    battery_sn: str
    app_platform: int
    app_version: str


def _fixed_utf8(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def parse_flightlog_identity(path: str | pathlib.Path) -> FlightLogIdentity:
    """Extract the unencrypted Details identity block from a DJI flight log.

    v13/v14 Details are contained in XOR-obfuscated AuxiliaryInfo. No DJI API key
    is required for this header metadata.
    """
    data = pathlib.Path(path).read_bytes()
    if len(data) < 100:
        raise ValueError("file is too small to be a DJI flight record")

    version = data[10]
    detail_offset_raw = int.from_bytes(data[:8], "little")

    if version >= 13:
        pos = 100
        if len(data) < pos + 3:
            raise ValueError("missing v13+ auxiliary Info block")
        magic = data[pos]
        size = int.from_bytes(data[pos + 1 : pos + 3], "little")
        if magic != 0:
            raise ValueError(f"expected AuxiliaryInfo magic 0, found {magic}")
        raw = data[pos + 3 : pos + 3 + size]
        if len(raw) != size:
            raise ValueError("truncated AuxiliaryInfo block")
        decoded = dji_xor_decode(raw, 0)
        if len(decoded) < 3:
            raise ValueError("decoded AuxiliaryInfo block is too short")
        info_len = int.from_bytes(decoded[1:3], "little")
        info = decoded[3 : 3 + info_len]
    else:
        detail_offset = detail_offset_raw if version < 12 else 100
        info = data[detail_offset : detail_offset + 436]

    if len(info) < 380:
        raise ValueError("DJI Details block is incomplete")

    if version <= 5:
        raise ValueError("flightlog-info currently supports DJI log version 6 and newer")

    product_type = info[271]
    aircraft_name = _fixed_utf8(info[280:312])
    aircraft_sn = _fixed_utf8(info[312:328])
    camera_sn = _fixed_utf8(info[328:344])
    rc_sn = _fixed_utf8(info[344:360])
    battery_sn = _fixed_utf8(info[360:376])
    app_platform = info[376]
    app_version = ".".join(str(v) for v in info[377:380])

    return FlightLogIdentity(
        version=version,
        product_type=product_type,
        aircraft_name=aircraft_name,
        aircraft_sn=aircraft_sn,
        camera_sn=camera_sn,
        rc_sn=rc_sn,
        battery_sn=battery_sn,
        app_platform=app_platform,
        app_version=app_version,
    )


def run_flightlog_info(path: str) -> int:
    try:
        ident = parse_flightlog_identity(path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    product = DJI_PRODUCT_NAMES.get(ident.product_type, f"DJI product type {ident.product_type}")
    print(f"Flight log: {path}")
    print(f"Log version: {ident.version}")
    print(f"Aircraft model: {ident.aircraft_name or product} (product type {ident.product_type})")
    print(f"Aircraft SN: {ident.aircraft_sn or '(not present)'}")
    print(f"Camera SN: {ident.camera_sn or '(not present)'}")
    print(f"RC SN: {ident.rc_sn or '(not present)'}")
    print(f"Battery SN: {ident.battery_sn or '(not present)'}")
    print(f"App platform: {ident.app_platform}")
    print(f"App version: {ident.app_version}")
    print("NOTE: This command reads only the flight-record header/details metadata.")
    return 0


def crc8_header(data: bytes, seed: int = 0x77) -> int:
    value = seed
    for byte in data:
        value = CRC8_TABLE[(byte ^ value) & 0xFF]
    return value


def crc16_duML(data: bytes, seed: int = 0x3692) -> int:
    """DJI DUMLv1 CRC16 (reflected 0x1021 polynomial / 0x8408 form)."""
    value = seed
    for byte in data:
        value ^= byte
        for _ in range(8):
            if value & 1:
                value = (value >> 1) ^ 0x8408
            else:
                value >>= 1
        value &= 0xFFFF
    return value


def build_packet(
    *,
    seq: int,
    payload: bytes,
    sender: int = COMM_DEV_PC,
    receiver: int = COMM_DEV_GIMBAL,
    packet_type: int = PACKET_TYPE_REQUEST,
    ack_type: int = ACK_BEFORE_EXEC,
    encrypt_type: int = NO_ENCRYPTION,
    cmd_set: int = CMD_SET_ZENMUSE,
    cmd_id: int = CMD_ID_GIMBAL_CALIB,
) -> bytes:
    length = 11 + len(payload) + 2
    if not 13 <= length <= 0x3FF:
        raise ValueError("DUML packet length out of range")

    ver_length = (1 << 10) | length
    cmd_type_data = ((packet_type & 1) << 7) | ((ack_type & 3) << 5) | (encrypt_type & 7)

    out = bytearray()
    out.append(SOF)
    out += ver_length.to_bytes(2, "little")
    out.append(crc8_header(bytes(out[:3])))
    out.append(sender & 0x1F)
    out.append(receiver & 0x1F)
    out += (seq & 0xFFFF).to_bytes(2, "little")
    out.append(cmd_type_data)
    out.append(cmd_set & 0xFF)
    out.append(cmd_id & 0xFF)
    out += payload
    out += crc16_duML(bytes(out)).to_bytes(2, "little")
    return bytes(out)


@dataclasses.dataclass(frozen=True)
class DumlFrame:
    raw: bytes
    sender: int
    receiver: int
    seq: int
    packet_type: int
    ack_type: int
    encrypt_type: int
    cmd_set: int
    cmd_id: int
    payload: bytes

    @property
    def hex(self) -> str:
        return self.raw.hex(" ")


def parse_frame(raw: bytes) -> DumlFrame:
    if len(raw) < 13:
        raise ValueError("frame too short")
    if raw[0] != SOF:
        raise ValueError("not a DUML 0x55 frame")

    advertised_len = int.from_bytes(raw[1:3], "little") & 0x03FF
    version = (int.from_bytes(raw[1:3], "little") >> 10) & 0x3F
    if version != 1:
        raise ValueError(f"unexpected DUML version {version}")
    if advertised_len != len(raw):
        raise ValueError(f"length mismatch: header={advertised_len}, actual={len(raw)}")
    if crc8_header(raw[:3]) != raw[3]:
        raise ValueError("header CRC8 mismatch")

    expected_crc = int.from_bytes(raw[-2:], "little")
    actual_crc = crc16_duML(raw[:-2])
    if actual_crc != expected_crc:
        raise ValueError(f"CRC16 mismatch: expected 0x{expected_crc:04x}, computed 0x{actual_crc:04x}")

    cmd_type_data = raw[8]
    return DumlFrame(
        raw=raw,
        sender=raw[4] & 0x1F,
        receiver=raw[5] & 0x1F,
        seq=int.from_bytes(raw[6:8], "little"),
        packet_type=(cmd_type_data >> 7) & 1,
        ack_type=(cmd_type_data >> 5) & 3,
        encrypt_type=cmd_type_data & 7,
        cmd_set=raw[9],
        cmd_id=raw[10],
        payload=raw[11:-2],
    )


class FrameReader:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> Iterable[DumlFrame]:
        self.buffer.extend(data)
        while True:
            try:
                sof_idx = self.buffer.index(SOF)
            except ValueError:
                self.buffer.clear()
                return

            if sof_idx:
                del self.buffer[:sof_idx]
            if len(self.buffer) < 4:
                return

            length = int.from_bytes(self.buffer[1:3], "little") & 0x03FF
            if length < 13 or length > 0x03FF:
                del self.buffer[0]
                continue
            if len(self.buffer) < length:
                return

            raw = bytes(self.buffer[:length])
            del self.buffer[:length]
            try:
                yield parse_frame(raw)
            except ValueError:
                # A bad 0x55 candidate may have consumed bytes. Put everything except
                # the first byte back so framing can resynchronize on a later 0x55.
                self.buffer = bytearray(raw[1:]) + self.buffer


def is_gimbal_calib_frame(frame: DumlFrame) -> bool:
    return (
        frame.sender == COMM_DEV_GIMBAL
        and frame.receiver == COMM_DEV_PC
        and frame.cmd_set == CMD_SET_ZENMUSE
        and frame.cmd_id == CMD_ID_GIMBAL_CALIB
    )


def is_reply_to(
    frame: DumlFrame,
    *,
    sender: int,
    seq: int,
    cmd_set: int,
    cmd_id: int,
) -> bool:
    return (
        frame.sender == sender
        and frame.receiver == COMM_DEV_PC
        and frame.seq == seq
        and frame.packet_type == PACKET_TYPE_RESPONSE
        and frame.cmd_set == cmd_set
        and frame.cmd_id == cmd_id
    )


def _ascii_until_nul(data: bytes) -> str:
    raw = data.split(b"\x00", 1)[0]
    if not raw:
        return ""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return ""
    if any(ord(ch) < 0x20 or ord(ch) > 0x7E for ch in text):
        return ""
    return text


def describe_general_serial_payload(payload: bytes) -> str:
    """Describe a General/Get Serial Number (0x00/0x51) response conservatively.

    The 2026-10-02 WM163 capture showed a leading status byte followed by a
    little-endian uint16 length and ASCII serial. Older DJI app code also shows a
    two-byte length-prefixed form without the leading status byte.
    """
    if len(payload) >= 3:
        status = payload[0]
        declared = int.from_bytes(payload[1:3], "little")
        if 0 < declared <= len(payload) - 3:
            serial_text = _ascii_until_nul(payload[3 : 3 + declared])
            if serial_text:
                return f"status=0x{status:02x}, serial={serial_text!r} (declared_len={declared})"

    if len(payload) >= 2:
        declared = int.from_bytes(payload[:2], "little")
        if 0 < declared <= len(payload) - 2:
            serial_text = _ascii_until_nul(payload[2 : 2 + declared])
            if serial_text:
                return f"serial={serial_text!r} (declared_len={declared})"
    return f"raw={payload.hex(' ')}"


GIMBAL_CHECK_DIAGNOSTICS = (
    (0, 40013, "GYROSCOPE_DATA_ERROR"),
    (1, 40014, "PITCH_ESC_DATA_ERROR"),
    (2, 40015, "ROLL_ESC_DATA_ERROR"),
    (3, 40016, "YAW_ESC_DATA_ERROR"),
    (4, 40012, "CONNECT_TO_FC_ERROR"),
    (7, 40021, "IMU_DATA_DISMATCH"),
    (10, 40004, "VIBRATION_ABNORMAL"),
    (11, 40007, "ROTATION_ERROR"),
    (13, 40008, "REACHED_ROLL_MECHANICAL_LIMIT"),
    (14, 40009, "REACHED_PITCH_MECHANICAL_LIMIT"),
    (16, 40010, "SECTORS_JUDGE_ERROR"),
    (24, 40011, "CALIBRATE_ERROR"),
)


def decode_gimbal_check_status(payload: bytes) -> tuple[int, list[tuple[int, str]]]:
    """Decode General/0xF1 DataGimbalGetPushCheckStatus.

    DJI's BytesUtil and DataBase parser treat the four status bytes as a
    little-endian 32-bit value. Modern decompiled DJI-family code maps bit 24 to
    whole-gimbal calibration error and bit 7 to IMU calibration mismatch.
    """
    if len(payload) < 4:
        raise ValueError("gimbal check-status payload is shorter than 4 bytes")
    value = int.from_bytes(payload[:4], "little")
    active = [
        (code, name)
        for bit, code, name in GIMBAL_CHECK_DIAGNOSTICS
        if value & (1 << bit)
    ]
    return value, active


def describe_gimbal_check_status_payload(payload: bytes) -> str:
    try:
        value, active = decode_gimbal_check_status(payload)
    except ValueError:
        return f"raw={payload.hex(' ')}"
    if not active:
        return f"flags=0x{value:08x}, diagnostics=none"
    diag = ", ".join(f"{code} {name}" for code, name in active)
    return f"flags=0x{value:08x}, diagnostics={diag}"


def describe_auto_cal_status_payload(payload: bytes) -> str:
    """Decode DataGimbalGetPushAutoCalibrationStatus.

    DJI's parser maps byte 0 to progress and byte 1 to status:
      1 = calibrating
      0 = successful
      any other value = failed/other
    """
    if len(payload) < 2:
        return f"raw={payload.hex(' ')}"
    progress = payload[0]
    status = payload[1]
    if status == 0:
        state = "SUCCESS"
    elif status == 1:
        state = "CALIBRATING"
    else:
        state = f"FAILED_OR_OTHER_{status}"
    return f"progress={progress}% status={status} ({state})"


def describe_common_device_id_payload(payload: bytes) -> str:
    """Decode raw General/GetSerialNum response for a selected FC identifier.

    Raw DUML response layout observed on WM163:
      ccode | uint16_le length | identifier bytes | optional trailing bytes

    DJI's DataCommonGetDeviceSerialNumber strips ccode first, then reads the
    two-byte length and identifier. Keep a hex fallback for non-ASCII IDs.
    """
    if not payload:
        return "empty payload"
    ccode = payload[0]
    if ccode not in (0x00, 0x01):
        return describe_ccode_payload(payload)
    if len(payload) < 3:
        return f"ccode=0x{ccode:02x}, raw={payload[1:].hex(' ')}"

    declared = int.from_bytes(payload[1:3], "little")
    available = payload[3:]
    if declared <= 0 or declared > len(available):
        return (
            f"ccode=0x{ccode:02x}, declared_len={declared}, "
            f"raw={available.hex(' ')}"
        )

    ident = available[:declared]
    extra = available[declared:]
    text_id = _ascii_until_nul(ident)
    if text_id and len(text_id) == len(ident.rstrip(b"\x00")):
        desc = f"ccode=0x{ccode:02x}, id={text_id!r}, declared_len={declared}"
    else:
        desc = (
            f"ccode=0x{ccode:02x}, binary_id={ident.hex()} "
            f"({declared} bytes)"
        )
    if extra:
        desc += f", extra={extra.hex(' ')}"
    return desc


def describe_ccode_payload(payload: bytes) -> str:
    if not payload:
        return "empty payload"
    code = payload[0]
    name = DJI_CCODES.get(code, "UNKNOWN")
    suffix = payload[1:]
    if suffix:
        return f"ccode=0x{code:02x} ({name}), data={suffix.hex(' ')}"
    return f"ccode=0x{code:02x} ({name})"


def describe_gimbal_serial_payload(payload: bytes) -> str:
    """Decode DataGimbalGetSerialParams using DJI RecvPack semantics.

    The first raw response byte is the DUML ccode and is stripped before DJI's
    DataGimbalGetSerialParams sees _recData. That class then returns bytes from
    _recData offset 2 onward as the serial field.
    """
    if not payload:
        return "empty payload"
    ccode = payload[0]
    data = payload[1:]
    if ccode not in (0x00, 0x01):
        return describe_ccode_payload(payload)
    if len(data) <= 2:
        return f"ccode=0x{ccode:02x}, data={data.hex(' ')}"
    header = data[:2]
    serial_bytes = data[2:]
    serial_text = _ascii_until_nul(serial_bytes)
    if serial_text:
        return (
            f"ccode=0x{ccode:02x}, header={header.hex(' ')}, "
            f"serial={serial_text!r}"
        )
    return (
        f"ccode=0x{ccode:02x}, header={header.hex(' ')}, "
        f"binary_serial_bytes={serial_bytes.hex()} ({len(serial_bytes)} bytes)"
    )


def describe_camera_sensor_id_payload(payload: bytes) -> str:
    """Decode DataCameraGetSensorID using DJI RecvPack semantics.

    DUML response byte 0 is the ccode. DJI RecvPack removes it before the
    DataCameraGetSensorID parser sees sensor type, ID length, and ID bytes.
    """
    if not payload:
        return "empty payload"
    ccode = payload[0]
    data = payload[1:]
    if ccode not in (0x00, 0x01):
        return describe_ccode_payload(payload)
    if len(data) < 2:
        return f"ccode=0x{ccode:02x}, data={data.hex(' ')}"
    sensor_type = data[0]
    declared = data[1]
    if declared > 0 and len(data) >= 2 + declared:
        raw_id = data[2 : 2 + declared]
        ascii_id = _ascii_until_nul(raw_id)
        if ascii_id:
            return (
                f"ccode=0x{ccode:02x}, sensor_type=0x{sensor_type:02x}, "
                f"id={ascii_id!r}, len={declared}"
            )
        return (
            f"ccode=0x{ccode:02x}, sensor_type=0x{sensor_type:02x}, "
            f"binary_id={raw_id.hex()} ({declared} bytes)"
        )
    return f"ccode=0x{ccode:02x}, raw_data={data.hex(' ')}"


def describe_active_status_payload(payload: bytes, version_hint: str) -> str:
    """Decode legacy ActiveStatus GET replies conservatively.

    v1.0 uses a fixed 10-byte serial beginning at offset 8.
    v1.1 uses a serial-length byte at offset 8 and serial bytes at offset 9.
    """
    if version_hint == "v1.1" and len(payload) >= 10:
        sn_len = payload[8]
        if 0 < sn_len <= 16 and len(payload) >= 9 + sn_len:
            serial_text = _ascii_until_nul(payload[9 : 9 + sn_len])
            if serial_text:
                return f"active=0x{payload[0]:02x}, serial={serial_text!r}, sn_len={sn_len}"

    if version_hint == "v1.0" and len(payload) >= 18:
        serial_text = _ascii_until_nul(payload[8:18])
        if serial_text:
            return f"active=0x{payload[0]:02x}, serial={serial_text!r}"

    if payload and payload[0] in DJI_CCODES:
        return describe_ccode_payload(payload)
    return f"raw={payload.hex(' ')}"


def describe_fc_device_info_payload(payload: bytes) -> str:
    """Describe FC/GetDeviceInfo (0x03/0x74) without assuming WM163 success codes."""
    if not payload:
        return "empty payload"
    status = payload[0]
    serial_text = _ascii_until_nul(payload[1:])
    if serial_text:
        after = payload[1 + len(serial_text) :]
        if after.startswith(b"\x00"):
            after = after[1:]
        suffix = f", extra={after.hex(' ')}" if after else ""
        return f"status=0x{status:02x}, serial={serial_text!r}{suffix}"
    return f"status=0x{status:02x}, raw={payload[1:].hex(' ')}"


def describe_payload(command_name: str, payload: bytes) -> str:
    if len(payload) == 0:
        return "empty payload"
    if len(payload) == 1:
        # WM163 field observation from public repair testing. Meaning is not yet
        # claimed; treating it as opaque avoids a false success/failure result.
        return f"WM163 one-byte reply 0x{payload[0]:02x} (meaning not yet confirmed)"
    if len(payload) == 2:
        legacy_pass = LEGACY_PASS.get(command_name)
        pair = (payload[0], payload[1])
        if legacy_pass and pair == legacy_pass:
            return f"two-byte progress 0x{pair[0]:02x} 0x{pair[1]:02x} (matches legacy completion marker)"
        return f"two-byte progress/status 0x{pair[0]:02x} 0x{pair[1]:02x}"
    return f"{len(payload)}-byte payload: {payload.hex(' ')}"


def next_sequence() -> int:
    # Same basic approach as upstream: centiseconds modulo 16 bits.
    return int(time.time() * 100) & 0xFFFF


def read_frames(ser_obj, reader: FrameReader, deadline: float) -> Iterable[DumlFrame]:
    while time.monotonic() < deadline:
        waiting = getattr(ser_obj, "in_waiting", 0) or 0
        chunk = ser_obj.read(waiting if waiting > 0 else 1)
        if chunk:
            yield from reader.feed(chunk)
        else:
            time.sleep(0.01)


def send_read_query(
    ser_obj,
    *,
    receiver: int,
    cmd_set: int,
    cmd_id: int,
    payload: bytes,
    timeout_seconds: float,
    verbose: int,
    label: str,
) -> Optional[DumlFrame]:
    seq = next_sequence()
    packet = build_packet(
        seq=seq,
        payload=payload,
        receiver=receiver,
        ack_type=ACK_AFTER_EXEC,
        cmd_set=cmd_set,
        cmd_id=cmd_id,
    )

    if verbose:
        print(f"{label} TX: {packet.hex(' ')}")

    ser_obj.reset_input_buffer()
    ser_obj.write(packet)
    ser_obj.flush()

    reader = FrameReader()
    deadline = time.monotonic() + timeout_seconds
    skipped = 0
    for frame in read_frames(ser_obj, reader, deadline):
        if is_reply_to(frame, sender=receiver, seq=seq, cmd_set=cmd_set, cmd_id=cmd_id):
            if verbose > 1:
                print(f"{label} RX: {frame.hex}")
            return frame
        skipped += 1
        if verbose > 2:
            print(f"{label} RX(other): {frame.hex}")
    if verbose > 1 and skipped:
        print(f"{label}: ignored {skipped} unrelated DUML frame(s) while waiting for the reply")
    return None


def run_identity_probe(port: str, baudrate: int, timeout_seconds: float, verbose: int) -> int:
    """Read-only identity/service probe for WM163 repair diagnostics."""
    if serial is None:
        print("ERROR: pyserial is required. Install with: python -m pip install pyserial", file=sys.stderr)
        return 2

    print(f"Model: {MODEL} ({PLATFORM})")
    print(f"Port: {port} @ {baudrate}")
    print("Mode: read-only identity probe; no serial number, pairing key, or calibration data is written.")

    responses = 0
    with serial.Serial(port, baudrate=baudrate, timeout=0.05) as ser_obj:
        # Confirmed on newer DJI captures: FC cmd-set 0x03 / cmd-id 0x74 returns
        # a status byte followed by the aircraft/FC serial string and model data.
        fc_info = send_read_query(
            ser_obj,
            receiver=COMM_DEV_FLYCONTROLLER,
            cmd_set=CMD_SET_FLYCONTROLLER,
            cmd_id=CMD_ID_FC_GET_DEVICE_INFO,
            payload=b"",
            timeout_seconds=timeout_seconds,
            verbose=verbose,
            label="FC device-info",
        )
        if fc_info is None:
            print("FC device-info: no matching response")
        else:
            responses += 1
            print(f"FC device-info: {describe_fc_device_info_payload(fc_info.payload)}")

        # ActiveStatus is the older DJI app's actual camera/gimbal activation-
        # identity path. These are GET selectors only; no activation data is written.
        for label, target_id, request_payload, version_hint in ACTIVE_STATUS_PROBES:
            frame = send_read_query(
                ser_obj,
                receiver=target_id,
                cmd_set=CMD_SET_GENERAL,
                cmd_id=CMD_ID_GENERAL_ACTIVE_STATUS,
                payload=request_payload,
                timeout_seconds=timeout_seconds,
                verbose=verbose,
                label=label,
            )
            if frame is None:
                print(f"{label}: no matching response")
            else:
                responses += 1
                print(f"{label}: {describe_active_status_payload(frame.payload, version_hint)}")

        # Builder-verified DJI camera identity path used by WM160-family camera
        # abstractions for the SDK SerialNumber key: CAMERA 0x02/0xB5 with four
        # zero request bytes. Read-only.
        frame = send_read_query(
            ser_obj,
            receiver=COMM_DEV_CAMERA,
            cmd_set=2,
            cmd_id=CMD_ID_CAMERA_GET_SENSOR_ID,
            payload=b"\x00\x00\x00\x00",
            timeout_seconds=timeout_seconds,
            verbose=verbose,
            label="camera sensor-id",
        )
        if frame is None:
            print("camera sensor-id: no matching response")
        else:
            responses += 1
            print(f"camera sensor-id: {describe_camera_sensor_id_payload(frame.payload)}")

        # Exact DJI app implementation: Gimbal/GetSerialParams uses Zenmuse/Gimbal
        # cmd 0x1F with request payload 00 02, and reads the serial from response
        # offset 2 onward. This is a read-only query.
        frame = send_read_query(
            ser_obj,
            receiver=COMM_DEV_GIMBAL,
            cmd_set=CMD_SET_ZENMUSE,
            cmd_id=CMD_ID_GIMBAL_GET_SERIAL_PARAMS,
            payload=b"\x00\x02",
            timeout_seconds=timeout_seconds,
            verbose=verbose,
            label="gimbal direct-serial",
        )
        if frame is None:
            print("gimbal direct-serial: no matching response")
        else:
            responses += 1
            print(f"gimbal direct-serial: {describe_gimbal_serial_payload(frame.payload)}")

        # Read the four FC identifier selectors defined by DJI's
        # DataCommonGetDeviceSerialNumber. Selector 0x01 was already capture-
        # validated on WM163; 0x02..0x04 remain read-only discovery probes.
        for label, selector, source_name in FC_DEVICE_ID_PROBES:
            frame = send_read_query(
                ser_obj,
                receiver=COMM_DEV_FLYCONTROLLER,
                cmd_set=CMD_SET_GENERAL,
                cmd_id=CMD_ID_GENERAL_GET_SN,
                payload=bytes([selector]),
                timeout_seconds=timeout_seconds,
                verbose=verbose,
                label=label,
            )
            if frame is None:
                print(f"{label}: no matching response ({source_name})")
            else:
                responses += 1
                print(
                    f"{label}: {describe_common_device_id_payload(frame.payload)} "
                    f"[{source_name}]"
                )

    print("NOTE: WM163 camera/gimbal ActiveStatus semantics are still being capture-validated; preserve raw -vv output.")
    print("FC BoardNum/ChipId/ModuleNum/DeviceNum probes are read-only; do not infer pairing from a value alone.")
    print("Do not post real aircraft or module serial numbers publicly.")
    return 0 if responses else 4


def run_gimbal_diagnostics(port: str, baudrate: int, seconds: float, verbose: int) -> int:
    """Passively read the gimbal General/0xF1 check-status push. Sends nothing."""
    if serial is None:
        print("ERROR: pyserial is required. Install with: python -m pip install pyserial", file=sys.stderr)
        return 2

    print(f"Model: {MODEL} ({PLATFORM})")
    print(f"Port: {port} @ {baudrate}")
    print(f"Mode: PASSIVE gimbal diagnostics for {seconds:.1f} seconds; no DUML request is transmitted.")

    reader = FrameReader()
    deadline = time.monotonic() + seconds
    seen: dict[bytes, int] = {}

    try:
        with serial.Serial(port, baudrate=baudrate, timeout=0.05) as ser_obj:
            ser_obj.reset_input_buffer()
            for frame in read_frames(ser_obj, reader, deadline):
                if (
                    frame.sender == COMM_DEV_GIMBAL
                    and frame.cmd_set == CMD_SET_GENERAL
                    and frame.cmd_id == CMD_ID_GENERAL_PUSH_CHECK_STATUS
                ):
                    seen[frame.payload] = seen.get(frame.payload, 0) + 1
                    if verbose:
                        print(
                            f"gimbal check-status: payload={frame.payload.hex(' ')}  "
                            f"{describe_gimbal_check_status_payload(frame.payload)}"
                        )
    except Exception as exc:
        if serial is not None and isinstance(exc, serial.SerialException):
            print(f"ERROR: could not open {port}: {exc}", file=sys.stderr)
            print("Another Windows process probably has the COM port open.", file=sys.stderr)
            print("Close DJI Assistant 2, serial terminals, and any other Python instance using the port, then retry.", file=sys.stderr)
            return 5
        raise

    if not seen:
        print("No gimbal General/0xF1 check-status push was observed.")
        return 3

    print("Observed gimbal check-status state(s):")
    for payload, count in sorted(seen.items(), key=lambda item: -item[1]):
        print(
            f"  {count:3d}x  payload={payload.hex(' ')}  "
            f"{describe_gimbal_check_status_payload(payload)}"
        )
    return 0


def run_fix_imu_40021_short(
    port: str,
    baudrate: int,
    precheck_seconds: float,
    reply_timeout_seconds: float,
    verbose: int,
) -> int:
    """Run the recovered WM163 short repair for gimbal diagnostic 40021.

    Flow recovered from DrGrey 1.5.2:
      1) require an active gimbal check-status bit 7 / 40021
      2) GIMBAL 0x04/0x36 payload 42 e9 7f 3f
      3) require the sequence-matched EMPTY response payload
      4) GENERAL 0x00/0x0B to BATTERY/PMU with empty payload to reboot

    The DrGrey USB capture shows its normal command transport uses ACK_AFTER_EXEC.
    This function deliberately does not send the 168-byte 0x36 matrix or the
    beta 0x51 -> 0x36 -> 0x68 read/push/save flow.
    """
    if serial is None:
        print("ERROR: pyserial is required. Install with: python -m pip install pyserial", file=sys.stderr)
        return 2

    print(f"Model: {MODEL} ({PLATFORM})")
    print(f"Port: {port} @ {baudrate}")
    print("Repair: bank-recovered short 40021 IMU fix")
    print(f"Write: GIMBAL 0x04/0x36 payload {IMU_FIX_SHORT_PAYLOAD.hex(' ')}")
    print("Success gate: exact sequence-matched EMPTY ACK before reboot")
    print("Reboot: GENERAL 0x00/0x0B to BATTERY/PMU")
    print("The 168-byte 0x36 matrix and beta 0x68 save flow are NOT used.")

    reader = FrameReader()
    try:
        with serial.Serial(port, baudrate=baudrate, timeout=0.05) as ser_obj:
            ser_obj.reset_input_buffer()

            print(f"Precheck: listening up to {precheck_seconds:.1f}s for active 40021...")
            deadline = time.monotonic() + precheck_seconds
            saw_check = False
            saw_40021 = False
            last_check: Optional[bytes] = None
            for frame in read_frames(ser_obj, reader, deadline):
                if (
                    frame.sender == COMM_DEV_GIMBAL
                    and frame.cmd_set == CMD_SET_GENERAL
                    and frame.cmd_id == CMD_ID_GENERAL_PUSH_CHECK_STATUS
                    and len(frame.payload) >= 4
                ):
                    saw_check = True
                    last_check = frame.payload
                    value, _active = decode_gimbal_check_status(frame.payload)
                    if verbose:
                        print(
                            f"Precheck status: payload={frame.payload.hex(' ')}  "
                            f"{describe_gimbal_check_status_payload(frame.payload)}"
                        )
                    if value & (1 << 7):
                        saw_40021 = True
                        break

            if not saw_check:
                print("REFUSED: no gimbal 0x00/0xF1 check-status push was observed.", file=sys.stderr)
                print("No write was sent.", file=sys.stderr)
                return 6
            if not saw_40021:
                print(
                    "REFUSED: diagnostic 40021 IMU_DATA_DISMATCH was not active"
                    + (f" (last status {last_check.hex(' ')})" if last_check else "")
                    + ".",
                    file=sys.stderr,
                )
                print("No write was sent.", file=sys.stderr)
                return 7

            seq = next_sequence()
            fix_packet = build_packet(
                seq=seq,
                payload=IMU_FIX_SHORT_PAYLOAD,
                receiver=COMM_DEV_GIMBAL,
                ack_type=ACK_AFTER_EXEC,
                cmd_set=CMD_SET_ZENMUSE,
                cmd_id=CMD_ID_GIMBAL_WRITE_IMU,
            )
            if verbose:
                print(f"FIX TX: {fix_packet.hex(' ')}")
            ser_obj.write(fix_packet)
            ser_obj.flush()

            fix_reply: Optional[DumlFrame] = None
            deadline = time.monotonic() + reply_timeout_seconds
            for frame in read_frames(ser_obj, reader, deadline):
                if is_reply_to(
                    frame,
                    sender=COMM_DEV_GIMBAL,
                    seq=seq,
                    cmd_set=CMD_SET_ZENMUSE,
                    cmd_id=CMD_ID_GIMBAL_WRITE_IMU,
                ):
                    fix_reply = frame
                    if verbose:
                        print(f"FIX RX: {frame.hex}")
                    break

            if fix_reply is None:
                print("REFUSED TO REBOOT: no matching 0x04/0x36 reply was received.", file=sys.stderr)
                return 8
            if fix_reply.payload != b"":
                print(
                    "REFUSED TO REBOOT: recovered WM163 flow expects an EMPTY 0x04/0x36 ACK; "
                    f"received payload={fix_reply.payload.hex(' ')}.",
                    file=sys.stderr,
                )
                return 9

            print("0x04/0x36 accepted: received the expected empty ACK.")

            reboot_seq = next_sequence()
            reboot_packet = build_packet(
                seq=reboot_seq,
                payload=b"",
                receiver=COMM_DEV_BATTERY,
                ack_type=ACK_AFTER_EXEC,
                cmd_set=CMD_SET_GENERAL,
                cmd_id=CMD_ID_GENERAL_REBOOT,
            )
            if verbose:
                print(f"REBOOT TX: {reboot_packet.hex(' ')}")

            written = ser_obj.write(reboot_packet)
            if written != len(reboot_packet):
                print(
                    f"WARNING: only {written}/{len(reboot_packet)} reboot bytes were written.",
                    file=sys.stderr,
                )
                return 10
            try:
                ser_obj.flush()
            except serial.SerialException:
                # A disappearing virtual COM immediately after the complete reboot
                # frame is expected behavior on some Windows/DJI service links.
                print("Reboot frame was fully written; COM dropped while the aircraft rebooted.")

            print("Reboot command sent to BATTERY/PMU.")
            print("Wait for the aircraft to reboot completely, then reconnect COM and reread gimbal diagnostics.")
            print("40021 must be verified after reconnect; 40011 may remain as a separate service-calibration fault.")
            return 0

    except Exception as exc:
        if serial is not None and isinstance(exc, serial.SerialException):
            print(f"ERROR: serial failure on {port}: {exc}", file=sys.stderr)
            return 5
        raise


def run_auto_cal_capture(port: str, baudrate: int, seconds: float, verbose: int) -> int:
    """Start DJI's normal gimbal auto-calibration and capture gimbal traffic.

    Builder-verified DJI Fly request:
      receiver GIMBAL(4), cmd_set 0x04, cmd_id 0x08, empty payload.
    This is distinct from the older service-tool subcommands that reuse 0x08
    with payload 01 (JointCoarse) or 02 (LinearHall).
    """
    if serial is None:
        print("ERROR: pyserial is required. Install with: python -m pip install pyserial", file=sys.stderr)
        return 2

    seq = next_sequence()
    packet = build_packet(
        seq=seq,
        payload=b"",
        receiver=COMM_DEV_GIMBAL,
        cmd_set=CMD_SET_ZENMUSE,
        cmd_id=CMD_ID_GIMBAL_CALIB,
        ack_type=ACK_BEFORE_EXEC,
    )

    print(f"Model: {MODEL} ({PLATFORM})")
    print(f"Port: {port} @ {baudrate}")
    print("Command: normal DJI gimbal Auto Calibration (0x04/0x08, empty payload)")
    print(f"Capture window: {seconds:.1f} seconds")
    print("This does NOT send JointCoarse, LinearHall, 0x04/0x68, or serial/pairing writes.")
    if verbose:
        print(f"TX: {packet.hex(' ')}")

    reader = FrameReader()
    counts: dict[tuple[int, int, int, int, bytes], int] = {}
    total = 0
    matched_reply = False
    final_auto_status: Optional[tuple[int, int]] = None

    with serial.Serial(port, baudrate=baudrate, timeout=0.05) as ser_obj:
        ser_obj.reset_input_buffer()
        ser_obj.write(packet)
        ser_obj.flush()

        started = time.monotonic()
        deadline = started + seconds
        for frame in read_frames(ser_obj, reader, deadline):
            if frame.sender != COMM_DEV_GIMBAL and frame.receiver != COMM_DEV_GIMBAL:
                continue

            total += 1
            key = (frame.sender, frame.receiver, frame.cmd_set, frame.cmd_id, frame.payload)
            counts[key] = counts.get(key, 0) + 1

            if is_reply_to(
                frame,
                sender=COMM_DEV_GIMBAL,
                seq=seq,
                cmd_set=CMD_SET_ZENMUSE,
                cmd_id=CMD_ID_GIMBAL_CALIB,
            ):
                matched_reply = True
                print(
                    "Auto-calibration reply: "
                    + (describe_ccode_payload(frame.payload) if frame.payload else "empty payload")
                )

            if (
                frame.sender == COMM_DEV_GIMBAL
                and frame.cmd_set == CMD_SET_ZENMUSE
                and frame.cmd_id == CMD_ID_GIMBAL_AUTO_CAL_STATUS
                and len(frame.payload) >= 2
            ):
                final_auto_status = (frame.payload[0], frame.payload[1])

            if verbose:
                elapsed = time.monotonic() - started
                decoded = ""
                if (
                    frame.sender == COMM_DEV_GIMBAL
                    and frame.cmd_set == CMD_SET_ZENMUSE
                    and frame.cmd_id == CMD_ID_GIMBAL_AUTO_CAL_STATUS
                ):
                    decoded = "  " + describe_auto_cal_status_payload(frame.payload)
                elif (
                    frame.sender == COMM_DEV_GIMBAL
                    and frame.cmd_set == CMD_SET_GENERAL
                    and frame.cmd_id == CMD_ID_GENERAL_PUSH_CHECK_STATUS
                ):
                    decoded = "  " + describe_gimbal_check_status_payload(frame.payload)
                print(
                    f"[{elapsed:6.2f}s] sender={frame.sender} receiver={frame.receiver} "
                    f"set=0x{frame.cmd_set:02x} id=0x{frame.cmd_id:02x} "
                    f"payload={frame.payload.hex(' ')}{decoded}"
                )
            if verbose > 1:
                print(f"  RAW: {frame.hex}")

    print(f"Captured {total} gimbal-related DUML frame(s).")
    if not matched_reply:
        print("No sequence-matched 0x04/0x08 reply was observed.")
    if final_auto_status is not None:
        progress, status = final_auto_status
        print(f"Auto-calibration final status: {describe_auto_cal_status_payload(bytes([progress, status]))}")
        if status == 0 and progress == 100:
            print("Result: DJI protocol reports gimbal Auto Calibration SUCCESS.")
        elif status == 1:
            print("Result: calibration was still reporting CALIBRATING when capture ended.")
        else:
            print("Result: DJI protocol did not report a successful final calibration state.")

    if counts:
        print("Summary (count sender->receiver set/id payload):")
        for (sender, receiver, cmd_set, cmd_id, payload), count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0][2], item[0][3])
        ):
            print(
                f"{count:4d}  {sender}->{receiver}  "
                f"0x{cmd_set:02x}/0x{cmd_id:02x}  {payload.hex(' ')}"
            )
    else:
        print("No gimbal-related frames were observed.")
    return 0


def run_passive_gimbal_capture(port: str, baudrate: int, seconds: float, verbose: int) -> int:
    """Passively listen for DUML frames involving the gimbal. Sends no packets."""
    if serial is None:
        print("ERROR: pyserial is required. Install with: python -m pip install pyserial", file=sys.stderr)
        return 2

    print(f"Model: {MODEL} ({PLATFORM})")
    print(f"Port: {port} @ {baudrate}")
    print(f"Mode: PASSIVE capture for {seconds:.1f} seconds; no DUML request is transmitted.")
    print("While this runs, reproduce the DJI Fly action/error you want to observe.")

    reader = FrameReader()
    deadline = time.monotonic() + seconds
    started = time.monotonic()
    counts: dict[tuple[int, int, int, int, bytes], int] = {}
    total = 0

    with serial.Serial(port, baudrate=baudrate, timeout=0.05) as ser_obj:
        ser_obj.reset_input_buffer()
        for frame in read_frames(ser_obj, reader, deadline):
            if frame.sender != COMM_DEV_GIMBAL and frame.receiver != COMM_DEV_GIMBAL:
                continue
            total += 1
            key = (frame.sender, frame.receiver, frame.cmd_set, frame.cmd_id, frame.payload)
            counts[key] = counts.get(key, 0) + 1
            if verbose:
                elapsed = time.monotonic() - started
                decoded = ""
                if (
                    frame.sender == COMM_DEV_GIMBAL
                    and frame.cmd_set == CMD_SET_GENERAL
                    and frame.cmd_id == CMD_ID_GENERAL_PUSH_CHECK_STATUS
                ):
                    decoded = "  " + describe_gimbal_check_status_payload(frame.payload)
                print(
                    f"[{elapsed:6.2f}s] sender={frame.sender} receiver={frame.receiver} "
                    f"set=0x{frame.cmd_set:02x} id=0x{frame.cmd_id:02x} "
                    f"payload={frame.payload.hex(' ')}{decoded}"
                )
            if verbose > 1:
                print(f"  RAW: {frame.hex}")

    print(f"Captured {total} gimbal-related DUML frame(s).")
    if not counts:
        print("No gimbal-related frames were observed.")
        return 0

    print("Summary (count sender->receiver set/id payload):")
    for (sender, receiver, cmd_set, cmd_id, payload), count in sorted(
        counts.items(), key=lambda item: (-item[1], item[0][2], item[0][3])
    ):
        print(
            f"{count:4d}  {sender}->{receiver}  "
            f"0x{cmd_set:02x}/0x{cmd_id:02x}  {payload.hex(' ')}"
        )
    return 0


def run_calibration(port: str, baudrate: int, command_name: str, monitor_seconds: float, verbose: int) -> int:
    if serial is None:
        print("ERROR: pyserial is required. Install with: python -m pip install pyserial", file=sys.stderr)
        return 2

    command_byte = CALIB_COMMANDS[command_name]
    seq = next_sequence()
    packet = build_packet(seq=seq, payload=bytes([command_byte]))

    print(f"Model: {MODEL} ({PLATFORM})")
    print(f"Command: {command_name} (0x{command_byte:02x})")
    print(f"Port: {port} @ {baudrate}")
    if verbose:
        print(f"TX: {packet.hex(' ')}")

    with serial.Serial(port, baudrate=baudrate, timeout=0.05) as ser_obj:
        ser_obj.reset_input_buffer()
        ser_obj.write(packet)
        ser_obj.flush()

        reader = FrameReader()
        first_deadline = time.monotonic() + 3.0
        got_reply = False

        for frame in read_frames(ser_obj, reader, first_deadline):
            if verbose > 1:
                print(f"RX: {frame.hex}")
            if not is_gimbal_calib_frame(frame):
                continue
            got_reply = True
            print(f"Reply: {describe_payload(command_name, frame.payload)}")
            break

        if not got_reply:
            print("No matching gimbal-calibration reply was received within 3 seconds.")
            print("The command may not have reached the gimbal; no calibration result is assumed.")
            return 3

        print("Calibration command was acknowledged at the DUML transport level.")
        print("Do not move the aircraft while the gimbal is calibrating.")

        end = time.monotonic() + monitor_seconds
        packet_count = 0
        legacy_complete = False
        last_payload: Optional[bytes] = None

        for frame in read_frames(ser_obj, reader, end):
            if verbose > 1:
                print(f"RX: {frame.hex}")
            if not is_gimbal_calib_frame(frame):
                continue
            packet_count += 1
            last_payload = frame.payload
            desc = describe_payload(command_name, frame.payload)
            if verbose:
                print(f"Progress {packet_count}: {desc}")
            if len(frame.payload) == 2 and tuple(frame.payload) == LEGACY_PASS.get(command_name):
                legacy_complete = True
                break

        print(f"Observed {packet_count} additional gimbal-calibration packet(s).")
        if legacy_complete:
            print("Result: calibration reached the legacy completion marker.")
            return 0

        if last_payload is not None:
            print(f"Last observed WM163 payload: {last_payload.hex(' ')}")
        print("Result: command was accepted, but WM163 completion semantics are not yet fully decoded.")
        print("Judge the repair by the gimbal's physical centering and a subsequent DJI Fly auto-calibration.")
        return 0


def replay_frames(command_name: str, frames: list[str]) -> int:
    reader = FrameReader()
    for item in frames:
        raw = bytes.fromhex(item)
        parsed = list(reader.feed(raw))
        if not parsed:
            print(f"No valid frame decoded from: {item}")
            continue
        for frame in parsed:
            print(frame.hex)
            print(f"  sender={frame.sender} receiver={frame.receiver} seq=0x{frame.seq:04x}")
            print(f"  packet_type={frame.packet_type} cmd_set=0x{frame.cmd_set:02x} cmd_id=0x{frame.cmd_id:02x}")
            print(f"  {describe_payload(command_name, frame.payload)}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Experimental repair-calibration helper for DJI Mini 3 (WM163) gimbals."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("-v", "--verbose", action="count", default=0)

    sub = parser.add_subparsers(dest="action", required=True)

    for name in ("joint-coarse", "linear-hall"):
        p = sub.add_parser(name, help=f"send the WM163 {name} gimbal calibration command")
        p.add_argument("--port", required=True, help="serial port exposed by the aircraft, e.g. COM3")
        p.add_argument("--baudrate", type=int, default=9600, help="serial baud rate (default: 9600)")
        p.add_argument(
            "--monitor-seconds",
            type=float,
            default=45.0 if name == "linear-hall" else 25.0,
            help="how long to collect calibration status packets",
        )
        p.add_argument(
            "--yes",
            action="store_true",
            help="required acknowledgement that this is experimental repair software",
        )

    flightlog = sub.add_parser(
        "flightlog-info",
        help="offline extraction of historical aircraft/camera identities from a DJI flight record",
    )
    flightlog.add_argument("path", help="path to DJIFlightRecord_*.txt")

    identify = sub.add_parser(
        "identify",
        help="read-only WM163 aircraft/camera/gimbal identity probe for post-replacement diagnostics",
    )
    identify.add_argument("--port", required=True, help="serial port exposed by the aircraft, e.g. COM23")
    identify.add_argument("--baudrate", type=int, default=9600, help="serial baud rate (default: 9600)")
    identify.add_argument(
        "--timeout-seconds",
        type=float,
        default=2.5,
        help="per-query response timeout (default: 2.5 seconds)",
    )

    diag = sub.add_parser(
        "diagnose-gimbal",
        help="passively decode DJI gimbal check-status diagnostics (General 0x00/0xF1)",
    )
    diag.add_argument("--port", required=True, help="serial port exposed by the aircraft, e.g. COM23")
    diag.add_argument("--baudrate", type=int, default=9600, help="serial baud rate (default: 9600)")
    diag.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        help="passive diagnostic capture duration (default: 5)",
    )

    fix_40021 = sub.add_parser(
        "fix-imu-40021-short",
        help="run the bank-recovered WM163 short repair for gimbal IMU diagnostic 40021",
    )
    fix_40021.add_argument("--port", required=True, help="serial port exposed by the aircraft, e.g. COM23")
    fix_40021.add_argument("--baudrate", type=int, default=9600, help="serial baud rate (default: 9600)")
    fix_40021.add_argument(
        "--precheck-seconds",
        type=float,
        default=5.0,
        help="time to require an active 40021 check-status bit before writing (default: 5)",
    )
    fix_40021.add_argument(
        "--reply-timeout-seconds",
        type=float,
        default=2.0,
        help="time to wait for the exact empty 0x04/0x36 ACK (default: 2)",
    )
    fix_40021.add_argument(
        "--yes",
        action="store_true",
        help="required acknowledgement before writing the WM163 IMU repair value and rebooting",
    )

    dry_fix = sub.add_parser(
        "dry-run-40021",
        help="build the recovered WM163 40021 short-fix and reboot packets without touching hardware",
    )
    dry_fix.add_argument("--seq", type=lambda s: int(s, 0), default=0x4000)

    auto_capture = sub.add_parser(
        "auto-cal-capture",
        help="start normal DJI gimbal auto-calibration over COM and capture resulting gimbal traffic",
    )
    auto_capture.add_argument("--port", required=True, help="serial port exposed by the aircraft, e.g. COM23")
    auto_capture.add_argument("--baudrate", type=int, default=9600, help="serial baud rate (default: 9600)")
    auto_capture.add_argument(
        "--seconds",
        type=float,
        default=60.0,
        help="capture duration after starting auto calibration (default: 60)",
    )
    auto_capture.add_argument(
        "--yes",
        action="store_true",
        help="required acknowledgement before starting gimbal auto calibration",
    )

    capture = sub.add_parser(
        "capture-gimbal",
        help="passively capture DUML traffic to/from the gimbal without transmitting requests",
    )
    capture.add_argument("--port", required=True, help="serial port exposed by the aircraft, e.g. COM23")
    capture.add_argument("--baudrate", type=int, default=9600, help="serial baud rate (default: 9600)")
    capture.add_argument(
        "--seconds",
        type=float,
        default=30.0,
        help="capture duration in seconds (default: 30)",
    )

    dry = sub.add_parser("dry-run", help="build a known request packet without touching hardware")
    dry.add_argument("command", choices=tuple(CALIB_COMMANDS))
    dry.add_argument("--seq", type=lambda s: int(s, 0), default=0xD839)

    replay = sub.add_parser("replay", help="decode one or more captured DUML hex frames")
    replay.add_argument("command", choices=tuple(CALIB_COMMANDS))
    replay.add_argument("frames", nargs="+")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.action == "dry-run":
        packet = build_packet(seq=args.seq, payload=bytes([CALIB_COMMANDS[args.command]]))
        print(packet.hex(" "))
        return 0

    if args.action == "replay":
        return replay_frames(args.command, args.frames)

    if args.action == "dry-run-40021":
        fix_packet = build_packet(
            seq=args.seq,
            payload=IMU_FIX_SHORT_PAYLOAD,
            receiver=COMM_DEV_GIMBAL,
            ack_type=ACK_AFTER_EXEC,
            cmd_set=CMD_SET_ZENMUSE,
            cmd_id=CMD_ID_GIMBAL_WRITE_IMU,
        )
        reboot_packet = build_packet(
            seq=(args.seq + 1) & 0xFFFF,
            payload=b"",
            receiver=COMM_DEV_BATTERY,
            ack_type=ACK_AFTER_EXEC,
            cmd_set=CMD_SET_GENERAL,
            cmd_id=CMD_ID_GENERAL_REBOOT,
        )
        print(f"FIX:    {fix_packet.hex(' ')}")
        print(f"REBOOT: {reboot_packet.hex(' ')}")
        return 0

    if args.action == "flightlog-info":
        return run_flightlog_info(args.path)

    if args.action == "identify":
        return run_identity_probe(args.port, args.baudrate, args.timeout_seconds, args.verbose)

    if args.action == "diagnose-gimbal":
        return run_gimbal_diagnostics(args.port, args.baudrate, args.seconds, args.verbose)

    if args.action == "capture-gimbal":
        return run_passive_gimbal_capture(args.port, args.baudrate, args.seconds, args.verbose)

    if args.action == "auto-cal-capture":
        if not args.yes:
            parser.error(
                "refusing to start gimbal auto calibration without --yes; "
                "remove propellers and place the DJI Mini 3 / WM163 on a level surface"
            )
        print("WARNING: This starts DJI's normal gimbal Auto Calibration over the COM service link.")
        print("Remove propellers and keep the aircraft stationary on a level surface.")
        return run_auto_cal_capture(args.port, args.baudrate, args.seconds, args.verbose)

    if args.action == "fix-imu-40021-short":
        if not args.yes:
            parser.error(
                "refusing to run the WM163 40021 repair without --yes; "
                "verify this aircraft is DJI Mini 3 / WM163 and remove the propellers"
            )
        print("WARNING: This performs the bank-confirmed WM163 short 40021 repair.")
        print("Remove propellers. Use only on DJI Mini 3 / WM163 with active diagnostic 40021.")
        return run_fix_imu_40021_short(
            args.port,
            args.baudrate,
            args.precheck_seconds,
            args.reply_timeout_seconds,
            args.verbose,
        )

    if not args.yes:
        parser.error(
            "refusing to send a hardware calibration command without --yes; "
            "verify the aircraft is a DJI Mini 3 / WM163, remove propellers, and place it on a level surface"
        )

    print("WARNING: Experimental WM163 repair calibration. This is not DJI-authorized service software.")
    print("Remove propellers and keep the aircraft stationary on a level surface.")
    return run_calibration(args.port, args.baudrate, args.action, args.monitor_seconds, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
