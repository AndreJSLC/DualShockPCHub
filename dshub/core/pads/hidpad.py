"""Pads read through hidapi (DS4, DS5, DS3 in DsHidMini SXS mode)."""

from __future__ import annotations

import threading
import zlib

import hid

from dshub.core.pads.base import Pad
from dshub.core.state import ControllerInfo

BT_HID_SERVICE = "00001124-0000-1000-8000-00805f9b34fb"


def is_bluetooth_path(path: bytes | str) -> bool:
    p = path.decode(errors="ignore") if isinstance(path, bytes) else path
    return BT_HID_SERVICE in p.lower()


def bt_crc(report: bytes | bytearray, seed: int = 0xA2) -> int:
    """CRC32 Sony appends to Bluetooth output reports (seeded with the HID
    transaction header byte: 0xA2 for output, 0xA3 for feature)."""
    return zlib.crc32(bytes(report), zlib.crc32(bytes([seed])))


class HidPad(Pad):
    READ_SIZE = 128
    READ_TIMEOUT_MS = 100

    def __init__(self, info: ControllerInfo, path: bytes) -> None:
        super().__init__(info, key=path.decode(errors="ignore"))
        self.path = path
        self.dev: hid.device | None = None
        self._write_lock = threading.Lock()
        self._nonblocking = False

    @property
    def bluetooth(self) -> bool:
        return is_bluetooth_path(self.path)

    def _open(self) -> None:
        self.dev = hid.device()
        self.dev.open_path(self.path)
        self._handshake()

    def _close(self) -> None:
        if self.dev is not None:
            dev, self.dev = self.dev, None
            dev.close()

    def _handshake(self) -> None:
        """Model-specific setup after opening (feature reads, initial output)."""

    #: With nobody remapping, only the UI (60 fps) or the battery readout needs
    #: the data, so wake at ~60 Hz and keep just the newest queued report.
    UI_PERIOD_S = 0.016

    def _read(self) -> list[int] | None:
        dev = self.dev
        if dev is None:
            raise OSError("closed")
        if self._listeners:
            # Remapping: block until each report arrives for minimal latency.
            if self._nonblocking:
                dev.set_nonblocking(0)
                self._nonblocking = False
            data = dev.read(self.READ_SIZE, self.READ_TIMEOUT_MS)
            if not data:
                return None
            self.raw_reports += 1
            return data
        if not self._nonblocking:
            dev.set_nonblocking(1)
            self._nonblocking = True
        if not self.low_power and self._wake.wait(self.UI_PERIOD_S):
            self._wake.clear()
        newest = None
        while True:  # drain what queued up since last time
            data = dev.read(self.READ_SIZE)
            if not data:
                break
            newest = data
            self.raw_reports += 1
        return newest

    def _write(self, report: bytes | bytearray) -> None:
        dev = self.dev
        if dev is None:
            return
        with self._write_lock:
            try:
                dev.write(bytes(report))
            except (OSError, ValueError):
                pass  # the reader thread notices disconnects

    def _feature(self, report_id: int, length: int) -> list[int] | None:
        dev = self.dev
        if dev is None:
            return None
        try:
            data = dev.get_feature_report(report_id, length)
        except (OSError, ValueError):
            return None
        return data or None


def mac_from(data, start: int) -> str:
    """6 little-endian bytes -> 'AA:BB:CC:DD:EE:FF'."""
    return ":".join(f"{data[start + i]:02X}" for i in reversed(range(6)))
