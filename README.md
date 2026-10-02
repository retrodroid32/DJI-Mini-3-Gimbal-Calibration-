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
