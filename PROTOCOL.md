# WM163 gimbal-calibration protocol notes

This document records only behavior supported by captures or inherited from the GPL-licensed `o-gs/dji-firmware-tools` implementation. Unknown fields remain explicitly unknown.

## DUMLv1 frame used by gimbal calibration

The calibration command uses a DJI DUMLv1 `0x55` frame:

| Offset | Size | Meaning |
|---|---:|---|
| 0 | 1 | `0x55` start byte |
| 1 | 2 | version/length, little-endian |
| 3 | 1 | header CRC8 |
| 4 | 1 | sender module/index |
| 5 | 1 | receiver module/index |
| 6 | 2 | sequence number |
| 8 | 1 | packet type / ACK type / encryption |
| 9 | 1 | command set |
| 10 | 1 | command ID |
| 11 | N | payload |
| end-2 | 2 | CRC16, little-endian |

For the repair-calibration command:

- PC module = `0x0A`
- gimbal module = `0x04`
- Zenmuse command set = `0x04`
- gimbal calibration command ID = `0x08`
- `JointCoarse` request payload = `01`
- `LinearHall` request payload = `02`

## Known Mini 3 capture

A public Mini 3 repair capture contains:

Request:

```text
55 0e 04 66 0a 04 39 d8 20 04 08 01 ee 6c
```

Reply:

```text
55 0e 04 66 04 0a 39 d8 80 04 08 01 ff 78
```

Decoded reply fields:

- sender: gimbal (`4`)
- receiver: PC (`10`)
- sequence: `0xD839`
- response packet
- command set: `0x04`
- command ID: `0x08`
- payload: one byte, `01`

The older upstream parser expects a two-byte gimbal calibration response. The one-byte Mini 3 payload is why the older parser rejects this otherwise valid frame.

## Unknowns to resolve

The following are intentionally not claimed yet:

- whether the initial one-byte `01` is an acknowledgement, command echo, phase value, or status value;
- whether later Mini 3 progress frames are one or two bytes;
- the exact Mini 3 completion marker for `JointCoarse`;
- the exact Mini 3 completion marker for `LinearHall`;
- whether firmware versions change the progress payload format.

Until captures establish these meanings, the tool records the bytes and reports transport acceptance rather than declaring calibration success from the one-byte response alone.


## WM163 capture: post-command gimbal state traffic

A live WM163 JointCoarse run on 2026-10-02 confirmed the normal one-byte `0x01`
acknowledgement and also exposed recurring gimbal-originated Zenmuse `0x30` packets.
During the capture, two-byte payloads were repeatedly observed as `51 01` and later
changed to `64 00`.

Those values are recorded as **state observations only**. This project does not yet
label either pair as progress, pass, fail, or completion because no authoritative
WM163 field definition has been established.

## Read-only identity research

Two read requests are now implemented by the `identify` command:

- Flight Controller `cmd_set=0x03, cmd_id=0x74`: newer public DJI captures describe
  the response as status + aircraft/FC serial + model data.
- General `cmd_set=0x00, cmd_id=0x51`: public DJI protocol maps identify this as
  Get Serial Number. Older DJI app code sends request payload `01` and parses the
  response as a little-endian 16-bit string length followed by UTF-8 serial text.

For WM163, camera/gimbal implementation details remain provisional. The command is
therefore read-only and preserves raw response bytes. No Set Serial Number
(`0x00/0x50`) or pairing/encryption write is implemented.


## 2026-10-02 live WM163 identity capture

A live Mini 3 / WM163 capture established several useful points:

- FC `cmd_set=0x03, cmd_id=0x74` returned a normal status byte followed by the
  aircraft/flight-controller serial.
- FC General/Get Serial Number `0x00/0x51` returned
  `status + uint16_le length + serial + trailing bytes`.
- Camera General/Get Serial Number `0x00/0x51` returned only `E0`.
- Gimbal General/Get Serial Number `0x00/0x51` produced no matching reply.
- The flight-controller debug stream repeatedly reported
  `[D-GYRO_ACC] ... ns_ex_flag_error is 32`, and later emitted
  `[L-GYRO_ACC][0] mis cali time`, `flag_misalign fff0`, and NaN calibration
  values. These messages are recorded as evidence of an unresolved gyro/accelerometer
  calibration/service state, but they are not yet attributed specifically to the
  replacement gimbal IMU.

Because older DJI app code obtains camera/gimbal identity through General ActiveStatus
(`0x00/0x32`), v0.3.0 changes the default read-only identity probe to:

- camera: ActiveStatus GET Ver1_0 selector `01`;
- gimbal: ActiveStatus GET Ver1_1 selector `11`.

No ActiveStatus SET, serial-number write, encryption/pairing write, or calibration-data
write is implemented.


## 2026-10-02 ActiveStatus result

