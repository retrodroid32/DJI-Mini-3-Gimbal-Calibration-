#!/usr/bin/env python3
"""Read-only parser for public DJI DUML General 00/42 upgrade status.

Source: o-gs/dji-firmware-tools, comm_dissector/wireshark/
dji-dumlv1-general.lua, general_common_upgrade_status_dissector.

GENERIC PUBLIC PROTOCOL only: this is not a capture-proven WM163 stock-restore
state machine. No port, firmware, or transport functionality exists here.
"""
from __future__ import annotations
from dataclasses import dataclass

STATES = {1: "verify", 2: "user_confirm", 3: "upgrading", 4: "complete"}
REASONS = {
    1: "success", 2: "failure", 3: "firmware_error", 4: "same_version",
    5: "user_cancel", 6: "timeout", 7: "motor_working", 8: "firmware_mismatch",
    9: "illegal_downgrade", 10: "rc_not_connected",
}

@dataclass(frozen=True)
class UpgradeStatus:
    """Decoded payload; optional fields apply only to the corresponding state."""
    state: int
    label: str
    user_time: int | None = None
    user_reserve: int | None = None
    progress: int | None = None
    current_upgrade_index: int | None = None
    upgrade_times: int | None = None
    complete_reason: int | None = None
    complete_reason_label: str | None = None

    @property
    def reports_success(self) -> bool:
        """A public-protocol status result, NOT hardware restore validation."""
        return self.state == 4 and self.complete_reason == 1

def parse_upgrade_status(payload: bytes) -> UpgradeStatus:
    """Parse payload bytes only, not a DUML frame; reject malformed lengths."""
    payload = bytes(payload)
    if not payload:
        raise ValueError("00/42 payload is empty")
    state = payload[0]
    if state not in STATES:
        raise ValueError(f"unknown 00/42 state {state}")
    expected_length = 1 if state == 1 else 3
    if len(payload) != expected_length:
        raise ValueError(
            f"00/42 state {state} needs {expected_length} payload bytes, got {len(payload)}"
        )
    if state == 1:
        return UpgradeStatus(state, STATES[state])
    if state == 2:
        return UpgradeStatus(state, STATES[state], user_time=payload[1], user_reserve=payload[2])
    if state == 3:
        return UpgradeStatus(
            state, STATES[state], progress=payload[1],
            current_upgrade_index=(payload[2] & 0xE0) >> 5,
            upgrade_times=payload[2] & 0x1F,
        )
    return UpgradeStatus(
        state, STATES[state], complete_reason=payload[1],
        complete_reason_label=REASONS.get(payload[1], "unknown"),
        upgrade_times=payload[2],
    )
