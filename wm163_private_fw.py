#!/usr/bin/env python3
"""Locate local-only WM163 service firmware inputs.

The private_firmware directory is intentionally excluded by .gitignore.
This module only locates files; it does not open a serial port or flash anything.
"""

from __future__ import annotations

from dataclasses import dataclass
import pathlib


PRIVATE_FIRMWARE_DIR = "private_firmware"
SERVICE_PACKAGE_FILENAME = "V30.00.0100_wm163_dji_system.bin"
SESSION_A_LOADER_FILENAME = "session_a_loader.bin"


@dataclass(frozen=True)
class PrivateServiceInputs:
    directory: pathlib.Path
    package: pathlib.Path | None
    loader: pathlib.Path | None

    @property
    def complete(self) -> bool:
        return self.package is not None and self.loader is not None


def find_private_service_inputs(
    base_dir: str | pathlib.Path | None = None,
) -> PrivateServiceInputs:
    """Find the canonical local-only WM163 service package and loader."""

    root = (
        pathlib.Path(base_dir)
        if base_dir is not None
        else pathlib.Path(__file__).resolve().parent
    )
    directory = root / PRIVATE_FIRMWARE_DIR
    package_path = directory / SERVICE_PACKAGE_FILENAME
    loader_path = directory / SESSION_A_LOADER_FILENAME

    return PrivateServiceInputs(
        directory=directory,
        package=package_path if package_path.is_file() else None,
        loader=loader_path if loader_path.is_file() else None,
    )
