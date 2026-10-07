"""DualSense Edge, straight-on: the DualSense body plus the Edge extras.

Same shell, plate, touchpad and controls as ``ds5`` (the Edge palette makes
the touchpad, keys and plate black). Adds the two Fn buttons just below the
sticks and the back paddles as tabs peeking out below the inner grips.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QTransform

from dshub.core.state import Button, Model
from dshub.ui.flat import ds5
from dshub.ui.flat.layout import FlatLayout, FlatPart, mirror, rrect

FN_DX, FN_Y = 58.0, 180.0  # just below each stick, near the plate's lower edge
PADDLE_C = QPointF(66.0, 299.0)  # left paddle tab centre (peeks out below the inner grip)


def _rotated(path: QPainterPath, centre: QPointF, angle: float) -> QPainterPath:
    t = QTransform().translate(centre.x(), centre.y()).rotate(angle).translate(-centre.x(), -centre.y())
    return t.map(path)


def build() -> FlatLayout:
    lay = ds5.build(Model.DS5_EDGE)
    lay.size = QRectF(0, 18, 2 * ds5.AX, 302)

    fn_l = _rotated(rrect(ds5.AX - FN_DX - 11, FN_Y - 4, 22, 8, 4), QPointF(ds5.AX - FN_DX, FN_Y), -12)
    lay.parts.append(FlatPart(Button.FN_L, fn_l))
    lay.parts.append(FlatPart(Button.FN_R, mirror(fn_l, ds5.AX)))

    paddle = _rotated(rrect(PADDLE_C.x() - 6.5, PADDLE_C.y() - 13, 13, 26, 6.5), PADDLE_C, 22)
    lay.behind += [FlatPart(Button.PADDLE_L, paddle, kind="paddle"),
                   FlatPart(Button.PADDLE_R, mirror(paddle, ds5.AX), kind="paddle")]
    return lay
