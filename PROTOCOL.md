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
