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

### Transport behavior — corrected

Session A uses the recovered blocking/ACK-oriented control and stream helpers. Session B's custom `0x2A` file records do **not** block on a matching ACK for every record: they are written through the pipelined transport path, advance one shared 16-bit sequence counter, service receives with `drain(15)` every 64 records, and perform `drain(300)` when the streaming iterator is exhausted. The later sections contain the exact recovered behavior and supersede older lockstep wording.

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


## Native entry-point map recovered from the Cython method table

The PE method table for `drgrey.mini3_service_flash.cp314-win_amd64.pyd` resolves the relevant Python-visible methods to these native implementations:

- `encode` -> `0x180002960`
- `Frame.is_response` -> `0x180004180`
- `decode_all` -> `0x1800044C0`
- `match_ack` -> `0x180006450`
- `EngineTransport.xfer` -> `0x1800074E0`
- `EngineTransport.write` -> `0x180007B90`
- `EngineTransport.drain` -> `0x180008130`
- `Flasher._ctrl` -> `0x1800090B0`
- `Flasher._stream` -> `0x18000A980`
- `Flasher.session_a` -> `0x18000BCE0`
- `Flasher.session_b` -> `0x18000DCD0`
- `Flasher._hold_for_commit` -> `0x180012F20`
- `load_loader` -> `0x1800148D0`

This mapping comes from direct PE string-pointer/method-table xrefs and is stronger than proximity-based disassembly guesses.

### Additional native observations

`Flasher.session_a` contains repeated immediate use of `0xA9`, which independently corroborates the recovered Session-A node value.

`Flasher.session_b` contains an immediate `0x01` late in the flow, but this alone is not enough to assign semantic meaning without tracing the surrounding Python object construction.

A `0x80` immediate also appears in `session_b`; its current use is not proven to be the firmware chunk size. Do not label it as `CHUNK=0x80` until the call target and argument semantics are decoded.

The current reverse-engineering priority is therefore:

1. decode `match_ack` field comparisons;
2. decode `EngineTransport.xfer` request/response contract;
3. trace the values constructed by `_ctrl`;
4. identify the slice/packing operation inside `_stream`;
5. only then assign chunk size, offset/index header and finalize payload semantics.


## Recovered transport constants

Direct reconstruction of Cython's module-initialization integer table resolves the following exported constants:

- `CMDSET = 0x00`
- `HOST = 0x2A`
- `FLAG_REQ_ACK = 0x40`
- `FLAG_RESP = 0x80`
- `CHUNK = 980` bytes (`0x03D4`)
- `CONFIRM = "FLASH-MINI3"`

These values are no longer inferred from nearby immediates. Cython constructs a 37-entry Python integer table at module initialization. The relevant indexes decode as:

- index 0 -> `0x00` -> `CMDSET`
- index 15 -> `0x2A` -> `HOST`
- index 17 -> `0x40` -> `FLAG_REQ_ACK`
- index 20 -> `0x80` -> `FLAG_RESP`
- index 29 -> `0x03D4` -> `CHUNK`

The `CONFIRM` value points to recovered Cython string index 12, which is exactly `FLASH-MINI3`.

This corrects an earlier ambiguity: the `0x80` immediate is the response flag, **not** the firmware chunk size. DrGrey's exported chunk constant is 980 bytes.

### Cython integer table recovered

The 37 module integers, in construction order, are:

```text
00 01 02 03 04 07 08 09 0A 0B 0C 0D 0F 14 28 2A
3C 40 55 77
0080 008C 0096 00B4 00C8 00FF 012C 0190 01F4 03D4
03E8 0FA0 3022 3692 4900 8408 FFFF
```

Not every integer has been assigned a semantic name yet.

## Recovered method argument signatures

The Cython argument-name table at the start of both native functions resolves:

```text
Flasher._ctrl(self, cmd_id, payload, dst, seq, what, timeout_ms)
Flasher._stream(self, cmd_id, payload, dst, seq, what, timeout_ms)
```

This is based on exact string-object addresses used by the Cython argument parser:

- `self`
- `cmd_id`
- `payload`
- `dst`
- `seq`
- `what`
- `timeout_ms`

This strongly indicates that `_ctrl` and `_stream` share the same packet-level call contract, with the distinction in how the payload is transmitted/acknowledged.


## Recovered ACK matching semantics

`match_ack(bufs, want_seq, want_cmd)` decodes received frames and returns a frame only when all of the following are true:

1. `frame.cmd_id == want_cmd`
2. `frame.is_response()` is true
3. `frame.seq == want_seq`

`Frame.is_response()` tests the recovered `FLAG_RESP = 0x80`.

Therefore DrGrey's lockstep ACK gate is at least:

```python
(frame.flags & 0x80) != 0
and frame.cmd_id == want_cmd
and frame.seq == want_seq
```

No source/destination equality check has yet been proven inside `match_ack` itself.

## Session-A call reconstruction

Because the recovered native signature is:

```text
Flasher._ctrl(self, cmd_id, payload, dst, seq, what, timeout_ms)
```

and the Session-A call sites pass six positional values total (omitting the default timeout), the argument arrays can be mapped directly.

### A/ENTER

High-confidence native reconstruction:

```python
self._ctrl(
    cmd_id=0x07,
    payload=b"\x00" * 9,
    dst=0xA9,
    seq=<runtime sequence>,
    what="A/ENTER",
)
```

Evidence:

- command object resolves to Cython integer-table index 5 = `0x07`
- payload object resolves to recovered bytes-string index 228 = nine zero bytes
- destination is constructed from immediate `0xA9`
- label is the exact recovered string `A/ENTER`

This matches DJI GENERAL `0x00/0x07` Enter Loader, but the wire arguments above come from DrGrey's native call site rather than from the public name alone.

### A/PREPARE

High-confidence native reconstruction:

```python
self._ctrl(
    cmd_id=0x0C,
    payload=b"\x00",
    dst=0xA9,
    seq=<runtime sequence>,
    what="A/PREPARE",
)
```

Evidence:

- command object address maps to integer-table index 10 = `0x0C`
- payload object maps to recovered bytes-string index 226 = one zero byte
- destination is `0xA9`
- label is exactly `A/PREPARE`

This is intentionally documented as DrGrey's actual `A/PREPARE` call. It must not be rewritten to public command `0x08` merely because DJI's generic command table calls `0x08` "Update Confirm / Prepare".

### A/REPORT_SIZE

The call site strongly identifies command object integer-table index 6 = `0x08` and label `A/REPORT_SIZE`, with destination `0xA9`.

The exact payload is still being traced backward through the preceding `struct.pack` construction and is not yet asserted here.

### A/CMD_0A

The call site resolves the command object to integer-table index 8 = `0x0A`, destination `0xA9`, and label `A/CMD_0A`.

Exact payload still unresolved.

### A/CMD_0B

The call site resolves the command object to integer-table index 9 = `0x0B`, destination `0xA9`, and label `A/CMD_0B`.

Exact payload still unresolved.


## Session-A payload reconstruction

### A/REPORT_SIZE

The native construction is now recovered:

```python
payload = (
    b"\x00"
    + struct.pack("<I", len(loader))
    + b"\x00" * 6
    + b"\x01\x00"
)

self._ctrl(
    cmd_id=0x08,
    payload=payload,
    dst=0xA9,
    seq=<runtime sequence>,
    what="A/REPORT_SIZE",
)
```

Total payload length is 13 bytes.

The `<I` format comes from recovered string index 14, and the loader length is obtained from the Session-A loader object immediately before the `struct.pack` call.

### A/CMD_0A

The native code constructs an MD5 digest of the Session-A loader and sends:

```python
payload = b"\x00" + hashlib.md5(loader).digest()

self._ctrl(
    cmd_id=0x0A,
    payload=payload,
    dst=0xA9,
    seq=<runtime sequence>,
    what="A/CMD_0A",
)
```

The payload is therefore 17 bytes: one leading zero byte plus the 16-byte binary MD5 digest.

This is consistent with DrGrey independently validating the bundled loader against its expected MD5 before use.

### A/CMD_0B

The payload construction is now narrowed to:

```text
00 01 + struct.pack(...) + ASCII "DEADBEEF"
```

The command is `0x0B`, destination `0xA9`, label `A/CMD_0B`.

The packed numeric field is still being traced and is not asserted yet.

## Session-B control reconstruction

Session B explicitly sets its destination/node value to `0x01`.

### B/ENTER

```python
self._ctrl(
    cmd_id=0x07,
    payload=b"\x00" * 9,
    dst=0x01,
    seq=<runtime sequence>,
    what="B/ENTER",
)
```

### B/REPORT_SIZE

The native construction mirrors Session A but uses a different two-byte trailer:

```python
payload = (
    b"\x00"
    + struct.pack("<I", total_size)
    + b"\x00" * 6
    + b"\x01\x02"
)

self._ctrl(
    cmd_id=0x08,
    payload=payload,
    dst=0x01,
    seq=<runtime sequence>,
    what="B/REPORT_SIZE",
)
```

Total payload length is 13 bytes.

The Session-A trailer is `01 00`; the Session-B trailer is `01 02`.

### B/FINALIZE

The recovered call is:

```python
self._ctrl(
    cmd_id=0x0A,
    payload=b"\x00" * 17,
    dst=0x01,
    seq=<runtime sequence>,
    what="B/FINALIZE",
)
```

This is stronger than the earlier generic assumption that Session B merely uses a standard empty Update-Finish packet: DrGrey sends an explicit 17-byte all-zero payload.


## Session-A stream and reboot payload — fully recovered

### A/DATA stream

Session A slices the loader into chunks of at most the recovered exported `CHUNK = 980` bytes.

For each chunk, DrGrey constructs:

```python
payload = (
    b"\x00"
    + struct.pack("<I", offset)
    + struct.pack("<H", len(chunk))
    + chunk
)

self._stream(
    cmd_id=0x09,
    payload=payload,
    dst=0xA9,
    seq=<runtime sequence>,
    what=f"A idx={...}",
)
```

Therefore the Session-A `0x09` data payload has a 7-byte header:

```text
offset  size  meaning
0       1     0x00
1       4     uint32_le image offset
5       2     uint16_le chunk length
7       N     chunk bytes (N <= 980)
```

The `<H` field is proven to be `len(chunk)`: the native code calls `len()` on the sliced chunk object immediately before `struct.pack("<H", ...)`.

### A/CMD_0B — exact payload

The previously unresolved packed numeric field is constructed from Cython integer-table index 30, value `0x03E8 = 1000`.

DrGrey therefore sends:

```python
payload = (
    b"\x00\x01"
    + struct.pack("<I", 1000)
    + b"DEADBEEF"
)

self._ctrl(
    cmd_id=0x0B,
    payload=payload,
    dst=0xA9,
    seq=<runtime sequence>,
    what="A/CMD_0B",
)
```