A second live WM163 capture returned `E3` for both camera and gimbal ActiveStatus
GET requests. DJI app `Ccode` maps decimal 227 / `0xE3` to
`GET_PARAM_FAILED`. Therefore these ActiveStatus replies are failures, not serial
or pairing data.

The same capture again returned the correct aircraft/FC serial from both FC
device-info and General/Get Serial Number.

### App-verified gimbal serial query

Decompiled DJI app code contains `DataGimbalGetSerialParams`:

- receiver: GIMBAL (4)
- command set: GIMBAL / Zenmuse (4)
- command ID: `0x1F`
- request payload: `00 02`
- response serial: bytes starting at response offset 2

v0.4.0 adds this exact read-only request to `identify`.

Modern command maps also name camera command `0x02/0x90` as
`uav_camera_serial_number_req`, but the request payload layout is not
builder-verified in the available app source, so it is not sent automatically.


## 2026-10-02 direct gimbal identity capture

WM163 replied successfully to GIMBAL `0x04/0x1F` / payload `00 02` with
a two-byte prefix followed by a 15-byte non-ASCII value. The available DJI app
class expects ASCII on older products, so v0.5.0 records the WM163 value as an
opaque binary fingerprint. Its persistence across repeated boots still needs to
be tested before calling it a serial number.

## Builder-verified camera Sensor ID query

`DataCameraGetSensorID` in DJI app code:

- receiver: CAMERA (1)
- command set: CAMERA (2)
- command ID: `0xB5`
- request payload: `00 00 00 00`
- response layout: byte 0 sensor type, byte 1 ID length, bytes 2.. ID

The WM160 camera abstraction uses this returned Sensor ID to satisfy the SDK
`SerialNumber` getter. v0.5.0 adds this read-only probe for WM163 testing.


## Response framing correction

DJI's `RecvPack` consumes a one-byte `ccode` on response packets for commands
that require completion codes before assigning the remaining bytes to `_recData`.
The standalone Python tool sees the raw DUML payload, so it must remove this byte
explicitly before applying DJI model-class offsets.

For `DataCameraGetSensorID`, the WM163 live response decoded successfully after
this correction as:

- ccode: OK
- sensor type: one byte
- ID length: 14 bytes
- camera/sensor identifier: printable ASCII

For `DataGimbalGetSerialParams`, the same correction leaves a two-byte data
header followed by a 14-byte non-ASCII serial field. The project records that
field as opaque binary serial bytes until its WM163 encoding is understood.

No device-specific serials or captured identifiers are documented here.


## FC component-identifier selectors

