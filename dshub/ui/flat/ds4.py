"""DualShock 4, straight-on, in the same ~400-unit drawing space as the DS3.

Proportions were measured from a front-on photo (Wikimedia Commons "Sony
DualShock 4 wireless controller for PlayStation 4 (black) - top view.jpg",
CC BY-SA 4.0; only the measurements are used, no image data), drawn here in
the flat emulator style.
"""

from __future__ import annotations

from math import cos, radians, sin

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QTransform

from dshub.core.state import Button, Model
from dshub.ui.flat.layout import (FlatLayout, FlatPart, FlatStick, circle, mirror, polygon, rounded_polygon, rrect,
                                  smooth_closed, union)

# Measured proportions. x: half-widths from the centre line (0 = centre, 1 = widest
# point, left half only; it is mirrored). y and sizes: body widths from the top.
#: Left half of the body outline, from top-centre round to bottom-centre.
OUTLINE = [
    (0.000, 0.024), (0.140, 0.024), (0.280, 0.024), (0.370, 0.027), (0.450, 0.032),
    (0.560, 0.038), (0.660, 0.044), (0.747, 0.054), (0.815, 0.082), (0.858, 0.125),
    (0.882, 0.185), (0.920, 0.258), (0.962, 0.328), (0.986, 0.394), (0.997, 0.460),
    (0.992, 0.525), (0.961, 0.586), (0.900, 0.630), (0.827, 0.651), (0.750, 0.653),
    (0.680, 0.645), (0.625, 0.615), (0.585, 0.565), (0.545, 0.505), (0.500, 0.443),
    (0.430, 0.408), (0.300, 0.402), (0.150, 0.401), (0.000, 0.401),
]
#: Top profile of the L1 bulge, inner end -> outer end (left side).
BUMPER = [(0.455, 0.033), (0.503, 0.010), (0.638, 0.002), (0.712, 0.020), (0.747, 0.054)]
#: Feature positions (x in half-widths, y and sizes in body widths).
FEATURES = {
    "dpad": (-0.641, 0.146, 0.077, 0.048),  # centre x, y, reach, arm width
    "dpad_recess": 0.112,
    "face": (0.641, 0.146, 0.0735, 0.029),  # centre x, y, spread, button radius
    "face_recess": 0.112,
    "sticks": (0.300, 0.277, 0.060, 0.080),  # |x|, y, cap radius, well radius
    "ps": (0.0, 0.298, 0.023),
    "touchpad": (0.331, 0.019, 0.311, 0.187),  # top half-width, top y, bottom half-width, bottom y
    "lightbar": (0.300, 0.010),
    "grille": (0.0, 0.223),
    "share": (-0.410, 0.058),
    "options": (0.410, 0.058),
}
#: Depth correction to Sony's published 162 x 98 mm (the photo was shot from slightly above).
Y_SCALE = 0.93

AX = 200.0
HALF_W = 198.0  # half-width in drawing units
TOP = 14.0
DEPTH = 2 * HALF_W * Y_SCALE  # one "body width" down, depth-corrected


def X(hw: float) -> float:
    return AX + hw * HALF_W


def Y(bw: float) -> float:
    return TOP + bw * DEPTH


def S(bw: float) -> float:
    return bw * 2 * HALF_W


def _shell() -> QPainterPath:
    left = [(X(-x), Y(y)) for x, y in OUTLINE]
    right = [(2 * AX - x, y) for x, y in reversed(left[1:-1])]
    return smooth_closed(left + right, tension=1.0)


def _bumper_left(lift: float = 0.0, inset: float = 0.0) -> QPainterPath:
    """L1 tab: the measured top profile, closed underneath the shell's top edge.

    ``lift``/``inset`` give the L2 tab peeking out behind it.
    """
    prof = [(X(-x), Y(y)) for x, y in BUMPER]  # inner end -> outer end (inner has larger x)
    inner_x, outer_x = prof[0][0] - inset, prof[-1][0] + inset
    top = [(x, y - lift) for x, y in prof[1:-1]]
    pts = ([(inner_x, prof[0][1] - lift * 0.5)] + top + [(outer_x, prof[-1][1] - lift * 0.5)]
           + [(outer_x + 2, Y(0.10)), (inner_x - 2, Y(0.10))])
    return smooth_closed(pts, tension=0.85)


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


def _dpad_arm(cx: float, cy: float, angle: float, reach: float, half_w: float) -> tuple[QPainterPath, QPainterPath]:
    """DS4 arm: separate key with a pointed inner end and an arrow printed on it."""
    def rot(x: float, y: float) -> tuple[float, float]:
        a = radians(angle)
        return cx + x * cos(a) - y * sin(a), cy + x * sin(a) + y * cos(a)

    arm = rounded_polygon([rot(-reach, -half_w), rot(-reach * 0.42, -half_w), rot(-reach * 0.2, 0),
                           rot(-reach * 0.42, half_w), rot(-reach, half_w)], 2.4)
    arrow = polygon([rot(-reach * 0.62, -3.6), rot(-reach * 0.62, 3.6), rot(-reach * 0.80, 0)])
    return arm, arrow


