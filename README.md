# DJI Mini 3 (WM163) Gimbal Calibration Tool

Experimental, open-source repair tooling for the **DJI Mini 3 (non-Pro)** after a camera/gimbal assembly, gimbal motor, or flex-cable replacement.

This repository is intentionally scoped to **Mini 3 / WM163**. It does **not** contain or flash DJI firmware, does not bypass account binding, and does not modify flight-limit or geofencing settings. It sends the existing DJI DUML gimbal service-calibration command and records the aircraft's responses.

## Why this fork exists

The upstream `o-gs/dji-firmware-tools` service utility supports `JointCoarse` and `LinearHall` gimbal calibration on older models. Public Mini 3 repair testing shows that the Mini 3 accepts the same command and physically moves the gimbal, but its first reply has a **one-byte payload**. Upstream expects the older **two-byte** calibration response and therefore reports `Unrecognized response` even when the command reached the gimbal.

This WM163-focused tool:

- identifies the regular Mini 3 correctly as **WM163**;
- includes a **read-only identity probe** for aircraft/flight-controller, camera, and gimbal serial-response research after a replacement assembly;
- sends only gimbal calibration command `0x08` to the gimbal module;
- accepts and logs the observed one-byte WM163 reply without falsely assigning it a meaning;
- keeps collecting raw calibration/status packets for protocol research;
- recognizes the older two-byte completion markers only as a compatibility hint;
- includes a dry-run packet fixture matching the publicly observed Mini 3 packet exactly;
- includes a replay mode so captures can be decoded without connecting an aircraft.

## Status

**Experimental.** The transport-level request and the public one-byte Mini 3 acknowledgement are validated against a captured packet. The exact semantics of all WM163 progress/completion packets are not yet documented, so the tool deliberately reports `accepted / completion semantics unknown` rather than inventing a success status.

This is repair software, not flight software. Remove the propellers before testing and keep the aircraft stationary on a level surface.

## Model warning

- **DJI Mini 3 (non-Pro): WM163 — this project**
- DJI Mini 3 Pro: WM162 — **do not use Mini 3 Pro calibration firmware on a Mini 3**

The two models have different platform identifiers. This project does not flash service firmware at all.

## Requirements

- Windows, Linux, or macOS
- Python 3.10+
- `pyserial`
- a USB/serial interface exposed by the aircraft that accepts DJI DUML traffic

Install the dependency:

```text
python -m pip install -r requirements.txt
```

## First test: no hardware command

Verify that packet generation matches the known Mini 3 `JointCoarse` capture:

```text
python mini3_gimbal_cal.py dry-run joint-coarse --seq 0xD839
```

Expected output:

```text
55 0e 04 66 0a 04 39 d8 20 04 08 01 ee 6c
```

Decode one of the public Mini 3 replies:

```text
python mini3_gimbal_cal.py replay joint-coarse "55 0e 04 66 04 0a 39 d8 80 04 08 01 ff 78"
```

## Hardware use

1. Remove the propellers.
2. Put the Mini 3 on a solid, level surface.
3. Connect it to the computer and identify its COM/serial port.
4. Start with `JointCoarse`.
5. Do not touch the aircraft while the gimbal moves.
6. Only after `JointCoarse`, try `LinearHall` if needed.
7. Power-cycle the aircraft and retry the normal DJI Fly gimbal auto-calibration.

Example on Windows:

```text
python mini3_gimbal_cal.py -vv joint-coarse --port COM3 --yes
```

Then, if appropriate:

```text
python mini3_gimbal_cal.py -vv linear-hall --port COM3 --yes
```

The default serial speed is `9600`, matching upstream service-tool behavior. Override it only if your interface requires a different rate.

## Read-only identity probe

After a replacement camera/gimbal has been mechanically calibrated but DJI Fly still reports errors such as **40011** or **40021**, use the read-only identity probe before attempting any pairing or service-data write:

```text
python mini3_gimbal_cal.py -vv identify --port COM23
```

The probe currently sends only read requests:

- Flight Controller command set `0x03`, command `0x74` (device info / aircraft serial response);
- General command set `0x00`, command `0x32` (ActiveStatus GET) to the camera and gimbal using the GET selectors found in DJI app code;
- Gimbal command set `0x04`, command `0x1F` (GetSerialParams) with payload `00 02`, matching DJI app code exactly;
- General command set `0x00`, command `0x51` (Get Serial Number) to the flight controller.

The first live WM163 capture showed that `0x00/0x51` is useful on the flight controller but returned only `E0` from the camera and no matching gimbal response, so v0.3.0 no longer uses it as the default camera/gimbal identity probe.

WM163 camera/gimbal ActiveStatus response semantics are still being validated. The tool prints raw replies rather than claiming that two serials are paired or mismatched. It **does not** write a serial number, key, pairing state, calibration blob, or firmware.

Do not post real aircraft or module serial numbers publicly. Redact them when sharing logs.

## What to capture for WM163 protocol work

Run with `-vv` and save the console output. The most useful data is:

