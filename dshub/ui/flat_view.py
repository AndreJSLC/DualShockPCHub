"""Flat, straight-on controller drawing with live input (emulator-style).

Static parts (shell, wells, keys at rest, light bar and LEDs) are painted once
into a cached pixmap; lit keys, stick caps and touch dots are pre-rendered
sprites; and each input change repaints only the area it affects.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from functools import partial
from math import ceil

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, \
    QRegion, QTransform
from PySide6.QtWidgets import QSizePolicy, QWidget

from dshub.core.state import MODEL_BUTTONS, Button, ControllerState, Model
from dshub.ui import theme
from dshub.ui.flat import FlatLayout, layout_for
from dshub.ui.flat.layout import FlatPart, FlatStick, circle

FADE_S = 0.12
MAX_FPS = 60


def _c(hex_: str, a: float = 1.0) -> QColor:
    c = QColor(hex_)
    c.setAlphaF(a)
    return c


@dataclass(frozen=True)
class FlatPalette:
    shell: QColor
    pad: QColor
    recess: QColor
    key: QColor
    key_dark: QColor
    bumper: QColor
    trigger: QColor
    seam: QColor
    arrow: QColor
    label: QColor
    ring: QColor
    gap: QColor
    cap: QColor
    cap_inner: QColor
    ps_fill: QColor
    plate: QColor = field(default_factory=lambda: _c("#2a2a2f"))
    touchpad: QColor = field(default_factory=lambda: _c("#2f2f34"))
    lightbar_off: QColor = field(default_factory=lambda: _c("#26262b"))
    glyph_rest: QColor | None = None  # None: the PlayStation colours (DS3/DS4 print them in colour)


OUTLINE = _c("#060607")  # black outlines everywhere: the emulator look
LED_OFF = _c("#3a1416")
LED_ON = _c("#ff3c46")
LED5_OFF = _c("#3b3b42")
LED5_ON = _c("#f4f7ff")
#: DualSense player-indicator patterns over its five LEDs (bit i = LED i, left to right).
DS5_PLAYER_PATTERNS = {1: 0x04, 2: 0x0A, 3: 0x15, 4: 0x1B, 5: 0x1F}

DARK = FlatPalette(
    shell=_c("#46464c"), pad=_c("#4b4b51"), recess=_c("#38383d"), key=_c("#77777f"), key_dark=_c("#5c5c63"),
    bumper=_c("#5b5b61"), trigger=_c("#4f4f55"), seam=_c("#141416"), arrow=_c("#8b8b93"), label=_c("#c4c4cc"),
    ring=_c("#3c3c41"), gap=_c("#18181b"), cap=_c("#6b6b73"), cap_inner=_c("#5f5f67"), ps_fill=_c("#2e2e33"),
)
DUALSENSE = FlatPalette(
    shell=_c("#e6e6ea"), pad=_c("#e6e6ea"), recess=_c("#d4d4da"), key=_c("#f4f4f6"), key_dark=_c("#d9d9de"),
    bumper=_c("#ededf0"), trigger=_c("#dcdce1"), seam=_c("#8e8e96"), arrow=_c("#9a9aa2"), label=_c("#55555c"),
    ring=_c("#2f2f34"), gap=_c("#121215"), cap=_c("#3d3d43"), cap_inner=_c("#34343a"), ps_fill=_c("#1d1d21"),
    plate=_c("#2a2a2f"), touchpad=_c("#f3f3f5"), lightbar_off=_c("#c4c7d0"), glyph_rest=_c("#74747c"),
)
EDGE = replace(DUALSENSE, plate=_c("#17171a"), touchpad=_c("#1c1c20"), key=_c("#2e2e33"), key_dark=_c("#232327"),
               arrow=_c("#c9c9cf"), glyph_rest=_c("#c9c9cf"), bumper=_c("#2a2a2f"), trigger=_c("#232327"))
PALETTES = {Model.DS3: DARK, Model.DS4: DARK, Model.DS5: DUALSENSE, Model.DS5_EDGE: EDGE}


class FlatView(QWidget):
    """Flat controller drawing that mirrors live input.

    Cheap to keep on screen: the body (plus the light bar and player LEDs, which
    only change when set) is a cached pixmap; everything that lights up or moves
    is pre-rendered once per size into small sprites and blitted with an opacity;
    ``set_state`` repaints only the regions whose input changed, and nothing at
    all while the widget is hidden.
    """

    buttonClicked = Signal(object)  # Button

    def __init__(self, model: Model, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._state = ControllerState()
        self._prev: frozenset[Button] = frozenset()
        self._released: dict[Button, float] = {}
        self._selected: Button | None = None
        self._hover: Button | None = None
        self._leds = 0
        self._lightbar: QColor | None = None
        self._dimmed = False
        self._static: QPixmap | None = None
        self._geom_key: tuple | None = None
        self._t = QTransform()
        self._dpr = 1.0
        self._sprites: dict[tuple, tuple[QPixmap, QPoint]] = {}
        self._regions: dict[Button, QRegion] = {}
        self._touch_region: QRegion | None = None
        self._fade = QTimer(self, interval=1000 // MAX_FPS, timeout=self._on_fade)
        self.set_model(model)

    # ------------------------------------------------------------------ API
    def model(self) -> Model:
        return self._model

    def set_model(self, model: Model) -> None:
        lay = layout_for(model)
        if lay is None:
            raise ValueError(f"no flat drawing for {model.value}")
        self._model, self._lay = model, lay
        self._pal = PALETTES.get(model, DARK)
        self._all_parts: list[FlatPart] = lay.behind + lay.parts
        # Shoulder tabs are tucked under the shell (and L2 under L1): only their visible part
        # may light up or take clicks, or a glow would spill over the D-pad / face buttons.
        self._visible: dict[int, QPainterPath] = {}
        covers = lay.shell
        for part in reversed(lay.behind):  # L1/R1 first, then L2/R2 behind them
            self._visible[id(part)] = part.shape.subtracted(covers).simplified()
            covers = covers.united(part.shape)
        for part in lay.parts:
            self._visible[id(part)] = part.shape
        self._static = None
        self._geom_key = None
        self.update()

    def set_state(self, state: ControllerState) -> None:
        """Store the latest input and repaint only what it changed."""
        prev = self._state
        now = time.perf_counter()
        for b in self._prev - state.buttons:
            self._released[b] = now
        changed = self._prev ^ state.buttons
        self._prev = state.buttons
        self._state = state
        if not self.isVisible():
            return
        self._ensure_geometry()
        regions = self._regions
        dirty = QRegion()
        for b in changed:
            if b in regions:
                dirty = dirty.united(regions[b])
        for b, now_xy, prev_xy in ((Button.L3, (state.lx, state.ly), (prev.lx, prev.ly)),
                                   (Button.R3, (state.rx, state.ry), (prev.rx, prev.ry))):
            if now_xy != prev_xy and b in regions:
                dirty = dirty.united(regions[b])
        for b, v, pv in ((Button.L2, state.l2, prev.l2), (Button.R2, state.r2, prev.r2)):
            if v != pv and b in regions:
                dirty = dirty.united(regions[b])
        if state.touches != prev.touches and self._touch_region is not None:
            dirty = dirty.united(self._touch_region)
        if not dirty.isEmpty():
            self.update(dirty)
        if self._released and not self._fade.isActive():
            self._fade.start()

    def set_selected(self, button: Button | None) -> None:
        if button != self._selected:
            self._selected = button
            self.update()

    def set_lightbar(self, color: QColor | None) -> None:
        if color != self._lightbar:
            self._lightbar = color
            if self._lay.lightbar is not None:
                self.update()

    def set_player_leds(self, n: int) -> None:
        if n != self._leds:
            self._leds = n
            if self._lay.leds:
                self.update()

    def set_dimmed(self, dimmed: bool) -> None:
        if dimmed != self._dimmed:
            self._dimmed = dimmed
            self.update()

    def button_at(self, pos: QPointF) -> Button | None:
        inv, ok = self._xform().inverted()
        if not ok:
            return None
        p = inv.map(pos)
        present = MODEL_BUTTONS[self._model]
        for stick in self._lay.sticks:
            d = p - stick.center
            if d.x() ** 2 + d.y() ** 2 <= stick.ring_r ** 2:
                return stick.button
        for part in reversed(self._all_parts):  # topmost first
            if part.button in present and self._visible[id(part)].contains(p):
                return part.button
        return None

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(640, 420)

    # ------------------------------------------------------------------ geometry
    def resizeEvent(self, _e) -> None:  # noqa: N802
        self._static = None
        self._geom_key = None

    def _xform(self) -> QTransform:
        b = self._lay.size
        margin = 14
        s = min((self.width() - 2 * margin) / b.width(), (self.height() - 2 * margin) / b.height())
        s = max(s, 0.01)
        ox = (self.width() - b.width() * s) / 2 - b.left() * s
        oy = (self.height() - b.height() * s) / 2 - b.top() * s
        return QTransform(s, 0, 0, s, ox, oy)

    def _ensure_geometry(self) -> None:
        """Transform, sprite cache and repaint regions for the current size (rebuilt on resize)."""
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, self._model)
        if key == self._geom_key:
            return
        self._geom_key = key
        self._dpr = dpr
        self._t = self._xform()
        self._sprites = {}
        lay, ow = self._lay, self._lay.outline
        regions: dict[Button, QRegion] = {}
        for part in self._all_parts:
            regions[part.button] = QRegion(self._dev_rect(self._lit_bounds(part)))
        for stick in lay.sticks:
            reach = max(stick.ring_r, stick.travel + stick.cap_r + 10.0 + ow) + 2.0
            c = stick.center
            regions[stick.button] = QRegion(self._dev_rect(QRectF(c.x() - reach, c.y() - reach, 2 * reach, 2 * reach)))
        self._regions = regions
        pads = [part for part in lay.parts if part.kind == "touchpad"]
        self._touch_region = (QRegion(self._dev_rect(pads[0].shape.boundingRect().adjusted(-14, -14, 14, 14)))
                              if pads else None)
        # Where the lights can paint (glows included): they are redrawn only when a repaint reaches them.
        self._lightbar_rect = (self._dev_rect(self._glow_rect(lay.lightbar.boundingRect(), 1.5))
                               if lay.lightbar is not None else QRect())
        self._led_rects = ([self._dev_rect(r.adjusted(-1, -1, 1, 1)) for r in lay.leds],  # unlit: just the LED
                           [self._dev_rect(self._glow_rect(r, 3.0)) for r in lay.leds])  # lit: with its glow

    def _led_rect(self) -> QRect:
        """Device area the player LEDs paint right now (a lit LED's glow reaches much further)."""
        lay = self._lay
        ds5 = lay.led_style == "ds5"
        bits = DS5_PLAYER_PATTERNS.get(self._leds, 0) if ds5 else 0
        out = QRect()
        for i in range(len(lay.leds)):
            on = lay.led_style == "ds2" or (bool(bits & (1 << i)) if ds5 else self._leds == i + 1)
            out = out.united(self._led_rects[1 if on else 0][i])
        return out

    def _dev_rect(self, r: QRectF) -> QRect:
        return self._t.mapRect(r).toAlignedRect().adjusted(-2, -2, 2, 2)

    @staticmethod
    def _glow_rect(r: QRectF, spread: float = 1.0) -> QRectF:
        rad = max(r.width(), r.height()) * 0.5 + 10 * spread
        c = r.center()
        return QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad)

    def _lit_bounds(self, part: FlatPart) -> QRectF:
        r = self._visible[id(part)].boundingRect()
        ow = self._lay.outline
        return self._glow_rect(r).united(r.adjusted(-ow, -ow, ow, ow))

    def _sprite(self, key: tuple, bounds: QRectF, paint) -> tuple[QPixmap, QPoint]:
        """Render ``paint(painter)`` (drawing units) once per size into a small pixmap."""
        sprite = self._sprites.get(key)
        if sprite is None:
            rect = self._dev_rect(bounds)
            pm = QPixmap(max(1, ceil(rect.width() * self._dpr)), max(1, ceil(rect.height() * self._dpr)))
            pm.setDevicePixelRatio(self._dpr)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setTransform(self._t * QTransform.fromTranslate(-rect.x(), -rect.y()))
            paint(p)
            p.end()
            sprite = self._sprites[key] = (pm, rect.topLeft())
        return sprite

    # ------------------------------------------------------------------ static layer
    def _render_static(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        lay = self._lay
        ow = lay.outline
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setTransform(self._xform())

        def fill_stroke(path: QPainterPath, fill: QColor, pen: QColor = OUTLINE, width: float = ow) -> None:
            p.fillPath(path, fill)
            pen_ = QPen(pen, width)
            pen_.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.strokePath(path, pen_)

        pal = self._pal
        # soft drop shadow so the pad sits on the glass
        shadow = lay.shell.translated(0, 4)
        for i, a in enumerate((0.10, 0.08, 0.06)):
            pen = QPen(QColor(0, 0, 0, round(255 * a)), 6 + i * 6)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.strokePath(shadow, pen)

        for part in lay.behind:  # L2/R2 then L1/R1 tabs, tucked behind the shell
            fill_stroke(part.shape, pal.trigger if part.kind == "trigger" else pal.bumper)
        fill_stroke(lay.shell, pal.shell)

        p.save()
        p.setClipPath(lay.shell)
        for pad in lay.pads:
            fill_stroke(pad, pal.pad, pal.seam, ow * 0.65)
        if lay.plate is not None:
            fill_stroke(lay.plate, pal.plate, OUTLINE, ow * 0.8)
        for seam in lay.seams:
            pen = QPen(pal.seam, ow * 0.65)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.strokePath(seam, pen)
        p.restore()
        fill_stroke(lay.shell, QColor(0, 0, 0, 0))  # crisp outer outline over the clipped seams
        if lay.lightbar is not None:
            fill_stroke(lay.lightbar, pal.lightbar_off, OUTLINE, ow * 0.6)

        for recess in lay.recesses:
            fill_stroke(recess, pal.recess, pal.seam, ow * 0.6)
        for stick in lay.sticks:
            fill_stroke(circle(stick.center.x(), stick.center.y(), stick.ring_r), pal.ring)
            fill_stroke(circle(stick.center.x(), stick.center.y(), stick.gap_r), pal.gap, OUTLINE, ow * 0.5)

        present = MODEL_BUTTONS[lay.model]
        for part in lay.parts:
            if part.button not in present:
                continue
            if part.kind == "ps":
                fill_stroke(part.shape, pal.ps_fill)
                self._ps_mark(p, part.shape.boundingRect())
            elif part.kind == "touchpad":
                fill_stroke(part.shape, pal.touchpad)
            elif part.kind == "face":
                fill_stroke(part.shape, pal.key_dark)
                rest = pal.glyph_rest or theme.FACE_COLORS.get(part.button, pal.label)
                self._glyph(p, part, rest, ow * 0.85)
            else:
                fill_stroke(part.shape, pal.key)
                if part.glyph is not None:  # D-pad arrows sit outside the arm
                    p.fillPath(part.glyph, pal.arrow)
        for pos, text, *size in lay.labels:  # optional third item: text size in drawing units
            self._text(p, pos, text, size[0] if size else 6.4, pal.label)
        p.end()
        return pm

    def _paint_lightbar(self, p: QPainter) -> None:
        """Light bar / light strips in the colour the pad is set to."""
        lay, ow = self._lay, self._lay.outline
        if lay.lightbar is not None and self._lightbar is not None:
            self._glow(p, lay.lightbar, self._lightbar, 0.8, spread=1.5)
            p.fillPath(lay.lightbar, self._lightbar)
            p.strokePath(lay.lightbar, QPen(OUTLINE, ow * 0.6))

    def _paint_leds(self, p: QPainter) -> None:
        """Player LEDs. DS3 lights one red LED per player number; the DualSense lights its
        five white dots in the same patterns the pad itself uses; the DS2 shows its ANALOG LED."""
        lay, ow = self._lay, self._lay.outline
        ds5 = lay.led_style == "ds5"
        lit_bits = DS5_PLAYER_PATTERNS.get(self._leds, 0) if ds5 else 0
        on_colour, off_colour = (LED5_ON, LED5_OFF) if ds5 else (LED_ON, LED_OFF)
        for i, r in enumerate(lay.leds):
            if lay.led_style == "ds2":
                on = True  # the ANALOG LED: sticks only work in analog mode, which adapters switch on
            else:
                on = bool(lit_bits & (1 << i)) if ds5 else self._leds == i + 1
            path = QPainterPath()
            path.addRoundedRect(r, r.height() / 2, r.height() / 2)
            if on:
                self._glow(p, path, on_colour, 1.0, spread=3.0)
            p.fillPath(path, on_colour if on else off_colour)
            p.strokePath(path, QPen(OUTLINE, ow * 0.4))

    @staticmethod
    def _glyph(p: QPainter, part: FlatPart, colour: QColor, width: float) -> None:
        if part.glyph is None:
            return
        pen = QPen(colour, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.strokePath(part.glyph, pen)

    @staticmethod
    def _text(p: QPainter, pos: QPointF, text: str, size: float, colour: QColor = DARK.label) -> None:
        f = QFont(theme.FONT_FAMILY)
        f.setPixelSize(max(1, round(size * 4)))  # draw at 4x and scale down: crisp at any zoom
        f.setWeight(QFont.Weight.DemiBold)
        p.save()
        p.translate(pos)
        p.scale(0.25, 0.25)
        p.setFont(f)
        p.setPen(colour)
        p.drawText(QRectF(-200, -size * 2.5, 400, size * 5), Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    def _ps_mark(self, p: QPainter, r: QRectF) -> None:
        self._text(p, r.center(), "PS", r.height() * 0.42, QColor("#a9a9b2"))

    # ------------------------------------------------------------------ sprite painters (k = 1)
    def _paint_lit(self, p: QPainter, part: FlatPart, colour: QColor) -> None:
        shape, ow = self._visible[id(part)], self._lay.outline
        self._glow(p, shape, colour, 1.0)
        p.fillPath(shape, _alpha(colour, 0.9))
        p.strokePath(shape, QPen(OUTLINE, ow))
        if part.kind == "face":
            self._glyph(p, part, QColor("white"), ow * 0.95)

    def _paint_cap(self, p: QPainter, stick: FlatStick, c: QPointF, k: float = 0.0) -> None:
        ow = self._lay.outline
        cap = circle(c.x(), c.y(), stick.cap_r)
        if k:
            self._glow(p, cap, theme.ACCENT, k)
        p.fillPath(cap.translated(0.8, 1.6), QColor(0, 0, 0, 110))
        p.fillPath(cap, _mix(self._pal.cap, theme.ACCENT, 0.85 * k))
        p.strokePath(cap, QPen(OUTLINE, ow))
        inner = circle(c.x(), c.y(), stick.cap_r * 0.72)
        p.strokePath(inner, QPen(_mix(self._pal.cap_inner, theme.ACCENT.lighter(130), k), ow * 0.6))

    def _paint_touch(self, p: QPainter, c: QPointF) -> None:
        dot = circle(c.x(), c.y(), 4.5)
        self._glow(p, dot, theme.ACCENT, 1.0, spread=0.8)
        p.fillPath(dot, theme.ACCENT.lighter(130))

    # ------------------------------------------------------------------ live layer
    def _intensity(self, button: Button, now: float) -> float:
        if button in self._state.buttons:
            return 1.0
        t = self._released.get(button)
        if t is None:
            return 0.0
        k = 1.0 - (now - t) / FADE_S
        if k <= 0:
            self._released.pop(button, None)
            return 0.0
        return k

    def _on_fade(self) -> None:
        now = time.perf_counter()
        dirty = QRegion()
        for b, t in list(self._released.items()):
            if b in self._regions:
                dirty = dirty.united(self._regions[b])
            if now - t > FADE_S:
                del self._released[b]  # this last repaint clears the glow
        if not self._released:
            self._fade.stop()
        if not dirty.isEmpty():
            self.update(dirty)

    def paintEvent(self, e) -> None:  # noqa: N802
        self._ensure_geometry()
        if self._static is None:
            self._static = self._render_static()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self._static)
        area = e.rect()
        lay, st, t, regions = self._lay, self._state, self._t, self._regions
        ow = lay.outline
        now = time.perf_counter()
        present = MODEL_BUTTONS[lay.model]
        scale = t.m11()

        def blit(sprite: tuple[QPixmap, QPoint], opacity: float = 1.0, offset: QPointF | None = None) -> None:
            pm, pos = sprite
            p.setOpacity(opacity)
            p.drawPixmap(QPointF(pos) + offset if offset is not None else QPointF(pos), pm)
            p.setOpacity(1.0)

        def visible(button: Button) -> bool:
            reg = regions.get(button)
            return reg is not None and reg.boundingRect().intersects(area)

        # analog triggers: the L2/R2 tabs fill from the bottom with the pressure
        for part in lay.behind:
            if part.kind != "trigger":
                continue
            v = st.l2 if part.button is Button.L2 else st.r2
            if v <= 0.01 or not visible(part.button):
                continue
            vis = self._visible[id(part)]
            r = vis.boundingRect()
            if v > 0.6:
                blit(self._sprite(("trigger-glow", part.button), self._glow_rect(r),
                                  partial(self._glow, shape=vis, colour=theme.ACCENT, k=1.0)), (v - 0.6) / 0.4)
            # fill (opaque accent, faded to the pressure's alpha) clipped to the pressed height, then outline
            fill = self._sprite(("trigger-fill", part.button), r.adjusted(-ow, -ow, ow, ow),
                                lambda q, shape=vis: q.fillPath(shape, theme.ACCENT))
            level = t.mapRect(QRectF(r.left() - ow, r.bottom() - r.height() * v, r.width() + 2 * ow, r.height() * v + ow))
            p.save()
            p.setClipRect(level)
            blit(fill, 0.55 + 0.45 * v)
            p.restore()
            blit(self._sprite(("trigger-outline", part.button), r.adjusted(-ow, -ow, ow, ow),
                              lambda q, shape=vis: q.strokePath(shape, QPen(OUTLINE, ow))))

        # pressed keys
        for part in self._all_parts:
            if part.kind == "trigger" or part.button not in present:
                continue
            k = self._intensity(part.button, now)
            if not k or not visible(part.button):
                continue
            colour = theme.FACE_COLORS.get(part.button, theme.ACCENT) if part.kind == "face" else theme.ACCENT
            blit(self._sprite(("lit", part.button), self._lit_bounds(part),
                              partial(self._paint_lit, part=part, colour=colour)), k)

        # sticks: caps move inside their rings
        values = {Button.L3: (st.lx, st.ly), Button.R3: (st.rx, st.ry)}
        for stick in lay.sticks:
            if not visible(stick.button):
                continue
            x, y = values.get(stick.button, (0.0, 0.0))
            k = self._intensity(stick.button, now)
            if not x and not y and not k:
                p.setTransform(t)  # at rest: drawn directly, exactly as before
                self._paint_cap(p, stick, stick.center)
                p.resetTransform()
                continue
            c = stick.center
            r = stick.cap_r
            bounds = QRectF(c.x() - r - 12, c.y() - r - 12, 2 * r + 24, 2 * r + 24)
            off = QPointF(round(x * stick.travel * scale), round(y * stick.travel * scale))  # whole pixels: plain blit
            blit(self._sprite(("cap", stick.button), bounds, partial(self._paint_cap, stick=stick, c=c)), 1.0, off)
            if k:
                blit(self._sprite(("cap-lit", stick.button), bounds,
                                  partial(self._paint_cap, stick=stick, c=c, k=1.0)), k, off)

        # light bar / light strips in the colour the pad is set to
        if self._lightbar is not None and self._lightbar_rect.intersects(area):
            p.setTransform(t)
            self._paint_lightbar(p)
            p.resetTransform()

        # touchpad fingers
        if self._touch_region is not None and self._touch_region.boundingRect().intersects(area):
            for part in lay.parts:
                if part.kind != "touchpad":
                    continue
                r = part.shape.boundingRect()
                mid = r.center()
                dot = self._sprite(("touch",), QRectF(mid.x() - 14, mid.y() - 14, 28, 28),
                                   partial(self._paint_touch, c=mid))
                for touch in st.touches:
                    if touch.active:
                        off = QPointF((r.left() + touch.x * r.width() - mid.x()) * scale,
                                      (r.top() + touch.y * r.height() - mid.y()) * scale)
                        blit(dot, 1.0, off)

        # hover + rebinding selection (after the player LEDs, as before)
        p.setTransform(t)
        if lay.leds and self._led_rect().intersects(area):
            self._paint_leds(p)
        for button, colour, width in ((self._hover, QColor(255, 255, 255, 150), ow * 0.9),
                                      (self._selected, theme.ACCENT, ow * 1.5)):
            shape = self._shape_of(button)
            if shape is not None:
                p.strokePath(shape, QPen(colour, width))

        if self._dimmed:
            p.resetTransform()
            p.fillRect(self.rect(), QColor(0, 0, 0, 120))

    def _shape_of(self, button: Button | None) -> QPainterPath | None:
        if button is None:
            return None
        for stick in self._lay.sticks:
            if stick.button is button:
                return circle(stick.center.x(), stick.center.y(), stick.ring_r)
        for part in self._all_parts:
            if part.button is button:
                return self._visible[id(part)]
        return None

    @staticmethod
    def _glow(p: QPainter, shape: QPainterPath, colour: QColor, k: float, spread: float = 1.0) -> None:
        r = shape.boundingRect()
        rad = max(r.width(), r.height()) * 0.5 + 10 * spread
        g = QRadialGradient(r.center(), rad)
        g.setColorAt(0.0, _alpha(colour, 0.55 * k))
        g.setColorAt(0.6, _alpha(colour, 0.22 * k))
        g.setColorAt(1.0, _alpha(colour, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(r.center(), rad, rad)

    # ------------------------------------------------------------------ mouse
    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        b = self.button_at(e.position())
        if b != self._hover:
            self._hover = b
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if b else Qt.CursorShape.ArrowCursor))
            self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        if self._hover is not None:
            self._hover = None
            self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            b = self.button_at(e.position())
            if b is not None:
                self.buttonClicked.emit(b)


def _alpha(c: QColor, a: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(max(0.0, min(1.0, a)))
    return out


def _mix(a: QColor, b: QColor, k: float) -> QColor:
    k = max(0.0, min(1.0, k))
    return QColor(round(a.red() + (b.red() - a.red()) * k), round(a.green() + (b.green() - a.green()) * k),
                  round(a.blue() + (b.blue() - a.blue()) * k))