Exact 14-byte payload:

```text
00 01 E8 03 00 00 44 45 41 44 42 45 45 46
```

This completes the known Session-A wire payload sequence:

```text
0x07 A/ENTER       9 zero bytes
0x0C A/PREPARE     00
0x08 A/REPORT_SIZE 00 + <I loader_size> + 6*00 + 01 00
0x09 A/DATA        00 + <I offset> + <H length> + chunk (<=980 B)
0x0A A/CMD_0A      00 + MD5(loader).digest()
0x0B A/CMD_0B      00 01 + <I 1000> + "DEADBEEF"
```


## Session-B loader-specific file protocol

Session B does **not** reuse Session A's `0x09` firmware-data records for the service-image contents.

After `B/ENTER` and `B/REPORT_SIZE`, DrGrey sends loader-specific records using:

```text
cmd_id = 0x2A
dst    = 0x01
```

The temporary WM163 loader interprets the first payload byte as a record type.

### File iteration model

The native loop iterates `(name, blob)` pairs.

For each item:

- `name` is encoded to bytes with `name.encode()`
- `blob` is the file/module content
- data chunks use the recovered exported `CHUNK = 980` bytes

### Record type 0x01 — FILE START

The native payload construction is:

```python
name_bytes = name.encode()

payload = (
    b"\x01"
    + struct.pack("<I", len(blob))
    + bytes([len(name_bytes) + 1])
    + name_bytes
    + b"\x00" * 4
)
```

Important implementation detail: Cython constructs a one-element Python list containing `len(name_bytes)+1` and passes that list to `bytes(...)`. Therefore this field is one length byte; it is **not** a zero-filled byte array of that size.

The file-start record is sent with command `0x2A`, destination `0x01`, and label `B file-start %s`.

### Record type 0x02 — FILE DATA

The native loop is equivalent to:

```python
for offset in range(0, len(blob), CHUNK):
    chunk = blob[offset:offset + CHUNK]
```

The 32-bit packed offset is explicitly sliced to its first three bytes before being appended to the payload:

```python
payload = (
    b"\x02"
    + struct.pack("<I", offset)[:3]
    + b"\x00"
    + chunk
)
```

Therefore the file-data header is exactly five bytes:

```text
02 | offset[7:0] | offset[15:8] | offset[23:16] | 00
```

followed by at most 980 file bytes.

For these data records the native code calls `encode(...)` directly with:

- `cmd_id = 0x2A`
- payload above
- `dst = 0x01`
- runtime sequence
- `flags = FLAG_REQ_ACK = 0x40`

and then writes the encoded packet through `transport.write(...)`.

This differs from the file-start/file-end control path and is the reason the exact Session-B ACK/window loop still needs to be decoded separately.

### Record type 0x03 — FILE END

The native code computes the MD5 of the current `blob` and sends:

```python
payload = (
    b"\x03"
    + hashlib.md5(blob).digest()
)
```

Total payload length: 17 bytes.

The file-end record uses command `0x2A`, destination `0x01`, and label `B file-end %s`.

### Session-B record summary

```text
START:
01
+ uint32_le(file_size)
+ uint8(len(filename_bytes)+1)
+ filename_bytes
+ 00 00 00 00

DATA:
02
+ uint24_le(offset)
+ 00
+ data[0..980]

END:
03
+ MD5(file_bytes).digest()
```

The recovered Session-B stream is pipelined: START/DATA/END records share one evolving sequence counter, the receive side is serviced every 64 records with `drain(15)`, and iterator exhaustion triggers `drain(300)`. There is no per-record blocking `xfer()` gate for these custom `0x2A` records. Exact exception propagation on a failed low-level write/drain remains under reconstruction.


## Candidate WM163 service package supplied 2026-10-03

A user-supplied file named `mini3(4).bin` was inspected offline only. It is a valid POSIX tar archive and its signed configuration manifest identifies:

```text
device = wm163
firmware formal = 30.00.0100
release version = 30.00.0100
antirollback = 0
antirollback_ext = cn:0
enforce = 0
```

This is significant because `30.00.0100` is one of the formal-version strings statically recovered from `drgrey.service_fw`, and DrGrey expects the Mini 3 service image under the external catalog name `mini3_service.bin`.

The archive contains these six signed modules:

| Order | Module | Version | Size |
|---:|---|---|---:|
| 1 | 0905 | 01.00.01.27 | 10,390,912 |
| 2 | 0306 | 03.04.11.31 | 1,760,032 |
| 3 | 1200 | 01.10.02.15 | 56,352 |
| 4 | 1100 | 10.75.00.17 | 94,720 |
| 5 | 0105 | 12.07.00.11 | 245,824 |
| 6 | 0100 | 01.55.00.45 | 39,459,264 |

Offline validation performed against the package manifest:

- every archive member size equals the manifest `size`
- every whole signed-module MD5 equals the manifest `md5`
- every module begins with the expected ASCII magic `IM*H`
- the `IM*H` header's stored total-size field equals the actual signed file size for all six modules
- the manifest provides an explicit component order: `0905 -> 0306 -> 1200 -> 1100 -> 0105 -> 0100`

The complete archive hashes are:

```text
MD5    7895303d687618766cc06efe405cf082
SHA256 c6c88d49c6da0026a9498d07f04a3db41ef8a8d650a5bbaf22de574dc8e60b26
```

This file is now the strongest candidate seen for the previously missing WM163 `mini3_service.bin`, but **it is not yet approved for live flashing**. Before any write path is enabled, DrGrey's exact `service_fw` parser/selection logic still needs to confirm that formal version `30.00.0100`, ARB `0`, this module set, and this container layout are accepted for the target aircraft state.

A separately supplied archive named `V20.00.0800_wm162_dji_system(1).bin` identifies itself as `wm162` and must not be used on the WM163 Mini 3.


## External corroboration and V20 WM163 search — 2026-10-03

Public sources now provide useful corroboration for the role of the supplied V30 package, but they do **not** yet establish that V30 is the service image used for 40021.

### Legacy DJI module-role references

The public `o-gs/dji-firmware-tools` wiki documents the older DJI module families as:

- `m0306` — flight-controller application
- `m1100` — battery firmware
- `m1200` — ESC firmware
- `m0100` — video-processing application
- `m0105` — historically named `CAMLCPUFw.bin`
- `m0400` — gimbal master control on older architectures

The supplied WM163 V30 package contains `0905, 0306, 1200, 1100, 0105, 0100` and no standalone `0400`. Those legacy roles are useful architectural clues, but they are **not proof that every identifier retained exactly the same hardware ownership on WM163**.

### AW-TOOL evidence

AW-TOOL's current public download page advertises a Mini 3 calibration firmware with:

```text
version: V30.00.0100
purpose: gimbal tilt / 4011 calibration
size: 50800 KB
```

This aligns closely with the inspected WM163 package:

```text
device = wm163
formal = 30.00.0100
archive size = 52,019,200 bytes
```

This is strong external corroboration that the supplied V30 package is a Mini 3 gimbal-calibration/service image for 40011-class repair.

### 40011 versus 40021

Do not extend the AW-TOOL claim beyond what the page says. Its public description names Mini 3 `V30.00.0100` for `4011` calibration; it does not explicitly identify that image as the 40021 pairing/IMU-repair image.

Separate repair-community sources do explicitly advertise or discuss Mini 3 workflows for both `40011` and `40021`:

- gzksoft forum thread title: `大疆mini3标定消错40011、40021固件软件` (Mini 3 calibration/error-clearing 40011/40021 firmware/software)
- another indexed Chinese repair archive groups Mini 3 material under `新版本-40011 40021消错`
- 4PDA Mini 3 discussions independently describe using service/calibration firmware for persistent gimbal-calibration errors, while users discuss 40021 as a separate repair condition

These sources support the existence of a Mini 3 service workflow covering both errors, but none of the public pages inspected exposes the exact WM163 V20 manifest or proves that V30 and the 40021 workflow use the same service image.

### Narrowed missing artifact

The high-value search target remains:

```text
V20.00.0100_wm163_dji_system.bin
```

or, preferably, only its signed manifest:

```text
wm163.cfg.sig
```

A manifest alone is sufficient to compare formal version, ARB fields, module order, module versions, sizes and MD5 entries against the validated V30.00.0100 package.

As of this search, no public GitHub code result or indexed web result exposed that exact V20 WM163 file or `wm163.cfg.sig`. Do not invent a V20 module table from nearby Mini 3 Pro / WM162 packages.


## Duplicate V30 package confirmation and exact V20 evidence — 2026-10-03

A second user-supplied file, `mini3(5).bin`, was inspected offline.

It is **byte-for-byte identical** to the previously validated V30 WM163 package:

```text
size   52,019,200 bytes
MD5    7895303d687618766cc06efe405cf082
SHA256 c6c88d49c6da0026a9498d07f04a3db41ef8a8d650a5bbaf22de574dc8e60b26
```

Its embedded signed manifest again identifies:

```text
device = wm163
formal = 30.00.0100
release = 30.00.0100
antirollback = 0
```

Therefore `mini3(5).bin` is not the missing V20 image; it is another copy of the already validated V30.00.0100 service/calibration package.

### Exact public evidence that V20 WM163 exists

A MavicPilots Mini 3 repair thread dated July 25, 2026 explicitly states:

```text
firmware calibration V20.00.0100_wm163
```

The poster then identifies the aircraft and target as:

```text
Mini 3 and the Gimbal
```

A separate indexed 4PDA Mini 3 discussion independently names:

```text
V20.00.0100_wm163_dji_system
```

and says it was obtained specifically because it enables Mini 3 gimbal calibration.

This is substantially stronger evidence than filename inference: `V20.00.0100_wm163_dji_system` is a real Mini 3 / WM163 calibration firmware package reported in active repair use.

The public sources inspected still do not expose its signed `wm163.cfg.sig` or module table, so a direct V20-vs-V30 manifest comparison remains pending.


## Commit-hold static analysis update — 2026-10-03

The recovered `Flasher._hold_for_commit` wrapper at `0x180012F20` dispatches to the native implementation beginning at approximately `0x1800131F0`. The implementation is large and performs repeated Python-object/method calls; it is **not** a single `sleep(150)` or a trivial one-packet loop.

Additional PE/import correlation confirms that the routine repeatedly performs dynamic method lookups/calls and object comparisons during the hold period. This reinforces the earlier conclusion that the post-`B/FINALIZE` phase actively services transport traffic while the aircraft verifies/commits firmware.

A search of the available conversation/library artifacts found **no actual Mini 3 service-flash USBPcap/pcapng capture**. Existing material includes Basic Calibration captures and textual service-flash reverse-engineering notes, but not a packet capture covering `B/FINALIZE -> _hold_for_commit()`.

