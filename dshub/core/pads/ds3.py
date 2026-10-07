"""DualShock 3 / SIXAXIS.

Windows has no in-box DS3 support; we rely on Nefarius' DsHidMini driver,
which can present the pad in several HID modes:

* **SXS** - raw SIXAXIS report over HID. We read it with hidapi and get
  everything, including the analog pressure of every face/D-pad button.
* **XInput** - shows up as an Xbox pad. Best for game compatibility; we read
  it through XInput (no pressure / motion) and pull battery level from the
  DsHidMini device properties.
"""

from __future__ import annotations

import time

from dshub.core import winapi
from dshub.core.pads.base import Capabilities, Pad, stick
from dshub.core.pads.hidpad import HidPad
from dshub.core.state import Battery, Button, ControllerInfo, ControllerState

PID_DS3 = 0x0268

# DsHidMini battery codes -> (percent, charging, full)
_BATTERY = {
    0x00: (0, False, False),
    0x01: (5, False, False),
    0x02: (25, False, False),
    0x03: (50, False, False),
    0x04: (75, False, False),
    0x05: (100, False, False),
    0xEE: (None, True, False),
    0xEF: (100, False, True),
}


def ds3_battery(code: int | None, wired: bool) -> Battery:
    if code is None or code not in _BATTERY:
        return Battery(wired=wired)
    level, charging, full = _BATTERY[code]
    return Battery(level=level, charging=charging, full=full, wired=wired or charging or full)


# ---------------------------------------------------------------- SXS (HID)

_SXS_B2 = ((0x01, Button.SELECT), (0x02, Button.L3), (0x04, Button.R3), (0x08, Button.START),
           (0x10, Button.DPAD_UP), (0x20, Button.DPAD_RIGHT), (0x40, Button.DPAD_DOWN),
           (0x80, Button.DPAD_LEFT))
_SXS_B3 = ((0x01, Button.L2), (0x02, Button.R2), (0x04, Button.L1), (0x08, Button.R1),
           (0x10, Button.TRIANGLE), (0x20, Button.CIRCLE), (0x40, Button.CROSS), (0x80, Button.SQUARE))
_SXS_PRESSURE = ((14, Button.DPAD_UP), (15, Button.DPAD_RIGHT), (16, Button.DPAD_DOWN), (17, Button.DPAD_LEFT),
                 (20, Button.L1), (21, Button.R1), (22, Button.TRIANGLE), (23, Button.CIRCLE),
                 (24, Button.CROSS), (25, Button.SQUARE))


def _be16(data, i: int) -> int:
    return (data[i] << 8) | data[i + 1]


def parse_sxs(data) -> ControllerState:
    """Original SIXAXIS input report 0x01 (49 bytes, report id at [0])."""
    btn: set[Button] = set()
    for mask, name in _SXS_B2:
        if data[2] & mask:
            btn.add(name)
    for mask, name in _SXS_B3:
        if data[3] & mask:
            btn.add(name)
    if data[4] & 0x01:
        btn.add(Button.PS)
    pressure = {name: data[i] / 255.0 for i, name in _SXS_PRESSURE if data[i]}
    st = ControllerState(
        buttons=frozenset(btn),
        lx=stick(data[6]), ly=stick(data[7]), rx=stick(data[8]), ry=stick(data[9]),
        l2=data[18] / 255.0, r2=data[19] / 255.0,
        pressure=pressure,
        battery=ds3_battery(data[30], wired=data[29] == 0x02),
    )
    if len(data) >= 49:
        st.accel = (_be16(data, 41) - 512, _be16(data, 43) - 512, _be16(data, 45) - 512)
        st.gyro = (0, 0, _be16(data, 47) - 498)
    return st


_SXS12_B0 = ((0x01, Button.TRIANGLE), (0x02, Button.CIRCLE), (0x04, Button.CROSS), (0x08, Button.SQUARE),
             (0x10, Button.L2), (0x20, Button.R2), (0x40, Button.L1), (0x80, Button.R1))
_SXS12_B1 = ((0x01, Button.START), (0x02, Button.SELECT), (0x04, Button.L3), (0x08, Button.R3),
             (0x10, Button.PS))


