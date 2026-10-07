"""Controller firmware: what can be updated on a PC, and parsers for version reports.

* DualSense / DualSense Edge: Sony's official "PlayStation Accessories" app
  (formerly "Firmware updater for DualSense") updates firmware over USB or
  Bluetooth. We link to / download Sony's installer; we never flash firmware.
* DualShock 4 and DualShock 3: Sony ships no PC updater; only a console can
  update them (and they rarely need it).

The parsers turn the raw feature reports (read by the HID backend) into
version numbers for display.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from dshub.core.state import Model

SONY_PAGE = "https://controller.dl.playstation.net/controller/lang/en/2100004.html"
SONY_INSTALLER = "https://fwupdater.dl.playstation.net/fwupdater/PlayStationAccessoriesInstaller.exe"
SONY_PUBLISHER = "Sony Interactive Entertainment"


@dataclass(frozen=True, slots=True)
class FirmwareTool:
    name: str
    page_url: str | None
    download_url: str | None
    summary: str


_PS_ACCESSORIES = FirmwareTool(
    name="PlayStation Accessories (Sony)",
    page_url=SONY_PAGE,
    download_url=SONY_INSTALLER,
    summary="Sony's official Windows app updates DualSense and DualSense Edge firmware over USB or "
            "Bluetooth (and customises Edge profiles). Close other controller apps first.",
)


def tool_for(model: Model) -> FirmwareTool:
    if model in (Model.DS5, Model.DS5_EDGE):
        return _PS_ACCESSORIES
    if model is Model.DS4:
        return FirmwareTool(
            "None needed", None, None,
            "Sony has no PC firmware updater for the DualShock 4. Its firmware only updates on a "
            "PS4/PS5, and current firmware works fine on Windows.")
    return FirmwareTool(
        "None available", None, None,
        "The DualShock 3 cannot be updated on a PC. Its firmware is fixed; DsHidMini handles "
        "everything on Windows.")


# ------------------------------------------------------------------ parsers
@dataclass(frozen=True, slots=True)
class FirmwareInfo:
    hardware: int
    firmware: int
    update: int | None = None  # DualSense "update version", the number Sony's tools show
    build: str | None = None  # "Sep 21 2023 08:31:24"

    @property
    def display(self) -> str:
        if self.update is not None:
            return f"{self.update >> 8:02X}.{self.update & 0xFF:02X}"
        return f"0x{self.firmware:04X}"


def _ascii(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", "replace").strip()


def parse_ds5_firmware(report: bytes) -> FirmwareInfo | None:
    """DualSense feature report 0x20 (64 bytes, report ID first). Layout from hid-playstation.c."""
    if len(report) < 46 or report[0] != 0x20:
        return None
    hw, fw = struct.unpack_from("<II", report, 24)
    update = struct.unpack_from("<H", report, 44)[0]
    build = f"{_ascii(report[1:12])} {_ascii(report[12:20])}".strip() or None
    return FirmwareInfo(hw, fw, update, build)


def parse_ds4_firmware(report: bytes) -> FirmwareInfo | None:
    """DualShock 4 feature report 0xA3 (49 bytes, report ID first). Layout from hid-sony.c."""
    if len(report) < 43 or report[0] != 0xA3:
        return None
    hw = struct.unpack_from("<H", report, 35)[0]
    fw = struct.unpack_from("<H", report, 41)[0]
    build = f"{_ascii(report[1:17])} {_ascii(report[17:33])}".strip() or None
    return FirmwareInfo(hw, fw, None, build)
