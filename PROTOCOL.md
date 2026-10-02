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
