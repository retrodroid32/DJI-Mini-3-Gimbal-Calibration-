# Contributing

Contributions that improve DJI Mini 3 / WM163 repair calibration are welcome.

Useful contributions include:

- raw `-vv` packet logs from a Mini 3 during `JointCoarse` or `LinearHall`;
- firmware versions for the gimbal and flight controller;
- the physical gimbal behavior corresponding to each packet sequence;
- reproducible tests for newly understood WM163 payloads;
- documentation corrections backed by captures or public DJI documentation.

Please do not submit account credentials, aircraft account-binding data, private keys, or personally identifying serial-number information.

Protocol changes should include an automated replay/unit test whenever possible. Unknown bytes should remain named as unknown until their meaning is supported by more than a guess.
