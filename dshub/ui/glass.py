"""Glass surfaces in the spirit of the PS3's glossy PS button.

Every effect here is pre-rendered once per size into a cached QPixmap, so a
repaint is a single blit: the look costs nothing while a game is running.

Lighting model shared with the controller artwork: one key light at the top
left, a curved specular reflection across the upper half of each glass
surface, a thin bright rim on top and a darker rim at the bottom.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)

from dshub.ui import theme

#: Tones: "dark" (default surface), "raised" (hover), "active" (selected),
#: "accent" (PlayStation-blue glass), "inset" (sunken field).
TONES = ("dark", "raised", "active", "accent", "inset")


def _rounded(r: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    return path


def _base_colors(tone: str) -> tuple[QColor, QColor]:
    if tone == "accent":
        return QColor(38, 140, 255), QColor(0, 82, 190)
    if tone == "active":
        return QColor(255, 255, 255, 34), QColor(255, 255, 255, 12)
    if tone == "raised":
        return QColor(255, 255, 255, 22), QColor(255, 255, 255, 7)
    if tone == "inset":
        return QColor(0, 0, 0, 90), QColor(0, 0, 0, 55)
    return QColor(255, 255, 255, 16), QColor(255, 255, 255, 5)


def paint_glass(p: QPainter, r: QRectF, radius: float, tone: str = "dark") -> None:
    """Draw a glass panel into ``r`` (uncached; use ``glass_pixmap`` in paintEvents)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    body = _rounded(r, radius)
    top, bottom = _base_colors(tone)
    if tone in ("dark", "raised", "active"):
        # smoked backing: keeps text readable when the window itself is see-through
        p.fillPath(body, QColor(0, 0, 0, 70))

    # 1. body: vertical gradient, brighter at the top where the light hits
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0.0, top)
    g.setColorAt(1.0, bottom)
    p.fillPath(body, g)

    if tone != "inset":
        # 2. curved specular reflection over the upper half (the PS-button gloss)
        gloss = QPainterPath()
        gloss.moveTo(r.left(), r.top())
        gloss.lineTo(r.right(), r.top())
        gloss.lineTo(r.right(), r.top() + r.height() * 0.30)
        gloss.cubicTo(r.right() - r.width() * 0.30, r.top() + r.height() * 0.52,
                      r.left() + r.width() * 0.30, r.top() + r.height() * 0.40,
                      r.left(), r.top() + r.height() * 0.56)
        gloss.closeSubpath()
        gloss = gloss.intersected(body)
        sg = QLinearGradient(r.topLeft(), QPointF(r.left(), r.top() + r.height() * 0.56))
        k = 1.6 if tone == "accent" else 1.0
        sg.setColorAt(0.0, QColor(255, 255, 255, int(38 * k)))
        sg.setColorAt(1.0, QColor(255, 255, 255, int(4 * k)))
        p.fillPath(gloss, sg)

        # 3. soft key-light hotspot, top-left
        hot = QRadialGradient(QPointF(r.left() + r.width() * 0.18, r.top()), max(r.width(), r.height()) * 0.55)
        hot.setColorAt(0.0, QColor(255, 255, 255, 22 if tone != "accent" else 40))
        hot.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(body, hot)

    # 4. bottom shade (depth)
    shade = QLinearGradient(QPointF(r.left(), r.bottom() - r.height() * 0.35), r.bottomLeft())
    shade.setColorAt(0.0, QColor(0, 0, 0, 0))
    shade.setColorAt(1.0, QColor(0, 0, 0, 70 if tone == "accent" else 46))
    p.fillPath(body, shade)

    # 5. rims: dark outer edge, bright hairline along the top inner edge
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 120 if tone != "inset" else 90), 1.0))
    p.drawPath(_rounded(r.adjusted(0.5, 0.5, -0.5, -0.5), radius))
    inner = r.adjusted(1.5, 1.5, -1.5, -1.5)
    rim = QLinearGradient(inner.topLeft(), inner.bottomLeft())
    if tone == "inset":
        rim.setColorAt(0.0, QColor(0, 0, 0, 70))
        rim.setColorAt(1.0, QColor(255, 255, 255, 18))
    else:
        rim.setColorAt(0.0, QColor(255, 255, 255, 70 if tone != "accent" else 120))
        rim.setColorAt(0.25, QColor(255, 255, 255, 14))
        rim.setColorAt(1.0, QColor(255, 255, 255, 8))
    p.setPen(QPen(QBrush(rim), 1.0))
    p.drawPath(_rounded(inner, max(0.0, radius - 1)))
    p.restore()


