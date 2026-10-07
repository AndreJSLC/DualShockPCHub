"""DualSense, straight-on, in drawing units (400 wide, centre line x = 200).

Outline traced from a front-on photo of the pad (left half, mirrored) and
scaled to Sony's 160 x 106 mm, so ~265 units tall. White shell, black centre
plate running down the inner grips, flush touchpad with the light strips
beside it, sticks on the plate, PS + mute below the speaker, Create/Options
pills by the touchpad corners, L1/L2 tabs over the shoulders.
"""

from __future__ import annotations

from math import cos, radians, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPainterPathStroker

from dshub.core.state import Button, Model
from dshub.ui.flat.layout import (FlatLayout, FlatPart, FlatStick, circle, mirror, polygon, rounded_polygon, rrect,
                                  smooth_closed)

AX = 200.0  # centre line
OUTLINE_LEFT = [  # top-centre -> shoulder (under L1) -> outer edge -> grip tip -> inner edge -> bottom-centre
    (200, 30.0), (183.4, 30.0), (167.4, 30.8), (151.2, 31.5), (135.0, 32.3), (121.4, 37.2),
    (108.0, 41.4), (92.0, 42.9), (76.0, 45.2), (60.0, 49.0), (48.0, 54.3), (39.8, 60.4),
    (33.4, 70.7), (27.4, 84.0), (22.2, 97.6), (17.6, 111.7), (13.6, 125.8), (10.4, 140.6),
    (7.2, 155.0), (4.4, 169.5), (2.2, 184.7), (0.8, 199.9), (0.0, 215.4), (0.0, 231.0),
    (1.4, 246.2), (4.0, 261.0), (9.4, 274.7), (22.0, 283.8), (36.2, 289.5), (50.2, 295.6),
    (61.6, 288.8), (68.0, 275.5), (73.6, 261.8), (78.8, 248.1), (83.8, 234.4), (89.0, 220.8),
    (94.6, 207.1), (103.4, 194.9), (117.8, 189.6), (134.0, 191.1), (150.2, 191.9), (166.6, 192.3),
    (183.2, 192.3), (200, 192.3),
]
PLATE_LEFT = [  # black centre plate: under the touchpad, around the sticks, down the inner grips
    (200, 96.0), (150.0, 97.0), (128.0, 97.0), (112.0, 106.0), (102.0, 117.0), (94.0, 138.0),
    (86.0, 158.0), (76.0, 182.0), (68.0, 205.0), (60.0, 231.0), (53.0, 254.0), (47.0, 278.0),
    (44.0, 305.0), (200, 316.0),
]
DPAD_X, CLUSTER_Y = 76.6, 87.8  # D-pad centre (face cluster mirrored at 2 * AX - DPAD_X)
DPAD_REACH, DPAD_HALF_W = 30.5, 9.5
FACE_SPREAD, FACE_R = 27.5, 13.0
STICK_DX, STICK_Y = 60.0, 131.0
RING_R, GAP_R, CAP_R = 30.0, 26.5, 24.0


def _shell() -> QPainterPath:
    right = [(2 * AX - x, y) for x, y in reversed(OUTLINE_LEFT[1:-1])]
    return smooth_closed(OUTLINE_LEFT + right)


def _plate() -> QPainterPath:
    right = [(2 * AX - x, y) for x, y in reversed(PLATE_LEFT[1:-1])]
    return smooth_closed(PLATE_LEFT + right, tension=0.9)


def _touchpad() -> QPainterPath:
    """Flush with the top edge; slightly tapered sides and a curved bottom."""
    p = QPainterPath(QPointF(126.0, 30.0))
    p.lineTo(274.0, 30.0)
    p.quadTo(279.5, 30.0, 279.5, 35.5)
    p.cubicTo(278.5, 60.0, 274.5, 80.0, 266.5, 92.0)
    p.cubicTo(255.0, 100.0, 230.0, 101.5, 200.0, 101.5)
    p.cubicTo(170.0, 101.5, 145.0, 100.0, 133.5, 92.0)
    p.cubicTo(125.5, 80.0, 121.5, 60.0, 120.5, 35.5)
    p.quadTo(120.5, 30.0, 126.0, 30.0)
    p.closeSubpath()
    return p


def _light_strips() -> QPainterPath:
    """The two light guides hugging the touchpad's sides and lower corners."""
    curve = QPainterPath(QPointF(116.8, 38.0))
    curve.cubicTo(QPointF(117.8, 62.0), QPointF(121.5, 84.0), QPointF(131.0, 95.5))
    curve.cubicTo(QPointF(137.0, 101.5), QPointF(144.0, 104.0), QPointF(152.0, 105.0))
    stroker = QPainterPathStroker()
    stroker.setWidth(3.4)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    left = stroker.createStroke(curve).simplified()
    return left.united(mirror(left, AX)).simplified()


def _shoulder(lift: float = 0.0, inset: float = 0.0) -> QPainterPath:
    """L1 (lift 0) or L2 (lifted, inset) tab over the left shoulder; tucked under the shell."""
    pts = [(116, 50), (113, 36), (104, 31.5), (90, 31.5), (74, 33.5), (60, 38), (48, 44), (39, 52), (36, 60),
           (48, 66), (80, 58), (112, 56)]
    mid = 76.0
    out = []
    for x, y in pts:
        x = x + (inset if x < mid else -inset)
        out.append((x, y - lift if y < 50 else y))
    return smooth_closed(out, tension=0.9)


