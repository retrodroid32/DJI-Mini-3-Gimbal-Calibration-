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
