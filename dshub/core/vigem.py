"""Minimal pure-ctypes client for the ViGEmBus driver.

Creates virtual Xbox 360 pads that games see as real XInput controllers.
It talks to the bus with DeviceIoControl, mirroring the official
ViGEmClient, so we need neither a bundled DLL nor any installer.  The bus
driver itself (ViGEmBus) must already be installed.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import logging
import threading
import uuid
from collections.abc import Callable

log = logging.getLogger(__name__)

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_cfg = ctypes.WinDLL("cfgmgr32")

_k32.CreateFileW.restype = w.HANDLE
_k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
_k32.DeviceIoControl.argtypes = [w.HANDLE, w.DWORD, w.LPVOID, w.DWORD, w.LPVOID, w.DWORD,
                                 ctypes.POINTER(w.DWORD), w.LPVOID]
_k32.GetOverlappedResult.argtypes = [w.HANDLE, w.LPVOID, ctypes.POINTER(w.DWORD), w.BOOL]
_k32.CreateEventW.restype = w.HANDLE
_k32.CreateEventW.argtypes = [w.LPVOID, w.BOOL, w.BOOL, w.LPCWSTR]
_k32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
_k32.CancelIoEx.argtypes = [w.HANDLE, w.LPVOID]
_k32.CloseHandle.argtypes = [w.HANDLE]

INVALID_HANDLE_VALUE = w.HANDLE(-1).value
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0

GUID_DEVINTERFACE_BUSENUM_VIGEM = uuid.UUID("96E42B22-F5E9-42F8-B043-ED0F932F014F")


def _ctl_code(function: int, access: int) -> int:
    file_device_bus_extender = 0x2A
    return (file_device_bus_extender << 16) | (access << 14) | (function << 2)  # METHOD_BUFFERED


_W, _RW = 0x2, 0x3  # FILE_WRITE_DATA, FILE_READ_DATA | FILE_WRITE_DATA
IOCTL_VIGEM_PLUGIN_TARGET = _ctl_code(0x801, _W)
IOCTL_VIGEM_UNPLUG_TARGET = _ctl_code(0x802, _W)
IOCTL_VIGEM_CHECK_VERSION = _ctl_code(0x803, _W)
IOCTL_VIGEM_WAIT_DEVICE_READY = _ctl_code(0x804, _W)
IOCTL_XUSB_REQUEST_NOTIFICATION = _ctl_code(0xA01, _RW)
IOCTL_XUSB_SUBMIT_REPORT = _ctl_code(0xA02, _W)

VIGEM_COMMON_VERSION = 0x0001
TARGET_X360 = 0


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", w.BYTE * 8)]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", w.DWORD), ("OffsetHigh", w.DWORD), ("hEvent", w.HANDLE)]


class VIGEM_CHECK_VERSION(ctypes.Structure):
    _fields_ = [("Size", w.ULONG), ("Version", w.ULONG)]


class VIGEM_PLUGIN_TARGET(ctypes.Structure):
    _fields_ = [("Size", w.ULONG), ("SerialNo", w.ULONG), ("TargetType", ctypes.c_int),
                ("VendorId", w.USHORT), ("ProductId", w.USHORT)]


class VIGEM_UNPLUG_TARGET(ctypes.Structure):
    _fields_ = [("Size", w.ULONG), ("SerialNo", w.ULONG)]


VIGEM_WAIT_DEVICE_READY = VIGEM_UNPLUG_TARGET  # same layout


class XUSB_REPORT(ctypes.Structure):
    _fields_ = [("wButtons", w.USHORT), ("bLeftTrigger", w.BYTE), ("bRightTrigger", w.BYTE),
                ("sThumbLX", w.SHORT), ("sThumbLY", w.SHORT), ("sThumbRX", w.SHORT), ("sThumbRY", w.SHORT)]


class XUSB_SUBMIT_REPORT(ctypes.Structure):
    _fields_ = [("Size", w.ULONG), ("SerialNo", w.ULONG), ("Report", XUSB_REPORT)]


class XUSB_REQUEST_NOTIFICATION(ctypes.Structure):
    _fields_ = [("Size", w.ULONG), ("SerialNo", w.ULONG), ("LargeMotor", w.BYTE),
                ("SmallMotor", w.BYTE), ("LedNumber", w.BYTE)]


class ViGEmError(OSError):
    pass


def bus_paths() -> list[str]:
    guid = _GUID.from_buffer_copy(GUID_DEVINTERFACE_BUSENUM_VIGEM.bytes_le)
    size = w.ULONG()
    if _cfg.CM_Get_Device_Interface_List_SizeW(ctypes.byref(size), ctypes.byref(guid), None, 0) != 0:
        return []
    buf = ctypes.create_unicode_buffer(size.value)
    if _cfg.CM_Get_Device_Interface_ListW(ctypes.byref(guid), None, buf, size, 0) != 0:
        return []
    return [p for p in buf[: size.value].split("\0") if p]


def bus_available() -> bool:
    return bool(bus_paths())


class _Handle:
    """An overlapped handle to the bus; closing it unplugs everything it owns."""

    def __init__(self) -> None:
        self.h = None
        for path in bus_paths():
            h = _k32.CreateFileW(path, 0xC0000000, 0x3, None, 3, 0x40000000 | 0x80, None)  # RW, share RW, OVERLAPPED
            if h in (None, INVALID_HANDLE_VALUE):
                continue
            self.h = h
            ver = VIGEM_CHECK_VERSION(ctypes.sizeof(VIGEM_CHECK_VERSION), VIGEM_COMMON_VERSION)
            if self.ioctl(IOCTL_VIGEM_CHECK_VERSION, ver):
                return
            _k32.CloseHandle(h)
            self.h = None
        raise ViGEmError("ViGEmBus driver not found or incompatible")

    def ioctl(self, code: int, inbuf: ctypes.Structure, outbuf: ctypes.Structure | None = None,
              stop: threading.Event | None = None) -> bool:
        ev = _k32.CreateEventW(None, True, False, None)
        ov = _OVERLAPPED()
        ov.hEvent = ev
        transferred = w.DWORD()
        out_ptr = ctypes.byref(outbuf) if outbuf is not None else None
        out_len = ctypes.sizeof(outbuf) if outbuf is not None else 0
        try:
            ok = _k32.DeviceIoControl(self.h, code, ctypes.byref(inbuf), ctypes.sizeof(inbuf), out_ptr, out_len,
                                      ctypes.byref(transferred), ctypes.byref(ov))
            if ok:
                return True
            if ctypes.get_last_error() != ERROR_IO_PENDING:
                return False
            if stop is not None:  # cancellable wait (rumble notifications pend indefinitely)
                while _k32.WaitForSingleObject(ev, 200) != WAIT_OBJECT_0:
                    if stop.is_set():
                        _k32.CancelIoEx(self.h, ctypes.byref(ov))
                        _k32.GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(transferred), True)
                        return False
            return bool(_k32.GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(transferred), True))
        finally:
            _k32.CloseHandle(ev)

    def close(self) -> None:
        if self.h:
            _k32.CloseHandle(self.h)
            self.h = None


class X360Pad:
    """A virtual Xbox 360 controller.

    ``rumble_callback(large, small)`` receives motor speeds 0..1 when a game
    vibrates the virtual pad, so we can forward it to the physical one.
    """

    def __init__(self, rumble_callback: Callable[[float, float], None] | None = None) -> None:
        self._bus = _Handle()
        self.serial = 0
        for serial in range(1, 64):
            plug = VIGEM_PLUGIN_TARGET(ctypes.sizeof(VIGEM_PLUGIN_TARGET), serial, TARGET_X360, 0x045E, 0x028E)
            if self._bus.ioctl(IOCTL_VIGEM_PLUGIN_TARGET, plug):
                self.serial = serial
                break
        if not self.serial:
            self._bus.close()
            raise ViGEmError("could not plug a virtual Xbox 360 pad (no free slot)")
        self._bus.ioctl(IOCTL_VIGEM_WAIT_DEVICE_READY,
                        VIGEM_WAIT_DEVICE_READY(ctypes.sizeof(VIGEM_WAIT_DEVICE_READY), self.serial))
        self._report = XUSB_SUBMIT_REPORT(ctypes.sizeof(XUSB_SUBMIT_REPORT), self.serial)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._rumble_cb = rumble_callback
        self._notify: threading.Thread | None = None
        if rumble_callback is not None:
            self._notify = threading.Thread(target=self._notifications, name="vigem-rumble", daemon=True)
            self._notify.start()

    def submit(self, buttons: int, lt: int, rt: int, lx: int, ly: int, rx: int, ry: int) -> None:
        with self._lock:
            r = self._report.Report
            r.wButtons, r.bLeftTrigger, r.bRightTrigger = buttons & 0xFFFF, lt, rt
            r.sThumbLX, r.sThumbLY, r.sThumbRX, r.sThumbRY = lx, ly, rx, ry
            if self._bus.h:
                self._bus.ioctl(IOCTL_XUSB_SUBMIT_REPORT, self._report)

    def _notifications(self) -> None:
        while not self._stop.is_set():
            req = XUSB_REQUEST_NOTIFICATION(ctypes.sizeof(XUSB_REQUEST_NOTIFICATION), self.serial)
            if not self._bus.ioctl(IOCTL_XUSB_REQUEST_NOTIFICATION, req, req, stop=self._stop):
                if self._stop.wait(0.05):
                    return
                continue
            try:
                self._rumble_cb(req.LargeMotor / 255.0, req.SmallMotor / 255.0)
            except Exception:  # noqa: BLE001
                log.exception("rumble callback failed")

    def close(self) -> None:
        self._stop.set()
        if self._notify:
            self._notify.join(timeout=1)
        with self._lock:
            if self.serial and self._bus.h:
                self._bus.ioctl(IOCTL_VIGEM_UNPLUG_TARGET,
                                VIGEM_UNPLUG_TARGET(ctypes.sizeof(VIGEM_UNPLUG_TARGET), self.serial))
            self._bus.close()
