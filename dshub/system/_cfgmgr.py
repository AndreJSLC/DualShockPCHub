"""Minimal ctypes bindings for the Windows Configuration Manager (cfgmgr32).

Read-only helpers to list device instance IDs and read typed device
properties (DEVPKEYs) without admin rights, WMI or PowerShell. Used by the
driver scanner, the conflict detector and the DS3 pairing helpers.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import uuid
from ctypes import wintypes
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

CR_SUCCESS = 0
CR_NO_SUCH_VALUE = 0x25
CR_BUFFER_SMALL = 0x1A
CM_GETIDLIST_FILTER_NONE = 0x0
CM_GETIDLIST_FILTER_PRESENT = 0x100
CM_LOCATE_DEVNODE_NORMAL = 0x0
CM_LOCATE_DEVNODE_PHANTOM = 0x1

# DEVPROPTYPE values (devpropdef.h)
_T_EMPTY = 0x00
_T_BYTE = 0x03
_T_INT16 = 0x04
_T_UINT16 = 0x05
_T_INT32 = 0x06
_T_UINT32 = 0x07
_T_INT64 = 0x08
_T_UINT64 = 0x09
_T_GUID = 0x0D
_T_FILETIME = 0x10
_T_BOOLEAN = 0x11
_T_STRING = 0x12
_T_NTSTATUS = 0x17
_T_STRING_LIST = 0x2012
_T_BINARY = 0x1003


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_str(cls, s: str) -> "_GUID":
        return cls.from_buffer_copy(uuid.UUID(s).bytes_le)


class _DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.ULONG)]


@dataclass(frozen=True)
class DevPropKey:
    fmtid: str
    pid: int

    def _c(self) -> _DEVPROPKEY:
        return _DEVPROPKEY(_GUID.from_str(self.fmtid), self.pid)


# Standard keys (devpkey.h)
DEVPKEY_Device_DeviceDesc = DevPropKey("a45c254e-df1c-4efd-8020-67d146a850e0", 2)
DEVPKEY_Device_HardwareIds = DevPropKey("a45c254e-df1c-4efd-8020-67d146a850e0", 3)
DEVPKEY_Device_Service = DevPropKey("a45c254e-df1c-4efd-8020-67d146a850e0", 6)
DEVPKEY_Device_Class = DevPropKey("a45c254e-df1c-4efd-8020-67d146a850e0", 9)
DEVPKEY_Device_Manufacturer = DevPropKey("a45c254e-df1c-4efd-8020-67d146a850e0", 13)
DEVPKEY_Device_FriendlyName = DevPropKey("a45c254e-df1c-4efd-8020-67d146a850e0", 14)
DEVPKEY_Device_UpperFilters = DevPropKey("a45c254e-df1c-4efd-8020-67d146a850e0", 19)
DEVPKEY_Device_LowerFilters = DevPropKey("a45c254e-df1c-4efd-8020-67d146a850e0", 20)
DEVPKEY_Device_DevNodeStatus = DevPropKey("4340a6c5-93fa-4706-972c-7b648008a5a7", 2)
DEVPKEY_Device_ProblemCode = DevPropKey("4340a6c5-93fa-4706-972c-7b648008a5a7", 3)
DEVPKEY_Device_Parent = DevPropKey("4340a6c5-93fa-4706-972c-7b648008a5a7", 8)
DEVPKEY_Device_Children = DevPropKey("4340a6c5-93fa-4706-972c-7b648008a5a7", 9)
DEVPKEY_Device_BusReportedDeviceDesc = DevPropKey("540b947e-8b40-45bc-a8a2-6a0b894cbda2", 4)
DEVPKEY_Device_IsPresent = DevPropKey("540b947e-8b40-45bc-a8a2-6a0b894cbda2", 5)
DEVPKEY_Device_DriverDate = DevPropKey("a8b865dd-2e3d-4094-ad97-e593a70c75d6", 2)
DEVPKEY_Device_DriverVersion = DevPropKey("a8b865dd-2e3d-4094-ad97-e593a70c75d6", 3)
DEVPKEY_Device_DriverInfPath = DevPropKey("a8b865dd-2e3d-4094-ad97-e593a70c75d6", 5)
DEVPKEY_Device_DriverProvider = DevPropKey("a8b865dd-2e3d-4094-ad97-e593a70c75d6", 9)
DEVPKEY_Bluetooth_DeviceAddress = DevPropKey("2bd67d8b-8beb-48d5-87e0-6cda3428040a", 1)


if IS_WINDOWS:
    _cfg = ctypes.WinDLL("cfgmgr32")
    _cfg.CM_Get_Device_ID_List_SizeW.argtypes = [ctypes.POINTER(wintypes.ULONG), wintypes.LPCWSTR,
                                                 wintypes.ULONG]
    _cfg.CM_Get_Device_ID_List_SizeW.restype = wintypes.ULONG
    _cfg.CM_Get_Device_ID_ListW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.ULONG,
                                            wintypes.ULONG]
    _cfg.CM_Get_Device_ID_ListW.restype = wintypes.ULONG
    _cfg.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.LPCWSTR,
                                        wintypes.ULONG]
    _cfg.CM_Locate_DevNodeW.restype = wintypes.ULONG
    _cfg.CM_Get_DevNode_PropertyW.argtypes = [wintypes.DWORD, ctypes.POINTER(_DEVPROPKEY),
                                              ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p,
                                              ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
    _cfg.CM_Get_DevNode_PropertyW.restype = wintypes.ULONG


DEVPKEY_Device_InstanceId = DevPropKey("78c34fc8-104a-4aca-9ea4-524d52996e57", 256)

if IS_WINDOWS:
    _cfg.CM_Get_Device_Interface_PropertyW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(_DEVPROPKEY), ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p,
        ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
    _cfg.CM_Get_Device_Interface_PropertyW.restype = wintypes.ULONG


def interface_instance_id(interface_path: str | bytes) -> str | None:
    """Device instance ID behind a device-interface path (e.g. a hidapi ``path``).

    ``\\\\?\\HID#VID_054C&PID_09CC&MI_03#8&1a2b3c4d&0&0000#{4d1e55b2-...}`` ->
    ``HID\\VID_054C&PID_09CC&MI_03\\8&1A2B3C4D&0&0000``. Works for Bluetooth paths too.
    """
    if not IS_WINDOWS:
        return None
    if isinstance(interface_path, bytes):
        interface_path = interface_path.decode("utf-8", "ignore")
    key = DEVPKEY_Device_InstanceId._c()
    ptype = wintypes.ULONG(0)
    size = wintypes.ULONG(0)
    rc = _cfg.CM_Get_Device_Interface_PropertyW(interface_path, ctypes.byref(key), ctypes.byref(ptype),
                                                None, ctypes.byref(size), 0)
    if rc not in (CR_SUCCESS, CR_BUFFER_SMALL) or size.value == 0:
        return None
    buf = (ctypes.c_ubyte * size.value)()
    rc = _cfg.CM_Get_Device_Interface_PropertyW(interface_path, ctypes.byref(key), ctypes.byref(ptype),
                                                buf, ctypes.byref(size), 0)
    if rc != CR_SUCCESS:
        return None
    return bytes(buf).decode("utf-16-le").rstrip("\0")


def _split_multi_sz(buf: str) -> list[str]:
    return [s for s in buf.split("\0") if s]


def device_ids(present_only: bool = True) -> list[str]:
    """All device instance IDs known to PnP (optionally only the present ones)."""
    if not IS_WINDOWS:
        return []
    flags = CM_GETIDLIST_FILTER_PRESENT if present_only else CM_GETIDLIST_FILTER_NONE
    for _ in range(4):  # the list can grow between the size and the data call
        size = wintypes.ULONG(0)
        if _cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), None, flags) != CR_SUCCESS:
            return []
        buf = ctypes.create_unicode_buffer(size.value + 64)
        rc = _cfg.CM_Get_Device_ID_ListW(None, buf, len(buf), flags)
        if rc == CR_SUCCESS:
            return _split_multi_sz(buf[: len(buf)])
        if rc != CR_BUFFER_SMALL:
            return []
    return []


def _locate(instance_id: str) -> int | None:
    if not IS_WINDOWS:
        return None
    devinst = wintypes.DWORD(0)
    rc = _cfg.CM_Locate_DevNodeW(ctypes.byref(devinst), instance_id, CM_LOCATE_DEVNODE_PHANTOM)
    return devinst.value if rc == CR_SUCCESS else None


def _decode(ptype: int, raw: bytes):
    base = ptype & 0x0FFF
    if ptype == _T_STRING:
        return raw.decode("utf-16-le").rstrip("\0")
    if ptype == _T_STRING_LIST:
        return _split_multi_sz(raw.decode("utf-16-le"))
    if base == _T_BYTE and ptype & 0x1000:  # DEVPROP_TYPEMOD_ARRAY of bytes = binary
        return bytes(raw)
    if ptype == _T_BYTE:
        return raw[0]
    if ptype == _T_BOOLEAN:
        return raw[0] != 0
    if ptype in (_T_UINT16,):
        return struct.unpack("<H", raw[:2])[0]
    if ptype in (_T_INT16,):
        return struct.unpack("<h", raw[:2])[0]
    if ptype in (_T_UINT32,):
        return struct.unpack("<I", raw[:4])[0]
    if ptype in (_T_INT32, _T_NTSTATUS):
        return struct.unpack("<i", raw[:4])[0]
    if ptype == _T_UINT64:
        return struct.unpack("<Q", raw[:8])[0]
    if ptype == _T_INT64:
        return struct.unpack("<q", raw[:8])[0]
    if ptype == _T_FILETIME:
        return struct.unpack("<Q", raw[:8])[0]
    if ptype == _T_GUID:
        return str(uuid.UUID(bytes_le=bytes(raw[:16])))
    return bytes(raw)


def get_property(instance_id: str, key: DevPropKey):
    """Read one property of a device; ``None`` when absent or on any error."""
    devinst = _locate(instance_id)
    if devinst is None:
        return None
    ckey = key._c()
    ptype = wintypes.ULONG(0)
    size = wintypes.ULONG(0)
    rc = _cfg.CM_Get_DevNode_PropertyW(devinst, ctypes.byref(ckey), ctypes.byref(ptype), None,
                                       ctypes.byref(size), 0)
    if rc not in (CR_SUCCESS, CR_BUFFER_SMALL) or size.value == 0:
        return None
    buf = (ctypes.c_ubyte * size.value)()
    rc = _cfg.CM_Get_DevNode_PropertyW(devinst, ctypes.byref(ckey), ctypes.byref(ptype), buf,
                                       ctypes.byref(size), 0)
    if rc != CR_SUCCESS:
        return None
    if ptype.value == _T_EMPTY:
        return None
    return _decode(ptype.value, bytes(buf[: size.value]))


@dataclass(slots=True)
class DeviceNode:
    instance_id: str
    present: bool
    friendly_name: str | None = None
    description: str | None = None
    service: str | None = None
    driver_version: str | None = None
    driver_inf: str | None = None
    driver_provider: str | None = None
    hardware_ids: tuple[str, ...] = ()
    problem_code: int | None = None

    @property
    def name(self) -> str:
        return self.friendly_name or self.description or self.instance_id


def describe(instance_id: str, present: bool = True) -> DeviceNode:
    return DeviceNode(
        instance_id=instance_id,
        present=present,
        friendly_name=get_property(instance_id, DEVPKEY_Device_FriendlyName),
        description=get_property(instance_id, DEVPKEY_Device_DeviceDesc),
        service=get_property(instance_id, DEVPKEY_Device_Service),
        driver_version=get_property(instance_id, DEVPKEY_Device_DriverVersion),
        driver_inf=get_property(instance_id, DEVPKEY_Device_DriverInfPath),
        driver_provider=get_property(instance_id, DEVPKEY_Device_DriverProvider),
        hardware_ids=tuple(get_property(instance_id, DEVPKEY_Device_HardwareIds) or ()),
        problem_code=get_property(instance_id, DEVPKEY_Device_ProblemCode),
    )


def find_devices(*needles: str, present_only: bool = True) -> list[DeviceNode]:
    """Devices whose instance ID or hardware IDs contain any of ``needles`` (case-insensitive)."""
    wanted = [n.upper() for n in needles]
    present = set(device_ids(present_only=True))
    pool = present if present_only else device_ids(present_only=False)
    out: list[DeviceNode] = []
    for iid in pool:
        if not any(n in iid.upper() for n in wanted):
            # Root-enumerated buses (ViGEmBus, HidHide) only show their name in hardware IDs.
            hw = " ".join(get_property(iid, DEVPKEY_Device_HardwareIds) or ()).upper()
            if not any(n in hw for n in wanted):
                continue
        out.append(describe(iid, iid in present))
    return out
