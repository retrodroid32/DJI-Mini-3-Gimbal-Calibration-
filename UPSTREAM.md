# Upstream and protocol notes

This project is a Mini 3 / WM163-focused derivative of the open-source DJI reverse-engineering work in:

- Project: `o-gs/dji-firmware-tools`
- License: GNU GPL v3 or later
- Upstream service utility: `comm_og_service_tool.py`
- Upstream packet implementation: `comm_mkdupc.py`
- Upstream checksum/framing implementation: `comm_dat2pcap.py`

Reference upstream revision observed while this fork was prepared:

`195692263c2684cf1ddc4995f2736be6c0fb135e`

## WM163 observation used by the initial implementation

A public upstream issue documents a regular DJI Mini 3 accepting the gimbal `JointCoarse` request while returning a 14-byte DUML frame whose payload is one byte instead of the two-byte payload expected by the older parser.

Observed request:

`55 0e 04 66 0a 04 39 d8 20 04 08 01 ee 6c`

Observed replies:

`55 0e 04 66 04 0a 39 d8 80 04 08 01 ff 78`

`55 0e 04 66 04 0a b5 89 80 04 08 01 8f 32`

This implementation treats the one-byte reply as opaque until its meaning is confirmed. It does not reinterpret `0x01` as success merely because the gimbal moved.

## Product identifier correction

DJI's current Mobile SDK model enumeration identifies:

- `WM163` as DJI Mini 3
- `WM162` as DJI Mini 3 Pro

Some community posts and issue titles swap these identifiers. This project uses `WM163` for the non-Pro Mini 3.