Therefore the live service flasher remains intentionally blocked at this exact boundary:

```text
B/FINALIZE (known)
    |
    v
_hold_for_commit() (active traffic, exact packet semantics not yet proven)
    |
    v
safe reboot/return to production firmware
```

Do not replace this missing behavior with a guessed keepalive or fixed sleep. A real DrGrey service-flash capture, or a fully resolved static reconstruction of the method calls inside `_hold_for_commit`, is still required before enabling live service flashing.


## ARB / selector correction and method mapping — 2026-10-03

Further direct inspection of the recovered binaries corrected an earlier assumption.

### Native method entry points recovered from `service_fw.cp314-win_amd64.pyd`

The Cython method table maps:

```text
parse_version       -> 0x180001580
arb_allows          -> 0x180002400
select_service_fw   -> 0x180002980
has_service_fw      -> 0x180004700
```

These addresses are now suitable anchors for static control-flow recovery.

### Important correction

A fresh byte-level search of the recovered `service_fw.cp314-win_amd64.pyd`, its disassembly report, and strings report did **not** find the following as plain embedded strings:

```text
20.00.0800
20.07.0700
30.00.0100
WM163
WM162
WA1617
mini3_service.bin
mini3pro_service.bin
mini4k_service.bin
```

Therefore previous notes describing these as directly embedded in the `service_fw` binary should not be used as proof of the selector's internal mapping.

They may originate from higher-level catalog/UI/recovered-context data or may be constructed indirectly at runtime. Until the `select_service_fw` and `arb_allows` control flow is decoded, do **not** hard-code a model/version-to-service-image mapping based on those strings alone.

The validated V30 package itself remains independently proven as:

```text
device = wm163
formal = 30.00.0100
```

from its own signed manifest and hashes. This correction only affects claims about how DrGrey's `service_fw` module selects/accepts service images.


## Cython transport wrapper mapping and sibling hold routine — 2026-10-03

Further static correlation of the Cython method table in `mini3_service_flash.cp314-win_amd64.pyd` recovered exact native wrapper entry points:

```text
encode                  -> 0x180002960
decode_all              -> 0x1800044C0
match_ack               -> 0x180006450
EngineTransport.xfer    -> 0x1800074E0
EngineTransport.write   -> 0x180007B90
EngineTransport.drain   -> 0x180008130
Flasher._ctrl           -> 0x1800090B0
Flasher._stream         -> 0x18000A980
Flasher.session_b       -> 0x18000DCD0
Flasher._hold_for_commit wrapper -> 0x180012F20
Flasher._hold_for_commit native  -> 0x1800131F0
```

These addresses provide concrete call-graph anchors for resolving the final post-finalize behavior.

A second important finding is that `mini3pro_service_flash.cp314-win_amd64.pyd` contains its own:

```text
Flasher.finalize
Flasher.monitor_install
Flasher._hold_for_commit
```

with:

```text
Mini 3 Pro _hold_for_commit wrapper -> 0x180017230
Mini 3 Pro _hold_for_commit native  -> 0x180017500
```

The Mini 3 Pro routine has the same broad Cython control-flow shape as the Mini 3 implementation: argument parsing wrapper followed by a large native loop performing repeated object/method lookups, calls, comparisons and cleanup. This creates a useful sibling implementation for differential analysis of the commit phase.

The Mini 3 method table also confirms the wrapper addresses above by direct `PyMethodDef`-style entries rather than inference from nearby disassembly.

Next static target:

1. normalize/diff Mini 3 `0x1800131F0` against Mini 3 Pro `0x180017500`;
2. identify the shared dynamic call that resolves to transport `write/xfer/drain`;
3. reconstruct its Python argument vector;
4. recover the exact encoded destination/cmdset/cmdid/payload/sequence values;
5. only then implement the post-finalize hold in the native WM163 flasher.

No live service-flash entrypoint should be enabled until that argument vector is fully proven.


## Mini 3 vs Mini 3 Pro commit-loop differential — 2026-10-03

The Mini 3 Pro service-flash method table was mapped further:

```text
Flasher.finalize          -> 0x180012F00
Flasher.monitor_install   -> 0x180013700
Flasher._hold_for_commit  -> 0x180017230 wrapper
native hold body          -> ~0x180017500
```

The WM163 Mini 3 hold body remains:

```text
Flasher._hold_for_commit  -> 0x180012F20 wrapper
native hold body          -> ~0x1800131F0
```

A normalized instruction-stream comparison was performed after stripping absolute branch/data addresses.

Result:

```text
Mini 3 hold instructions:      2929
Mini 3 Pro hold instructions:  2909
SequenceMatcher ratio:         ~0.3104
```

There are several substantial matching blocks, confirming related/generated control-flow structure, but the routines are **not close enough to justify copying the Mini 3 Pro post-finalize packet/behavior into WM163**.

This is an important anti-brick constraint:

```text
Mini 3 Pro implementation = useful differential/reference
Mini 3 Pro implementation != proof of WM163 packet semantics
```

The Mini 3 Pro `finalize()` and `monitor_install()` wrappers provide additional anchors immediately before its hold routine, but their dynamically-resolved Python constants/arguments still need reconstruction before they can be compared meaningfully with the WM163 argument vector.

No WM162/WM163 cross-use should be implemented from structural similarity alone.


## Exact WM163 post-finalize poll recovered — 2026-10-03

Direct Cython call-frame reconstruction has now resolved the core packet sent by `Flasher._hold_for_commit()`.

### Constant table recovery

The module initializer creates a fixed PyLong constant table. Relevant recovered entries are:

```text
0      -> 0x180026780
15     -> 0x1800267E0
40     -> 0x1800267F0   # 0x28
64     -> 0x180026808   # 0x40
150    -> 0x180026830
500    -> 0x180026860
980    -> 0x180026868
1000   -> 0x180026870
4000   -> 0x180026878
```

The `_hold_for_commit` wrapper uses the `150` object as its default duration. The native loop references `15` for its periodic status cadence and `500` for the transport call timeout.

### encode() parameter mapping

The `encode` wrapper has six parameter-name objects in this order:

```text
0x180026238
0x1800264A0
0x1800262B8
0x180026550
0x180026310
0x180026598
```

The first four are shared, in the same order, with `Flasher._ctrl(self, cmd_id, payload, dst, seq, what, timeout_ms)`. This proves the corresponding `encode` names are:

```text
cmd_id
payload
dst
seq
flags
cmd_set
```

The final two `encode` parameters have defaults. The recovered callers explicitly set `flags` and omit `cmd_set`; the module-global initialization assigns `CMDSET = 0`.

### Empty payload proof

Global `0x180026648`, used as the second positional argument in the hold-loop encode call, is also passed as the separator to CPython `PyBytes_Join` and returned as the empty result in the transport receive path. It is therefore the module's cached:

```python
b""
```

### ACK flag proof

The module initializer assigns integer `64 / 0x40` to the same module-global name object (`0x180026120`) that `_ctrl()` and `_hold_for_commit()` resolve and pass as `encode(..., flags=...)`.

This is the recovered:

```text
FLAG_REQ_ACK = 0x40
```

The neighboring initializer assignments independently match the previously recovered constants:

```text
CMDSET        = 0x00
FLAG_REQ_ACK  = 0x40
FLAG_RESP     = 0x80
HOST          = 0x2A
```

### Exact encode call

The post-finalize hold therefore constructs:

```python
encode(
    0x01,
    b"",
    dst=0x28,
    seq=0,
    flags=0x40,
    cmd_set=0x00,
)
```

Semantically:

```text
HOST raw address: 0x2A
DST raw address:  0x28
SEQ:              0
FLAGS:            0x40 (request ACK)
CMDSET:           0x00 GENERAL
CMDID:            0x01
PAYLOAD:          empty
```

Using the recovered DJI DUML CRC algorithms, the corresponding 13-byte request is:

```text
55 0D 04 33 2A 28 00 00 40 00 01 F1 FD
```

This frame is **not inferred from WM162**; it is reconstructed from the WM163 `mini3_service_flash` binary itself.

### Exact transport call

The `EngineTransport.xfer` wrapper parameter names are:

```text
self
<frame/data>
timeout_ms
```

and its default timeout object is `4000`.

Inside `_hold_for_commit()`, Cython constructs a keyword tuple using that same `timeout_ms` name and the recovered integer `500`, then invokes the same transport-method name used by `_ctrl()`.

Therefore the hold operation is:

```python
transport.xfer(
    encoded_commit_poll,
    timeout_ms=500,
)
```

where `encoded_commit_poll` is the exact frame above.

### Remaining work

The packet itself is no longer the blocker. What remains to recover before enabling a live service flasher is the **loop/exit policy** around this transaction:

- how xfer timeout/no-response is treated while commit is in progress;
- which decoded reply/state is considered terminal success;
- whether any non-ACK/status frames alter the hold duration;
- exact logging/poll cadence behavior around the recovered 15-second interval;
- the final return/reboot behavior after the 150-second hold.

Do not yet reduce the routine to blindly transmitting the poll for 150 seconds. Preserve the distinction between the now-proven packet and the still-being-decoded commit-state/exit semantics.


### Hold-loop exit and reply handling recovered

The surrounding native control flow is now sufficiently resolved to remove another earlier uncertainty.

After each:

```python
transport.xfer(commit_poll, timeout_ms=500)
```

the returned Python object is immediately decreferenced/discarded. The hold routine does **not** inspect a returned ACK payload, decoded frame, status code, or response field to decide whether commit is complete.

The loop obtains the current monotonic/time value, subtracts the saved start value, and performs a Python `<` comparison against the requested hold-duration argument. In conceptual form:

```python
while (now() - started) < hold_seconds:
    transport.xfer(commit_poll, timeout_ms=500)
    ...
```

The wrapper supplies:

```text
hold_seconds = 150
```

unless overridden.

Therefore the normal end condition is **time-based**, not a special terminal firmware ACK.

The transport receive implementation also joins accumulated receive chunks with the cached `b""`; when no chunks were accumulated, it returns that same empty-bytes object. This confirms that a normal no-data receive result is representable without fabricating a terminal commit response.

The loop separately compares elapsed time against the recovered `15` constant for periodic progress/status output. That cadence is logging/progress behavior, not the commit-success condition.

This substantially changes the remaining blocker:

```text
exact commit poll packet       RECOVERED
xfer timeout                   RECOVERED (500 ms)
hold duration                  RECOVERED (150 s)
normal loop exit               RECOVERED (elapsed >= duration)
reply payload success test     NONE in hold loop
15-second cadence              progress/status only
```

The remaining work before a complete live flasher is now concentrated in reproducing the complete Session-A/Session-B sequencing, ACK/error behavior, and transition into/out of this recovered hold loop—not in discovering another hidden commit-success packet.


## Session-B streaming window and sequence behavior recovered — 2026-10-03

