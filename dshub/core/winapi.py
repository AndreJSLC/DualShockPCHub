"""Thin ctypes wrappers around the Windows APIs the device layer needs.

* XInput (including the undocumented ordinals for the PS/Guide button and
  vendor/product ids) - used for a DS3 running DsHidMini in XInput mode.
* cfgmgr32 device properties - DsHidMini publishes battery and mode there.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import uuid
from dataclasses import dataclass

# --------------------------------------------------------------------- XInput

XINPUT_BUTTONS = {
    "dpad_up": 0x0001,
    "dpad_down": 0x0002,
    "dpad_left": 0x0004,
    "dpad_right": 0x0008,
    "start": 0x0010,
    "back": 0x0020,
    "ls": 0x0040,
    "rs": 0x0080,
    "lb": 0x0100,
    "rb": 0x0200,
    "guide": 0x0400,
    "a": 0x1000,
    "b": 0x2000,
    "x": 0x4000,
    "y": 0x8000,
}


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", w.WORD),
        ("bLeftTrigger", w.BYTE),
        ("bRightTrigger", w.BYTE),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", w.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [("wLeftMotorSpeed", w.WORD), ("wRightMotorSpeed", w.WORD)]


class XINPUT_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("Type", w.BYTE),
        ("SubType", w.BYTE),
        ("Flags", w.WORD),
        ("Gamepad", XINPUT_GAMEPAD),
        ("Vibration", XINPUT_VIBRATION),
    ]


class XINPUT_CAPABILITIES_EX(ctypes.Structure):
    _fields_ = [
        ("Capabilities", XINPUT_CAPABILITIES),
        ("VendorId", w.WORD),
        ("ProductId", w.WORD),
        ("ProductVersion", w.WORD),
        ("unk1", w.WORD),
        ("unk2", w.DWORD),
    ]


ERROR_SUCCESS = 0
ERROR_DEVICE_NOT_CONNECTED = 1167


class XInput:
    """Lazy binding to xinput1_4.dll (ships with Windows 8+)."""

    def __init__(self) -> None:
        self._dll = ctypes.WinDLL("xinput1_4.dll")
        # Ordinal 100 = XInputGetStateEx (adds the Guide/PS button bit).
        self._get_state = self._dll[100]
        self._get_state.argtypes = [w.DWORD, ctypes.POINTER(XINPUT_STATE)]
        self._get_state.restype = w.DWORD
        # Ordinal 108 = XInputGetCapabilitiesEx (adds VID/PID).
        try:
            self._get_caps_ex = self._dll[108]
            self._get_caps_ex.argtypes = [w.DWORD, w.DWORD, w.DWORD, ctypes.POINTER(XINPUT_CAPABILITIES_EX)]
            self._get_caps_ex.restype = w.DWORD
        except AttributeError:  # pragma: no cover - very old xinput
            self._get_caps_ex = None
        self._set_state = self._dll.XInputSetState
        self._set_state.argtypes = [w.DWORD, ctypes.POINTER(XINPUT_VIBRATION)]
        self._set_state.restype = w.DWORD

    def get_state(self, slot: int) -> XINPUT_STATE | None:
        st = XINPUT_STATE()
        if self._get_state(slot, ctypes.byref(st)) != ERROR_SUCCESS:
            return None
        return st

    def ids(self, slot: int) -> tuple[int, int] | None:
        if self._get_caps_ex is None:
            return None
        caps = XINPUT_CAPABILITIES_EX()
        if self._get_caps_ex(1, slot, 0, ctypes.byref(caps)) != ERROR_SUCCESS:
            return None
        return caps.VendorId, caps.ProductId

    def set_vibration(self, slot: int, left: float, right: float) -> None:
        vib = XINPUT_VIBRATION(int(max(0.0, min(1.0, left)) * 65535), int(max(0.0, min(1.0, right)) * 65535))
        self._set_state(slot, ctypes.byref(vib))


_xinput: XInput | None = None


def xinput() -> XInput:
    global _xinput
    if _xinput is None:
        _xinput = XInput()
    return _xinput


# ------------------------------------------------------------ cfgmgr32 props

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", w.BYTE * 8)]


class DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", w.ULONG)]


def propkey(fmtid: str, pid: int) -> DEVPROPKEY:
    key = DEVPROPKEY()
    key.fmtid = _GUID.from_buffer_copy(uuid.UUID(fmtid).bytes_le)
    key.pid = pid
    return key


CR_SUCCESS = 0
CM_GETIDLIST_FILTER_PRESENT = 0x00000100
CM_GETIDLIST_FILTER_ENUMERATOR = 0x00000001

_cfg = ctypes.WinDLL("cfgmgr32")


def device_ids(enumerator: str | None = None) -> list[str]:
    """Instance ids of present devices, optionally limited to one enumerator."""
    flags = CM_GETIDLIST_FILTER_PRESENT
    filt = None
    if enumerator:
        flags |= CM_GETIDLIST_FILTER_ENUMERATOR
        filt = ctypes.c_wchar_p(enumerator)
    size = w.ULONG()
    if _cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), filt, flags) != CR_SUCCESS:
        return []
    buf = ctypes.create_unicode_buffer(size.value)
    if _cfg.CM_Get_Device_ID_ListW(filt, buf, size, flags) != CR_SUCCESS:
        return []
    return [s for s in buf[: size.value].split("\0") if s]


def devnode_property(instance_id: str, key: DEVPROPKEY) -> bytes | None:
    inst = w.DWORD()
    if _cfg.CM_Locate_DevNodeW(ctypes.byref(inst), ctypes.c_wchar_p(instance_id), 0) != CR_SUCCESS:
        return None
    prop_type = w.ULONG()
    size = w.ULONG(0)
    _cfg.CM_Get_DevNode_PropertyW(inst, ctypes.byref(key), ctypes.byref(prop_type), None, ctypes.byref(size), 0)
    if size.value == 0:
        return None
    buf = (ctypes.c_ubyte * size.value)()
    if _cfg.CM_Get_DevNode_PropertyW(inst, ctypes.byref(key), ctypes.byref(prop_type), buf,
                                     ctypes.byref(size), 0) != CR_SUCCESS:
        return None
    return bytes(buf[: size.value])


# DsHidMini custom properties (read-only for us; no admin needed).
DSHM_BATTERY = propkey("3FECF510-CC94-4FBE-8839-738201F84D59", 2)
DSHM_LAST_PAIRING_STATUS = propkey("3FECF510-CC94-4FBE-8839-738201F84D59", 3)
DSHM_HID_MODE = propkey("6D293077-C3D6-4062-9597-BE4389404C02", 2)
DEVPKEY_BLUETOOTH_ADDRESS = propkey("2BD67D8B-8BEB-48D5-87E0-6CDA3428040A", 1)
DEVPKEY_DRIVER_VERSION = propkey("A8B865DD-2E3D-4094-AD97-E593A70C75D6", 3)
DEVPKEY_DRIVER_PROVIDER = propkey("A8B865DD-2E3D-4094-AD97-E593A70C75D6", 9)

DSHM_MODES = {1: "SDF", 2: "GPJ", 3: "SXS", 4: "DS4Windows", 5: "XInput"}


@dataclass
class DsHidMiniDevice:
    instance_id: str
    bluetooth: bool
    battery_raw: int | None
    mode: int | None
    driver_version: str | None
    mac: str | None = None  # the DS3's own Bluetooth address, "AA:BB:CC:DD:EE:FF"

    @property
    def mode_name(self) -> str:
        return DSHM_MODES.get(self.mode or 0, "Unknown")


def _utf16(data: bytes | None) -> str | None:
    if not data:
        return None
    return data.decode("utf-16-le", "ignore").rstrip("\0") or None


def _v3_mode(mac_prop: bytes | None) -> int | None:
    """DsHidMini 3.x keeps the HID mode in %ProgramData%\\DsHidMini\\DsHidMini.json."""
    import json
    import os

    path = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "DsHidMini", "DsHidMini.json")
    try:
        with open(path, encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return None
    mac = "".join(c for c in (_utf16(mac_prop) or "") if c.isalnum()).upper()
    dev = (cfg.get("Devices") or {}).get(mac) or {}
    name = str(dev.get("HidDeviceMode") or (cfg.get("Global") or {}).get("HidDeviceMode") or "")
    if not name:
        return None
    if "xinput" in name.lower():
        return 5
    return next((num for num, label in DSHM_MODES.items() if label.lower() == name.lower()), None)


def dshidmini_devices() -> list[DsHidMiniDevice]:
    """DS3s handled by DsHidMini (USB or BthPS3), with battery + HID mode."""
    out: list[DsHidMiniDevice] = []
    for enum in ("USB", "BTHPS3BUS"):
        for iid in device_ids(enum):
            if "PID_0268" not in iid.upper():
                continue
            provider = _utf16(devnode_property(iid, DEVPKEY_DRIVER_PROVIDER)) or ""
            mode = devnode_property(iid, DSHM_HID_MODE)
            if "nefarius" not in provider.lower() and mode is None:
                continue  # some other driver (or none) owns this DS3
            batt = devnode_property(iid, DSHM_BATTERY)
            mac_prop = devnode_property(iid, DEVPKEY_BLUETOOTH_ADDRESS)
            mode_num = mode[0] if mode else _v3_mode(mac_prop)
            raw_mac = "".join(c for c in (_utf16(mac_prop) or "") if c.isalnum()).upper()
            mac = ":".join(raw_mac[i:i + 2] for i in range(0, 12, 2)) if len(raw_mac) == 12 else None
            out.append(DsHidMiniDevice(
                instance_id=iid,
                bluetooth=enum == "BTHPS3BUS",
                battery_raw=batt[0] if batt else None,
                mode=mode_num,
                driver_version=_utf16(devnode_property(iid, DEVPKEY_DRIVER_VERSION)),
                mac=mac,
            ))
    return out
