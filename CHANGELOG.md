# Changelog

## 0.12.0

- Added a fail-closed, WM163-only short repair path for active gimbal diagnostic 40021.
- Recovered transaction: GIMBAL `0x04/0x36`, payload `42 e9 7f 3f`, empty ACK required.
- Added BATTERY/PMU reboot transaction: GENERAL `0x00/0x0B`, empty payload.
- Matched DrGrey capture behavior by using DUML ACK_AFTER_EXEC for the recovered flow.
- Added a mandatory live 40021 precheck and no-reboot behavior on missing/non-empty 0x36 replies.
- Added `dry-run-40021` and packet-construction tests.
- Explicitly excluded the unrelated 168-byte matrix and beta `0x68` save paths.
- Does not claim to clear separate diagnostic 40011.


## 0.1.0

- Initial Mini 3 / WM163-focused release.
- Added DUMLv1 packet construction and validation.
- Added `JointCoarse` and `LinearHall` repair-calibration commands.
- Added WM163 one-byte reply handling without assigning unverified semantics.
- Added raw progress capture, replay mode, and known-packet dry-run tests.
- Added explicit Mini 3 vs Mini 3 Pro platform warning.
