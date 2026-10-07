"""DualShock 3, straight-on, in drawing units (~400 x 250, centre line x = 201).

Built from simple geometry: two round lobes (D-pad / face buttons), a centre
bridge, two stick rings, two long grips and the L1/R1 + L2/R2 tabs.
Proportions follow the real pad (157 x 95 mm body).
"""

from __future__ import annotations

from math import cos, radians, sin

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath

from dshub.core.state import Button, Model
from dshub.ui.flat.layout import (FlatLayout, FlatPart, FlatStick, circle, mirror, polygon, rounded_polygon, rrect,
                                  smooth_closed, union)

AX = 201.0  # centre line
LOBE_DX, LOBE_Y, LOBE_R = 117.5, 93.5, 61.8
STICK_DX, STICK_Y = 57.5, 154.0
RING_R, GAP_R, CAP_R = 39.0, 30.0, 27.0
BRIDGE_TOP, BRIDGE_BOTTOM, BRIDGE_HALF = 41.6, 170.5, 84.5
FACE_SPREAD, FACE_R = 29.0, 13.0
DPAD_REACH, DPAD_HALF_W = 30.5, 8.5
CROSS_HALF_LEN, CROSS_HALF_W = 46.5, 17.5


def _grip_left() -> QPainterPath:
    # outer edge runs almost straight down from the lobe, rounds off at the
    # bottom, and the inner edge climbs back to the stick housing
    return smooth_closed([
        (24, 70), (19, 105), (13, 145), (7.5, 185), (4.5, 210), (8, 231), (22, 245.5), (47, 250),
        (67, 246), (81.5, 236), (93.5, 216), (103.5, 196), (112, 181), (122, 169), (150, 130), (100, 60),
    ], tension=1.0)


def _bumper_left(lift: float = 0.0, inset: float = 0.0) -> QPainterPath:
    x0, x1 = 50.0 + inset, 116.5 - inset
    mid = (x0 + x1) / 2
    return smooth_closed([
        (x0, 47 - lift), (x0 + 3.5, 20 - lift), (x0 + 10, 11 - lift), (mid, 7 - lift),
        (x1 - 10, 11 - lift), (x1 - 3.5, 20 - lift), (x1, 47 - lift),
    ], tension=0.9)


def _cross(cx: float, cy: float) -> QPainterPath:
    """Plus-shaped recess the D-pad / face buttons sit in."""
    return union(rrect(cx - CROSS_HALF_LEN, cy - CROSS_HALF_W, 2 * CROSS_HALF_LEN, 2 * CROSS_HALF_W, 6),
                 rrect(cx - CROSS_HALF_W, cy - CROSS_HALF_LEN, 2 * CROSS_HALF_W, 2 * CROSS_HALF_LEN, 6))


def _dpad_arm(cx: float, cy: float, angle: float) -> tuple[QPainterPath, QPainterPath]:
    """One D-pad arm pointing towards the centre, plus its little arrow outside."""
    def rot(x: float, y: float) -> tuple[float, float]:
        a = radians(angle)
        return cx + x * cos(a) - y * sin(a), cy + x * sin(a) + y * cos(a)

    w = DPAD_HALF_W
    arm = rounded_polygon([rot(-DPAD_REACH, -w), rot(-13.5, -w), rot(-7.0, 0), rot(-13.5, w), rot(-DPAD_REACH, w)],
                          2.2)
    arrow = polygon([rot(-36.0, -4.2), rot(-36.0, 4.2), rot(-41.0, 0)])
    return arm, arrow


def _glyph_triangle(cx: float, cy: float, s: float) -> QPainterPath:
    h = s * 0.87
    return polygon([(cx - s / 2, cy + h / 3), (cx + s / 2, cy + h / 3), (cx, cy - 2 * h / 3)])


def _glyph_square(cx: float, cy: float, s: float) -> QPainterPath:
    return rrect(cx - s / 2, cy - s / 2, s, s, 0.6)


def _glyph_cross(cx: float, cy: float, s: float) -> QPainterPath:
    p = QPainterPath()
    p.moveTo(cx - s / 2, cy - s / 2)
    p.lineTo(cx + s / 2, cy + s / 2)
    p.moveTo(cx - s / 2, cy + s / 2)
    p.lineTo(cx + s / 2, cy - s / 2)
    return p