@lru_cache(maxsize=96)
def glass_pixmap(w: int, h: int, radius: float, tone: str = "dark", dpr: float = 1.0) -> QPixmap:
    pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_glass(p, QRectF(0, 0, w, h), radius, tone)
    p.end()
    return pm


def draw_glass(p: QPainter, widget, radius: float | None = None, tone: str = "dark",
               rect: QRectF | None = None) -> None:
    """Blit a cached glass panel covering ``rect`` (default: the whole widget)."""
    r = rect or QRectF(widget.rect())
    rad = (r.height() / 2) if radius is None else radius
    pm = glass_pixmap(int(r.width()), int(r.height()), round(rad, 1), tone, widget.devicePixelRatioF())
    p.drawPixmap(QPointF(r.x(), r.y()), pm)


# ---------------------------------------------------------------- glass dome
def paint_dome(p: QPainter, c: QPointF, rad: float) -> None:
    """A black glass dome with a chrome rim, like the PS3 controller's PS button."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # chrome rim: light top-left, dark bottom-right
    rim = QLinearGradient(QPointF(c.x() - rad, c.y() - rad), QPointF(c.x() + rad, c.y() + rad))
    rim.setColorAt(0.0, QColor(210, 214, 226))
    rim.setColorAt(0.45, QColor(96, 100, 112))
    rim.setColorAt(1.0, QColor(28, 28, 34))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(rim)
    p.drawEllipse(c, rad, rad)
    # glass body: deep black, slightly lifted towards the bottom (light passing through)
    inner = rad * 0.88
    body = QRadialGradient(QPointF(c.x(), c.y() + inner * 0.55), inner * 1.25)
    body.setColorAt(0.0, QColor(30, 34, 46))
    body.setColorAt(0.6, QColor(10, 10, 14))
    body.setColorAt(1.0, QColor(2, 2, 4))
    p.setBrush(body)
    p.drawEllipse(c, inner, inner)
    p.restore()


def paint_dome_gloss(p: QPainter, c: QPointF, rad: float) -> None:
    """The glass highlight; draw it *after* whatever sits under the glass."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    inner = rad * 0.88
    clip = QPainterPath()
    clip.addEllipse(c, inner, inner)
    p.setClipPath(clip)
    # big curved reflection over the top ~55 %
    hl = QPainterPath()
    hl.addEllipse(QRectF(c.x() - inner * 1.05, c.y() - inner * 1.32, inner * 2.1, inner * 1.62))
    g = QLinearGradient(QPointF(c.x(), c.y() - inner), QPointF(c.x(), c.y() + inner * 0.25))
    g.setColorAt(0.0, QColor(255, 255, 255, 150))
    g.setColorAt(0.55, QColor(255, 255, 255, 34))
    g.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(hl, g)
    # small sharp specular dot, top-left
    spot = QRadialGradient(QPointF(c.x() - inner * 0.42, c.y() - inner * 0.52), inner * 0.32)
    spot.setColorAt(0.0, QColor(255, 255, 255, 190))
    spot.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(spot)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(c.x() - inner * 0.42, c.y() - inner * 0.52), inner * 0.32, inner * 0.32)
    # faint blue light caught at the bottom edge
    caught = QRadialGradient(QPointF(c.x() + inner * 0.2, c.y() + inner * 1.0), inner * 0.9)
    caught.setColorAt(0.0, QColor(90, 160, 255, 70))
    caught.setColorAt(1.0, QColor(90, 160, 255, 0))
    p.setBrush(caught)
    p.drawEllipse(c, inner, inner)
    p.restore()


