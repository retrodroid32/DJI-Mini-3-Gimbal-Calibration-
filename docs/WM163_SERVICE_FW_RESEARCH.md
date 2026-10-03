# WM163 service-firmware research

This document tracks the recovered DJI Mini 3 / WM163 service-firmware path used by DrGrey 1.5.2.

## Confirmed

### Dedicated flasher

Recovered module:

`drgrey.mini3_service_flash`

Major routines:

- `Flasher.session_a`
- `Flasher.session_b`
- `Flasher._ctrl`
- `Flasher._stream`
- `Flasher._hold_for_commit`
- `load_loader`

### Session-A loader

Bundled file:

`drgrey/data/session_a_loader.bin`

Observed size:

`743120 bytes`

Expected MD5 embedded by DrGrey:

`72f7a3d3f40648c9e6c02583360c16b3`

The recovered loader hash matches this expected MD5.

The actual WM163 service image is not bundled in the recovered executable. DrGrey expects an external file named:

`mini3_service.bin`

Related catalog names include `mini3pro_service.bin` and `mini4k_service.bin`.

### Two-session flow

Recovered strings and control flow show:

```text
SESSION A
  -> deliver session_a_loader.bin
  -> loader boots
  -> poll until loader identity reports "WM163 UAV"

SESSION B
  -> loader handshake
  -> stream mini3_service.bin lockstep
  -> FINALIZE
  -> aircraft verifies and commits image
```

Recovered node labels:

- Session A node: `0xA9`
- Session B node: `0x01`

These are internal transport/node values in the dedicated flasher and must not be conflated with DUML device-type/module identifiers without proof.

### DJI GENERAL firmware-update family

Public DJI DUML dissectors independently identify:

- `0x00/0x07` Enter Loader
- `0x00/0x08` Update Confirm / Prepare
- `0x00/0x09` Update Transmit
- `0x00/0x0A` Update Finish / Verify
- `0x00/0x0B` Reboot Chip
- `0x00/0x0C` Get Device State

Recovered DrGrey labels include:

- `A/ENTER`
- `A/PREPARE`
- `A/CMD_0A`
- `A/CMD_0B`
- `A/REPORT_SIZE`
- `B/ENTER`
- `B/REPORT_SIZE`
- `B/FINALIZE`
- `CMDSET`
- `CHUNK`
- `CONFIRM`

This strongly supports that DrGrey wraps DJI's normal GENERAL firmware-update family, but the exact payload structures are not yet fully recovered.

### Lockstep transfer

Recovered messages show that streaming is ACK-gated. DrGrey aborts if a chunk is not acknowledged rather than advancing the stream.

### 40011 service-calibration path

Recovered WM163 catalog notes describe the bench-confirmed sequence:

```text
service firmware active
  -> GIMBAL 0x04/0x08 payload 01 (Joint Coarse)
  -> wait for 0x04/0x30 = 64 00
  -> do not end the calibration session
  -> GIMBAL 0x04/0x08 payload 02 (Linear Hall)
  -> wait for 0x04/0x30 = 64 00
  -> keep service session alive
  -> monitor GIMBAL 0x00/0xF1
  -> expected transition 00 00 00 01 -> 00 00 00 00
  -> persistent 40011 clears
```

Recovered UI text states that without service firmware the gimbal may mechanically calibrate but not validate, leaving the DJI Fly calibration error active.

### Corrected interpretation of 0x72 / 0x77

Values `0x72` and `0x77` observed near Advanced Calibration disassembly are not sufficient evidence for DUML commands `0x04/0x72` or `0x04/0x77`. In the Cython-generated native code they appear in a run of values used as internal traceback/source-line markers. Do not transmit these commands based on that evidence.

### Corrected interpretation of 0100 / 0306 / 1100

The recovered WM163 catalog records modules `0100 / 0306 / 1100` as verified against the aircraft report for the known-good service-firmware test.

Do not assume old DJI platform meanings for those identifiers, and do not treat them as direct flash destinations merely because older DJI firmware documentation used similar module names.

A live read-only version probe against DUML addresses corresponding to CAMERA.0, FLYC.6 and BATTERY.0 returned valid responses on the target WM163, but that does not prove those are the service-flash transport targets.

## Still unresolved before any service-firmware write

The following must be recovered from `Flasher._ctrl` and `Flasher._stream` before implementing a live flasher:

1. Exact Session-A ENTER payload
2. Exact Session-A PREPARE payload
3. REPORT_SIZE payload layout
4. Firmware CHUNK size
5. Per-chunk payload header
6. Sequence/index/offset encoding
7. Exact ACK/CONFIRM matching rules
8. Exact Session-A `0x0A` payload
9. Exact Session-A `0x0B` payload
10. Exact Session-B ENTER command and payload
11. Exact Session-B FINALIZE payload
12. Commit/reboot hold timing and success criteria
13. ARB selection mapping for WM163 service images
14. Full validation rules for `mini3_service.bin` (model, manifest, module table, sizes, MD5, IM*H headers)

No live service-firmware flashing should be added until these are decoded and tested offline.
