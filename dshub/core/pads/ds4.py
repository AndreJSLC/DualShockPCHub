"""DualShock 4 (CUH-ZCT1 / CUH-ZCT2 and the Sony wireless adapter).

Report layout (USB report 0x01; Bluetooth report 0x11 is the same data
shifted by two bytes):

    1-4   LX LY RX RY            8-9   L2 R2 analog
    5     hat | square cross circle triangle
    6     L1 R1 L2 R2 share options L3 R3
    7     PS | touchpad click | counter
    13-18 gyro, 19-24 accel      30    battery nibble | 0x10 cable
    35-38 touch 0, 39-42 touch 1
"""

from __future__ import annotations

from dshub.core.pads.base import Capabilities, s16
from dshub.core.pads.hidpad import HidPad, bt_crc, mac_from
from dshub.core.pads.tables import DS4_SYSTEM, HAT_FACE, SHOULDERS, STICK, TRIGGER
from dshub.core.state import Battery, ControllerState, Touch

PIDS = {0x05C4: "v1", 0x09CC: "v2", 0x0BA0: "adapter"}

TOUCH_W, TOUCH_H = 1920, 943


def _touch(data, i: int) -> Touch:
    b = data[i]
    x = data[i + 1] | ((data[i + 2] & 0x0F) << 8)
    y = (data[i + 2] >> 4) | (data[i + 3] << 4)
    return Touch(active=not (b & 0x80), id=b & 0x7F, x=min(x / TOUCH_W, 1.0), y=min(y / TOUCH_H, 1.0))


def _battery(status: int) -> Battery:
    raw = status & 0x0F
    if status & 0x10:  # cable
        return Battery(level=min(raw * 10, 100), charging=raw <= 10, full=raw > 10, wired=True)
    return Battery(level=min(raw * 100 // 8, 100))


_BATTERY = tuple(_battery(s) for s in range(256))


def signature(data, o: int) -> bytes:
    """Buttons, triggers, battery and touch: everything except the sticks,
    the frame counter (top bits of byte o+6) and motion data."""
    return bytes((data[o + 4], data[o + 5], data[o + 6] & 0x03, data[o + 7], data[o + 8], data[o + 29], *data[o + 34:o + 42]))


def unchanged(data, o: int, sig: bytes, last_sig: bytes, last_sticks: tuple, tol: int = 1) -> bool:
    """True when a report carries no new input worth parsing.

    Sticks jitter by one step at rest; with ``tol=1`` a +/-1 change against
    the last parsed report is ignored (fine for the UI). Remapping passes
    ``tol=0`` so games get every step of slow, precise stick movement.
    """
    if sig != last_sig or not last_sticks:
        return False
    a, b, c, d = data[o], data[o + 1], data[o + 2], data[o + 3]
    la, lb, lc, ld = last_sticks
    return abs(a - la) <= tol and abs(b - lb) <= tol and abs(c - lc) <= tol and abs(d - ld) <= tol


def parse_ds4(data, o: int, full: bool = True) -> ControllerState:
    """Parse a DS4 input report whose LX byte sits at ``data[o]``."""
    st = ControllerState(
        buttons=HAT_FACE[data[o + 4]] | SHOULDERS[data[o + 5]] | DS4_SYSTEM[data[o + 6]],
        lx=STICK[data[o]], ly=STICK[data[o + 1]], rx=STICK[data[o + 2]], ry=STICK[data[o + 3]],
        l2=TRIGGER[data[o + 7]], r2=TRIGGER[data[o + 8]],
    )
    if not full:
        return st
    st.gyro = (s16(data, o + 12), s16(data, o + 14), s16(data, o + 16))
    st.accel = (s16(data, o + 18), s16(data, o + 20), s16(data, o + 22))
    st.battery = _BATTERY[data[o + 29]]
    st.touches = (_touch(data, o + 34), _touch(data, o + 38))
    return st


class DualShock4(HidPad):
    caps = Capabilities(lightbar=True, rumble=True, touchpad=True, motion=True)

    def _handshake(self) -> None:
        if self.bluetooth:
            # Reading the calibration feature report flips a BT-connected DS4
            # from the reduced 0x01 report into the full 0x11 report.
            self._feature(0x05, 41)
        else:
            pairing = self._feature(0x12, 16)
            if pairing and len(pairing) >= 16:
                self.info.serial = mac_from(pairing, 1)
            fw = self._feature(0xA3, 49)
            if fw and len(fw) >= 20:
                date = bytes(fw[1:17]).split(b"\0")[0].decode(errors="ignore").strip()
                if date:
                    self.info.firmware = f"build {date}"
        if self._lightbar is None:
            self._lightbar = (20, 60, 255)
        self._send_output()

    _sig: bytes = b""
    _sticks: tuple = ()

    def _poll(self) -> ControllerState | None:
        data = self._read()
        if data is None:
            return None
        rid = data[0]
        if rid == 0x01 and len(data) >= 64:
            o = 1
        elif rid == 0x11 and len(data) >= 66:
            o = 3
        elif rid == 0x01:  # reduced BT report before the handshake took effect
            return parse_ds4(data, 1, full=False)
        else:
            return None
        sig = signature(data, o)
        if self.loss is not None:
            self.loss.see(data[o + 6] >> 2, 64)  # 6-bit frame counter
        if unchanged(data, o, sig, self._sig, self._sticks, 0 if self._listeners else 1):
            return None  # only motion, counters or stick jitter changed
        self._sig, self._sticks = sig, (data[o], data[o + 1], data[o + 2], data[o + 3])
        return parse_ds4(data, o)

    def _send_output(self) -> None:
        r, g, b = self._lightbar or (0, 0, 0)
        strong, weak = self._rumble
        if self.bluetooth:
            rep = bytearray(78)
            rep[0] = 0x11
            rep[1] = 0xC0 | 0x04  # enable HID + CRC, 4 ms poll interval
            rep[3] = 0x07  # rumble | lightbar | flash
            rep[6] = int(weak * 255)
            rep[7] = int(strong * 255)
            rep[8], rep[9], rep[10] = r, g, b
            crc = bt_crc(rep[:74])
            rep[74:78] = crc.to_bytes(4, "little")
        else:
            rep = bytearray(32)
            rep[0] = 0x05
            rep[1] = 0x07
            rep[4] = int(weak * 255)
            rep[5] = int(strong * 255)
            rep[6], rep[7], rep[8] = r, g, b
        self._write(rep)
