"""App settings: autostart, tray behaviour, notifications, about."""

from __future__ import annotations

import sys
import webbrowser
import winreg
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QSlider, QVBoxLayout, QWidget

from dshub import __version__
from dshub.ui import theme
from dshub.ui.hub import Hub
from dshub.ui.widgets import Card, Segmented, Toggle, hbox, label

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DualShockPCHub"
REPO_URL = "https://github.com/"


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    # Installed into a venv (pip install -e .): use its windowless launcher.
    script = Path(sys.executable).with_name("dualshock-pc-hub.exe")
    if script.exists():
        return f'"{script}" --tray'
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pythonw}" -m dshub --tray'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass


class SettingsPage(QWidget):
    def __init__(self, hub: Hub, parent: QWidget | None = None, on_transparency=None,
                 on_glass_style=None) -> None:
        super().__init__(parent)
        self.hub = hub
        self._on_transparency = on_transparency
        self._on_glass_style = on_glass_style
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 20)
        lay.setSpacing(14)

        general = Card()
        general.lay.addWidget(label("GENERAL", "section"))
        self._row(general, "Start with Windows", "Opens quietly in the tray when you sign in.",
                  autostart_enabled(), set_autostart)
        self._row(general, "Close to tray", "The close button hides the window; remapping keeps working. "
                                            "Quit from the tray icon.",
                  hub.settings.get("close_to_tray", True), lambda v: hub.settings.set("close_to_tray", v))
        self._row(general, "Low-battery alerts", "A Windows notification when a controller drops below 15%.",
                  hub.settings.get("battery_alerts", True), lambda v: hub.settings.set("battery_alerts", v))
        lay.addWidget(general)

        look = Card()
        look.lay.addWidget(label("APPEARANCE", "section"))
        self.style_seg = Segmented(["Frosted", "Clear"])
        self.style_seg.index = 1 if hub.settings.get("glass_style", theme.DEFAULT_GLASS_STYLE) == "clear" else 0
        self.style_seg.changed.connect(self._style_changed)
        look.lay.addLayout(hbox(label("Glass", "h2"), None, self.style_seg))
        style_text = label("Frosted blurs whatever is behind the window (Windows shows it solid while the window "
                           "isn't focused). Clear is smoked glass that stays see-through.", "dim")
        style_text.setWordWrap(True)
        look.lay.addWidget(style_text)
        look.lay.addSpacing(6)
        look.lay.addWidget(label("Glass transparency", "h2"))
        sub_text = label("How much of your desktop shows through the window. Lower it if busy wallpapers make "
                         "text hard to read.", "dim")
        sub_text.setWordWrap(True)
        look.lay.addWidget(sub_text)
        self.glass = QSlider(Qt.Orientation.Horizontal)
        self.glass.setRange(0, 100)
        self.glass.setValue(round(100 * hub.settings.get("transparency", theme.DEFAULT_TRANSPARENCY)))
        self.glass.valueChanged.connect(self._glass_changed)
        self.glass.sliderReleased.connect(lambda: hub.settings.set("transparency", self.glass.value() / 100))
        look.lay.addLayout(hbox(label("Solid", "faint"), self.glass, label("Clear", "faint"), spacing=10))
        lay.addWidget(look)

        perf = Card()
        perf.lay.addWidget(label("PERFORMANCE", "section"))
        text = label("While the window is hidden, DualShock PC Hub draws nothing and samples idle controllers "
                     "once every 2 seconds. Only a controller you're remapping is read at full speed, and that "
                     "thread sleeps until the controller sends input.", "dim")
        text.setWordWrap(True)
        perf.lay.addWidget(text)
        lay.addWidget(perf)

        about = Card()
        about.lay.addWidget(label("ABOUT", "section"))
        about.lay.addWidget(label(f"DualShock PC Hub {__version__}", "h2"))
        credits = label("Uses Nefarius' DsHidMini, BthPS3 and ViGEmBus drivers, hidapi and Qt. Not affiliated "
                        "with Sony Interactive Entertainment. PlayStation, DualShock and DualSense are "
                        "trademarks of Sony Interactive Entertainment Inc.", "faint")
        credits.setWordWrap(True)
        about.lay.addWidget(credits)
        data = QPushButton("Open settings folder")
        data.setProperty("kind", "ghost")
        data.clicked.connect(self._open_data)
        about.lay.addLayout(hbox(data, None))
        lay.addWidget(about)
        lay.addStretch(1)

    def _style_changed(self, idx: int) -> None:
        style = "clear" if idx == 1 else "frosted"
        self.hub.settings.set("glass_style", style)
        if self._on_glass_style is not None:
            self._on_glass_style(style)

    def _glass_changed(self, value: int) -> None:
        if self._on_transparency is not None:
            self._on_transparency(value / 100)
        if not self.glass.isSliderDown():  # keyboard / click on the groove
            self.hub.settings.set("transparency", value / 100)

    @staticmethod
    def _row(card: Card, title: str, sub: str, value: bool, setter) -> None:
        t = Toggle()
        t.setChecked(bool(value))
        t.toggled.connect(setter)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(title, "h2"))
        s = label(sub, "dim")
        s.setWordWrap(True)
        col.addWidget(s)
        card.lay.addLayout(hbox(col, t, spacing=16))

    @staticmethod
    def _open_data() -> None:
        from dshub.config import data_dir

        webbrowser.open(data_dir().as_uri())