def _dpad_arm(cx: float, cy: float, angle: float) -> tuple[QPainterPath, QPainterPath]:
    """One D-pad arm, its tip pointing at the centre, with the arrow moulded into it."""
    def rot(x: float, y: float) -> tuple[float, float]:
        a = radians(angle)
        return cx + x * cos(a) - y * sin(a), cy + x * sin(a) + y * cos(a)

    w = DPAD_HALF_W
    arm = rounded_polygon([rot(-DPAD_REACH, -w), rot(-12.5, -w), rot(-6.0, 0), rot(-12.5, w), rot(-DPAD_REACH, w)],
                          2.6)
    arrow = polygon([rot(-20.5, -3.6), rot(-20.5, 3.6), rot(-25.5, 0)])
    return arm, arrow


def _glyph_triangle(cx: float, cy: float, s: float) -> QPainterPath:
    h = s * 0.87
    return polygon([(cx - s / 2, cy + h / 3), (cx + s / 2, cy + h / 3), (cx, cy - 2 * h / 3)])


def _glyph_cross(cx: float, cy: float, s: float) -> QPainterPath:
    p = QPainterPath()
    p.moveTo(cx - s / 2, cy - s / 2)
    p.lineTo(cx + s / 2, cy + s / 2)
    p.moveTo(cx - s / 2, cy + s / 2)
    p.lineTo(cx + s / 2, cy - s / 2)
    return p


def _grille(cx: float, cy: float) -> QPainterPath:
    """Speaker holes as dots (zero-length round-capped seam strokes)."""
    p = QPainterPath()
    for row in range(2):
        for col in range(6):
            x, y = cx + (col - 2.5) * 5.0, cy + (row - 0.5) * 4.6
            p.moveTo(x, y)
            p.lineTo(x + 0.01, y)
    return p


def build(model: Model = Model.DS5) -> FlatLayout:
    shell = _shell()
    lay = FlatLayout(model, QRectF(0, 18, 2 * AX, 300), shell, outline=2.1)
    lay.plate = _plate()
    lay.lightbar = _light_strips()
    lay.seams = [_grille(AX, 114.0)]

    l2 = _shoulder(lift=8.0, inset=4.0)
    l1 = _shoulder()
    lay.behind = [
        FlatPart(Button.L2, l2, kind="trigger"), FlatPart(Button.R2, mirror(l2, AX), kind="trigger"),
        FlatPart(Button.L1, l1, kind="bumper"), FlatPart(Button.R1, mirror(l1, AX), kind="bumper"),
    ]

    lay.parts.append(FlatPart(Button.TOUCHPAD, _touchpad(), kind="touchpad"))

    for button, angle in ((Button.DPAD_LEFT, 0.0), (Button.DPAD_UP, 90.0), (Button.DPAD_RIGHT, 180.0),
                          (Button.DPAD_DOWN, 270.0)):
        arm, arrow = _dpad_arm(DPAD_X, CLUSTER_Y, angle)
        lay.parts.append(FlatPart(button, arm, arrow, kind="dpad"))

    fx = 2 * AX - DPAD_X
    for button, (dx, dy), glyph in (
        (Button.TRIANGLE, (0, -FACE_SPREAD), _glyph_triangle(fx, CLUSTER_Y - FACE_SPREAD, 15.0)),
        (Button.CIRCLE, (FACE_SPREAD, 0), circle(fx + FACE_SPREAD, CLUSTER_Y, 7.8)),
        (Button.CROSS, (0, FACE_SPREAD), _glyph_cross(fx, CLUSTER_Y + FACE_SPREAD, 12.0)),
        (Button.SQUARE, (-FACE_SPREAD, 0), rrect(fx - FACE_SPREAD - 6.3, CLUSTER_Y - 6.3, 12.6, 12.6, 0.6)),
    ):
        lay.parts.append(FlatPart(button, circle(fx + dx, CLUSTER_Y + dy, FACE_R), glyph, kind="face"))

    # Create / Options pills by the touchpad's top corners
    lay.parts.append(FlatPart(Button.SELECT, rrect(105.75, 44.5, 8.5, 17.0, 4.25)))
    lay.parts.append(FlatPart(Button.START, rrect(2 * AX - 114.25, 44.5, 8.5, 17.0, 4.25)))

    # PS between the sticks, mute below it
    lay.parts.append(FlatPart(Button.PS, circle(AX, 136.0, 10.5), kind="ps"))
    lay.parts.append(FlatPart(Button.MUTE, rrect(AX - 9.0, 156.5, 18.0, 6.5, 3.25)))

    lay.sticks = [FlatStick(Button.L3, QPointF(AX - STICK_DX, STICK_Y), RING_R, GAP_R, CAP_R, 7.5),
                  FlatStick(Button.R3, QPointF(AX + STICK_DX, STICK_Y), RING_R, GAP_R, CAP_R, 7.5)]

    # player indicator: five small white LEDs just under the touchpad's bottom edge
    lay.leds = [QRectF(AX - 17.25 + i * 7.5, 104.2, 4.5, 1.6) for i in range(5)]
    lay.led_style = "ds5"
    return lay