def parse_sxs12(data, triggers_inverted: bool) -> ControllerState:
    """DsHidMini SXS-mode input: 12 bytes, no report id (layout from DsHidMini
    source; the analog trigger bytes are stored inverted)."""
    from dshub.core.pads.base import hat_to_dpad

    btn: set[Button] = {name for mask, name in _SXS12_B0 if data[0] & mask}
    btn |= {name for mask, name in _SXS12_B1 if data[1] & mask}
    up, right, down, left = hat_to_dpad(data[3] & 0x0F)
    for flag, name in ((up, Button.DPAD_UP), (right, Button.DPAD_RIGHT), (down, Button.DPAD_DOWN),
                       (left, Button.DPAD_LEFT)):
        if flag:
            btn.add(name)

    def trig(v: int) -> float:
        return (255 - v) / 255.0 if triggers_inverted else v / 255.0

    return ControllerState(
        buttons=frozenset(btn),
        lx=stick(data[4]), ly=stick(data[5]), rx=stick(data[6]), ry=stick(data[7]),
        l2=trig(data[10]), r2=trig(data[11]),
    )


class DualShock3Hid(HidPad):
    """DS3 under DsHidMini SXS mode (or a 49-byte raw SIXAXIS report)."""

    caps = Capabilities(rumble=True, player_leds=True, motion=True, pressure=True)

    def __init__(self, *a, devnode: str | None = None, **kw) -> None:
        super().__init__(*a, **kw)
        self.devnode = devnode
        self._inverted: bool | None = None
        self._battery = Battery()
        self._battery_at = 0.0

    def _handshake(self) -> None:
        if self._player == 0:
            self._player = self.info.slot or 1

    def _poll(self) -> ControllerState | None:
        data = self._read()
        if data is None:
            return None
        if len(data) >= 31 and data[0] == 0x01:
            return parse_sxs(data)
        if len(data) >= 12:
            if self._inverted is None:  # triggers rest at 0xFF when stored inverted
                self._inverted = data[10] > 0x80 and data[11] > 0x80
            st = parse_sxs12(data, self._inverted)
            if time.monotonic() - self._battery_at > 5.0 and self.devnode:
                self._battery_at = time.monotonic()
                raw = winapi.devnode_property(self.devnode, winapi.DSHM_BATTERY)
                self._battery = ds3_battery(raw[0] if raw else None,
                                            wired=not self.devnode.upper().startswith("BTHPS3BUS"))
            st.battery = self._battery
            return st
        return None

    def _send_output(self) -> None:
        strong, weak = self._rumble
        rep = bytearray(49)
        rep[0] = 0x01
        rep[2] = 0xFF if weak else 0  # right (weak) motor: duration
        rep[3] = 1 if weak > 0.1 else 0  # right motor is on/off only
        rep[4] = 0xFF if strong else 0
        rep[5] = int(strong * 255)
        rep[10] = (1 << self._player) & 0x1E if 1 <= self._player <= 4 else 0
        for i in range(4):  # per-LED blink params: always on
            base = 11 + i * 5
            rep[base:base + 5] = b"\xff\x27\x10\x00\x32"
        self._write(rep)


# ---------------------------------------------------------------- XInput

_XI_MAP = (
    ("dpad_up", Button.DPAD_UP), ("dpad_down", Button.DPAD_DOWN), ("dpad_left", Button.DPAD_LEFT),
    ("dpad_right", Button.DPAD_RIGHT), ("start", Button.START), ("back", Button.SELECT),
    ("ls", Button.L3), ("rs", Button.R3), ("lb", Button.L1), ("rb", Button.R1), ("guide", Button.PS),
    ("a", Button.CROSS), ("b", Button.CIRCLE), ("x", Button.SQUARE), ("y", Button.TRIANGLE),
)

#: VID/PID pairs an XInput slot reports when it is a DsHidMini DS3.
DSHM_XINPUT_IDS = {(0x054C, 0x0268), (0x7331, 0x0002)}
#: DsHidMini 3.x "XInputHID" mode uses Microsoft's generic id; only trust it
#: when DsHidMini actually has a DS3 in XInput mode.
XINPUT_HID_GENERIC = (0x045E, 0x02FF)


def _thumb(v: int, invert: bool = False) -> float:
    f = v / 32767.0
    f = max(-1.0, min(1.0, f))
    if abs(f) < 0.008:
        f = 0.0
    return -f if invert else f


