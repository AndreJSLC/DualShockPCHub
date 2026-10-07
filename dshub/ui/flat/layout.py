"""Geometry container + small path helpers for the flat drawings."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF, QTransform

from dshub.core.state import Button, Model


@dataclass
class FlatPart:
    button: Button
    shape: QPainterPath  # fill + hit area
    glyph: QPainterPath | None = None  # symbol drawn on the part (stroked)
    kind: str = "key"  # "face" | "key" | "dpad" | "bumper" | "trigger" | "ps"


@dataclass
class FlatStick:
    button: Button  # L3 / R3
    center: QPointF
    ring_r: float  # outer boss ring
    gap_r: float  # dark gap around the cap
    cap_r: float  # the moving cap
    travel: float  # max cap offset (drawing units)


@dataclass
class FlatLayout:
    model: Model
    size: QRectF  # drawing bounds (units)
    shell: QPainterPath  # outer silhouette, filled with the body colour
    seams: list[QPainterPath] = field(default_factory=list)  # thin interior lines (clipped to the shell)
    recesses: list[QPainterPath] = field(default_factory=list)  # darker sunken areas (D-pad / face crosses)
    pads: list[QPainterPath] = field(default_factory=list)  # round lobes under D-pad and face buttons
    behind: list[FlatPart] = field(default_factory=list)  # parts drawn before the shell (L2/R2, L1/R1)
    parts: list[FlatPart] = field(default_factory=list)
    sticks: list[FlatStick] = field(default_factory=list)
    leds: list[QRectF] = field(default_factory=list)
    labels: list[tuple] = field(default_factory=list)  # (pos, text) or (pos, text, size)
    outline: float = 2.0  # outline width in drawing units
    lightbar: QPainterPath | None = None  # DS4 light bar / DualSense light strips (union of both)
    plate: QPainterPath | None = None  # DualSense black centre plate (drawn over the shell)
    led_style: str = "ds3"  # "ds3": red, one per player; "ds5": five white dots in patterns; "ds2": ANALOG LED
    # A part with kind="touchpad" gets touch dots; its bounding box maps the 0..1 touch coordinates.


# ------------------------------------------------------------------ helpers
def P(x: float, y: float) -> QPointF:
    return QPointF(x, y)


def circle(cx: float, cy: float, r: float) -> QPainterPath:
    p = QPainterPath()
    p.addEllipse(QPointF(cx, cy), r, r)
    return p


def rrect(x: float, y: float, w: float, h: float, r: float) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(QRectF(x, y, w, h), r, r)
    return p


def polygon(points: list[tuple[float, float]]) -> QPainterPath:
    p = QPainterPath()
    p.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    p.closeSubpath()
    return p


def rounded_polygon(points: list[tuple[float, float]], radius: float) -> QPainterPath:
    """Polygon with its corners rounded by ``radius`` (quadratic fillets)."""
    pts = [QPointF(x, y) for x, y in points]
    n = len(pts)
    path = QPainterPath()
    for i in range(n):
        prev, cur, nxt = pts[i - 1], pts[i], pts[(i + 1) % n]
        a, b = _toward(cur, prev, radius), _toward(cur, nxt, radius)
        if i == 0:
            path.moveTo(a)
        else:
            path.lineTo(a)
        path.quadTo(cur, b)
    path.closeSubpath()
    return path


def _toward(a: QPointF, b: QPointF, dist: float) -> QPointF:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = max((dx * dx + dy * dy) ** 0.5, 1e-6)
    k = min(dist, length / 2) / length
    return QPointF(a.x() + dx * k, a.y() + dy * k)


def smooth_closed(points: list[tuple[float, float]], tension: float = 1.0) -> QPainterPath:
    """Closed Catmull-Rom spline through ``points`` (as cubic Beziers)."""
    pts = [QPointF(x, y) for x, y in points]
    n = len(pts)
    path = QPainterPath(pts[0])
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = p1 + (p2 - p0) * (tension / 6)
        c2 = p2 - (p3 - p1) * (tension / 6)
        path.cubicTo(c1, c2, p2)
    path.closeSubpath()
    return path


def mirror(path: QPainterPath, axis_x: float) -> QPainterPath:
    return QTransform(-1, 0, 0, 1, 2 * axis_x, 0).map(path)


def union(*paths: QPainterPath) -> QPainterPath:
    out = QPainterPath()
    for p in paths:
        out = out.united(p)
    return out.simplified()