def paint_sphere(p: QPainter, c: QPointF, rad: float, color: QColor) -> None:
    """Glossy ball (toggle thumbs, slider handles, status dots)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    body = QRadialGradient(QPointF(c.x() - rad * 0.3, c.y() - rad * 0.4), rad * 1.4)
    body.setColorAt(0.0, color.lighter(140))
    body.setColorAt(0.55, color)
    body.setColorAt(1.0, color.darker(190))
    p.setPen(QPen(QColor(0, 0, 0, 110), 0.8))
    p.setBrush(body)
    p.drawEllipse(c, rad, rad)
    hl = QPainterPath()
    hl.addEllipse(QRectF(c.x() - rad * 0.62, c.y() - rad * 0.86, rad * 1.24, rad * 0.86))
    g = QLinearGradient(QPointF(c.x(), c.y() - rad), QPointF(c.x(), c.y()))
    g.setColorAt(0.0, QColor(255, 255, 255, 190))
    g.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(hl, g)
    p.restore()


# ---------------------------------------------------------------- backdrop
@lru_cache(maxsize=8)
def backdrop_pixmap(w: int, h: int, dpr: float, opaque: bool, transparency: float = 0.55,
                    style: str = "frosted") -> QPixmap:
    """Window background: deep black-blue glass gradient plus faint XMB-like waves."""
    pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    tint = QColor(theme.WINDOW_TINT_FALLBACK if opaque else theme.window_tint(transparency, style))
    g = QLinearGradient(0, 0, 0, h)
    top = QColor(tint)
    top.setRed(min(255, top.red() + 4))
    top.setGreen(min(255, top.green() + 6))
    top.setBlue(min(255, top.blue() + 14))
    g.setColorAt(0.0, top)
    g.setColorAt(0.55, tint)
    bottom = QColor(tint)
    bottom.setAlpha(min(255, tint.alpha() + 18))
    g.setColorAt(1.0, bottom)
    p.fillRect(QRectF(0, 0, w, h), g)
    if not opaque:
        sheen = QLinearGradient(0, 0, w * 0.35, h * 0.5)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 16))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, 0, w, h), sheen)
        edge = QLinearGradient(0, 0, w, 0)
        edge.setColorAt(0.0, QColor(255, 255, 255, 0))
        edge.setColorAt(0.3, QColor(255, 255, 255, 40))
        edge.setColorAt(0.7, QColor(255, 255, 255, 40))
        edge.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, 0, w, 1), edge)

    # three soft ribbons sweeping across the lower part of the window
    for i, (amp, y0, alpha, width) in enumerate(((46, 0.80, 16, 1.4), (34, 0.84, 11, 1.0), (58, 0.88, 8, 0.8))):
        path = QPainterPath()
        steps = 48
        phase = i * 1.3
        for s in range(steps + 1):
            x = w * s / steps
            y = h * y0 + amp * math.sin(s / steps * math.pi * 1.6 + phase) * (0.6 + 0.4 * math.cos(s / steps * 3.1))
            path.moveTo(x, y) if s == 0 else path.lineTo(x, y)
        pen_g = QLinearGradient(0, 0, w, 0)
        pen_g.setColorAt(0.0, QColor(120, 170, 255, 0))
        pen_g.setColorAt(0.35, QColor(140, 190, 255, alpha))
        pen_g.setColorAt(0.7, QColor(200, 220, 255, alpha))
        pen_g.setColorAt(1.0, QColor(120, 170, 255, 0))
        p.setPen(QPen(QBrush(pen_g), width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # a faint glow band under the main ribbon
        if i == 0:
            band = QPainterPath(path)
            band.lineTo(w, h)
            band.lineTo(0, h)
            band.closeSubpath()
            bg = QLinearGradient(0, h * y0 - amp, 0, h)
            bg.setColorAt(0.0, QColor(60, 120, 255, 10))
            bg.setColorAt(1.0, QColor(60, 120, 255, 0))
            p.fillPath(band, bg)
    p.end()
    return pm
