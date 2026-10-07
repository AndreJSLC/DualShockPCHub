"""Lights & rumble: lightbar colour, player LEDs, motor test."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QColorDialog, QHBoxLayout, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

from dshub.core.pads.base import Pad
from dshub.core.state import Model
from dshub.ui import theme
from dshub.ui.flat_view import FlatView
from dshub.ui.hub import Hub
from dshub.ui.widgets import Card, Segmented, Toggle, hbox, label

SWATCHES = [
    ("PlayStation blue", (20, 60, 255)), ("Ice", (120, 200, 255)), ("White", (255, 255, 255)),
    ("Violet", (140, 60, 255)), ("Pink", (255, 60, 170)), ("Red", (255, 30, 40)), ("Orange", (255, 110, 10)),
    ("Gold", (255, 200, 20)), ("Green", (30, 230, 90)), ("Teal", (20, 220, 190)),
]


class Swatch(QAbstractButton):
    def __init__(self, name: str, rgb: tuple[int, int, int] | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rgb = rgb
        self.setToolTip(name)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(30, 30))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        if self.rgb is None:
            p.setPen(QPen(theme.TEXT_DIM, 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r)
            inset = r.adjusted(3, 3, -3, -3)
            p.drawLine(inset.bottomLeft(), inset.topRight())
        else:
            col = QColor(*self.rgb)
            glow = QColor(col)
            glow.setAlpha(70 if self.isChecked() else 0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
            p.setBrush(col)
            p.drawEllipse(r)
        if self.isChecked():
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(-2.5, -2.5, 2.5, 2.5))


class LightsPage(QWidget):
    def __init__(self, hub: Hub, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hub = hub
        self.pad: Pad | None = None
        self._last_state = None
        self._last_lights = None
        self._base_rgb: tuple[int, int, int] | None = SWATCHES[0][1]

        self.view = FlatView(Model.DS4)

        panel = QVBoxLayout()
        panel.setSpacing(12)

        # Lightbar
        self.light_card = Card()
        self.light_card.lay.addWidget(label("LIGHTBAR", "section"))
        grid = QHBoxLayout()
        grid.setSpacing(2)
        self.swatches: list[Swatch] = []
        rows = QVBoxLayout()
        for chunk in (SWATCHES[:5], SWATCHES[5:]):
            row = QHBoxLayout()
            row.setSpacing(2)
            for name, rgb in chunk:
                sw = Swatch(name, rgb)
                sw.clicked.connect(lambda _=False, c=rgb: self._pick(c))
                self.swatches.append(sw)
                row.addWidget(sw)
            row.addStretch(1)
            rows.addLayout(row)
        off = Swatch("Off", None)
        off.clicked.connect(lambda: self._pick(None))
        self.swatches.append(off)
        grid.addLayout(rows)
        self.light_card.lay.addLayout(grid)
        custom = QPushButton("Custom colour…")
        custom.clicked.connect(self._custom)
        self.light_card.lay.addLayout(hbox(off, custom, None))
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(5, 100)
        self.brightness.setValue(100)
        self.brightness.valueChanged.connect(lambda _v: self._apply())
        self.light_card.lay.addLayout(hbox(label("Brightness", "faint"), self.brightness, spacing=10))
        panel.addWidget(self.light_card)
        self.no_light = label("", "dim")
        self.no_light.setWordWrap(True)

        # Player LEDs
        self.player_card = Card()
        self.player_card.lay.addWidget(label("PLAYER LIGHTS", "section"))
        self.player = Segmented(["Off", "1", "2", "3", "4"])
        self.player.changed.connect(self._player)
        self.player_card.lay.addWidget(self.player)
        panel.addWidget(self.player_card)

        # Battery saver (DualSense)
        self.saver_card = Card()
        self.saver_card.lay.addWidget(label("BATTERY SAVER", "section"))
        self.saver = Toggle()
        self.saver.toggled.connect(self._saver)
        self.saver_card.lay.addLayout(hbox(label("Save battery", "h2"), None, self.saver))
        saver_text = label("Turns the light bar off, dims the player lights, halves rumble and puts the "
                           "unused motion sensors to sleep. The DualSense's light bar and haptic motors are "
                           "what drain it fastest.", "dim")
        saver_text.setWordWrap(True)
        self.saver_card.lay.addWidget(saver_text)
        panel.addWidget(self.saver_card)

        # Rumble
        self.rumble_card = Card()
        self.rumble_card.lay.addWidget(label("RUMBLE TEST", "section"))
        self.power = QSlider(Qt.Orientation.Horizontal)
        self.power.setRange(10, 100)
        self.power.setValue(70)
        self.rumble_card.lay.addLayout(hbox(label("Strength", "faint"), self.power, spacing=10))
        strong = QPushButton("Strong motor")
        weak = QPushButton("Weak motor")
        both = QPushButton("Both")
        strong.clicked.connect(lambda: self._buzz(1, 0))
        weak.clicked.connect(lambda: self._buzz(0, 1))
        both.clicked.connect(lambda: self._buzz(1, 1))
        self.rumble_card.lay.addLayout(hbox(strong, weak, both))
        panel.addWidget(self.rumble_card)
        panel.addWidget(self.no_light)
        panel.addStretch(1)
        self._stop_timer = QTimer(self, singleShot=True, timeout=self._stop_buzz)

        panel_w = QWidget()
        panel_w.setLayout(panel)
        panel_w.setFixedWidth(330)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 20, 20)
        lay.setSpacing(16)
        lay.addWidget(self.view, 1)
        lay.addWidget(panel_w)

    def set_pad(self, pad: Pad | None) -> None:
        self.pad = pad
        self._last_state = None
        self._last_lights = None
        if pad is None:
            return
        self.view.set_model(pad.info.model)
        caps = pad.caps
        self.light_card.setVisible(caps.lightbar)
        self.player_card.setVisible(caps.player_leds)
        self.rumble_card.setVisible(caps.rumble)
        self.saver_card.setVisible(caps.battery_saver)
        self.saver.blockSignals(True)
        self.saver.setChecked(pad.battery_saver)
        self.saver.blockSignals(False)
        notes = []
        if not caps.lightbar:
            notes.append("This controller has no lightbar.")
        if pad.info.model is Model.DS3 and not caps.player_leds:
            notes.append("Player lights on a DS3 in XInput mode follow the Windows controller slot.")
        self.no_light.setText(" ".join(notes))
        self.no_light.setVisible(bool(notes))
        rgb = pad.lightbar
        self._base_rgb = rgb
        self.brightness.blockSignals(True)
        self.brightness.setValue(100)
        self.brightness.blockSignals(False)
        for sw in self.swatches:
            sw.setChecked(sw.rgb == rgb)
        self.player.index = pad.player_led
        self.player.update()

    def _pick(self, rgb: tuple[int, int, int] | None) -> None:
        self._base_rgb = rgb
        self._apply()

    def _apply(self) -> None:
        if self.pad is None:
            return
        rgb = self._base_rgb
        if rgb is not None:
            k = self.brightness.value() / 100
            rgb = tuple(round(c * k) for c in rgb)
        self.hub.set_lightbar(self.pad, rgb)

    def _custom(self) -> None:
        start = QColor(*(self._base_rgb or (20, 60, 255)))
        col = QColorDialog.getColor(start, self, "Lightbar colour")
        if col.isValid():
            for sw in self.swatches:
                sw.setAutoExclusive(False)
                sw.setChecked(False)
                sw.setAutoExclusive(True)
            self._pick((col.red(), col.green(), col.blue()))

    def _player(self, idx: int) -> None:
        if self.pad is not None:
            self.hub.set_player(self.pad, idx)

    def _saver(self, on: bool) -> None:
        if self.pad is not None:
            self.hub.set_battery_saver(self.pad, on)

    def _buzz(self, strong: float, weak: float) -> None:
        if self.pad is None:
            return
        k = self.power.value() / 100
        self.pad.set_rumble(strong * k, weak * k)
        self._stop_timer.start(450)

    def _stop_buzz(self) -> None:
        if self.pad is not None:
            self.pad.set_rumble(0, 0)

    def tick(self) -> None:
        pad = self.pad
        if pad is None:
            return
        st = pad.state
        if st is not self._last_state:
            self._last_state = st
            self.view.set_state(st)
        lights = (pad.lightbar, pad.player_led)
        if lights != self._last_lights:
            self._last_lights = lights
            self.view.set_lightbar(QColor(*lights[0]) if lights[0] else None)
            self.view.set_player_leds(lights[1])
