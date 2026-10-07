"""DualSense and DualSense Edge.

Input (USB report 0x01; Bluetooth 0x31 is the same data shifted by one):

    1-4   LX LY RX RY      5-6   L2 R2      8 hat | face buttons
    9     L1 R1 L2 R2 create options L3 R3
    10    PS touchpad mute | (Edge) Fn-L Fn-R paddle-L paddle-R
    16-21 gyro  22-27 accel   33-36 touch 0   37-40 touch 1
    53    battery nibble | charging state nibble
"""

from __future__ import annotations

from dshub.core.pads.base import Capabilities, s16
from dshub.core.pads.hidpad import HidPad, bt_crc, mac_from
from dshub.core.pads.tables import DS5_EDGE_SYSTEM, DS5_SYSTEM, HAT_FACE, SHOULDERS, STICK, TRIGGER
from dshub.core.state import Battery, ControllerState, Touch

PID_DS5 = 0x0CE6
PID_EDGE = 0x0DF2

TOUCH_W, TOUCH_H = 1920, 1080

# Player indicator patterns (five LEDs under the touchpad).
PLAYER_PATTERNS = {0: 0x00, 1: 0x04, 2: 0x0A, 3: 0x15, 4: 0x1B, 5: 0x1F}


def _touch(data, i: int) -> Touch:
    b = data[i]
    x = data[i + 1] | ((data[i + 2] & 0x0F) << 8)
    y = (data[i + 2] >> 4) | (data[i + 3] << 4)
    return Touch(active=not (b & 0x80), id=b & 0x7F, x=min(x / TOUCH_W, 1.0), y=min(y / TOUCH_H, 1.0))


def _battery(status: int) -> Battery:
    level, charge = status & 0x0F, status >> 4
    if charge == 0x2:
        return Battery(level=100, full=True, wired=True)
    if charge == 0x1:
        return Battery(level=min(level * 10 + 5, 100), charging=True, wired=True)
    if charge == 0x0:
        return Battery(level=min(level * 10 + 5, 100))
    return Battery(level=None, wired=True)  # 0xA/0xB/0xF: temperature or charging error


_BATTERY = tuple(_battery(s) for s in range(256))


def signature(data, o: int) -> bytes:
    """Everything except the sticks, frame counters and motion data."""
    return bytes((*data[o + 4:o + 6], *data[o + 7:o + 10], data[o + 52], *data[o + 32:o + 40]))


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


def parse_ds5(data, o: int, edge: bool = False) -> ControllerState:
    """Parse a DualSense input report whose LX byte sits at ``data[o]``."""
    system = DS5_EDGE_SYSTEM if edge else DS5_SYSTEM
    return ControllerState(
        buttons=HAT_FACE[data[o + 7]] | SHOULDERS[data[o + 8]] | system[data[o + 9]],
        lx=STICK[data[o]], ly=STICK[data[o + 1]], rx=STICK[data[o + 2]], ry=STICK[data[o + 3]],
        l2=TRIGGER[data[o + 4]], r2=TRIGGER[data[o + 5]],
        gyro=(s16(data, o + 15), s16(data, o + 17), s16(data, o + 19)),
        accel=(s16(data, o + 21), s16(data, o + 23), s16(data, o + 25)),
        touches=(_touch(data, o + 32), _touch(data, o + 36)),
        battery=_BATTERY[data[o + 52]],
    )


class DualSense(HidPad):
    caps = Capabilities(lightbar=True, rumble=True, player_leds=True, touchpad=True, motion=True,
                        adaptive_triggers=True, battery_saver=True)

    #: Battery saver: rumble strength cap, and the output-report power-save bits we set.
    SAVER_RUMBLE = 0.5
    # Power-save control byte (common[9], enabled by valid_flag1 bit 0x02). Bit layout per the
    # community-documented DualSense output report: 0x01 touch, 0x02 motion sensors,
    # 0x04 haptics, 0x08 audio power save, 0x10 mic mute. We only sleep the motion sensors
    # (this app never reads them); touch stays on so the touchpad view keeps working.
    POWER_SAVE_MOTION = 0x02

    def __init__(self, *a, edge: bool = False, **kw) -> None:
        super().__init__(*a, **kw)
        self.edge = edge
        self._seq = 0
        self._released_lightbar = False

    def _handshake(self) -> None:
        # Feature 0x05 (calibration) also switches a BT DualSense to report 0x31.
        self._feature(0x05, 41)
        pairing = self._feature(0x09, 20)
        if pairing and len(pairing) >= 7:
            self.info.serial = mac_from(pairing, 1)
        fw = self._feature(0x20, 64)
        if fw and len(fw) >= 46:
            update = fw[44] | (fw[45] << 8)
            self.info.firmware = f"{update >> 8:02X}.{update & 0xFF:02X}"
        if self._lightbar is None:
            self._lightbar = (20, 60, 255)
        if self._player == 0:
            self._player = 1
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
        elif rid == 0x31 and len(data) >= 64:
            o = 2
        elif rid == 0x01:  # reduced BT report: sticks/buttons only, DS4-like layout
            from dshub.core.pads.ds4 import parse_ds4

            return parse_ds4(data, 1, full=False)
        else:
            return None
        sig = signature(data, o)
        if self.loss is not None:
            self.loss.see(data[o + 6], 256)  # sequence number
        if unchanged(data, o, sig, self._sig, self._sticks, 0 if self._listeners else 1):
            return None  # only motion, sequence or stick jitter changed
        self._sig, self._sticks = sig, (data[o], data[o + 1], data[o + 2], data[o + 3])
        return parse_ds5(data, o, self.edge)

    def _common(self) -> bytearray:
        """The 47-byte block shared by USB and BT output reports."""
        c = bytearray(47)
        strong, weak = self._rumble
        saver = self.battery_saver
        if saver:  # the voice-coil motors are the biggest drain after the light bar
            strong, weak = strong * self.SAVER_RUMBLE, weak * self.SAVER_RUMBLE
        c[0] = 0x01 | 0x02  # compatible vibration + haptics select
        c[1] = 0x04 | 0x10 | 0x02  # lightbar + player indicator + power-save control
        c[2] = int(weak * 255)
        c[3] = int(strong * 255)
        c[9] = self.POWER_SAVE_MOTION if saver else 0x00
        if not self._released_lightbar:
            # Fade out the boot animation so our colour takes over.
            c[38] = 0x02
            c[41] = 0x02
            self._released_lightbar = True
        c[42] = 0x02 if saver else 0x00  # player LED brightness: low / high
        c[43] = PLAYER_PATTERNS.get(self._player, 0)
        r, g, b = (0, 0, 0) if saver else (self._lightbar or (0, 0, 0))  # light bar off while saving
        c[44], c[45], c[46] = r, g, b
        return c

    def _send_output(self) -> None:
        common = self._common()
        if self.bluetooth:
            rep = bytearray(78)
            rep[0] = 0x31
            rep[1] = (self._seq << 4) & 0xF0
            rep[2] = 0x10
            rep[3:3 + len(common)] = common
            self._seq = (self._seq + 1) & 0x0F
            rep[74:78] = bt_crc(rep[:74]).to_bytes(4, "little")
        else:
            rep = bytearray(48)
            rep[0] = 0x02
            rep[1:1 + len(common)] = common
        self._write(rep)
