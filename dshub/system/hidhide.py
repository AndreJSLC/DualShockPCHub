"""HidHide integration: hide controllers from every app except DualShock PC Hub.

Facts this module relies on (HidHide v1.5.230 source; details in
docs/RESEARCH-drivers.md, "HidHide integration"):

* The control device ``\\\\.\\HidHide`` is open to all users, so **no admin or UAC
  prompt is needed**. It is exclusive (one handle at a time), so every
  operation opens it, acts and closes immediately.
* The registry copy of the configuration is locked down (deny-all ACL); the
  driver is the source of truth and is read/written through IOCTLs.
* Block-list entries are HID *child* device instance IDs (HIDClass/XUSB setup
  classes only), compared case-insensitively. Allow-list entries are NT image
  paths (``\\Device\\HarddiskVolumeN\\...``) of the process that opens the device.
* Hiding is checked when a handle is opened: apps that already hold the pad
  (e.g. Steam) keep it until the controller reconnects.
* We only ever add/remove our own entries; other apps' entries are preserved.
"""

from __future__ import annotations

import ctypes
import string
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

from . import _cfgmgr as cm
from . import drivers

CONTROL_DEVICE = r"\\.\HidHide"


def _ctl(function: int) -> int:
    """CTL_CODE(0x8001, function, METHOD_BUFFERED, FILE_READ_DATA)."""
    return (0x8001 << 16) | (0x0001 << 14) | (function << 2)


IOCTL_GET_WHITELIST = _ctl(2048)  # 0x80016000
IOCTL_SET_WHITELIST = _ctl(2049)
IOCTL_GET_BLACKLIST = _ctl(2050)
IOCTL_SET_BLACKLIST = _ctl(2051)
IOCTL_GET_ACTIVE = _ctl(2052)
IOCTL_SET_ACTIVE = _ctl(2053)
IOCTL_GET_WLINVERSE = _ctl(2054)
IOCTL_SET_WLINVERSE = _ctl(2055)

_LIST_BUFFER_BYTES = 256 * 1024  # read lists in one call; avoids the size probe that fails on some 25H2 builds

GENERIC_READ = 0x80000000
FILE_SHARE_ALL = 0x1 | 0x2 | 0x4
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
PROCESS_NAME_NATIVE = 1


class HidHideError(RuntimeError):
    """HidHide refused or failed an operation."""


class HidHideUnavailable(HidHideError):
    """HidHide is not installed, or its driver is not running yet (restart after installing)."""


class HidHideBusy(HidHideError):
    """Another app (HidHide's own client, DS4Windows, ...) currently holds HidHide's control device."""


# ------------------------------------------------------------ data formats
def encode_multi_sz(items: list[str]) -> bytes:
    """Exactly what HidHideCLI sends: every string NUL-terminated, then one final NUL."""
    return ("".join(item + "\0" for item in items) + "\0").encode("utf-16-le")


def decode_multi_sz(raw: bytes) -> list[str]:
    return [s for s in raw.decode("utf-16-le", "ignore").split("\0") if s]


def _drive_map() -> dict[str, str]:
    """``{"C:": "\\Device\\HarddiskVolume3", ...}`` for every mounted drive letter."""
    out: dict[str, str] = {}
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    buf = ctypes.create_unicode_buffer(1024)
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i) and ctypes.windll.kernel32.QueryDosDeviceW(f"{letter}:", buf, len(buf)):
            out[f"{letter}:"] = buf.value
    return out


def dos_to_nt(path: str) -> str:
    """``C:\\Python312\\pythonw.exe`` -> ``\\Device\\HarddiskVolume3\\Python312\\pythonw.exe``."""
    if path.startswith("\\Device\\"):
        return path
    drive, rest = path[:2].upper(), path[2:]
    device = _drive_map().get(drive)
    if device is None:
        raise HidHideError(f"{path} is not on a local drive letter.")
    return device + rest


def nt_to_dos(path: str) -> str:
    """Best-effort reverse of ``dos_to_nt`` for display; returns the input if unmapped."""
    for drive, device in _drive_map().items():
        if path.lower().startswith(device.lower() + "\\"):
            return drive + path[len(device):]
    return path


