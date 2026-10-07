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

## 40021 repair operation — capture-confirmed

The genuine Dr.Grey Fix Gimbal IMU Sensor 40021 operation confirms the
project's existing short repair path exactly.

Captured request:

```text
sender=0x0A
dst=0x04
seq=0x0064
flags=0x40
cmdset/cmd=04/36
payload=42 E9 7F 3F
```

Captured response about 186.7 ms later:

```text
sender=0x04
dst=0x0A
seq=0x0064
flags=0x80
cmdset/cmd=04/36
payload=<empty>
```

The empty ACK is therefore the genuine success condition.

About 1.64 seconds after the 04/36 request, Dr.Grey sends the reboot/power
transition command:

```text
sender=0x2A
dst=0x0B
seq=0x0065
flags=0x40
cmdset/cmd=00/0B
payload=00 01 00 00 00 00 00 00 00 00 00 00 00 00
```

The response is status 00 and aircraft shutdown/reboot activity follows.

Earlier observations of CmdSet 0x21 / CmdId 0x11 traffic were misattributed to
the repair. Those packets occur roughly 113-120 seconds later after reconnect
and are not the 40021 write itself.

Therefore the existing known-working project behavior is now independently
capture-confirmed:

```text
04/36 42 E9 7F 3F
-> require empty ACK
-> battery/PMU reboot
```

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


## Compiled Session-B transport probe — confirmed

Offline execution of the recovered CPython 3.14
`drgrey.transport.SerialTransport` against a fake serial backend established
the remaining Session-B transport behavior.

### send_and_collect(window_ms=0, read_timeout_ms=1)

With or without an immediately available response, the compiled helper did:

```text
write(packet)
flush()
return []
```

There was:

- no reset_input_buffer()
- no read()
- no response collection when window_ms=0

This is the path used by recovered `EngineTransport.write()` for Session-B
0x2A streaming records.

Therefore Session-B streaming must not use the Session-A gray-flasher
reset-before-write path.

### read_burst(budget_ms=120, read_timeout_ms=40)

With four bytes preloaded, the compiled helper performed:

```text
read(4096) timeout=0.040 -> 4 bytes
read(4096) timeout=0.040 -> empty
return [4-byte chunk]
```

With no data and `budget_ms=5, read_timeout_ms=1`:

```text
read(4096) timeout=0.001 -> empty
return []
```

Thus read_burst performs blocking reads and terminates on the first empty read;
the nominal budget is an overall bound, not a requirement to remain in the
loop for the entire budget.

### Project transport model after probe

The project now keeps three distinct operations:

1. gray/control xfer: reset RX -> write -> collect immediate response
2. Session-B stream write: write -> flush only
3. drain/read_burst: blocking reads until first empty read

The captured `F7` result remains accepted only for WM163 Session-B FINALIZE.
Generic control status acceptance remains unchanged.

Live flashing remains disabled.


## Offline state-machine validator — PASS

The genuine Dr.Grey USBPcap capture was validated by
`validate_wm163_service_state_machine.py`.

Observed result:

```text
WM163 Dr.Grey service-flash state machine: PASS
DUML frames found: 161649
A/CMD_0B -> ACK: 0.571 ms
A/CMD_0B -> loader probe: 1.977 ms
A/CMD_0B -> WM163 UAV response: 14.828 ms
A/CMD_0B -> B/ENTER: 57.809 ms
Session B ENTER -> FINALIZE: 54.438 s
B/FINALIZE -> F7 ACK: 1.576 ms
B/FINALIZE -> first commit probe: 19.537 ms
Commit probes / loader responses: 113 / 112
Commit-probe median interval: 0.512 s
Last good WM163 UAV response: +58.405 s
Last probe: +58.907 s
OFFLINE ONLY: no serial port was opened.
```

This confirms the capture-backed Service-FW control/state sequence from
A/CMD_0B through temporary-loader activation, Session B, F7 finalization, and
post-finalize commit monitoring.

Packet-byte parity and state-machine validation are now both established for
the captured genuine Dr.Grey Service-FW run.

Live flashing remains disabled pending review of the remaining calibration
workflow and any uncaptured runtime assumptions.


## Advanced Calibration validator — PASS

The genuine Dr.Grey capture was validated offline with
`validate_wm163_advanced_calibration.py`.

Observed:

```text
WM163 Dr.Grey Advanced Calibration: PASS
DUML frames found: 161649
Joint Coarse request seq: 0x0062
Joint Coarse -> 64 00: 84.127 s
64 00 -> Linear Hall request: 0.138 s
Linear Hall request seq: 0x0063
Linear Hall -> 64 00: 80.087 s
04/12 keepalives: 49
04/12 median interval: 3.282 s
Linear Hall -> first 00/F1 clear: 75.136 s
Final 64 00 -> confirmed 00/F1 clear: 0.049 s
```

No FLYC 00/01 keepalive was observed during this genuine WM163 Advanced
Calibration window. The capture-confirmed service-calibration keepalive is the
GIMBAL 04/12 packet with payload:

```text
E6 01 43 00 00 00 00 00 00 00 00 08
```
