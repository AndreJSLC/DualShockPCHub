"""Small custom-painted widgets that make up the minimal UI."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from dshub.core.state import Battery, Model
from dshub.ui import theme
from dshub.ui.glass import draw_glass, paint_sphere


def label(text: str = "", role: str | None = None, parent: QWidget | None = None) -> QLabel:
    lab = QLabel(text, parent)
    if role:
        lab.setProperty("role", role)
    return lab


def font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies([theme.FONT_FAMILY, theme.FONT_FALLBACK])
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def battery_text(b: Battery) -> str:
    if b.full:
        return "Full"
    if b.level is None:
        return "Charging" if b.charging else "—"
    return f"{b.level}%" + (" · charging" if b.charging else "")


def battery_color(b: Battery) -> QColor:
    if b.charging or b.full:
        return theme.OK
    if b.level is None:
        return theme.TEXT_DIM
    if b.level <= 15:
        return theme.BAD
    if b.level <= 35:
        return theme.WARN
    return theme.TEXT


class Card(QFrame):
    """Translucent rounded surface."""

    def __init__(self, parent: QWidget | None = None, padding: int = 16) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding, padding, padding)
        self.lay.setSpacing(8)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        draw_glass(p, self, theme.RADIUS)


class BatteryIcon(QWidget):
    def __init__(self, parent: QWidget | None = None, size: QSize = QSize(26, 13)) -> None:
        super().__init__(parent)
        self._b = Battery()
        self.setFixedSize(size)

    def set_battery(self, b: Battery) -> None:
        if b != self._b:
            self._b = b
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        wdt, hgt = self.width() - 3, self.height()
        body = QRectF(0.75, 0.75, wdt - 1.5, hgt - 1.5)
        col = battery_color(self._b)
        p.setPen(QPen(theme.TEXT_DIM, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, 3, 3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.TEXT_DIM)
        p.drawRoundedRect(QRectF(wdt, hgt * 0.32, 2.5, hgt * 0.36), 1, 1)
        level = self._b.level if self._b.level is not None else (100 if self._b.full else 0)
        if level:
            inner = body.adjusted(2, 2, -2, -2)
            inner.setWidth(max(1.5, inner.width() * level / 100))
            p.setBrush(col)
            p.drawRoundedRect(inner, 1.5, 1.5)
        if self._b.charging:
            bolt = QPainterPath()
            cx, cy, s = body.center().x(), body.center().y(), hgt * 0.42
            bolt.moveTo(cx + s * 0.25, cy - s)
            bolt.lineTo(cx - s * 0.45, cy + s * 0.15)
            bolt.lineTo(cx + s * 0.05, cy + s * 0.15)
            bolt.lineTo(cx - s * 0.25, cy + s)
            bolt.lineTo(cx + s * 0.45, cy - s * 0.15)
            bolt.lineTo(cx - s * 0.05, cy - s * 0.15)
            bolt.closeSubpath()
            p.setPen(QPen(QColor(0, 0, 0, 160), 1.2))
            p.setBrush(QColor("white"))
            p.drawPath(bolt)


class Pill(QWidget):
    """Compact chip: optional status dot + text."""

    def __init__(self, text: str = "", dot: QColor | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text, self._dot = text, dot
        self.setFont(font(12, QFont.Weight.Medium))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set(self, text: str, dot: QColor | None = None) -> None:
        if text == self._text and dot == self._dot:
            return  # called every frame; relayout only on a real change
        resize = len(text) != len(self._text) or (dot is None) != (self._dot is None)
        self._text, self._dot = text, dot
        if resize:
            self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        tw = self.fontMetrics().horizontalAdvance(self._text)
        return QSize(tw + 22 + (12 if self._dot else 0), 24)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        draw_glass(p, self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        x = 11
        if self._dot:
            paint_sphere(p, QPointF(x + 3, r.center().y()), 3.6, self._dot)
            x += 12
        p.setPen(theme.TEXT_DIM)
        p.drawText(QRectF(x, 0, r.width() - x, r.height()), Qt.AlignmentFlag.AlignVCenter, self._text)


class Segmented(QWidget):
    """Pill-shaped segmented tab control."""

    changed = Signal(int)

    def __init__(self, items: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items = items
        self.index = 0
        self._hover = -1
        self.setMouseTracking(True)
        self.setFont(font(13, QFont.Weight.Medium))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("interactive", True)
        self.setFixedHeight(34)

    def _seg_w(self) -> list[float]:
        fm = self.fontMetrics()
        return [fm.horizontalAdvance(t) + 32 for t in self.items]

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(int(sum(self._seg_w())) + 8, 34)

    def set_index(self, i: int) -> None:
        if i != self.index:
            self.index = i
            self.update()
            self.changed.emit(i)

    def _at(self, x: float) -> int:
        acc = 4.0
        for i, sw in enumerate(self._seg_w()):
            if acc <= x < acc + sw:
                return i
            acc += sw
        return -1

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        h = self._at(e.position().x())
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        i = self._at(e.position().x())
        if i >= 0:
            self.set_index(i)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        draw_glass(p, self, tone="inset")
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        x = 4.0
        for i, (text, sw) in enumerate(zip(self.items, self._seg_w())):
            seg = QRectF(x, 4, sw, r.height() - 8)
            if i == self.index:
                draw_glass(p, self, tone="active", rect=seg)
            elif i == self._hover:
                draw_glass(p, self, tone="dark", rect=seg)
            p.setPen(theme.TEXT if i == self.index else theme.TEXT_DIM)
            p.drawText(seg, Qt.AlignmentFlag.AlignCenter, text)
            x += sw


class Toggle(QAbstractButton):
    """iOS-style switch."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        on = self.isChecked()
        draw_glass(p, self, tone="accent" if on else "inset", rect=r)
        rad = r.height() / 2 - 3
        cx = r.right() - rad - 3 if on else r.left() + rad + 3
        paint_sphere(p, QPointF(cx, r.center().y()), rad, QColor(236, 238, 244) if on else QColor(140, 142, 152))
        if not self.isEnabled():
            p.fillRect(self.rect(), QColor(0, 0, 0, 90))


