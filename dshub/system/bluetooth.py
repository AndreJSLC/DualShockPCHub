"""Local Bluetooth radio facts (read-only): address, name, vendor, BthPS3 service state."""

from __future__ import annotations

import ctypes
import sys
import winreg
from ctypes import wintypes
from dataclasses import dataclass

from . import _cfgmgr as cm

BTHPS3_SERVICE_GUID = "{1cb831ea-79cd-4508-b0fc-85f7c85ae8e0}"
BTHPS3_SERVICE_NAME = "BthPS3Service"
BLUETOOTH_CLASS_GUID = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"

_MANUFACTURERS = {  # Bluetooth SIG company identifiers seen on PC radios
    0x0002: "Intel", 0x000A: "Qualcomm (CSR)", 0x000F: "Broadcom", 0x001D: "Qualcomm",
    0x0046: "MediaTek", 0x005D: "Realtek", 0x0006: "Microsoft", 0x0131: "Cypress",
}


@dataclass(frozen=True, slots=True)
class Radio:
    address: str  # "AA:BB:CC:DD:EE:FF"
    name: str
    manufacturer_id: int
    lmp_subversion: int

    @property
    def manufacturer(self) -> str:
        return _MANUFACTURERS.get(self.manufacturer_id, f"0x{self.manufacturer_id:04X}")


def format_mac(value: int | str | None) -> str | None:
    """``0xAABBCCDDEEFF`` / ``"AABBCCDDEEFF"`` -> ``"AA:BB:CC:DD:EE:FF"``."""
    if value is None:
        return None
    if isinstance(value, int):
        value = f"{value:012X}"
    hexdigits = "".join(c for c in value if c.isalnum()).upper()
    if len(hexdigits) != 12:
        return None
    return ":".join(hexdigits[i:i + 2] for i in range(0, 12, 2))


class _FindRadioParams(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]


class _RadioInfo(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("address", ctypes.c_ulonglong),
                ("szName", wintypes.WCHAR * 248), ("ulClassofDevice", wintypes.ULONG),
                ("lmpSubversion", wintypes.USHORT), ("manufacturer", wintypes.USHORT)]


def radios() -> list[Radio]:
    """All local Bluetooth radios that the Microsoft stack can see."""
    if sys.platform != "win32":
        return []
    try:
        api = ctypes.WinDLL("BluetoothApis")
    except OSError:
        return []
    api.BluetoothFindFirstRadio.restype = wintypes.HANDLE
    api.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(_FindRadioParams),
                                            ctypes.POINTER(wintypes.HANDLE)]
    api.BluetoothFindNextRadio.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE)]
    api.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
    api.BluetoothGetRadioInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_RadioInfo)]
    close = ctypes.windll.kernel32.CloseHandle

    params = _FindRadioParams(ctypes.sizeof(_FindRadioParams))
    radio = wintypes.HANDLE()
    find = api.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
    if not find:
        return []
    found: list[Radio] = []
    try:
        while True:
            info = _RadioInfo()
            info.dwSize = ctypes.sizeof(_RadioInfo)
            if api.BluetoothGetRadioInfo(radio, ctypes.byref(info)) == 0:
                found.append(Radio(format_mac(info.address) or "", info.szName,
                                   info.manufacturer, info.lmpSubversion))
            close(radio)
            if not api.BluetoothFindNextRadio(find, ctypes.byref(radio)):
                break
    finally:
        api.BluetoothFindRadioClose(find)
    return found


def host_address() -> str | None:
    """MAC of the first radio: the address DsHidMini writes into a DS3 when auto-pairing."""
    found = radios()
    return found[0].address if found else None


@dataclass(frozen=True, slots=True)
class LocalService:
    registered: bool
    enabled: bool
    name: str | None


def bthps3_local_service() -> LocalService:
    """State of BthPS3's Bluetooth local-service registration (BTHPORT LocalServices)."""
    path = rf"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\LocalServices\{BTHPS3_SERVICE_GUID}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as root:
            sub = winreg.EnumKey(root, 0)
            with winreg.OpenKey(root, sub) as key:
                enabled = _reg_value(key, "Enabled") == 1
                name = _reg_value(key, "ServiceName")
                return LocalService(True, enabled, name)
    except OSError:
        return LocalService(False, False, None)


def bluetooth_class_lower_filters() -> list[str]:
    path = rf"SYSTEM\CurrentControlSet\Control\Class\{BLUETOOTH_CLASS_GUID}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return list(_reg_value(key, "LowerFilters") or [])
    except OSError:
        return []


def bthps3_enumerator() -> cm.DeviceNode | None:
    """The "Nefarius Bluetooth PS Enumerator" PDO; its absence breaks DS3 Bluetooth."""
    found = cm.find_devices("{1CB831EA-79CD-4508-B0FC-85F7C85AE8E0}", present_only=False)
    present = [d for d in found if d.present]
    return (present or found or [None])[0]


def radio_devices() -> list[cm.DeviceNode]:
    """PnP nodes of the radios themselves (to show the vendor driver and transport)."""
    out = []
    for iid in cm.device_ids(present_only=True):
        if cm.get_property(iid, cm.DEVPKEY_Device_Service) in ("BTHUSB", "BthMini", "BTHX"):
            out.append(cm.describe(iid))
    return out


def _reg_value(key, name: str):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None
