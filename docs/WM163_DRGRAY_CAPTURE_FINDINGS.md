# WM163 genuine Dr.Grey USB capture findings

Source: genuine Dr.Grey run on DJI Mini 3 / WM163 captured through USBPcap
during:

1. Service FW install
2. Advanced Calibration
3. Fix Gimbal IMU Sensor 40021

This document records packet-capture observations. It supersedes earlier
inferences where they conflict.

## Safety status

**Live flashing from this project is disabled.**

The capture proved protocol differences in the previous reconstruction.
Do not re-enable live Session A/B until the project's offline-generated trace
matches the genuine capture for the relevant transfer.

## USB transport

The DJI virtual COM path was captured on USBPcap2.

Observed direction:

- host -> aircraft: endpoint 0x02
- aircraft -> host: endpoint 0x83

The pre-service baseline contained normal DUML traffic and repeated GIMBAL
00/F1 payload:

```text
00 00 00 01
```

consistent with the active 40011 calibration error before repair.

## Session A — genuine capture

Destination/raw node: 0xA9
CmdSet: 0x00
Initial sequence: 0x4900

Observed control sequence:

```text
A/ENTER       seq 0x4900 cmd 0x07
A/PREPARE     seq 0x4901 cmd 0x0C
A/REPORT_SIZE seq 0x4902 cmd 0x08
A/DATA        seq 0x4903..0x4BF9 cmd 0x09
A/VERIFY      seq 0x4BFA cmd 0x0A
A/CMD_0B      seq 0x4BFB cmd 0x0B
```

### Critical correction: DATA field is chunk index

Captured A/DATA prefixes:

```text
chunk 0: 00 00 00 00 00 D4 03 ...
chunk 1: 00 01 00 00 00 D4 03 ...
chunk 2: 00 02 00 00 00 D4 03 ...
```

The 32-bit field is therefore the **chunk index**, not the byte offset.

The previous reconstruction incorrectly sent byte offsets
(0, 980, 1960, ...). This is a strong explanation for the earlier behavior
where all DATA records ACKed but A/VERIFY rejected with status F5.

### A/VERIFY

Captured payload:

```text
00 72 F7 A3 D3 F4 06 48 C9 E6 C0 25 83 36 0C 16 B3
```

That is:

```text
00 + MD5(session_a_loader.bin).digest()
```

with loader MD5:

```text
72f7a3d3f40648c9e6c02583360c16b3
```

The genuine run received success status 00.

The genuine Session-A transfer completed in roughly 2.8 seconds.

## Session B — genuine capture

### Critical correction: DATA field is per-file chunk index

Captured 0x2A DATA prefixes:

```text
02 00 00 00 00 ...
02 01 00 00 00 ...
02 02 00 00 00 ...
```

The 24-bit field is a per-file **chunk index**, not a byte offset.

### Critical correction: one sequence gap after every START record

For each file, the genuine tool sends START, leaves the next sequence unused,
then begins DATA.

Example:

```text
START  seq 0x3024
       seq 0x3025 unused
DATA   seq 0x3026
```

There are seven transferred files in the validated WM163 V30 package, so the
final sequence is shifted by +7 relative to the earlier reconstruction.

Captured:

```text
B/FINALIZE seq = 0xFF8A
```

Previous incorrect prediction:

```text
0xFF83
```

## Advanced Calibration — capture-confirmed

The genuine run confirms the service calibration sequence:

```text
GIMBAL 04/08 payload 01    Joint Coarse
GIMBAL 04/30 ...           progress
GIMBAL 04/30 64 00         phase complete

GIMBAL 04/08 payload 02    Linear Hall
GIMBAL 04/30 ...           progress
GIMBAL 04/30 64 00         phase complete
```

The second phase occurs without ending the service calibration session.

The genuine gimbal keepalive is:

```text
CmdSet 04
CmdId  12
Payload:
E6 01 43 00 00 00 00 00 00 00 00 08
```

Observed cadence is approximately 3.3 seconds. The project already contained
this exact payload; it is now capture-confirmed.

During final validation, GIMBAL 00/F1 changed from:

```text
00 00 00 01
```

to:

```text
00 00 00 00
```

The Dr.Grey UI simultaneously reported calibration complete and validated by
the gimbal.

## 40021 repair operation

The later Fix Gimbal IMU Sensor 40021 operation is distinct from the
04/08 calibration flow.

The capture shows CmdSet 0x21 / CmdId 0x11 traffic addressed to multiple DJI
nodes, including raw targets observed as:

```text
0x12
0xC3
0x01
0x04
0x02
```

Do not assign undocumented semantics to those targets until their request and
response payloads are fully decoded.

The existing known-working 40021 repair path must remain unchanged unless a
capture-backed correction is proven.

## Project changes derived from this capture

- Session-A DATA now uses chunk index.
- Session-B DATA now uses per-file chunk index.
- Session-B sequence accounting includes one unused sequence after each START.
- Known WM163 V30 B/FINALIZE sequence is now 0xFF8A.
- Existing WM163 04/12 keepalive is marked capture-confirmed.
- Live service flashing remains disabled pending full offline trace parity.


## Offline generated trace vs genuine capture

The project-generated offline trace from the exact known WM163 V30 package and
Session-A loader was compared directly against the genuine Dr.Grey USBPcap
capture.

Generated trace:

```text
total rows: 53861
Session A rows: 764
Session B rows: 53097
Session-B sequence-gap rows: 7
Session-B transmitted packets: 53090
B/FINALIZE: 0xFF8A
```

### Session A

All **764/764** generated Session-A packets were found in the genuine capture
**byte-for-byte and in order**, including:

```text
A/ENTER
A/PREPARE
A/REPORT_SIZE
759 A/DATA records
A/VERIFY
A/CMD_0B
```

This confirms the corrected chunk-index semantics and all encoded Session-A
packet bytes for the captured known-good run.

### Session B

Of **53,090** generated transmitted Session-B packets, **53,064** were found in
the genuine capture byte-for-byte and in order.

The only 26 generated packets not present in the capture occur in two
contiguous 13-packet DATA runs:

```text
0x7660 .. 0x766C
0xB960 .. 0xB96C
```

Exact matching resumes immediately at 0x766D and 0xB96D respectively and remains
synchronized afterward through B/FINALIZE.

Because the genuine Dr.Grey flash completed successfully and the packet stream
re-synchronizes exactly after both gaps, these two runs are treated as likely
capture omissions rather than evidence of a generated-protocol mismatch.

### Current parity conclusion

For every transmitted packet that is present in the capture, the current
offline generator matches the genuine Dr.Grey packet **byte-for-byte** through
the full Session-A/Session-B sequence, including the captured sequence gaps and
final B/FINALIZE at 0xFF8A.

Live flashing remains disabled until this result is reviewed together with
remaining state-machine/timing/re-enumeration behavior. Packet-byte parity alone
does not prove that a live implementation is safe.


## State-machine timing and B/FINALIZE behavior

Additional timing analysis of the genuine Dr.Grey capture established:

### A -> temporary loader -> B

```text
A/CMD_0B TX                         t = 0
A/CMD_0B ACK status 00              +0.571 ms
loader probe 00/01 -> dst 0x28      +1.977 ms
"WM163 UAV Ver.A" response          +14.828 ms
B/ENTER TX                          +57.809 ms
```

Therefore the genuine tool begins Session B only about 43 ms after receiving
the temporary-loader identity response.

This is consistent with a short ~40 ms quiet read/drain rather than waiting the
entire nominal 200 ms drain budget.

### B control timings

```text
B/ENTER TX -> ACK                   ~24.6 ms
B/REPORT_SIZE TX -> ACK             ~203.8 ms
B/ENTER -> B/FINALIZE TX            ~54.44 s
```

### B/FINALIZE response is F7

The genuine captured final exchange is:

```text
TX:
dst=0x01 seq=0xFF8A cmdset=0x00 cmd=0x0A
payload=17 zero bytes

RX:
src=0x01 dst=0x2A seq=0xFF8A response cmdset=0x00 cmd=0x0A
payload=F7
```

Dr.Grey does **not** treat this F7 as a fatal rejection. It immediately enters
the post-finalize commit/power-off monitoring phase and ultimately reports:

```text
Service firmware loaded and committed.
```

Therefore the earlier generic assumption that every control ACK must have an
empty payload or leading 0x00 is not valid for this Session-B FINALIZE path.

### Post-finalize commit monitoring

The first commit probe is sent about 19.5 ms after B/FINALIZE TX.

Dr.Grey then sends the 00/01 probe to dst 0x28 approximately every 0.512 s.
Successful responses contain the temporary-loader identity string:

```text
WM163 UAV Ver.A
```

The last successful captured response occurs about 58.4 seconds after
B/FINALIZE. A further probe at about 58.9 seconds receives no normal response,
followed by USB shutdown/disconnect activity several seconds later.

These observations must be incorporated into the live orchestration model
before live flashing can be considered.
