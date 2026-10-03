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

The exact in-flight window, ACK collection, timeout and abort semantics for DATA records remain under active reconstruction and are intentionally not asserted yet.


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
