"""DualShock 2, straight-on: the DualShock 3 shell with the DS2's centre controls.

Same body, lobes, D-pad, face buttons, sticks and shoulders as ``ds3``. The
PS button and the player LEDs are gone; in their place sit the ANALOG button
with its red mode LED and the printed ANALOG label. The ANALOG button never
reaches the PC (it only switches the pad's own mode), so it is drawn as a
moulded detail rather than a clickable part.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF

from dshub.core.state import Button, Model
from dshub.ui.flat import ds3
from dshub.ui.flat.layout import FlatLayout, circle

ANALOG_C = QPointF(ds3.AX, 131.0)
ANALOG_R = 7.5


def build() -> FlatLayout:
    lay = ds3.build()
    lay.model = Model.DS2
    lay.parts = [part for part in lay.parts if part.button is not Button.PS]
    lay.pads.append(circle(ANALOG_C.x(), ANALOG_C.y(), ANALOG_R))  # ANALOG button (not reported to the PC)
    lay.leds = [QRectF(ds3.AX - 4.0, 117.0, 8.0, 3.6)]  # analog-mode LED
    lay.led_style = "ds2"
    lay.labels.append((QPointF(ds3.AX, 146.5), "ANALOG"))
    return lay
