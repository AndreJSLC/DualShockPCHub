"""Precomputed byte -> value tables so report parsing is a few lookups.

A DS4/DualSense sends hundreds of reports per second; decoding bit by bit in
Python costs real CPU while a game is running, table lookups barely any.
"""

from __future__ import annotations

from dshub.core.pads.base import hat_to_dpad, stick
from dshub.core.state import Button

#: 0..255 HID axis -> -1..1
STICK = tuple(stick(v) for v in range(256))
#: 0..255 trigger -> 0..1
TRIGGER = tuple(v / 255.0 for v in range(256))


def _bits(table: tuple[tuple[int, Button], ...]) -> tuple[frozenset[Button], ...]:
    return tuple(frozenset(name for mask, name in table if v & mask) for v in range(256))


def _hat_face() -> tuple[frozenset[Button], ...]:
    out = []
    for v in range(256):
        up, right, down, left = hat_to_dpad(v & 0x0F)
        s = {name for flag, name in ((up, Button.DPAD_UP), (right, Button.DPAD_RIGHT),
                                     (down, Button.DPAD_DOWN), (left, Button.DPAD_LEFT)) if flag}
        s |= {name for mask, name in ((0x10, Button.SQUARE), (0x20, Button.CROSS), (0x40, Button.CIRCLE),
                                      (0x80, Button.TRIANGLE)) if v & mask}
        out.append(frozenset(s))
    return tuple(out)


#: DS4 byte 5 / DualSense byte 8: hat in the low nibble, face buttons above.
HAT_FACE = _hat_face()
#: DS4 byte 6 / DualSense byte 9.
SHOULDERS = _bits(((0x01, Button.L1), (0x02, Button.R1), (0x04, Button.L2), (0x08, Button.R2),
                   (0x10, Button.SELECT), (0x20, Button.START), (0x40, Button.L3), (0x80, Button.R3)))
#: DS4 byte 7 (low two bits; the rest is a frame counter).
DS4_SYSTEM = _bits(((0x01, Button.PS), (0x02, Button.TOUCHPAD)))
#: DualSense byte 10.
DS5_SYSTEM = _bits(((0x01, Button.PS), (0x02, Button.TOUCHPAD), (0x04, Button.MUTE)))
DS5_EDGE_SYSTEM = _bits(((0x01, Button.PS), (0x02, Button.TOUCHPAD), (0x04, Button.MUTE), (0x10, Button.FN_L),
                         (0x20, Button.FN_R), (0x40, Button.PADDLE_L), (0x80, Button.PADDLE_R)))