class DualShock3XInput(Pad):
    """DS3 under DsHidMini XInput mode, read via the XInput API."""

    caps = Capabilities(rumble=True)
    # XInput has no "wait for input" call, so we poll. 125 Hz while remapping
    # (below the DS3's own report rate), 60 Hz when only the UI is watching.
    POLL_REMAP_S = 0.008
    POLL_UI_S = 0.016

    def __init__(self, info: ControllerInfo, slot: int, devnode: str | None,
                 ids: tuple[int, int] | None = None) -> None:
        super().__init__(info, key=f"xinput:{slot}")
        self.xslot = slot
        self.ids = ids
        self.devnode = devnode
        self._packet = -1
        self._battery = Battery()
        self._battery_at = 0.0
        self._ids_at = 0.0

    def _open(self) -> None:
        self._xi = winapi.xinput()
        self._refresh_battery()

    def _close(self) -> None:
        try:
            self._xi.set_vibration(self.xslot, 0, 0)
        except OSError:
            pass

    def _refresh_battery(self) -> None:
        self._battery_at = time.monotonic()
        if not self.devnode:
            return
        raw = winapi.devnode_property(self.devnode, winapi.DSHM_BATTERY)
        bluetooth = self.devnode.upper().startswith("BTHPS3BUS")
        self._battery = ds3_battery(raw[0] if raw else None, wired=not bluetooth)

    def _poll(self) -> ControllerState | None:
        time.sleep(self.POLL_REMAP_S if self._listeners else self.POLL_UI_S)
        st = self._xi.get_state(self.xslot)
        if st is None:
            raise OSError("xinput slot disconnected")
        now = time.monotonic()
        if now - self._ids_at > 0.25:
            # Windows can reshuffle XInput slots when another pad (e.g. our own
            # virtual Xbox pad) arrives; never read someone else's slot.
            self._ids_at = now
            if self._xi.ids(self.xslot) != self.ids:
                raise OSError("xinput slot reassigned")
        if now - self._battery_at > 5.0:
            self._refresh_battery()
            self._packet = -1  # force a state refresh so the battery change shows
        if st.dwPacketNumber == self._packet:
            return None
        self._packet = st.dwPacketNumber
        gp = st.Gamepad
        btn = frozenset(name for key, name in _XI_MAP if gp.wButtons & winapi.XINPUT_BUTTONS[key])
        l2, r2 = gp.bLeftTrigger / 255.0, gp.bRightTrigger / 255.0
        if l2 > 0.12:
            btn |= {Button.L2}
        if r2 > 0.12:
            btn |= {Button.R2}
        return ControllerState(
            buttons=btn,
            lx=_thumb(gp.sThumbLX), ly=_thumb(gp.sThumbLY, invert=True),
            rx=_thumb(gp.sThumbRX), ry=_thumb(gp.sThumbRY, invert=True),
            l2=l2, r2=r2,
            battery=self._battery,
        )

    def _send_output(self) -> None:
        strong, weak = self._rumble
        self._xi.set_vibration(self.xslot, strong, weak)


# ---------------------------------------------------------------- DS4Windows mode

#: DsHidMini's "DS4Windows" mode: a vendor-defined device Steam and games
#: ignore, carrying a DS4-layout report. Ideal for "only this app sees the pad".
DS4W_VID, DS4W_PID = 0x7331, 0x0001


class DualShock3DS4Mode(HidPad):
    caps = Capabilities(rumble=True)

    def __init__(self, *a, devnode: str | None = None, **kw) -> None:
        super().__init__(*a, **kw)
        self.devnode = devnode
        self._battery = Battery()
        self._battery_at = 0.0

    def _poll(self) -> ControllerState | None:
        from dshub.core.pads.ds4 import parse_ds4

        data = self._read()
        if data is None:
            return None
        if data[0] == 0x01 and len(data) >= 64:
            st = parse_ds4(data, 1)
        elif len(data) >= 63:
            st = parse_ds4(data, 0)
        else:
            return None
        st.touches = ControllerState().touches  # a DS3 has no touchpad
        if time.monotonic() - self._battery_at > 5.0 and self.devnode:
            self._battery_at = time.monotonic()
            raw = winapi.devnode_property(self.devnode, winapi.DSHM_BATTERY)
            self._battery = ds3_battery(raw[0] if raw else None,
                                        wired=not self.devnode.upper().startswith("BTHPS3BUS"))
        st.battery = self._battery
        return st

    def _send_output(self) -> None:
        strong, weak = self._rumble
        rep = bytearray(32)
        rep[0] = 0x05
        rep[1] = 0x01  # rumble only
        rep[4] = int(weak * 255)
        rep[5] = int(strong * 255)
        self._write(rep)
