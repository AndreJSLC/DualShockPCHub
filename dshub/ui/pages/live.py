"""Live view: the controller lighting up, plus battery and connection facts."""

from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dshub.core.pads.base import Pad
from dshub.core.state import Connection, Model
from dshub.ui import theme
from dshub.ui.flat_view import FlatView
from dshub.ui.widgets import BatteryIcon, Card, Meter, StickPlot, battery_color, font, label


class LivePage(QWidget):
    def __init__(self, hub=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hub = hub
        self._est_t = 0.0
        self.pad: Pad | None = None
        self._last_state = None
        self._last_battery = None
        self._last_lights = None
        self._bat_color = ""
        self._rate_t = time.perf_counter()
        self._rate_n = 0

        self.view = FlatView(Model.DS4)
        self.view.setCursor(Qt.CursorShape.ArrowCursor)

        side = QVBoxLayout()
        side.setSpacing(12)

        # Battery card
        bat = Card()
        bat.lay.addWidget(label("BATTERY", "section"))
        row = QHBoxLayout()
        self.bat_value = QLabel("—")
        self.bat_value.setFont(font(30, QFont.Weight.DemiBold))
        self.bat_icon = BatteryIcon(size=QSize(34, 17))
        row.addWidget(self.bat_value)
        row.addStretch(1)
        row.addWidget(self.bat_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        bat.lay.addLayout(row)
        self.bat_note = label("", "dim")
        self.bat_note.setTextFormat(Qt.TextFormat.RichText)
        self.bat_note.setWordWrap(True)
        bat.lay.addWidget(self.bat_note)
        side.addWidget(bat)

        # Connection card
        conn = Card()
        conn.lay.addWidget(label("CONNECTION", "section"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self.facts: dict[str, QLabel] = {}
        for r, key in enumerate(("Link", "Address", "Firmware", "Driver", "Report rate")):
            k = label(key, "dim")
            v = QLabel("—")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setFont(font(12))
            grid.addWidget(k, r, 0)
            grid.addWidget(v, r, 1, Qt.AlignmentFlag.AlignRight)
            self.facts[key] = v
        conn.lay.addLayout(grid)
        side.addWidget(conn)

        # Analog card
        ana = Card()
        ana.lay.addWidget(label("ANALOG", "section"))
        sticks = QHBoxLayout()
        self.left = StickPlot("L")
        self.right = StickPlot("R")
        sticks.addWidget(self.left)
        sticks.addWidget(self.right)
        ana.lay.addLayout(sticks)
        self.l2 = Meter("L2")
        self.r2 = Meter("R2")
        ana.lay.addWidget(self.l2)
        ana.lay.addWidget(self.r2)
        test = QPushButton("Test sticks…")
        test.setToolTip("Measure drift, noise, reach and how smoothly the sticks update")
        test.clicked.connect(self._stick_test)
        ana.lay.addWidget(test)
        side.addWidget(ana)
        side.addStretch(1)

        sidew = QWidget()
        sidew.setLayout(side)
        sidew.setFixedWidth(272)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 20, 20)
        lay.setSpacing(16)
        lay.addWidget(self.view, 1)
        lay.addWidget(sidew)

    def set_pad(self, pad: Pad | None) -> None:
        self.pad = pad
        self._last_state = None
        self._last_battery = None
        self._last_lights = None
        if pad is None:
            return
        self.view.set_model(pad.info.model)
        self.view.set_dimmed(False)
        info = pad.info
        link = "USB cable" if info.connection is Connection.USB else "Bluetooth"
        self.facts["Link"].setText(link)
        self.facts["Address"].setText(info.serial or "—")
        self.facts["Firmware"].setText(info.firmware or "—")
        driver = {"hid": "Windows HID (built-in)", "dshidmini-xinput": "DsHidMini · XInput",
                  "dshidmini-ds4w": "DsHidMini · exclusive"}.get(info.backend,
                                                                                                info.backend)
        if info.backend == "hid" and info.model is Model.DS3:
            driver = "DsHidMini · SXS"
        self.facts["Driver"].setText(driver)
        self._rate_t, self._rate_n = time.perf_counter(), self._count(pad)
        self.left.deadzone = self.right.deadzone = 0.0

    def _show_battery(self, b) -> None:
        self.bat_value.setText(f"{b.level}%" if b.level is not None else ("Full" if b.full else "—"))
        col = battery_color(b).name()
        if col != self._bat_color:
            self._bat_color = col
            self.bat_value.setStyleSheet(f"color: {col}")
        self.bat_icon.set_battery(b)
        if b.full:
            note = "Fully charged"
        elif b.charging:
            note = "Charging" + (" (level not reported while charging)" if b.level is None else "")
        elif b.wired:
            note = "On cable power"
        elif b.level is None:
            note = "Level not reported"
        else:
            note = "On battery"
        est = self.hub.battery_estimate(self.pad) if self.hub is not None and self.pad is not None else None
        if est is not None and est.text():
            note += f" · {est.text()}"
        slow = self.hub.slow_charge_factor(self.pad) if self.hub is not None and self.pad is not None else None
        tip = ""
        if slow is not None:
            note += f"<br><span style='color:{theme.WARN.name()}'>Charges {slow:.1f}× slower than normal</span>"
            tip = ("Measured by this app while the controller was plugged in. Usually it's the cable: try a short, "
                   "good-quality cable, and turn on Save battery on the Lights page while it charges. If it's still "
                   "slow, the controller's battery is wearing out (a common, inexpensive repair).")
        self.bat_note.setText(note)
        self.bat_note.setToolTip(tip)

    def _stick_test(self) -> None:
        if self.pad is None:
            return
        from dshub.ui.stick_test import StickTestDialog

        StickTestDialog(self.pad, self.window(), hub=self.hub).exec()

    @staticmethod
    def _count(pad: Pad) -> int:
        return pad.raw_reports or pad.reports

    def tick(self) -> None:
        pad = self.pad
        if pad is None:
            return
        st = pad.state
        if time.perf_counter() - self._est_t > 5.0 and self._last_battery is not None:
            self._est_t = time.perf_counter()  # the estimate drifts with time, not just with level changes
            self._show_battery(self._last_battery)
        if st is not self._last_state:
            self._last_state = st
            self.view.set_state(st)
            self.left.set_value(st.lx, st.ly)
            self.right.set_value(st.rx, st.ry)
            self.l2.set_value(st.l2)
            self.r2.set_value(st.r2)
            b = st.battery
            if b != self._last_battery:
                self._last_battery = b
                self._show_battery(b)
        lights = (pad.lightbar, pad.player_led or (pad.info.slot if pad.info.model is Model.DS3 else 0))
        if lights != self._last_lights:
            self._last_lights = lights
            self.view.set_lightbar(QColor(*lights[0]) if lights[0] else None)
            self.view.set_player_leds(lights[1])

        now = time.perf_counter()
        if now - self._rate_t >= 0.5:
            n = self._count(pad)
            hz = (n - self._rate_n) / (now - self._rate_t)
            self._rate_t, self._rate_n = now, n
            self.facts["Report rate"].setText(f"{hz:.0f} Hz" if hz >= 1 else "idle")