def self_image_path(native: bool = True) -> str:
    """Image path of *this* process (the one that opens the controllers).

    Under a venv, ``.venv\\Scripts\\pythonw.exe`` is only a launcher: the real
    process is the base interpreter (e.g. ``C:\\Python312\\pythonw.exe``), so that
    is what HidHide must allow. Frozen builds report the app's own .exe.
    """
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    size = wintypes.DWORD(32768)
    buf = ctypes.create_unicode_buffer(size.value)
    flags = PROCESS_NAME_NATIVE if native else 0
    if not k32.QueryFullProcessImageNameW(k32.GetCurrentProcess(), flags, buf, ctypes.byref(size)):
        raise ctypes.WinError()
    return buf.value


def instance_id_for_hid_path(hid_path: str | bytes) -> str | None:
    """Block-list entry for a hidapi device path (the HID child's instance ID, upper-case)."""
    iid = cm.interface_instance_id(hid_path)
    return iid.upper() if iid else None


# ----------------------------------------------------------------- driver IO
class _Control:
    """Short-lived handle on HidHide's (exclusive) control device."""

    def __enter__(self) -> "_Control":
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                        ctypes.c_void_p]
        k32.DeviceIoControl.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32 = k32
        handle = k32.CreateFileW(CONTROL_DEVICE, GENERIC_READ, FILE_SHARE_ALL, None, OPEN_EXISTING, 0, None)
        if handle in (None, 0, INVALID_HANDLE_VALUE):
            err = ctypes.get_last_error()
            if err in (2, 3):  # file / path not found
                raise HidHideUnavailable(
                    "HidHide is not installed, or its driver is not running yet "
                    "(restart Windows after installing it).")
            if err in (5, 32, 170):  # access denied / sharing violation / busy: exclusive device in use
                raise HidHideBusy(
                    "HidHide's settings are open in another app (e.g. the HidHide Configuration "
                    "Client or DS4Windows). Close it and try again.")
            raise HidHideError(f"Could not open HidHide ({ctypes.WinError(err).strerror}).")
        self._handle = handle
        return self

    def __exit__(self, *exc) -> None:
        self._k32.CloseHandle(self._handle)

    def _ioctl(self, code: int, data: bytes | None, out_size: int) -> bytes:
        in_buf = ctypes.create_string_buffer(data, len(data)) if data else None
        out_buf = ctypes.create_string_buffer(out_size) if out_size else None
        returned = wintypes.DWORD(0)
        ok = self._k32.DeviceIoControl(self._handle, code, in_buf, len(data) if data else 0,
                                       out_buf, out_size, ctypes.byref(returned), None)
        if not ok:
            err = ctypes.get_last_error()
            hint = (" This is a known HidHide issue on some Windows 11 25H2+ builds (HidHide #215)."
                    if err == 87 else "")
            raise HidHideError(f"HidHide request 0x{code:08X} failed: {ctypes.WinError(err).strerror}.{hint}")
        return out_buf.raw[: returned.value] if out_buf is not None else b""

    def get_list(self, code: int) -> list[str]:
        try:
            return decode_multi_sz(self._ioctl(code, None, _LIST_BUFFER_BYTES))
        except HidHideError:
            # Fall back to the CLI's way: ask for the size first, then read.
            needed = wintypes.DWORD(0)
            self._k32.DeviceIoControl(self._handle, code, None, 0, None, 0, ctypes.byref(needed), None)
            if not needed.value:
                raise
            return decode_multi_sz(self._ioctl(code, None, needed.value))

    def set_list(self, code: int, items: list[str]) -> None:
        self._ioctl(code, encode_multi_sz(items), 0)

    def get_bool(self, code: int) -> bool:
        return self._ioctl(code, None, 1)[:1] not in (b"", b"\x00")

    def set_bool(self, code: int, value: bool) -> None:
        self._ioctl(code, b"\x01" if value else b"\x00", 0)