Direct reconstruction of the common `0x2A` send block inside WM163 `Flasher.session_b()` resolves an important earlier uncertainty: component records are **not** transferred with a blocking `xfer()/ACK` transaction for every record.

### Common 0x2A send path

For the Session-B custom file protocol, DrGrey constructs:

```python
encode(
    0x2A,
    record_payload,
    dst=<session_b_destination>,
    seq=current_seq,
    flags=FLAG_REQ_ACK,   # 0x40
    cmd_set=0x00,
)
```

and sends the encoded frame through the transport's non-blocking/write path.

The previously recovered record payload forms remain:

```text
START: 01 + size + filename metadata
DATA:  02 + 24-bit offset + 00 + chunk
END:   03 + MD5(file)
```

### Sequence advancement

Immediately after a successful write call, the native code computes:

```python
current_seq = (current_seq + 1) & 0xFFFF
```

The operation is visible as:

1. Python-number add helper with literal `1`;
2. mask/modulo conversion against `0xFFFF`;
3. replacement of the saved sequence object.

This common send block is used by the custom `0x2A` records, so each transmitted Session-B file-protocol record consumes one sequence number.

### 64-record receive-service cadence

The native code explicitly computes a transfer counter modulo `64`:

```python
if transfer_counter % 64 == 0:
    ...
```

At that boundary it resolves the same transport object and invokes the method identified from the transport API as:

```python
transport.drain(15)
```

The return object is checked only for call success/non-null at this site; no per-record ACK payload is matched before the next transmission.

Therefore Session B is a **windowed/pipelined write stream**, not a lockstep `send -> matching ACK -> send next` loop.

### Longer drain at iterator exhaustion

When the active transfer iterator is exhausted, the same transport-drain method is invoked with:

```python
transport.drain(300)
```

The `300` value is independently recovered from the module's PyLong constant table and is also the default argument in the `EngineTransport.drain` wrapper.

This longer receive-service interval occurs at the end of that streaming iterator before the routine advances into the following Session-B phase.

### Corrected transport model

The accurate current model is therefore:

```text
Session-A control/stream operations:
    blocking ACK-oriented helpers where recovered

Session-B custom 0x2A file records:
    encode current seq
    transport.write(frame)
    seq = (seq + 1) & 0xffff

    every 64 records:
        transport.drain(15)

    at streaming-iterator exhaustion:
        transport.drain(300)
```

Do not implement Session B as one blocking `xfer()` per 980-byte data chunk; that would not reproduce DrGrey's recovered transfer behavior.

Still to pin down before enabling a live flasher:

- exact initial Session-B sequence seed as assigned at entry;
- whether START/DATA/END all pass through precisely the same counter used by the 64-record cadence (the common send block strongly indicates this, but phase edges are still being traced);
- exact ordering of control calls around each file and the final `00/0A`;
- complete error/exception behavior if `write` or `drain` fails.


## WM163 post-finalize hold packet fully recovered — 2026-10-03

Direct reconstruction of Cython's compressed name/constant table in
`mini3_service_flash.cp314-win_amd64.pyd` resolved the previously opaque globals
used by `Flasher._hold_for_commit`.

The module stores its names in a zlib-compressed table. Recovering that table maps
the hold routine's data slots to:

```text
0x1800262D0 -> encode
0x1800262B8 -> dst
0x180026550 -> seq
0x180026310 -> flags
0x180026120 -> FLAG_REQ_ACK
0x180026640 -> xfer
0x1800265D8 -> timeout_ms
0x1800265D0 -> time
0x180026580 -> sleep
```

The integer-constant table also decodes the exact values used by the hold routine:

```text
0x180026780 -> 0
0x180026788 -> 1
0x1800267F0 -> 40 / 0x28
0x180026860 -> 500
0x180026778 -> 0.5
```

Cython's `encode` wrapper exposes the argument names/order as:

```text
encode(cmd_id, payload, dst, seq, flags, src)
```

with the module-wide `CMDSET` used internally.

The constant positional tuple used by `_hold_for_commit` is reconstructed from
module initialization as:

```python
(1, b"")
```

and the keyword dictionary is built as:

```python
{
    "dst": 0x28,
    "seq": 0,
    "flags": FLAG_REQ_ACK,
}
```

Therefore the exact post-finalize probe is now proven as:

```python
probe = encode(
    0x01,
    b"",
    dst=0x28,
    seq=0,
    flags=FLAG_REQ_ACK,
)
```

Because this module's global `CMDSET` is `0x00`, the wire-level command is:

```text
destination/raw node: 0x28
CmdSet:              0x00 GENERAL
CmdId:               0x01
payload:             empty
sequence:            0
flags:               ACK requested
```

The routine then calls the same transport object's:

```python
self.t.xfer(probe, timeout_ms=500)
```

This resolves the previously missing CmdSet, CmdId, payload and timeout.

### Hold-loop behavior

The same recovered constant table proves:

```text
sleep interval = 0.5 seconds
```

The routine logs:

```text
//  holding the link while it applies (do NOT disconnect, up to %ds)…
//  …applying, link alive (%.0fs)
//  ✅ the drone rebooted (~%.0fs) — applying firmware
//  wait ended (%ds): the drone did not reboot on its own — give it a few seconds
```

Static control flow shows the 0x00/0x01 probe is repeatedly sent through
`xfer(..., timeout_ms=500)` while the link remains alive. A transport
failure/no-response path during this phase is handled as the expected reboot
transition and produces the `drone rebooted` message; if the requested hold
duration expires while the link keeps answering, it emits the `wait ended`
message instead.

This removes the final unknown packet from the WM163 post-finalize hold phase.
Before enabling live flashing, the remaining engineering task is to reproduce
DrGrey's complete session sequencing/error handling around this now-proven probe
and preserve the model/manifest/hash/ARB guards.


## Correction: service_fw constants are compressed, not absent — 2026-10-03

A direct scan of the native `service_fw.cp314-win_amd64.pyd` found its Cython
constant/name blob as a zlib stream beginning at file offset `0xD1E0`.
Decompressing that blob proves the previously discussed model/version/service
strings are in fact shipped inside the binary, but not as ordinary plain-text PE
strings.

Recovered directly from the decompressed constant blob:

```text
20.00.0800
20.07.0700
30.00.0100

mini3_service.bin
mini3pro_service.bin
mini4k_service.bin

WA1617
WM162
WM163

SERVICE_FW_DIR
SERVICE_FW_LIBRARY
ServiceFw
ServiceFw.full_path
parse_version
arb_allows
select_service_fw
has_service_fw
drone_public_version
service_version
eligible
cands
newest
```

Recovered user-facing ARB/selection messages include:

```text
ARB bloquea: el dron está en versión pública ...
No hay FW de servicio en la biblioteca para ...
OK: FW de servicio ...
el FW de servicio más nuevo disponible es ... (más viejo).
Necesitás el FW de servicio para el ARB actual del dron.
```

Therefore the earlier note saying those strings were not embedded in
`service_fw.pyd` is superseded: they are embedded in the compressed Cython
constant table. The next step is to reconstruct the actual dictionary entries and
comparison logic from `arb_allows()` and `select_service_fw()`, rather than
merely infer mappings from string adjacency.


## Service firmware catalog and ARB policy fully recovered — 2026-10-03

Reconstructing the full 125-entry Cython compressed constant table (1,713
decompressed bytes, with all entry lengths accounted for exactly) made it
possible to resolve the service catalog and selector control flow directly.

### Exact embedded catalog

Module initialization constructs these `ServiceFw` records:

```text
20.00.0800 -> mini3pro_service.bin
30.00.0100 -> mini3_service.bin
20.07.0700 -> mini4k_service.bin
```

and inserts them into `SERVICE_FW_LIBRARY` under:

```text
WM162  -> 20.00.0800 / mini3pro_service.bin
WM163  -> 30.00.0100 / mini3_service.bin
WA1617 -> 20.07.0700 / mini4k_service.bin
```

This mapping is now proven from initialization control flow, not inferred from
string adjacency.

For this project:

```text
DJI Mini 3 non-Pro = WM163
DrGrey service image = mini3_service.bin
DrGrey service version = 30.00.0100
```

This independently agrees with the supplied package's signed manifest:

```text
device=wm163
formal=30.00.0100
```

### Exact parse_version behavior

Static reconstruction shows the version parser:

1. returns an empty tuple for false/empty input;
2. replaces `_` with `.`;
3. replaces `-` with `.`;
4. splits on `.`;
5. keeps only tokens where `tok.isdigit()` is true;
6. converts those tokens to integers;
7. returns them as a tuple.

Equivalent logic:

```python
def parse_version(s):
    if not s:
        return ()
    parts = str(s).replace("_", ".").replace("-", ".").split(".")
    return tuple(int(tok) for tok in parts if tok.isdigit())
```

### Exact ARB predicate

`arb_allows(service_version, drone_public_version)` parses both versions and
performs Python rich comparison operation `Py_GE`:

```python
parse_version(service_version) >= parse_version(drone_public_version)
```

So a service image is rejected when its parsed version is older than the
aircraft's reported public version.

### select_service_fw behavior

The selector:

1. uses `SERVICE_FW_LIBRARY` unless an alternate library is supplied;
2. normalizes the model code with `.strip().upper()`;
3. obtains that model's candidate list;
4. returns no image if the model has no candidates;
5. filters candidates through `arb_allows(fw.version, drone_public_version)`;
6. if none are eligible, computes the newest available candidate only for the
   ARB-block diagnostic message and returns no image;
7. otherwise chooses the **newest eligible** candidate using
   `max(..., key=lambda f: parse_version(f.version))`.

This proves that DrGrey does not silently cross-select WM162 firmware for WM163
and does not fall back to an ARB-incompatible older image.


## Session-B package parser and exact total_size recovered — 2026-10-03

The higher-level Mini 3 flash worker was traced into
`drgrey.mini3pro_package.parse_service_package_bytes()`, which is reused as the
signed DJI service-package parser.

The parser flow is now reconstructed:

1. `BytesIO(data)`
2. `tarfile.open(...)`
3. iterate regular tar members;
4. read every regular member into a dictionary keyed by filename;
5. locate the single `*.cfg.sig` manifest member;
6. collect `*.pro.fw.sig` module names;
7. call `_manifest_order(cfg_blob, module_names)`;
8. construct the transfer list as `(filename, blob)` pairs beginning with the
   cfg pair, followed by the manifest-selected module files;
9. compute:
   ```python
   total_size = sum(len(blob) for _name, blob in transfer_files)
   ```
10. return the package result containing the transfer files and `total_size`.

The generator used by `sum()` was statically decoded: for each two-element
`(name, blob)` pair it takes the second element and calls `PyObject_Size`,
confirming that only the blob byte length is counted.