- every `TX:` packet;
- every `RX:` packet;
- which physical gimbal movement was occurring at that moment;
- whether the gimbal finished centered, left, or right;
- whether DJI Fly calibration still stops at 85% afterward.

Do not publish aircraft serial numbers, account information, or other personal identifiers in bug reports.

## Relationship to upstream

Protocol framing, CRC behavior, and the calibration command are derived from:

- `o-gs/dji-firmware-tools`
- upstream `comm_og_service_tool.py`
- upstream `comm_mkdupc.py`
- upstream `comm_dat2pcap.py`

The project is distributed under GPL-3.0-or-later to remain license-compatible with that work. See `UPSTREAM.md` and `LICENSE`.

## Safety / warranty

There is no warranty. A repair-calibration command can move the gimbal unexpectedly. Do not fly during testing. This tool intentionally does not flash firmware because using WM162/other-model service firmware on WM163 could damage the aircraft.


### v0.4.0 WM163 note

A live WM163 run showed `E3` as the first byte of both camera and gimbal ActiveStatus replies. In DJI app code, `E3` maps to `GET_PARAM_FAILED`, so those replies are now reported as command failures rather than opaque identity data.

v0.4.0 therefore adds the app-verified read-only gimbal serial request `0x04/0x1F` with payload `00 02`. The camera-specific `0x02/0x90` serial-number command is documented in modern DJI command maps, but its request layout has not yet been builder-verified, so this tool does not send it by default.


### v0.5.0 camera identity probe

DJI app code contains a second, builder-verified camera identity path:
`DataCameraGetSensorID` sends CAMERA command set `0x02`, command `0xB5`,
with payload `00 00 00 00`. DJI's WM160-family camera abstraction uses the
returned Sensor ID as the SDK camera `SerialNumber`.

v0.5.0 adds this exact read-only request to `identify`. It also labels the
WM163 gimbal `0x04/0x1F` response as a binary fingerprint when the returned
bytes are not printable ASCII instead of presenting them as an undecoded serial.


### v0.5.1 response-decoding correction

The first live `DataCameraGetSensorID` capture exposed an important framing detail:
the raw DUML payload begins with a one-byte completion code (`ccode`). DJI's own
`RecvPack` removes that byte before model-specific parsers see the response.

v0.5.1 mirrors that behavior:

- camera Sensor ID: raw `ccode | sensor_type | length | ID...`;
- gimbal GetSerialParams: raw `ccode | data...`, then the DJI class treats the
  first two data bytes as a header and the remaining bytes as the serial field.

Device-specific capture values are not used as test fixtures; tests use synthetic data.


### v0.6.0 flight-controller component identifiers

If no pre-replacement DJI Fly flight record is available, \`identify\` now follows
DJI's \`DataCommonGetDeviceSerialNumber\` read path and queries all four documented
selector values from the flight controller:

- \`01\` — \`BoardNum\`
- \`02\` — \`ChipId\`
- \`03\` — \`ModuleNum\`
- \`04\` — \`DeviceNum\`

These are General/GetSerialNum (\`0x00/0x51\`) **read requests only**. The tool
does not write any of these identifiers and does not claim that any one of them is
a camera/gimbal binding record. The purpose is to inventory the WM163 service
identity state before researching any association mechanism.


### v0.7.0 passive gimbal capture

`capture-gimbal` opens the DJI virtual COM port and only listens. It does not
transmit a DUML command. This is intended for WM163 cases where a command is known
to exist (for example gimbal calibration-data status) but its safe request layout
has not yet been capture-verified.

Example:

```text
python mini3_gimbal_cal.py -v capture-gimbal --port COM23 --seconds 30
```

Start the capture first, then reproduce the DJI Fly gimbal calibration/error while
the timer is running. The tool prints gimbal-related frames and a compact summary.

Also corrected the legacy DJI completion-code mapping: `0xE3` is
`INVALID_PARAM`; `0xE7` is `GET_PARAM_FAILED`.


### v0.8.0 historical flight-log identity extraction

The tool can now read the unencrypted identity metadata from DJI flight records
without a DJI API key:

```text
python mini3_gimbal_cal.py flightlog-info "DJIFlightRecord_2024-09-25_[16-12-06].txt"
```

For v13/v14 logs, DJI stores the Details metadata inside an XOR-obfuscated
AuxiliaryInfo block. The command decodes only that header metadata and reports
aircraft, camera, RC, battery, app, and product identifiers. It does not decrypt
the flight telemetry stream.

This is useful after a camera/gimbal replacement because an older flight record
can establish the camera identity that the aircraft used before the repair.
No device-specific serials are committed to this repository.


### v0.8.1 completion-code note

DJI's decompiled `Ccode` enum maps `0xFD` to `FLASH_FLUSHING`
(`ICameraVideoResolutionRes.VR_MAX` resolves to 253). The WM163 FC `ChipId`
and `ModuleNum` selector probes returned `0xFD` with zero-filled data, so the
tool now labels that code correctly instead of `UNKNOWN`. Those selector
responses are still not treated as useful camera/gimbal pairing evidence.