# ------------------------------------------------------------------ public
@dataclass(slots=True)
class HidHideState:
    active: bool  # "cloak": hiding is switched on
    inverse: bool  # inverse mode: the allow-list becomes a deny-list
    allowed_apps: list[str] = field(default_factory=list)  # DOS paths where mappable
    hidden_devices: list[str] = field(default_factory=list)  # device instance IDs
    self_allowed: bool = False  # this process can see hidden devices

    def is_hidden(self, instance_id: str) -> bool:
        return instance_id.upper() in {d.upper() for d in self.hidden_devices}


def installed() -> bool:
    return drivers.service_exists("HidHide")


def cli_path() -> Path | None:
    """HidHideCLI.exe from HidHide's install folder (informational; this module doesn't need it)."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Nefarius Software Solutions e.U.\HidHide") as key:
            base = Path(winreg.QueryValueEx(key, "Path")[0])
    except OSError:
        base = Path(r"C:\Program Files\Nefarius Software Solutions\HidHide")
    exe = base / "x64" / "HidHideCLI.exe"
    return exe if exe.exists() else None


def _read(ctl: _Control) -> HidHideState:
    allowed_nt = ctl.get_list(IOCTL_GET_WHITELIST)
    me = self_image_path().lower()
    return HidHideState(
        active=ctl.get_bool(IOCTL_GET_ACTIVE),
        inverse=ctl.get_bool(IOCTL_GET_WLINVERSE),
        allowed_apps=[nt_to_dos(p) for p in allowed_nt],
        hidden_devices=ctl.get_list(IOCTL_GET_BLACKLIST),
        self_allowed=any(p.lower() == me for p in allowed_nt),
    )


def state() -> HidHideState:
    """Current HidHide configuration (no admin needed). Raises HidHideUnavailable/HidHideBusy."""
    with _Control() as ctl:
        return _read(ctl)


def apply(hide: list[str] = (), unhide: list[str] = (), allow_apps: list[str] = (),
          disallow_apps: list[str] = (), cloak: bool | None = None) -> HidHideState:
    """Change HidHide's lists in one short session; other apps' entries are left untouched.

    The allow-list is written before the block-list and cloak, so this app never
    loses sight of a pad mid-change. Returns the resulting state.
    """
    with _Control() as ctl:
        if ctl.get_bool(IOCTL_GET_WLINVERSE) and (allow_apps or hide):
            raise HidHideError("HidHide is in inverse mode, where its app list blocks instead of "
                               "allows. Turn inverse mode off in the HidHide Configuration Client.")
        allowed = ctl.get_list(IOCTL_GET_WHITELIST)
        add = [dos_to_nt(p) for p in allow_apps]
        drop = {dos_to_nt(p).lower() for p in disallow_apps}
        new_allowed = [p for p in allowed if p.lower() not in drop]
        new_allowed += [p for p in add if p.lower() not in {a.lower() for a in new_allowed}]
        if new_allowed != allowed:
            ctl.set_list(IOCTL_SET_WHITELIST, new_allowed)

        hidden = ctl.get_list(IOCTL_GET_BLACKLIST)
        gone = {d.upper() for d in unhide}
        new_hidden = [d for d in hidden if d.upper() not in gone]
        new_hidden += [d for d in hide if d.upper() not in {h.upper() for h in new_hidden}]
        if new_hidden != hidden:
            ctl.set_list(IOCTL_SET_BLACKLIST, new_hidden)

        if cloak is not None and cloak != ctl.get_bool(IOCTL_GET_ACTIVE):
            ctl.set_bool(IOCTL_SET_ACTIVE, cloak)
        return _read(ctl)


def hide_from_others(instance_ids: list[str]) -> HidHideState:
    """Hide these pads from every app except this one (allow self, block pads, cloak on)."""
    return apply(hide=instance_ids, allow_apps=[self_image_path()], cloak=True)


def unhide(instance_ids: list[str]) -> HidHideState:
    """Make these pads visible again. Cloak and our allow-list entry are left as they are,
    because other hidden devices may still depend on them."""
    return apply(unhide=instance_ids)