The UI worker then obtains `pkg.files`, applies the separately recovered
`gray_order()`, obtains `pkg.total_size`, and calls:

```python
flasher.session_b(ordered_files, total_size)
```

So Session B transfers the signed cfg plus all signed module blobs; tar headers,
padding, filenames and DUML framing are not included in `total_size`.

For the validated WM163 V30.00.0100 package:

```text
wm163.cfg.sig   2,336
0100       39,459,264
0105          245,824
0306        1,760,032
0905       10,390,912
1100           94,720
1200           56,352
---------------------
total_size 52,009,440 bytes
```

The complete tar is 52,019,200 bytes, leaving 9,760 bytes of tar
metadata/padding that are intentionally not reported/transferred as firmware
content.

After `gray_order()`, the actual Session-B transfer order is:

```text
wm163.cfg.sig
0100
0105
0306
0905
1100
1200
```


## Session-B sequence state is caller-seeded — 2026-10-03

Further static tracing of the native `Flasher.session_b()` implementation narrows the remaining sequence-number question.

The Cython name table for `drgrey.mini3_service_flash` contains an explicit `seq0` argument. In the native Session-B body, the Python integer received through that argument path is copied into the saved sequence-state slot before the custom transfer loop. The later common send paths repeatedly replace that saved object with the recovered operation:

```python
seq = (seq + 1) & 0xFFFF
```

This proves the Session-B transfer does not synthesize an opaque/random sequence seed internally: its starting sequence is supplied by the caller through the `seq0` parameter.

The higher-level UI worker has already been traced calling:

```python
flasher.session_b(ordered_files, total_size)
```

without an explicit sequence argument, so the remaining exact question is now reduced to one item: recover the Cython wrapper's default value for `seq0` (or the equivalent default object installed by the wrapper). Do not assume that default is zero until the wrapper/default-object mapping is proven.

This also confirms that the same saved sequence state seen in the 0x2A transfer body is the state advanced modulo 16 bits; the next trace target is the wrapper default plus the phase edges around START/DATA/END and finalization.


## Session-B seq0 default proven: zero — 2026-10-03

The remaining Session-B initial sequence seed is now resolved from the Cython wrapper and module constant initialization.

The Python-callable `Flasher.session_b` wrapper at `0x18000DCD0` accepts five argument slots total:

```text
self
required arg 1
required arg 2
optional arg 3
optional arg 4
```

Only the first three slots (including `self`) are required. The first optional slot is the integer-like path passed as the native function's fourth register argument and is the previously identified `seq0` value.

When that slot is omitted, the wrapper loads its default from module-state pointer `0x180026880`.

Cython's module initialization creates the cached integer objects in a 37-entry table. The integer table begins:

```text
index 0 = 0
index 1 = 1
index 2 = 2
index 3 = 3
...
```

The module-state layout places the first cached integer entry at exactly `0x180026880`. Therefore the wrapper's omitted `seq0` argument resolves to:

```python
seq0 = 0
```

This matches the higher-level worker call already recovered:

```python
flasher.session_b(ordered_files, total_size)
```

because no explicit sequence value is passed and the Cython wrapper supplies zero.

Combined with the already recovered send block, the Session-B 0x2A stream sequence is now:

```python
seq = 0
# for each successfully written 0x2A record:
seq = (seq + 1) & 0xFFFF
```

This removes the Session-B initial-sequence seed from the blocker list. Remaining phase-edge work is to pin down exactly which control records consume separate sequence values (if any) around ENTER, REPORT_SIZE, START/DATA/END, and FINALIZE, plus the Session-A-to-loader-to-Session-B handoff/error paths.


## CORRECTION — exact Session-B defaults are seq0=0x3022 and timeout_s=180 — 2026-10-03

The immediately preceding note that identified the omitted `seq0` default as zero was based on an incorrect base-address assumption for Cython's cached integer table. Static reconstruction of the actual module-state base resolves this exactly and **supersedes that note**.

### Module-state layout proof

Cython initializes the module-state base with:

```text
0x180025D60
```

The cached PyLong table begins at module-state offset:

```text
+0xA20
```

therefore cached integer entry zero lives at:

```text
0x180026780
```

not at `0x180026880`.

The `Flasher.session_b` wrapper constructs its two-default tuple with:

```text
first optional default  -> 0x180026880
second optional default -> 0x180026838
```

Relative to the actual integer-table start, those are:

```text
0x180026880 -> integer-cache index 32
0x180026838 -> integer-cache index 23
```

### Integer table reconstruction

The PyLong initializer is directly visible in module init. Relevant entries are:

```text
index 20 = 128
index 21 = 140
index 22 = 150
index 23 = 180
index 24 = 200
index 25 = 255
index 26 = 300
index 27 = 400
index 28 = 500
index 29 = 980
index 30 = 1000
index 31 = 4000
index 32 = 0x3022 = 12322
index 33 = 0x3692 = 13970
index 34 = 0x4900 = 18688
```

The wrapper's five parameter-name objects correspond to the recovered Session-B signature fields present in the Cython name table:

```python
session_b(self, files, total_size, seq0=0x3022, timeout_s=180)
```

Therefore the exact default starting sequence is:

```text
seq0 = 0x3022
     = 12322 decimal
```

and the Session-B timeout argument defaults to:

```text
timeout_s = 180
```

The custom 0x2A record stream then advances the saved sequence with the already recovered rule:

```python
seq = (seq + 1) & 0xFFFF
```

after each successful write.

This correction removes the initial Session-B sequence seed as an unknown and explains why assuming a conventional zero seed would have produced a non-faithful implementation. Do not use the superseded zero-default note.


## Session-B phase sequence is one shared counter — 2026-10-03

Static tracing of the native `Flasher.session_b()` body now resolves the remaining phase-edge sequence question. The earlier wording that left open whether control records and file records might use separate sequence state is superseded by this section.

The wrapper default remains:

```text
seq0 = 0x3022
```

The native body initializes its working sequence from that value and uses the same Python-integer state through the complete Session-B transaction.

### B/ENTER consumes seq0

The first Session-B control call is constructed with:

```text
cmd_id  = 0x07
payload = 9 zero bytes
dst     = 0x01
seq     = current sequence
label   = B/ENTER
```

At this point:

```text
current sequence = 0x3022
```

Immediately after the control call returns successfully, the native code performs the already recovered operation:

```python
seq = (seq + 1) & 0xFFFF
```

Therefore:

```text
B/ENTER seq = 0x3022
next seq    = 0x3023
```

### B/REPORT_SIZE consumes the next value

The next control vector contains integer-table index 6 = `0x08`, the recovered Session-B size descriptor, destination `0x01`, and the saved sequence produced by the previous increment.

Therefore:

```text
B/REPORT_SIZE seq = 0x3023
next seq          = 0x3024
```

The code again performs `(seq + 1) & 0xFFFF` immediately after a successful call.

### START / DATA / END share the same counter

The three native `0x2A` construction sites correspond to the already recovered Session-B record phases:

```text
START  type 0x01
DATA   type 0x02
END    type 0x03
```

Each site receives the current saved sequence object. After a successful send/write path, the same modulo-16-bit increment operation updates that saved sequence before the next record.

Thus there is no separate sequence namespace for control packets versus loader file records. Conceptually:

```python
seq = 0x3022

send B/ENTER(seq)
seq = (seq + 1) & 0xffff

send B/REPORT_SIZE(seq)
seq = (seq + 1) & 0xffff

for each file:
    send START(seq)
    seq = (seq + 1) & 0xffff

    for each DATA record:
        send DATA(seq)
        seq = (seq + 1) & 0xffff

    send END(seq)
    seq = (seq + 1) & 0xffff
```

The existing 64-record drain cadence applies to the pipelined 0x2A record stream; it does not reset the sequence.

### B/FINALIZE uses the sequence left by the stream

Near the end of the native function, the final control vector contains:

```text
cmd_id  = 0x0A
payload = 17 zero bytes
dst     = 0x01
seq     = current saved sequence
label   = B/FINALIZE
```

The sequence object passed to B/FINALIZE is the same saved state produced by the file-transfer loop. There is no reset to `seq0` before finalization.

The exact Session-B ordering is therefore now:

```text
seq=0x3022
B/ENTER
  increment
B/REPORT_SIZE
  increment
for each gray_order file:
  START
    increment
  DATA x N
    increment after each record
  END
    increment
B/FINALIZE using resulting seq
post-finalize _hold_for_commit()
```

This also supersedes the older note suggesting START/END might follow a materially different sequence-control path from DATA. Their payload construction paths differ, but all three consume the same Session-B sequence state.


## Session-A default sequence and A→B sequence reset proven — 2026-10-03

Static reconstruction of the Python-callable `Flasher.session_a` wrapper resolves the Session-A initial sequence seed.

The wrapper accepts:

```python
session_a(self, loader, seq0=0x4900)
```

When the optional `seq0` argument is omitted, the wrapper loads module-state pointer `0x180026890`. Using the already reconstructed cached-PyLong table base `0x180026780`, this is integer-cache index 34:

```text
index 34 = 0x4900 = 18688
```

The native Session-A body receives that Python integer in its sequence argument and carries it forward through the Session-A control/stream operations. After successful operations it applies the same recovered modulo-16-bit advancement primitive used elsewhere:

```python
seq = (seq + 1) & 0xFFFF
```

Therefore Session A begins with:

```text
A initial seq = 0x4900
```

and advances that shared Session-A counter through A/ENTER, A/PREPARE, A/REPORT_SIZE, A/DATA records, A/CMD_0A and A/CMD_0B as those operations succeed.

### The A→B transition resets sequence space

The higher-level worker invokes both session methods without explicit sequence overrides. Their independently recovered wrapper defaults are:

```text
Session A seq0 = 0x4900
Session B seq0 = 0x3022
```

Thus Session B does **not** inherit the final Session-A sequence value after the temporary loader comes up. The two service-flash stages deliberately start from separate fixed sequence seeds.

Conceptually:

```text
SESSION A
  seq = 0x4900
  ... upload temporary loader ...
  ... wait for WM163 UAV identity ...

SESSION B
  seq = 0x3022      # fresh fixed seed
  B/ENTER
  B/REPORT_SIZE
  START/DATA/END ...
  B/FINALIZE
```

This removes sequence carry-over from the handoff/reconnect blocker. What remains to prove at the higher-level worker is transport-object lifetime/reuse and exact failure/reconnect behavior around the moment Session A observes the `WM163 UAV` loader and returns to the worker.


## Deterministic Session-A transfer count / terminal sequence — 2026-10-03

The recovered bundled loader and chunk size allow the complete Session-A record count to be calculated without guessing:

```text
loader size = 743,120 bytes
CHUNK       = 980 bytes
```

Therefore:

```text
758 full DATA records × 980 bytes = 742,840 bytes
1 final DATA record               =     280 bytes
-----------------------------------------------
DATA records total                =     759
```

Session-A sequence-consuming operations are:

```text
1   A/ENTER
1   A/PREPARE
1   A/REPORT_SIZE
759 A/DATA
1   A/CMD_0A (loader MD5 verify)
1   A/CMD_0B (execute/reboot loader)
-----------------------------------
764 operations
```

With the proven Session-A seed `0x4900` and one modulo-16-bit increment after each successful operation, the expected next-unused Session-A sequence after A/CMD_0B is:

```text
0x4900 + 764 = 0x4BFC
```

No wrap occurs in this transfer.

This is useful as an offline consistency check: a faithful Session-A implementation should emit 759 loader DATA records, the final DATA payload should carry 280 loader bytes, and the sequence state immediately after the final A/CMD_0B success should be `0x4BFC` before the code waits for the `WM163 UAV` loader identity.

Session B still begins independently at its recovered fixed seed `0x3022`; it does not inherit `0x4BFC`.


## Exact known-V30 Session-B record count and FINALIZE sequence — 2026-10-03

Using the validated WM163 V30.00.0100 signed member sizes, recovered `CHUNK = 980`, recovered gray ordering, and the now-proven shared Session-B sequence counter, the complete Session-B record count can be derived exactly.

Signed transfer sizes and DATA-record counts:

```text
wm163.cfg.sig      2,336 bytes ->     3 DATA records
0100          39,459,264 bytes -> 40,265 DATA records
0105             245,824 bytes ->   251 DATA records
0306           1,760,032 bytes -> 1,796 DATA records
0905          10,390,912 bytes ->10,603 DATA records
1100              94,720 bytes ->    97 DATA records
1200              56,352 bytes ->    58 DATA records
----------------------------------------------------
DATA total                         53,073 records
```

Each of the seven files also consumes one START and one END record:

```text
53,073 DATA
+    7 START
+    7 END
----------------
53,087 total 0x2A records
```

Session B begins at `seq0 = 0x3022`:

```text
B/ENTER       seq 0x3022
B/REPORT_SIZE seq 0x3023
first START   seq 0x3024
```

After all 53,087 0x2A records consume and advance that same counter, the exact sequence presented to B/FINALIZE is:

```text
(0x3024 + 53,087) & 0xFFFF = 0xFF83
```

Therefore for the exact validated V30 archive:

```text
B/FINALIZE seq = 0xFF83
next seq       = 0xFF84   # if advanced after finalize
```

No 16-bit wrap occurs until very near the end; the stream remains below `0x10000` and finalizes at `0xFF83`.

The 64-record receive-service cadence produces:

```text
53,087 // 64 = 829 periodic drain boundaries
53,087 % 64  = 31 records after the last 64-record boundary
```

followed by the separately recovered end-of-iterator `drain(300)` before the final control phase.

This gives a strong offline invariant for a faithful V30 transfer implementation: wrong file ordering, wrong chunk size, omitted START/END, accidental tar-padding transfer, or an incorrect sequence increment will cause the calculated B/FINALIZE sequence to differ from `0xFF83`.


## Worker handoff: same Flasher and EngineTransport are reused — 2026-10-03

The remaining Session-A-to-Session-B object-lifetime question is now resolved by reconstructing the Cython string table and annotating the native `_M3FlashWorker.run()` call sites.

### Exact Cython name mapping

The UI extension stores a 334-entry string-length table next to its compressed name blob. Reconstructing that table maps the worker's module-state addresses exactly, including:

```text
0x180023F98 -> EngineTransport
0x180023FA8 -> Flasher
0x180024228 -> _fl
0x180024290 -> gray_order
0x180024308 -> load_loader
0x180024318 -> log
0x180024460 -> on_progress
0x180024528 -> session_a
0x180024530 -> session_b
0x180024628 -> total_size
```

This removes the need to infer these call sites from nearby assembly shape.

### One EngineTransport instance

At native `_M3FlashWorker.run()` address `0x180003091`, the worker constructs `EngineTransport` once. The returned Python object is preserved in the worker frame and later recovered from the same saved slot before the WM163 `Flasher` constructor.

There is no second `EngineTransport` construction in the WM163 Session-A -> Session-B path.

### One Flasher instance

At `0x180005287`, the worker constructs one `Flasher` object. The returned object is saved in register/local state and is then used as the first positional object (the receiver) for both session method calls.

The Session-A vectorcall at `0x18000533E` is equivalent to:

```python
flasher.session_a(loader)
```

The receiver placed into the call vector is the same saved `Flasher` object created at `0x180005287`.

After that call returns successfully, the native code does not construct another `Flasher` or `EngineTransport`. It advances directly to the Session-B vectorcall at `0x1800053FD`:

```python
flasher.session_b(ordered_files, total_size)
```

The first positional object in this call vector is the same `Flasher` object used for `session_a`.

Therefore the higher-level WM163 orchestration is now proven as:

```python
transport = EngineTransport(...)
flasher = Flasher(..., transport, log=..., on_progress=...)

flasher.session_a(loader)
flasher.session_b(ordered_files, total_size)
```

with no worker-level transport/flasher reconstruction between the two sessions.

### No explicit worker-level reconnect between sessions

The recovered Cython name table contains no worker API names for `open`, `close`, or `reconnect`, and—more importantly—the native path between the successful `session_a` return and the `session_b` call contains no transport constructor or replacement assignment. The same object graph remains live across the loader handoff.

This means a faithful implementation must not automatically close/reopen the COM transport between Session A and Session B unless later lower-level evidence specifically requires it. The temporary `WM163 UAV` wait occurs at the beginning of `session_b()` while the existing transport/flasher state is retained.

### Failure propagation at the boundary

The worker does not inspect a special success payload returned by `session_a`. It only requires the Python call to return a non-NULL object. A raised exception takes the worker's error path and Session B is not invoked.

Likewise, Session B begins immediately after a normal Session-A return; there is no separate worker-level reconnect-success predicate between them.

So the recovered boundary semantics are:

```text
session_a raises/fails
    -> worker error path
    -> DO NOT call session_b

session_a returns normally
    -> retain same Flasher/EngineTransport
    -> call session_b immediately
```

This closes the previously listed transport-object lifetime/reuse blocker. Remaining high-value worker work is the exact public-version object supplied to the ARB gate and complete mapping of the worker's user-facing exception/error strings.


## Service-firmware UI availability gate is not the ARB gate — 2026-10-03

Reconstruction of `drgrey.service_fw.cp314-win_amd64.pyd` resolves an important policy distinction that had previously been conflated with the UI worker.

The Cython compressed-name table contains 125 entries. Reconstructing its length table gives exact function argument names and separates the three relevant APIs.

### Exact signatures

```python
arb_allows(service_version, drone_public_version)
select_service_fw(model_code, drone_public_version, library=...)
has_service_fw(model_code, library=...)
```

The `arb_allows` wrapper begins at `0x180002400`; the `select_service_fw` wrapper begins at `0x180002980`; and the `has_service_fw` wrapper begins at `0x180004700`.

Critically, `has_service_fw` has **no `drone_public_version` parameter**. The UI-side `drgrey.ui.flasher` code calls `service_fw.has_service_fw(...)` while deciding Mini-3 flasher availability/visibility. That API can establish that the service-firmware library contains an entry for the normalized model, but it cannot by itself enforce anti-rollback compatibility.

The recovered policy separation is therefore:

```text
has_service_fw(model_code, library)
    -> catalog/availability check only

arb_allows(service_version, drone_public_version)
    -> version compatibility predicate

select_service_fw(model_code, drone_public_version, library)
    -> model-specific, ARB-aware image selection
```

For the guarded replacement flasher, do not treat `has_service_fw("WM163")` as sufficient authorization to write. A public-version-aware ARB check/selection step must remain explicit before service firmware is sent.

This corrects the earlier idea that `_M3FlashWorker.run()` itself necessarily obtains a `device.public_version` and directly calls `arb_allows`. The remaining trace target is the source of the `drone_public_version` object at the actual `select_service_fw` call site.


## Correction: UI flasher does not expose a local public-version selector call — 2026-10-03

Full reconstruction of the 334-entry Cython name table in `drgrey.ui.flasher` rules out an earlier inference about the Mini-3 UI worker.

The UI extension contains names for `service_fw`, `has_service_fw`, `_model_code`, and `fetch_mini3_fw`, but it contains **none** of the following names:

```text
public_version
drone_public_version
arb_allows
select_service_fw
```

Therefore the earlier description that `_M3FlashWorker.run()` obtains `_fl.device.public_version` and directly invokes `arb_allows("WM163", ...)` is not supported by this binary and should be treated as superseded.

### Actual service-image download call

In the native `m3_download_fw` path, the call to `fetch_mini3_fw` at `0x18000DDAC` constructs a one-element keyword-name tuple containing exactly:

```text
model
```

The vectorcall supplies two positional objects plus that `model=` keyword value. The exact semantic identities of the two positional objects are still being traced, so they are not asserted here.

What is proven is that the UI module does not name or retrieve a `public_version` field at this call site, and it does not call the local `service_fw.select_service_fw`/`arb_allows` APIs by name.

This leaves two plausible implementation layers for DrGrey's own product: the remote `fetch_mini3_fw` service may make the final image-policy decision, or the UI path may rely on a server-selected image after its model-only availability check. The binary evidence here does not distinguish those possibilities yet.

For our replacement flasher, the safe consequence is unambiguous: retain an explicit local WM163 model guard and local ARB/public-version compatibility guard before any write rather than assuming the UI's `has_service_fw` or download path provides that protection.


## Exact fetch_mini3_fw signature recovered — 2026-10-03

The service-image download call is now fully resolved by tracing the implementation in `production/licensing/client.cp314-win_amd64.pyd` rather than inferring its parameters from the UI caller.

The Cython wrapper at `0x180009980` parses three Python argument slots total. They map, in lexical/module-state order, to:

```text
0x18002D6E0 -> self
0x18002D2E0 -> dest_path
0x18002D4E0 -> model
```

The wrapper requires the first two slots (`self` and `dest_path`) and supplies a default for the third. Therefore the exact Python-visible method signature is:

```python
LicenseClient.fetch_mini3_fw(self, dest_path, model=None)
```

The native body preserves the third argument as the model selector and falls back to its default object when it is false/omitted.

This also explains the UI vectorcall at `0x18000DDAC`: it passes two positional objects (the `LicenseClient` receiver plus the destination path) and one keyword argument whose recovered keyword name is exactly `model`.

Conceptually the UI performs:

```python
license_client.fetch_mini3_fw(dest_path, model=model_code)
```

There is no `public_version`, `drone_public_version`, ARB value, token, callback, or other hidden policy argument in this method signature.

