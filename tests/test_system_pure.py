"""Unit tests for the pure (no hardware, no network) parts of ``dshub.system``.

Run with ``python -m pytest tests`` or ``python tests/test_system_pure.py``.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dshub.core.state import Model  # noqa: E402
from dshub.system import bluetooth, drivers, ds3_pairing, elevate, firmware, hidhide  # noqa: E402


def test_version_tuple() -> None:
    assert drivers.version_tuple("setup-v3.17.1-r1") == (3, 17, 1)
    assert drivers.version_tuple("2.6.174.0") == (2, 6, 174)
    assert drivers.version_tuple("v1.22.0") == (1, 22, 0)
    assert drivers.version_tuple(None) == ()
    assert drivers.version_tuple("3.20.1") > drivers.version_tuple("3.5.1")  # numeric, not lexical


def test_update_available() -> None:
    c = drivers.catalog()[0]
    c.installed_version, c.latest_version = "2.2.282.0", "3.20.1"
    assert c.update_available
    c.installed_version = "3.20.1.0"
    assert not c.update_available


def test_format_mac() -> None:
    assert bluetooth.format_mac(0x0123456789AB) == "01:23:45:67:89:AB"
    assert bluetooth.format_mac("a1b2c3d4e5f6") == "A1:B2:C3:D4:E5:F6"
    assert bluetooth.format_mac("nonsense") is None
    assert bluetooth.format_mac(None) is None


def test_ds3_battery() -> None:
    charging = ds3_pairing.battery_from_status(0xEE, wired=True)
    assert charging.charging and charging.wired and charging.level is None
    full = ds3_pairing.battery_from_status(0xEF, wired=True)
    assert full.full and full.level == 100
    assert ds3_pairing.battery_from_status(0x03, wired=False).level == 50
    assert ds3_pairing.battery_from_status(None, wired=False).level is None


def test_parse_ds5_firmware() -> None:
    report = bytearray(64)
    report[0] = 0x20
    report[1:12] = b"Sep 21 2023"
    report[12:20] = b"08:31:24"
    struct.pack_into("<II", report, 24, 0x00000E10, 0x0001_0641)
    struct.pack_into("<H", report, 44, 0x0641)
    info = firmware.parse_ds5_firmware(bytes(report))
    assert info is not None
    assert info.update == 0x0641 and info.display == "06.41"
    assert info.build == "Sep 21 2023 08:31:24"
    assert firmware.parse_ds5_firmware(b"\x01" * 64) is None  # wrong report id


def test_parse_ds4_firmware() -> None:
    report = bytearray(49)
    report[0] = 0xA3
    struct.pack_into("<H", report, 35, 0x0100)
    struct.pack_into("<H", report, 41, 0x08B4)
    info = firmware.parse_ds4_firmware(bytes(report))
    assert info is not None and info.hardware == 0x0100 and info.firmware == 0x08B4
    assert firmware.parse_ds4_firmware(b"\xa3") is None  # too short


def test_firmware_tools() -> None:
    assert firmware.tool_for(Model.DS5).download_url == firmware.SONY_INSTALLER
    assert firmware.tool_for(Model.DS5_EDGE).page_url == firmware.SONY_PAGE
    assert firmware.tool_for(Model.DS4).download_url is None
    assert firmware.tool_for(Model.DS3).download_url is None


def test_uninstall_string_rewrites_msi_install_to_remove() -> None:
    calls = []
    original = elevate.run_elevated
    elevate.run_elevated = lambda program, params="", wait=True, cwd=None: calls.append((program, params))
    try:
        elevate.run_uninstall_string("MsiExec.exe /I{3B1D1A07-1234-4F2E-9B2A-0C7E2B1A9F00}")
        elevate.run_uninstall_string('"C:\\Program Files\\Foo\\unins000.exe" /SILENT')
    finally:
        elevate.run_elevated = original
    assert calls[0] == ("MsiExec.exe", "/X{3B1D1A07-1234-4F2E-9B2A-0C7E2B1A9F00}")
    assert calls[1] == ("C:\\Program Files\\Foo\\unins000.exe", "/SILENT")


def test_hid_modes_cover_v2_and_v3() -> None:
    assert ds3_pairing.HID_MODES[5] == "XInput" and ds3_pairing.HID_MODES[3] == "SXS"
    assert set(ds3_pairing.HID_MODE_HELP) == set(ds3_pairing.HID_MODES.values())


def test_hidhide_ioctl_codes_match_driver() -> None:
    assert hidhide.IOCTL_GET_WHITELIST == 0x80016000
    assert hidhide.IOCTL_SET_BLACKLIST == 0x8001600C
    assert hidhide.IOCTL_SET_ACTIVE == 0x80016014
    assert hidhide.IOCTL_SET_WLINVERSE == 0x8001601C


def test_hidhide_multi_sz_matches_cli_format() -> None:
    nul = "\x00"
    assert hidhide.encode_multi_sz([]) == nul.encode("utf-16-le")
    assert hidhide.encode_multi_sz(["A", "BC"]) == f"A{nul}BC{nul}{nul}".encode("utf-16-le")
    items = [r"HID\VID_054C&PID_09CC&MI_03\8&1A2B3C4D&0&0000", r"HID\VID_045E&PID_02FF&IG_00\7&1&4&0000"]
    assert hidhide.decode_multi_sz(hidhide.encode_multi_sz(items)) == items
    assert hidhide.decode_multi_sz(b"") == []


def test_hidhide_paths() -> None:
    nt = hidhide.dos_to_nt(r"C:\Python312\pythonw.exe")
    assert nt.startswith("\\Device\\") and nt.endswith(r"\Python312\pythonw.exe")
    assert hidhide.nt_to_dos(nt) == r"C:\Python312\pythonw.exe"
    me = hidhide.self_image_path()
    assert me.startswith("\\Device\\") and me.lower().endswith(".exe")
    assert hidhide.nt_to_dos(me).lower() == hidhide.self_image_path(native=False).lower()


def test_hidhide_unavailable_is_reported_cleanly() -> None:
    if hidhide.installed():
        return  # the live driver is exercised manually instead
    try:
        hidhide.state()
    except hidhide.HidHideUnavailable:
        return
    raise AssertionError("expected HidHideUnavailable when HidHide is not installed")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