DJI's public/decompiled \`DataCommonGetDeviceSerialNumber\` implementation defines
four one-byte selectors for General/GetSerialNum (\`cmd_set=0x00, cmd_id=0x51\`):

1. \`BoardNum\`
2. \`ChipId\`
3. \`ModuleNum\`
4. \`DeviceNum\`

For WM160-family behavior the request is sent directly to the flight controller.
A WM163 live capture has already validated selector \`01\`; v0.6.0 adds read-only
probes for selectors \`02\` through \`04\` as well. Results are treated as
inventory data only, not proof of camera/gimbal pairing.


## Completion-code correction

Review of DJI's decompiled `Ccode` enum corrected an earlier label:
`0xE3` is `INVALID_PARAM`, not `GET_PARAM_FAILED`. The latter is `0xE7`.
The WM163 camera/gimbal ActiveStatus captures therefore show that the older
ActiveStatus request form is rejected as an invalid parameter on this platform.

## Passive capture before probing 0x04/0x68

Modern DJI command maps name GIMBAL `0x04/0x68` as
`uav_gimbal_cali_data_exist_req/rsp`, which is highly relevant to a persistent
gimbal-calibration error. However, the available static references do not expose
a verified request-payload layout. v0.7.0 therefore does not guess a payload.
Instead, `capture-gimbal` passively records gimbal DUML traffic so the command
can be observed during normal DJI Fly behavior before any active probe is added.


## Historical camera identity from DJI flight records

DJI v13/v14 flight records keep their Details metadata in an AuxiliaryInfo block
starting at the 100-byte prefix boundary. That block uses DJI's CRC64-derived XOR
obfuscation but does not require the online AES keychain used for the telemetry
record stream.

The Details layout used by DJI places, for version >5:

- product type at offset 271
- aircraft name at 280..311
- aircraft serial at 312..327
- camera serial at 328..343
- RC serial at 344..359
- battery serial at 360..375
- app platform at 376
- app version bytes at 377..379

v0.8.0 adds an offline `flightlog-info` command based on this layout. Historical
camera identity is treated as evidence of what hardware identity was present at
the time of the flight; it is not by itself proof of the location or format of
any later camera/mainboard pairing record.


## WM163 selector 0xFD result

The FC `ChipId` and `ModuleNum` selector probes returned raw ccode `0xFD`
plus zero-filled payloads. In DJI's decompiled `Ccode` enum, `0xFD` is
`FLASH_FLUSHING`. This is recorded as the protocol result only; it does not
establish that flash activity is actually occurring, nor does it identify a
camera/gimbal binding field.


## PC-only normal auto calibration

Static DJI Fly reverse engineering identifies `DataGimbalAutoCalibration` as:

- receiver: GIMBAL (4)
- command set: GIMBAL (0x04)
- command id: 0x08
- request payload: empty

Status is returned through the gimbal auto-calibration status path. This command
shares command ID 0x08 with older service-tool calibration subcommands but differs
by payload: normal Auto Calibration is empty, JointCoarse uses 01, and LinearHall
uses 02.

v0.9.0 adds `auto-cal-capture` for Mini 3 units whose USB service boot prevents
a simultaneous normal controller/DJI Fly connection. It starts only the normal
auto-calibration request and then captures gimbal traffic. It does not guess the
payload for name-only `0x04/0x68 uav_gimbal_cali_data_exist_req`.


## WM163 normal Auto Calibration success capture

A live Mini 3 / WM163 capture of the builder-verified empty-payload
`0x04/0x08` request returned an immediate successful command acknowledgement
and then `0x04/0x30` AutoCalibrationStatus pushes.

DJI's `DataGimbalGetPushAutoCalibrationStatus` reads:

- byte 0: progress
- byte 1: status

DJI SDK abstraction logic treats status 1 as calibrating, status 0 as calibration
successful, and any other status as not successful. The WM163 capture reached
`64 00` (100%, success) at about 18 seconds.

No `0x04/0x68 uav_gimbal_cali_data_exist_req/rsp` traffic was observed during
the normal Auto Calibration capture, so that name-only command is not assumed to
be part of the normal calibration path.


## Direct mapping of WM163 40011 + 40021

The normal Auto Calibration capture repeatedly included:

`GIMBAL -> PC, cmd_set 0x00, cmd_id 0xF1, payload 80 00 00 01`.

DJI command tables identify General `0xF1` as `GetPushCheckStatus`.
`DataGimbalGetPushCheckStatus` parses the first four bytes little-endian and
defines bit 7 as `getIMUCalibrateMatchStatus()` and bit 24 as
`getGimbalWholeCalibrateIsError()`. The current DJI-family implementation uses
bit 24 directly for whole-gimbal calibration error.

DJI's `GimbalDiagnosticsHandler` maps those predicates to:

- `IMU_DATA_DISMATCH` = 40021
- `CALIBRATE_ERROR` = 40011

For payload `80 00 00 01` the 32-bit value is `0x01000080`, so exactly those
two diagnostic bits are set. This provides protocol-level confirmation of the
same two errors shown by DJI Fly after reboot, despite the separate
AutoCalibrationStatus stream reaching `64 00` (100%, success).


## Recovered WM163 short repair for diagnostic 40021

DrGrey 1.5.2 static constants and embedded documentation identify a bank-confirmed
Mini 3 / WM163 short repair for an active 40021:

- target: GIMBAL / receiver type 4
- request: `0x04/0x36`
- payload: `42 e9 7f 3f`
- accepted result: response packet with zero payload bytes
- then reboot: GENERAL `0x00/0x0B`, empty payload, BATTERY/PMU receiver type 11
- verify only after the aircraft reboots and reconnects

A USBPcap capture of DrGrey's Basic Calibration and device-info operations showed
all 15 distinct host request forms in that session using DUML ACK_AFTER_EXEC.
That includes its GIMBAL `0x04/0x08` JointCoarse request, which appeared on the
wire with cmd-type byte `0x40`. v0.12.0 therefore uses ACK_AFTER_EXEC for both
the recovered short write and the reboot request.

The repair command is fail-closed:

- it requires a live `0x00/0xF1` gimbal status with bit 7 set;
- it sends only the four-byte WM163 payload;
- it requires an exact sequence-matched empty response from `0x04/0x36`;
- it does not reboot after no reply or a non-empty reply;
- it does not send the 168-byte matrix form;
- it does not send the beta `0x04/0x68` save command.

The separate bit-24 / diagnostic 40011 state is not claimed to be repaired by this
flow.


## v0.12.1 factory-state hold

Later recovery material for `drgrey.ui.factory_fix` indicates that DrGrey's
model-specific short 40021 routine reads factory state, enters/ensures a required
factory/service state, performs the short 0x36 operation, validates/commits it,
and finally restores/cleans up factory state.

The exact DUML request(s), target(s), payload(s), and response semantics used by
`_read_factory_state` and `_set_factory` remain unresolved in the static
high-level reconstruction. Therefore the previously implemented live short write
is disabled until those transactions are verified from packet capture or direct
binary decoding. The dry-run packet builder is retained.