Consequently the Mini-3 firmware download call itself cannot locally choose an image by comparing the connected aircraft's public version. For our replacement flasher, model validation and the separately recovered local ARB compatibility check remain explicit pre-write requirements.


## Worker session failure semantics: fail closed, no retry — 2026-10-03

Native tracing of `_M3FlashWorker.run()` now resolves the Session-A/Session-B exception behavior in addition to the already-proven object reuse.

### Session A

The optimized Cython call to `session_a` occurs at `0x18000533E`. Its return value is tested immediately:

```text
call session_a(...)
if return == NULL:
    enter common exception-cleanup path
```

The NULL branch begins at `0x18000538E` and records the Cython traceback/state marker before jumping to the worker's common error unwinding path. There is no second `session_a` invocation, transport reconstruction, reconnect call, or fallback invocation of Session B on this branch.

### Session B

The optimized `session_b` call occurs at `0x1800053FD`. Its result is likewise tested immediately. A NULL return takes the error branch beginning at `0x180005461`, which enters the same common exception-unwind machinery.

There is no retry of Session B in the recovered worker path.

### Handoff policy

The exact high-level behavior is therefore:

```python
transport = EngineTransport(...)
flasher = Flasher(...)

try:
    flasher.session_a(loader)
except Exception:
    abort_worker()
    # Session B is never attempted

try:
    flasher.session_b(ordered_files, total_size)
except Exception:
    abort_worker()
    # no automatic retry/reconnect
```

Cython implements this through NULL-return exception propagation rather than the literal Python shown above, but the control-flow semantics are equivalent.

This is a useful safety requirement for the replacement implementation: Session A failure must fail closed before any Session-B service-image transfer, and a Session-B transport/write/drain/control exception must abort rather than automatically replaying records against an uncertain loader state.

Together with the previous object-lifetime result, the Session-A -> loader -> Session-B worker boundary is now substantially closed:

```text
same EngineTransport
same Flasher
Session B performs the loader-ready wait before B/ENTER
no worker-level close/reopen
normal Session-A return -> immediate Session-B call
Session-A exception -> abort
Session-B exception -> abort
no automatic retry at either boundary
```




## Correction: temporary-loader wait belongs to Session B and defaults to 180 seconds — 2026-10-03

Further native tracing corrects the earlier 60-second/Session-A attribution.

The exact loader-wait strings cross-reference the beginning of the native `Flasher.session_b()` body, not `session_a()`:

```text
0x18000E29C -> "//  waiting for the loader to boot (poll version→0x28, up to %ds)…"
0x18000ED27 -> "the loader did not report 'WM163 UAV' within %ds (poll 0x01→0x28)..."
0x18000F0E7 -> "//  loader up ('WM163 UAV') after %.0fs"
```

`session_a()` ends after the recovered A/CMD_0B transaction and logs:

```text
// Session A OK (loader delivered, %d frames)
```

The higher-level worker then invokes `session_b(...)` on the same `Flasher` object. Session B first waits for the temporary loader, and only after the loader is recognized does it continue to B/ENTER and the service-image transfer.

### Exact loader-wait timeout

The wait-loop comparison uses the `timeout_s` argument passed to `session_b`. The already-recovered wrapper signature is:

```python
session_b(self, files, total_size, seq0=0x3022, timeout_s=180)
```

Therefore the default loader-wait bound is:

```text
180 seconds
```

The previously identified module integer `60` is not the Session-B loader-wait bound.

### Exact probe construction

At the start of the wait loop, DrGrey initializes a separate loader-probe sequence to zero and calls the recovered `encode` helper with positional tuple `(1, b"")` plus:

```python
encode(
    0x01,
    b"",
    dst=0x28,
    seq=probe_seq,
    flags=FLAG_REQ_ACK,
)
```

with module `CMDSET = 0x00`.

Thus the first loader probe is:

```text
CmdSet:  0x00
CmdId:   0x01
Dst:     0x28
Seq:     0
Flags:   0x40 (request ACK)
Payload: empty
```

The first request is therefore wire-identical to the already-recovered post-finalize commit probe. Their surrounding state machines are different.

### Per-poll transport behavior

The loader-wait call to `EngineTransport.xfer` supplies no explicit `timeout_ms` keyword, so it uses the recovered method default:

```text
xfer timeout = 4000 ms
```

Immediately afterward Session B calls:

```python
transport.drain(200)
```

and concatenates the bytes returned by `xfer` and `drain` before examining the result.

The probe sequence is then advanced with the same recovered 16-bit rule:

```python
probe_seq = (probe_seq + 1) & 0xFFFF
```

This loader-probe counter is separate from the later Session-B transfer counter, which still starts fresh at `seq0 = 0x3022` for B/ENTER.

### Loader identity recognition

The native code does not require a parsed frame object whose model string equals the full literal `"WM163 UAV"`. It performs a containment test for the recovered bytes/string constant:

```text
UAV
```

against the combined raw receive bytes. Conceptually:

```python
rx = transport.xfer(probe) + transport.drain(200)
probe_seq = (probe_seq + 1) & 0xffff

if b"UAV" in rx:
    loader_ready = True
```

The log text calls the expected loader `WM163 UAV`, but the native acceptance predicate recovered at this site is the substring marker `UAV`.

### Retry cadence

If the marker is absent and the elapsed time has not exceeded `timeout_s`, the native code resolves `time.sleep` and passes cached integer `2`:

```python
time.sleep(2)
```

The loop then sends another probe using the incremented probe sequence.

So the recovered pre-B/ENTER state machine is:

```text
probe_seq = 0
start = time.time()

repeat:
    send 00/01 -> dst 0x28, seq=probe_seq, ACK requested, empty payload
    rx = xfer(..., default 4000 ms) + drain(200)
    probe_seq = (probe_seq + 1) & 0xffff

    if b"UAV" in rx:
        loader ready
        continue to B/ENTER using independent seq0=0x3022

    if elapsed > timeout_s:       # default 180 s
        raise FlashError

    sleep(2 s)
```

This supersedes all earlier notes describing a 60-second Session-A loader wait.


## Session-B transport return handling recovered — 2026-10-03

Static tracing of `EngineTransport.write`, `EngineTransport.drain`, and their Session-B call sites resolves the remaining return-value handling question.

`EngineTransport.write(self, pkt)` delegates to the underlying transport's `send_and_collect` method with recovered timing values `window_ms=0` and `read_timeout_ms=1`. The wrapper does not compare a returned numeric count with the packet length. At this layer, a normal Python return is accepted; an exception/NULL return propagates as failure.

`EngineTransport.drain(self, budget_ms=300)` uses the underlying `read_burst` operation with a recovered `read_timeout_ms=40`, accumulates received byte chunks during the requested budget, and returns their byte concatenation. An empty receive result is representable as `b""`.

At the Session-B periodic `drain(15)` and iterator-end `drain(300)` call sites, the returned bytes are not parsed or matched against sequence/command fields. The native code only requires the call to complete normally, then discards the returned object. A raised exception aborts Session B; a normal return, including an empty bytes result, is accepted.

Likewise, after a normal custom-0x2A `write()` return, Session B discards that return object and advances the shared 16-bit sequence. There is no additional per-record ACK-content predicate at this call site.

This confirms the custom Session-B stream is exception-gated at the `write`/`drain` wrapper layer rather than lockstep ACK-content-gated. The lower-level contract of the transport object's `send_and_collect` implementation remains a separate layer if exact transport internals are needed later.


## Lower serial write contract recovered — 2026-10-03

The remaining short-write question behind `EngineTransport.write()` is resolved by tracing `drgrey.transport.SerialTransport.send_and_collect` in `transport.cp314-win_amd64.pyd`.

The Cython wrapper exposes the relevant `send_and_collect` parameters as `self`, `data`, `read_len`, `window_ms`, and `read_timeout_ms`. The WM163 `EngineTransport.write` path supplies the packet plus `window_ms=0` and `read_timeout_ms=1`.

Inside the SerialTransport native body, DrGrey retrieves `self.ser`, resolves its `write` attribute, and invokes the equivalent of:

```python
self.ser.write(data)
```

The Python object returned by that call is only checked for normal call completion, then decreferenced/discarded. It is not converted to an integer and is not compared with `len(data)`.

The code then resolves the same serial object's `flush` method and invokes the equivalent of:

```python
self.ser.flush()
```

Again, normal completion is required and exceptions propagate through the transport error path.

Therefore there is no additional short-write count validation in either layer recovered so far:

```text
Session-B 0x2A call site
  -> EngineTransport.write(frame)
      -> tp.send_and_collect(frame, window_ms=0, read_timeout_ms=1)
          -> ser.write(frame)     # returned count discarded
          -> ser.flush()
```

The recovered implementation relies on normal completion/exception behavior rather than checking the numeric return from `serial.write`. A guarded replacement may choose to enforce a stricter full-write invariant, but doing so would be an intentional safety hardening rather than an exact reproduction of this DrGrey behavior.


## EngineTransport.xfer no-response semantics recovered — 2026-10-03

Static tracing of `EngineTransport.xfer()` resolves the distinction between an ordinary no-response window and a transport exception for the actual Mini-3 serial path.

The Python-visible signature is:

```python
EngineTransport.xfer(self, pkt, timeout_ms=4000)
```

The native body first obtains `self.tp` and checks whether that transport exposes `send_like_gray_flasher`. `SerialTransport` does expose that method, so this is the active branch for the WM163 serial workflow.

On that branch, `xfer()` invokes the equivalent of:

```python
parts = tp.send_like_gray_flasher(
    pkt,
    wait_response=True,
    window_ms=timeout_ms,
)
```

The recovered keyword-name objects at this call site are exactly `wait_response` and `window_ms`; the first value is Python `True`, and the second is the caller's `timeout_ms` object.

After the transport call returns, `EngineTransport.xfer()` performs a truth test on the returned object. Its behavior is:

```python
if parts:
    return b"".join(parts)
return b""
```

Thus an empty/no-response collection is a normal result represented by `b""`. It is not converted into a timeout exception by `EngineTransport.xfer()` itself.

If the underlying `send_like_gray_flasher` Python call raises/returns NULL, the exception propagates through `xfer()` instead of being converted into `b""`.

`xfer()` also contains a compatibility fallback for transport objects that do not expose `send_like_gray_flasher`: that branch invokes `send_recv(pkt, timeout_ms=timeout_ms)`. The WM163 serial transport uses the preferred `send_like_gray_flasher` branch, so the fallback does not define the normal Mini-3 behavior.

This explains the two recovered callers cleanly:

```text
Session-B loader-ready polling:
    xfer(... default 4000 ms)
    no response -> b"" -> combine with drain(200) -> no UAV marker -> retry
    transport exception -> abort Session B

Post-finalize hold:
    xfer(... timeout 500 ms)
    no response -> normal empty result; hold logic does not inspect payload
    transport exception/link loss -> exception path associated with reboot transition
```