def _capsule(cx: float, cy: float, w: float, h: float, angle: float) -> QPainterPath:
    p = rrect(cx - w / 2, cy - h / 2, w, h, w / 2)
    return QTransform().translate(cx, cy).rotate(angle).translate(-cx, -cy).map(p)


def build() -> FlatLayout:
    f = FEATURES
    shell = _shell()
    lay = FlatLayout(Model.DS4, QRectF(0, -6, 2 * AX, Y(0.653) + 12), shell, outline=2.1)

    # shoulders: L2/R2 behind L1/R1
    l1 = _bumper_left()
    l2 = _bumper_left(lift=9.0)
    lay.behind = [
        FlatPart(Button.L2, l2, kind="trigger"), FlatPart(Button.R2, mirror(l2, AX), kind="trigger"),
        FlatPart(Button.L1, l1, kind="bumper"), FlatPart(Button.R1, mirror(l1, AX), kind="bumper"),
    ]

    # round wells for the D-pad and the face buttons
    dx, dy, reach, arm_w = f["dpad"]
    fx, fy, spread, face_r = f["face"]
    lay.recesses = [circle(X(dx), Y(dy), S(f["dpad_recess"])), circle(X(fx), Y(fy), S(f["face_recess"]))]

    # touchpad + light bar + speaker grille
    th, tt, bh, bt = f["touchpad"]
    pad = rounded_polygon([(X(-th), Y(tt)), (X(th), Y(tt)), (X(bh), Y(bt)), (X(-bh), Y(bt))], 5)
    lay.parts.append(FlatPart(Button.TOUCHPAD, pad, kind="touchpad"))
    lb_hw, lb_y = f["lightbar"]
    lay.lightbar = rrect(X(-lb_hw), Y(lb_y) - 2.2, X(lb_hw) - X(-lb_hw), 4.4, 2.2)
    gx, gy = f["grille"]
    for row in range(3):
        for col in range(9):
            if (col, row) in ((0, 0), (8, 0), (0, 2), (8, 2)):
                continue
            lay.recesses.append(circle(X(gx) + (col - 4) * 4.6, Y(gy) + (row - 1) * 4.6, 1.15))

    # D-pad
    cx, cy = X(dx), Y(dy)
    for button, angle in ((Button.DPAD_LEFT, 0.0), (Button.DPAD_UP, 90.0), (Button.DPAD_RIGHT, 180.0),
                          (Button.DPAD_DOWN, 270.0)):
        arm, arrow = _dpad_arm(cx, cy, angle, S(reach), S(arm_w) / 2)
        lay.parts.append(FlatPart(button, arm, arrow, kind="dpad"))

    # face buttons
    fcx, fcy, d, r = X(fx), Y(fy), S(spread), S(face_r)
    for button, (ox, oy), glyph in (
        (Button.TRIANGLE, (0, -d), _glyph_triangle(fcx, fcy - d, r * 1.18)),
        (Button.CIRCLE, (d, 0), circle(fcx + d, fcy, r * 0.62)),
        (Button.CROSS, (0, d), _glyph_cross(fcx, fcy + d, r * 0.95)),
        (Button.SQUARE, (-d, 0), _glyph_square(fcx - d, fcy, r * 1.0)),
    ):
        lay.parts.append(FlatPart(button, circle(fcx + ox, fcy + oy, r), glyph, kind="face"))

    # Share / Options, PS
    for button, key, angle in ((Button.SELECT, "share", -14.0), (Button.START, "options", 14.0)):
        sx, sy = f[key]
        lay.parts.append(FlatPart(button, _capsule(X(sx), Y(sy), S(0.017), S(0.042), angle)))
    psx, psy, psr = f["ps"]
    lay.parts.append(FlatPart(Button.PS, circle(X(psx), Y(psy), S(psr)), kind="ps"))
    # printed just above Share/Options, nudged inwards so a lit L1/R1 tab never covers them
    lay.labels = [(QPointF(X(f["share"][0]) + 4.5, Y(f["share"][1]) - 13), "SHARE", 5.4),
                  (QPointF(X(f["options"][0]) - 4.5, Y(f["options"][1]) - 13), "OPTIONS", 5.4)]

    sx, sy, cap, well = f["sticks"]
    for button, x in ((Button.L3, -sx), (Button.R3, sx)):
        lay.sticks.append(FlatStick(button, QPointF(X(x), Y(sy)), S(well), S(well) * 0.82, S(cap), S(well) * 0.2))
    return lay