class StickPlot(QWidget):
    """Analog stick readout: circle, deadzone ring, live dot."""

    #: Ignore changes smaller than ~1 px; resting sticks jitter by an LSB.
    EPS = 0.012

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.x = self.y = 0.0
        self.deadzone = 0.0
        self._static: QPixmap | None = None
        self._label = ""
        self.setMinimumSize(96, 112)

    def set_value(self, x: float, y: float) -> None:
        if abs(x - self.x) < self.EPS and abs(y - self.y) < self.EPS:
            return
        self.x, self.y = x, y
        mag = math.hypot(x, y)
        # Ignore normal resting drift (a few percent) in the numeric readout.
        text = f"{self.title}  {x:+.2f} {(-y):+.2f}" if mag > 0.06 else self.title
        if text != self._label:
            self._label = text
            self.update()
        else:
            self.update(self._dot_rect())

    def resizeEvent(self, _e) -> None:  # noqa: N802
        self._static = None

    def _geom(self) -> tuple[QPointF, float, float]:
        size = min(self.width(), self.height() - 18) - 4
        return QPointF(self.width() / 2, 2 + size / 2), size / 2, size

    def _dot_rect(self):
        c, rad, _ = self._geom()
        return QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad).toAlignedRect().adjusted(-2, -2, 2, 2)

    def _render_static(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c, rad, _ = self._geom()
        # recessed glass well: dark centre, lit bottom rim (light comes from the top-left)
        from PySide6.QtGui import QLinearGradient, QRadialGradient

        well = QRadialGradient(QPointF(c.x(), c.y() - rad * 0.25), rad * 1.15)
        well.setColorAt(0.0, QColor(0, 0, 0, 70))
        well.setColorAt(1.0, QColor(0, 0, 0, 150))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(well)
        p.drawEllipse(c, rad, rad)
        rim = QLinearGradient(QPointF(c.x(), c.y() - rad), QPointF(c.x(), c.y() + rad))
        rim.setColorAt(0.0, QColor(0, 0, 0, 160))
        rim.setColorAt(1.0, QColor(255, 255, 255, 46))
        p.setPen(QPen(rim, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, rad - 0.6, rad - 0.6)
        p.setPen(QPen(theme.HAIRLINE, 1))
        p.drawLine(QPointF(c.x() - rad, c.y()), QPointF(c.x() + rad, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - rad), QPointF(c.x(), c.y() + rad))
        if self.deadzone > 0:
            p.setPen(QPen(theme.ACCENT_SOFT, 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, rad * self.deadzone, rad * self.deadzone)
        p.end()
        return pm

    def paintEvent(self, _e) -> None:  # noqa: N802
        if self._static is None:
            self._static = self._render_static()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._static)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c, rad, size = self._geom()
        dot = QPointF(c.x() + self.x * (rad - 6), c.y() + self.y * (rad - 6))
        p.setPen(QPen(QColor(theme.ACCENT.red(), theme.ACCENT.green(), theme.ACCENT.blue(), 110), 1.5))
        p.drawLine(c, dot)
        paint_sphere(p, dot, 5.0, theme.ACCENT)
        p.setPen(theme.TEXT_FAINT)
        p.setFont(font(11))
        p.drawText(QRectF(0, size + 4, self.width(), 16), Qt.AlignmentFlag.AlignCenter, self._label or self.title)


class Meter(QWidget):
    """Horizontal 0..1 bar with a label (triggers, report rate...)."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.value = 0.0
        self.text = ""
        self.setFixedHeight(30)
        self.setMinimumWidth(110)

    def set_value(self, v: float, text: str = "") -> None:
        v = max(0.0, min(1.0, v))
        if abs(v - self.value) > 0.004 or text != self.text:
            self.value, self.text = v, text
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(font(11))
        p.setPen(theme.TEXT_FAINT)
        p.drawText(QRectF(0, 0, self.width(), 14), Qt.AlignmentFlag.AlignLeft, self.title)
        p.drawText(QRectF(0, 0, self.width(), 14), Qt.AlignmentFlag.AlignRight,
                   self.text or f"{round(self.value * 100)}%")
        track = QRectF(0, 18, self.width(), 8)
        draw_glass(p, self, tone="inset", rect=track)
        if self.value > 0:
            # One cached full-width bar, revealed up to the value (no per-value renders).
            fill = QRectF(track)
            fill.setWidth(max(8.0, track.width() * self.value))
            clip = QPainterPath()
            clip.addRoundedRect(fill, 4, 4)
            p.setClipPath(clip)
            draw_glass(p, self, tone="accent", rect=track)


def controller_icon_path(model: Model, rect: QRectF) -> QPainterPath:
    """Tiny controller silhouette for the sidebar tiles."""
    x, y, wdt, hgt = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath()
    path.moveTo(x + wdt * 0.22, y + hgt * 0.12)
    path.lineTo(x + wdt * 0.78, y + hgt * 0.12)
    path.cubicTo(x + wdt * 0.98, y + hgt * 0.12, x + wdt * 1.02, y + hgt * 0.62, x + wdt * 0.96, y + hgt * 0.86)
    path.cubicTo(x + wdt * 0.92, y + hgt * 1.02, x + wdt * 0.78, y + hgt * 0.98, x + wdt * 0.70, y + hgt * 0.74)
    path.lineTo(x + wdt * 0.30, y + hgt * 0.74)
    path.cubicTo(x + wdt * 0.22, y + hgt * 0.98, x + wdt * 0.08, y + hgt * 1.02, x + wdt * 0.04, y + hgt * 0.86)
    path.cubicTo(x - wdt * 0.02, y + hgt * 0.62, x + wdt * 0.02, y + hgt * 0.12, x + wdt * 0.22, y + hgt * 0.12)
    path.closeSubpath()
    return path


def _accent_bar(p: QPainter, r: QRectF) -> None:
    """PS-blue light strip on the left edge of the selected sidebar row."""
    from PySide6.QtGui import QLinearGradient

    bar = QRectF(r.left() + 1.5, r.center().y() - 11, 3, 22)
    glow = QColor(theme.ACCENT)
    glow.setAlpha(60)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawRoundedRect(bar.adjusted(-1.5, -2, 1.5, 2), 3, 3)
    g = QLinearGradient(bar.topLeft(), bar.bottomLeft())
    g.setColorAt(0.0, QColor(150, 205, 255))
    g.setColorAt(1.0, theme.ACCENT_DEEP)
    p.setBrush(g)
    p.drawRoundedRect(bar, 1.5, 1.5)


class ControllerTile(QAbstractButton):
    """Sidebar entry: mini controller icon, "DS4 1", connection + battery."""

    def __init__(self, title: str, model: Model, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title, self.model = title, model
        self.subtitle = ""
        self.battery = Battery()
        self.lightbar: QColor | None = None
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(58)
        self._hover = False

    def update_info(self, subtitle: str, battery: Battery, lightbar: QColor | None) -> None:
        if (subtitle, battery, lightbar) != (self.subtitle, self.battery, self.lightbar):
            self.subtitle, self.battery, self.lightbar = subtitle, battery, lightbar
            self.update()

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked() or self._hover:
            draw_glass(p, self, 11, "active" if self.isChecked() else "dark")
        if self.isChecked():
            _accent_bar(p, r)

        icon = QRectF(r.left() + 14, r.center().y() - 11, 34, 22)
        path = controller_icon_path(self.model, icon)
        p.setPen(QPen(theme.TEXT if self.isChecked() else theme.TEXT_DIM, 1.4))
        p.setBrush(QColor(255, 255, 255, 14))
        p.drawPath(path)
        if self.lightbar is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.lightbar)
            p.drawRoundedRect(QRectF(icon.center().x() - 6, icon.top() + 1, 12, 2.2), 1, 1)

        tx = icon.right() + 12
        p.setPen(theme.TEXT)
        p.setFont(font(14, QFont.Weight.DemiBold))
        p.drawText(QRectF(tx, r.top() + 10, r.width() - tx - 40, 20), Qt.AlignmentFlag.AlignVCenter, self.title)
        p.setPen(theme.TEXT_DIM)
        p.setFont(font(11))
        p.drawText(QRectF(tx, r.top() + 29, r.width() - tx - 8, 16), Qt.AlignmentFlag.AlignVCenter, self.subtitle)

        # battery glyph, right-aligned
        bw, bh = 22.0, 11.0
        body = QRectF(r.right() - bw - 14, r.top() + 15, bw - 3, bh)
        p.setPen(QPen(theme.TEXT_FAINT, 1.1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, 2.5, 2.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.TEXT_FAINT)
        p.drawRoundedRect(QRectF(body.right() + 0.5, body.top() + 3.5, 2, 4), 1, 1)
        b = self.battery
        lvl = b.level if b.level is not None else (100 if b.full else (50 if b.charging else 0))
        if lvl:
            inner = body.adjusted(1.8, 1.8, -1.8, -1.8)
            inner.setWidth(max(1.5, inner.width() * lvl / 100))
            p.setBrush(battery_color(b))
            p.drawRoundedRect(inner, 1.2, 1.2)


class NavItem(QAbstractButton):
    """Sidebar navigation row with a drawn glyph."""

    def __init__(self, text: str, glyph: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.glyph = glyph
        self.badge: QColor | None = None
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self._hover = False

    def set_badge(self, color: QColor | None) -> None:
        self.badge = color
        self.update()

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked() or self._hover:
            draw_glass(p, self, 9, "active" if self.isChecked() else "dark")
        if self.isChecked():
            _accent_bar(p, r)
        col = theme.TEXT if self.isChecked() else theme.TEXT_DIM
        g = QRectF(r.left() + 14, r.center().y() - 8, 16, 16)
        p.setPen(QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.glyph == "chip":  # drivers
            p.drawRoundedRect(g.adjusted(3, 3, -3, -3), 2, 2)
            for i in (5.5, 8.0, 10.5):
                p.drawLine(QPointF(g.left() + i, g.top()), QPointF(g.left() + i, g.top() + 3))
                p.drawLine(QPointF(g.left() + i, g.bottom() - 3), QPointF(g.left() + i, g.bottom()))
        elif self.glyph == "gear":
            c = g.center()
            p.drawEllipse(c, 2.6, 2.6)
            for k in range(8):
                a = k * math.pi / 4
                p.drawLine(QPointF(c.x() + 5 * math.cos(a), c.y() + 5 * math.sin(a)),
                           QPointF(c.x() + 7.5 * math.cos(a), c.y() + 7.5 * math.sin(a)))
            p.drawEllipse(c, 5, 5)
        p.setPen(col)
        p.setFont(font(13, QFont.Weight.Medium))
        p.drawText(QRectF(g.right() + 12, r.top(), r.width(), r.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.badge is not None:
            paint_sphere(p, QPointF(r.right() - 14, r.center().y()), 4.2, self.badge)


class WindowButton(QAbstractButton):
    """Minimise / maximise / close glyph buttons for the custom title bar."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(46, 34)
        self._hover = False

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hover:
            p.fillRect(self.rect(), QColor(232, 17, 35) if self.kind == "close" else QColor(255, 255, 255, 18))
        c = QPointF(self.width() / 2, self.height() / 2)
        p.setPen(QPen(QColor("white") if (self._hover and self.kind == "close") else theme.TEXT_DIM, 1.1))
        s = 5.0
        if self.kind == "min":
            p.drawLine(QPointF(c.x() - s, c.y()), QPointF(c.x() + s, c.y()))
        elif self.kind == "max":
            p.drawRoundedRect(QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s), 1.5, 1.5)
        else:
            p.drawLine(QPointF(c.x() - s, c.y() - s), QPointF(c.x() + s, c.y() + s))
            p.drawLine(QPointF(c.x() - s, c.y() + s), QPointF(c.x() + s, c.y() - s))


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for wdg in widgets:
        if wdg is None:
            lay.addStretch(1)
        elif isinstance(wdg, int):
            lay.addSpacing(wdg)
        elif isinstance(wdg, QWidget):
            lay.addWidget(wdg)
        else:
            lay.addLayout(wdg)
    return lay


def vbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for wdg in widgets:
        if wdg is None:
            lay.addStretch(1)
        elif isinstance(wdg, int):
            lay.addSpacing(wdg)
        elif isinstance(wdg, QWidget):
            lay.addWidget(wdg)
        else:
            lay.addLayout(wdg)
    return lay