So `b""` and an exception are distinct states in the recovered transport stack; a faithful implementation must not treat an ordinary empty response window as an automatic hard failure during loader polling.


## `_ctrl` / `_stream` ACK deadlines and no-retransmit behavior recovered — 2026-10-03

Native tracing of the two ACK-gated helpers resolves their timeout units and retry model.

### Wrapper defaults are seconds despite the `timeout_ms` name

The Python-visible wrappers expose:

```python
Flasher._ctrl(self, cmd_id, payload, dst, seq, what, timeout_ms=15)
Flasher._stream(self, cmd_id, payload, dst, seq, what, timeout_ms=20)
```

The parameter name is misleading. In both native bodies the value is added directly to `time()` using Python numeric addition:

```python
deadline = time() + timeout_ms
```

Since `time()` is in seconds, the recovered defaults are:

```text
_ctrl ACK deadline   = 15 seconds
_stream ACK deadline = 20 seconds
```

### Initial transmit / receive window

Each helper constructs one ACK-requested frame and invokes `EngineTransport.xfer(frame)` once. No explicit `timeout_ms` keyword is supplied to `xfer` at these call sites, so the already-recovered `EngineTransport.xfer` default applies:

```text
initial xfer response window = 4000 ms
```

The bytes returned by that first xfer are placed into the accumulated receive collection and examined through `match_ack(...)`.

### Additional ACK collection uses `drain(400)`

If no matching ACK is found in the accumulated bytes and the helper has not passed its deadline, both native bodies call:

```python
transport.drain(400)
```

The returned bytes are appended to the receive collection and `match_ack(...)` is run again. The loop continues until either a matching ACK is found or the deadline expires.

The module-state address used for this call maps exactly to the recovered `drain` name, and the argument object is cached integer `400`.

### No request retransmission

There is only one reference to the `xfer` method in each native helper body. The deadline loops jump back to the receive/`drain(400)` path after the original send; they do not return to the encode/xfer transmit site.

Therefore the recovered model is:

```text
_ctrl:
  send once via xfer(default 4000 ms)
  search accumulated bytes for matching ACK
  while no match and before time()+15 s deadline:
      append drain(400)
      search again
  never retransmit the request

_stream:
  send once via xfer(default 4000 ms)
  search accumulated bytes for matching ACK
  while no match and before time()+20 s deadline:
      append drain(400)
      search again
  never retransmit the stream frame
```

`match_ack` remains the previously recovered predicate requiring response flag, matching command ID, and matching sequence number. The exact interpretation of a matched control ACK payload as accepted versus rejected is a separate remaining detail; the binary contains the recovered error fragments `%s: no response from the drone` and `: rejected (` but that payload-status check is not asserted here until fully mapped.


## `_ctrl` matched-ACK payload acceptance recovered — 2026-10-03

Static tracing of `Flasher._ctrl` resolves the remaining device-side
accept/reject rule after `match_ack(...)` has found a response with the
expected command id and sequence.

The matched frame's `payload` is sliced as:

```python
status = frame.payload[:1]
```

DrGrey accepts either of these two values:

```python
status == b""
status == b"\x00"
```

Thus the effective control-ACK rule is:

```python
frame = match_ack(received, want_seq=seq, want_cmd=cmd_id)
if frame is None:
    # continue collecting with drain(400), then eventually
    # raise the recovered "no response from the drone" failure
    ...

status = frame.payload[:1]
if status not in (b"", b"\x00"):
    raise FlashError(f"{what}: rejected (...)")
```

The native rejection branch re-reads the frame payload and formats a hex
preview into the recovered `: rejected (` diagnostic. The exact preview
slice length is diagnostic-only and is not required to reproduce the
accept/reject safety predicate.

This check belongs to `_ctrl`. The separately recovered `_stream` path
requires a matching ACK but does not perform this same leading-payload-status
acceptance test.

The transport-agnostic implementation now exposes
`ctrl_ack_payload_accepted(payload)` so a future guarded flasher can fail
closed on an explicit non-zero control status without enabling any live write
path.


## Session-B pipeline abort / FINALIZE boundary recovered — 2026-10-03

Static control-flow tracing resolves the error boundary between the custom
`0x2A` file stream and `B/FINALIZE`.

The recovered Session-B order is:

```text
B/ENTER via _ctrl
B/REPORT_SIZE via _ctrl

for each START/DATA/END 0x2A record:
    transport.write(...)
    if record_count % 64 == 0:
        transport.drain(15)

iterator exhausted
    -> transport.drain(300)

only after that call returns normally:
    -> B/FINALIZE via _ctrl
```

There is no Session-B-local exception handler that converts failures from the
custom stream writes or drains into success. A Python exception/NULL return
from any of these calls propagates through the Cython function's error cleanup
and prevents the later FINALIZE call:

- custom `0x2A` `transport.write(...)`
- periodic `transport.drain(15)`
- terminal `transport.drain(300)`

A **normal** drain return is sufficient even when the returned bytes are empty.
The Session-B call sites do not parse or ACK-match the bytes returned by those
drains.

Therefore the exact transition condition is:

```python
stream iterator exhausted
and terminal drain(300) returned normally
    -> FINALIZE may be attempted
```

This is now represented offline by
`session_b_finalize_gate(stream_exhausted=..., final_drain_completed=...)`.

`B/FINALIZE` itself is not fire-and-forget. It uses the recovered `_ctrl`
path with command `0x0A`, 17 zero payload bytes, destination `0x01`, and
the current shared sequence. Consequently it requires a matching response
(command id + response flag + sequence), and the matched control ACK must have
either no payload status byte or a leading `0x00`. A non-zero leading status
is an explicit device-side rejection.

This means a guarded implementation must **not** attempt FINALIZE after any
stream/write/drain exception, and must **not** interpret a non-zero FINALIZE
status as success.


## Commit-hold empty-response vs transport-loss semantics recovered — 2026-10-03

The post-FINALIZE `_hold_for_commit()` success/transition semantics are now
narrowed further by combining the recovered `EngineTransport.xfer()` behavior
with the native hold loop.

For the WM163 serial transport, `EngineTransport.xfer()` distinguishes:

```text
underlying call returns no response parts
    -> xfer() returns b""

underlying transport raises / returns NULL
    -> exception propagates
```

The commit-hold loop calls the already-recovered probe:

```python
00/01 -> dst 0x28
seq = 0
flags = 0x40
payload = b""
xfer timeout = 500 ms
```

and does **not** inspect the returned response bytes for ACK content or any
identity/status marker. Therefore a normal `b""` return from `xfer()` is
not, by itself, treated as proof that the aircraft rebooted. The hold loop may
continue after such an empty response window.

The separate transport-exception path is what corresponds to the expected
loss of the temporary loader/application link during reboot/transition. That
path is intentionally distinct from an ordinary empty response result.

The resulting recovered distinction is:

```text
xfer returns normally (including b"")
    -> link call completed normally
    -> continue hold-loop timing/probing logic

xfer raises transport exception / link disappears
    -> enter recovered reboot/application-transition path
```

If the hold reaches its configured maximum (default 150 s) without observing
the transport-loss transition, DrGrey reports that the aircraft did not reboot
automatically and advises allowing additional time. That timeout condition is
not equivalent to a positively confirmed reboot.

A guarded reimplementation should preserve this distinction and must not
promote a single empty 500-ms receive window into a false reboot-success signal.


## Mini-3 licensing download path is model-only — 2026-10-03

Static reconstruction of
`production.licensing.client.LicenseClient.fetch_mini3_fw` resolves the
remaining public-version-source question for the normal Mini-3 UI path.

The Cython method wrapper begins at `0x180009980`. Its argument parser has
three slots: two required arguments and one optional argument. Correlating the
parser slots with the decompressed Cython name table and the native body gives
the effective signature:

```python
fetch_mini3_fw(self, dest_path, model=...)
```

The optional third value is the model selector used by the download request.
The UI call site passes the connected/model-derived value using the exact
keyword:

```text
model
```

The licensing client's complete decompressed name table contains
`fetch_mini3_fw`, `dest_path`, `model`, `mini3_fw_url`, `params`,
and the download/streaming names, but contains none of:

```text
public_version
drone_public_version
arb_allows
select_service_fw
```

The native body inserts the model argument into an outbound mapping before the
HTTP request. No public-firmware-version argument is accepted by this method or
constructed locally for this request.

Combined with the separately reconstructed UI name table, this proves:

```text
Mini-3 UI availability:
    service_fw.has_service_fw(model_code)
    -> catalog presence only

Mini-3 server download:
    LicenseClient.fetch_mini3_fw(dest_path, model=...)
    -> model-selected service image request

_M3FlashWorker.run:
    validates/parses the selected package and executes Session A/B
    -> no local public-version selector call

service_fw.select_service_fw(model_code, drone_public_version):
    exists as the recovered ARB-aware policy API
    -> not invoked by this normal UI download/worker path
```

Therefore there is no aircraft public-version object to recover from
`_M3FlashWorker.run()`: the earlier blocker was based on an incorrect
assumption about where DrGrey applied the ARB-aware selector.

For the guarded replacement implementation, preserve a stricter policy than
this UI path: require an explicit, trustworthy aircraft public-version source
before calling `select_service_fw()`, and fail closed if that source cannot be
obtained. Do not treat `has_service_fw("WM163")` or a successful server
download as ARB authorization.

The offline `has_service_fw` reconstruction has been corrected to match the
binary signature exactly:

```python
has_service_fw(model_code, library=...)
```

It now tests only whether the normalized model has one or more catalog
candidates. ARB-aware eligibility remains exclusively in
`select_service_fw()`.


## Recovered-module search confirms no public-version producer — 2026-10-03

A zlib-aware scan was run across every recovered Cython `.pyd` module in the
DrGrey application, rather than relying on ordinary PE `strings` output.

Search terms:

```text
public_version
drone_public_version
firmware_version
formal_version
```

Only one recovered extension contains either public-version identifier:

```text
drgrey/service_fw.cp314-win_amd64.pyd
    public_version
    drone_public_version
```

No public-version producer/reference was found in the recovered:

```text
drgrey.ui.flasher
production.licensing.client
drgrey.device_info
core.device_info
drgrey.scanner
drgrey.commands
drgrey.unit_diagnostics
core.unit_diagnostics
```

This independently confirms the call-graph finding: the normal Mini-3 UI
download/flash path does not retrieve an aircraft public-version value and
therefore does not invoke the ARB-aware selector with live aircraft version
state.

Accordingly, the guarded replacement should treat ARB verification as an
intentional safety enhancement. It must obtain a trustworthy read-only
aircraft public-version value from a separately proven source before using
`select_service_fw()`; if that source is unavailable or ambiguous, live
service flashing must remain blocked.
