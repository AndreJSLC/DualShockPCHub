"""DualShock 2 adapters: identification and report parsing (no hardware needed)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dshub.core import hid_descriptor as H  # noqa: E402
from dshub.core.pads.ds2 import FAMILY_W, DualShock2, find_adapter  # noqa: E402
from dshub.core.state import Button, Connection, ControllerInfo, Model  # noqa: E402

# A Twin-USB-style descriptor: report id 1; X, Y, Z, Rz (8 bit each); hat (4 bit) + 12 buttons; padding.
TWIN_USB = bytes([
    0x05, 0x01, 0x09, 0x04, 0xA1, 0x01, 0x85, 0x01,
    0x15, 0x00, 0x26, 0xFF, 0x00, 0x75, 0x08, 0x95, 0x04,
    0x09, 0x30, 0x09, 0x31, 0x09, 0x32, 0x09, 0x35, 0x81, 0x02,
    0x15, 0x00, 0x25, 0x07, 0x75, 0x04, 0x95, 0x01, 0x09, 0x39, 0x81, 0x42,
    0x05, 0x09, 0x19, 0x01, 0x29, 0x0C, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x0C, 0x81, 0x02,
    0x75, 0x08, 0x95, 0x01, 0x81, 0x03, 0xC0,
])


def test_identifies_adapters_but_not_lookalike_gamepads() -> None:
    assert find_adapter(0x0810, 0x0001, "Twin USB Joystick").name == "Twin USB"
    assert find_adapter(0x0925, 0x8866, "MP-8866 Dual USB Joypad").mapping is FAMILY_W
    assert find_adapter(0x2563, 0x0575, "ShanWan PC/PS3/Android") is None  # ordinary ShanWan pad
    assert find_adapter(0x0E8F, 0x0003, "USB Joystick") is None  # shared GreenAsia id without the 2In1 name
    assert find_adapter(0x1234, 0x5678, "Generic PS2 Adapter") is not None  # name hint for unknown boxes
    assert find_adapter(0x045E, 0x028E, "Controller (XBOX 360 For Windows)") is None


def test_parses_a_twin_usb_report() -> None:
    lay = H.parse(TWIN_USB)
    assert lay.uses_report_ids and lay.report_ids() == [1] and len(lay.buttons(1)) == 12
    pad = DualShock2(ControllerInfo(uid="t", model=Model.DS2, connection=Connection.USB, name="DS2"),
                     b"fake", find_adapter(0x0810, 0x0001, "Twin USB Joystick"), 1)
    pad._layout = lay  # noqa: SLF001 - skip opening a device

    class Dev:  # stand-in for hidapi
        def get_report_descriptor(self):
            return list(TWIN_USB)

    pad.dev = Dev()
    pad._handshake()  # noqa: SLF001
    # report: id 1, X=255 (left stick right), Y=128, Z=0 (right stick up), Rz=128,
    # hat=2 (right) | buttons: 1 (triangle), 9 (select), 12 (R3)
    hat_and_buttons = 2 | (1 << 4) | (1 << (4 + 8)) | (1 << (4 + 11))
    report = [1, 255, 128, 0, 128] + list(hat_and_buttons.to_bytes(2, "little")) + [0]
    pad._read = lambda: report  # noqa: SLF001
    st = pad._poll()  # noqa: SLF001
    assert st.buttons == {Button.TRIANGLE, Button.SELECT, Button.R3, Button.DPAD_RIGHT}
    assert st.lx > 0.99 and abs(st.ly) < 0.01
    assert st.ry < -0.99 and abs(st.rx) < 0.01  # Twin USB: right stick X = Rz, Y = Z