def build() -> FlatLayout:
    lx, rx = AX - LOBE_DX, AX + LOBE_DX
    lobe_l, lobe_r = circle(lx, LOBE_Y, LOBE_R), circle(rx, LOBE_Y, LOBE_R)
    bridge = rrect(AX - BRIDGE_HALF, BRIDGE_TOP, 2 * BRIDGE_HALF, BRIDGE_BOTTOM - BRIDGE_TOP, 4)
    ring_l, ring_r = circle(AX - STICK_DX, STICK_Y, RING_R), circle(AX + STICK_DX, STICK_Y, RING_R)
    grip_l = _grip_left()
    shell = union(lobe_l, lobe_r, bridge, ring_l, ring_r, grip_l, mirror(grip_l, AX))

    lay = FlatLayout(Model.DS3, QRectF(0, -2, 2 * AX, 254), shell, outline=2.1)
    lay.pads = [lobe_l, lobe_r]
    lay.recesses = [_cross(lx, LOBE_Y), _cross(rx, LOBE_Y)]

    # seams: face-plane edge along the top, bridge's lower edge between the sticks
    top = QPainterPath()
    top.moveTo(AX - 72, 52)
    top.lineTo(AX + 72, 52)
    low = QPainterPath()
    low.moveTo(AX - 19.5, 164)
    low.lineTo(AX + 19.5, 164)
    lay.seams = [top, low]

    # shoulder buttons: L2/R2 peek out behind L1/R1
    l2 = _bumper_left(lift=9.5, inset=4.0)
    l1 = _bumper_left()
    lay.behind = [
        FlatPart(Button.L2, l2, kind="trigger"), FlatPart(Button.R2, mirror(l2, AX), kind="trigger"),
        FlatPart(Button.L1, l1, kind="bumper"), FlatPart(Button.R1, mirror(l1, AX), kind="bumper"),
    ]

    # D-pad
    for button, angle in ((Button.DPAD_LEFT, 0.0), (Button.DPAD_UP, 90.0), (Button.DPAD_RIGHT, 180.0),
                          (Button.DPAD_DOWN, 270.0)):
        arm, arrow = _dpad_arm(lx, LOBE_Y, angle)
        lay.parts.append(FlatPart(button, arm, arrow, kind="dpad"))

    # face buttons
    for button, (dx, dy), glyph in (
        (Button.TRIANGLE, (0, -FACE_SPREAD), _glyph_triangle(rx, LOBE_Y - FACE_SPREAD, 15.5)),
        (Button.CIRCLE, (FACE_SPREAD, 0), circle(rx + FACE_SPREAD, LOBE_Y, 8.0)),
        (Button.CROSS, (0, FACE_SPREAD), _glyph_cross(rx, LOBE_Y + FACE_SPREAD, 12.5)),
        (Button.SQUARE, (-FACE_SPREAD, 0), _glyph_square(rx - FACE_SPREAD, LOBE_Y, 13.0)),
    ):
        lay.parts.append(FlatPart(button, circle(rx + dx, LOBE_Y + dy, FACE_R), glyph, kind="face"))

    # centre: Select, Start, PS
    lay.parts.append(FlatPart(Button.SELECT, rrect(155, 95, 20, 10, 2.6)))
    lay.parts.append(FlatPart(Button.START, rounded_polygon([(226, 94.5), (245, 100), (226, 105.5)], 1.6)))
    lay.parts.append(FlatPart(Button.PS, circle(AX, 129, 12.5), kind="ps"))
    lay.labels = [(QPointF(165, 87.5), "SELECT"), (QPointF(235.5, 87.5), "START")]

    # player LEDs on the front edge
    lay.leds = [QRectF(AX - 23.5 + i * 13, 44.2, 8, 3.6) for i in range(4)]

    lay.sticks = [FlatStick(Button.L3, QPointF(AX - STICK_DX, STICK_Y), RING_R, GAP_R, CAP_R, 8.5),
                  FlatStick(Button.R3, QPointF(AX + STICK_DX, STICK_Y), RING_R, GAP_R, CAP_R, 8.5)]
    return lay
