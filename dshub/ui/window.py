"""Main window: sidebar of pads, header with tabs, page stack, tray."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import logging
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMenu,
                               QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from dshub.app import SHOW_MESSAGE
from dshub.core.pads.base import Pad
from dshub.core.state import Connection
from dshub.ui import theme
from dshub.ui.acrylic import AcrylicWindow
from dshub.ui.glass import paint_dome, paint_dome_gloss
from dshub.ui.hub import Hub
from dshub.ui.pages.drivers import DriversPage
from dshub.ui.pages.lights import LightsPage
from dshub.ui.pages.live import LivePage
from dshub.ui.pages.remap import RemapPage
from dshub.ui.pages.settings import SettingsPage
from dshub.ui.widgets import (ControllerTile, NavItem, Pill, Segmented, WindowButton, battery_color, battery_text,
                              font, label)

log = logging.getLogger(__name__)
WM_DEVICECHANGE = 0x0219
WM_SHOW_REQUEST = ctypes.windll.user32.RegisterWindowMessageW(SHOW_MESSAGE)  # from a second launch
TICK_MS = 16


def app_icon(size: int = 64) -> QIcon:
    """The four PlayStation symbols on a dark rounded tile."""
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(s, s)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if s >= 32:
            paint_dome_logo(p, QPointF(s / 2, s / 2), s * 0.48)
        else:  # tiny sizes: plain symbols read better than a dome
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(12, 12, 16))
            p.drawEllipse(QRectF(0.5, 0.5, s - 1, s - 1))
            _draw_symbols(p, QRectF(s * 0.06, s * 0.06, s * 0.88, s * 0.88), max(1.3, s / 10))
        p.end()
        icon.addPixmap(pm)
    return icon


def _draw_symbols(p: QPainter, r: QRectF, pen_w: float) -> None:
    from dshub.core.state import Button

    q = r.width() / 4
    centers = {Button.TRIANGLE: QPointF(r.center().x(), r.top() + q),
               Button.CIRCLE: QPointF(r.right() - q, r.center().y()),
               Button.CROSS: QPointF(r.center().x(), r.bottom() - q),
               Button.SQUARE: QPointF(r.left() + q, r.center().y())}
    rad = q * 0.5
    p.setBrush(Qt.BrushStyle.NoBrush)
    for b, c in centers.items():
        p.setPen(QPen(theme.FACE_COLORS[b], pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        if b is Button.TRIANGLE:
            path = QPainterPath()
            path.moveTo(c.x(), c.y() - rad)
            path.lineTo(c.x() + rad * 0.95, c.y() + rad * 0.7)
            path.lineTo(c.x() - rad * 0.95, c.y() + rad * 0.7)
            path.closeSubpath()
            p.drawPath(path)
        elif b is Button.CIRCLE:
            p.drawEllipse(c, rad * 0.85, rad * 0.85)
        elif b is Button.CROSS:
            k = rad * 0.75
            p.drawLine(QPointF(c.x() - k, c.y() - k), QPointF(c.x() + k, c.y() + k))
            p.drawLine(QPointF(c.x() - k, c.y() + k), QPointF(c.x() + k, c.y() - k))
        else:
            k = rad * 0.75
            p.drawRect(QRectF(c.x() - k, c.y() - k, 2 * k, 2 * k))


def paint_dome_logo(p: QPainter, c: QPointF, rad: float) -> None:
    """The four symbols sealed under a black glass dome (PS3 PS-button style)."""
    paint_dome(p, c, rad)
    inner = rad * 0.70  # symbols fill about half the dome, leaving a ring of glass around them
    _draw_symbols(p, QRectF(c.x() - inner, c.y() - inner, inner * 2, inner * 2), max(1.1, rad / 12))
    paint_dome_gloss(p, c, rad)


class Logo(QWidget):
    def __init__(self, parent: QWidget | None = None, size: int = 34) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pm: QPixmap | None = None

    def paintEvent(self, _e) -> None:  # noqa: N802
        if self._pm is None or self._pm.devicePixelRatio() != self.devicePixelRatioF():
            dpr = self.devicePixelRatioF()
            self._pm = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
            self._pm.setDevicePixelRatio(dpr)
            self._pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(self._pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_dome_logo(q, QPointF(self.width() / 2, self.height() / 2), self.width() / 2 - 0.5)
            q.end()
        QPainter(self).drawPixmap(0, 0, self._pm)


class Toast(QLabel):
    COLORS = {"ok": theme.OK, "warn": theme.WARN, "error": theme.BAD, "info": theme.ACCENT}

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_text(self, text: str, level: str = "info") -> None:
        col = self.COLORS.get(level, theme.ACCENT)
        self.setStyleSheet(
            f"background: rgba(28,28,36,0.97); border: 1px solid rgba({col.red()},{col.green()},{col.blue()},0.55);"
            f"border-radius: 10px; padding: 10px 16px; font-size: 13px;")
        self.setText(text)
        self.setMaximumWidth(560)
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 24)
        self.raise_()
        self.show()
        self._timer.start(4500 if level in ("ok", "info") else 8000)


class EmptyPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = label("No controllers connected", "h1")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = label("Plug one in with USB or pair it over Bluetooth. Missing a driver? See Drivers & Firmware.",
                     "dim")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(60, 0, 60, 60)
        lay.addStretch(1)
        lay.addWidget(title)
        lay.addSpacing(6)
        lay.addWidget(hint)
        lay.addStretch(1)


class PadPages(QStackedWidget):
    """Live / Remap / Lights for whichever pad is selected."""

    def __init__(self, hub: Hub, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.live = LivePage(hub)
        self.remap = RemapPage(hub)
        self.lights = LightsPage(hub)
        for page in (self.live, self.remap, self.lights):
            self.addWidget(page)

    def set_pad(self, pad: Pad | None) -> None:
        for page in (self.live, self.remap, self.lights):
            page.set_pad(pad)

    def tick(self) -> None:
        self.currentWidget().tick()


class MainWindow(AcrylicWindow):
    def __init__(self, hub: Hub) -> None:
        super().__init__()
        self.hub = hub
        self.setWindowTitle("DualShock PC Hub")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(980, 640)
        self.resize(1180, 740)
        self.current: Pad | None = None
        self.tiles: dict[str, ControllerTile] = {}
        self._low_alerted: set[str] = set()
        self._quitting = False

        # ---------------------------------------------------------- sidebar
        side = QVBoxLayout()
        side.setContentsMargins(14, 0, 14, 14)
        side.setSpacing(6)
        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 0)
        brand.setSpacing(10)
        brand.addWidget(Logo())
        name = QLabel("DualShock PC Hub")
        name.setFont(font(17, QFont.Weight.Light))
        brand.addWidget(name)
        brand.addStretch(1)
        brand_w = QWidget()
        brand_w.setLayout(brand)
        brand_w.setFixedHeight(self.TITLE_HEIGHT + 10)
        side.addWidget(brand_w)
        side.addWidget(label("  CONTROLLERS", "section"))
        self.tile_box = QVBoxLayout()
        self.tile_box.setSpacing(4)
        side.addLayout(self.tile_box)
        self.no_pads = label("  Nothing connected yet", "faint")
        side.addWidget(self.no_pads)
        side.addStretch(1)
        self.group = QButtonGroup(self)
        self.nav_drivers = NavItem("Drivers & Firmware", "chip")
        self.nav_settings = NavItem("Settings", "gear")
        for nav in (self.nav_drivers, self.nav_settings):
            self.group.addButton(nav)
            side.addWidget(nav)
        self.nav_drivers.clicked.connect(lambda: self.show_page("drivers"))
        self.nav_settings.clicked.connect(lambda: self.show_page("settings"))
        sidebar = QWidget()
        sidebar.setLayout(side)
        sidebar.setFixedWidth(250)

        # ---------------------------------------------------------- header
        self.title = QLabel("")
        self.title.setFont(font(24, QFont.Weight.Light))
        self.link_pill = Pill()
        self.batt_pill = Pill()
        self.remap_pill = Pill("Remapping", theme.ACCENT)
        self.tabs = Segmented(["Live", "Remap", "Lights"])
        self.tabs.changed.connect(self._on_tab)
        controls = QHBoxLayout()
        controls.setSpacing(0)
        for kind in ("min", "max", "close"):
            b = WindowButton(kind)
            b.clicked.connect(getattr(self, f"_win_{kind}"))
            controls.addWidget(b)
        header = QHBoxLayout()
        header.setContentsMargins(20, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.title)
        header.addWidget(self.link_pill)
        header.addWidget(self.batt_pill)
        header.addWidget(self.remap_pill)
        header.addStretch(1)
        header.addLayout(controls)
        header.setAlignment(controls, Qt.AlignmentFlag.AlignTop)
        header_w = QWidget()
        header_w.setLayout(header)
        header_w.setFixedHeight(self.TITLE_HEIGHT + 10)
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(20, 0, 20, 4)
        tab_row.addWidget(self.tabs)
        tab_row.addStretch(1)
        self.tab_row_w = QWidget()
        self.tab_row_w.setLayout(tab_row)

        # ---------------------------------------------------------- pages
        self.stack = QStackedWidget()
        self.empty = EmptyPage()
        self.pad_pages = PadPages(hub)
        self.drivers = DriversPage(hub)
        self.set_glass_style(hub.settings.get("glass_style", theme.DEFAULT_GLASS_STYLE))
        self.set_transparency(hub.settings.get("transparency", theme.DEFAULT_TRANSPARENCY))
        self.settings_page = SettingsPage(hub, on_transparency=self.set_transparency,
                                          on_glass_style=self.set_glass_style)
        for page in (self.empty, self.pad_pages, self.drivers, self.settings_page):
            self.stack.addWidget(page)

        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(6)
        main.addWidget(header_w)
        main.addWidget(self.tab_row_w)
        main.addWidget(self.stack, 1)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(sidebar)
        root.addLayout(main, 1)

        self.toast = Toast(self)
        hub.toast.connect(self.toast.show_text)
        hub.padAdded.connect(self._pad_added)
        hub.padRemoved.connect(self._pad_removed)
        hub.remapChanged.connect(lambda _p: self._refresh_header())
        hub.blockedChanged.connect(self._blocked)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.CoarseTimer)  # never raise the system timer resolution
        self.timer.timeout.connect(self._tick)
        self._side_t = 0.0
        # Battery alerts + tray tooltip keep working while hidden, at a crawl.
        self.slow_timer = QTimer(self, interval=30_000, timeout=self._background_tick)
        self.slow_timer.setTimerType(Qt.TimerType.VeryCoarseTimer)
        self.slow_timer.start()

        self._make_tray()
        self.show_page("empty")

    # ------------------------------------------------------------------ tray
    def _make_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("DualShock PC Hub")
        menu = QMenu()
        show = QAction("Open DualShock PC Hub", menu)
        show.triggered.connect(self.bring_to_front)
        quit_ = QAction("Quit", menu)
        quit_.triggered.connect(self.quit)
        menu.addAction(show)
        menu.addSeparator()
        menu.addAction(quit_)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.bring_to_front() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def bring_to_front(self) -> None:
        self.showNormal() if self.isMinimized() else self.show()
        self.raise_()
        self.activateWindow()

    def quit(self) -> None:
        self._quitting = True
        self.tray.hide()
        self.close()
        QApplication.quit()

    # ------------------------------------------------------------------ window buttons
    def _win_min(self) -> None:
        self.showMinimized()

    def _win_max(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _win_close(self) -> None:
        self.close()

    def closeEvent(self, e) -> None:  # noqa: N802
        if not self._quitting and self.hub.settings.get("close_to_tray", True):
            e.ignore()
            self.hide()
            if not self.hub.settings.get("tray_hint_shown"):
                self.tray.showMessage("DualShock PC Hub", "Still running in the tray. Remapping keeps working.",
                                      app_icon(), 4000)
                self.hub.settings.set("tray_hint_shown", True)
            return
        self._quitting = True
        self.tray.hide()
        e.accept()
        QApplication.quit()

    # ------------------------------------------------------------------ foreground / background
    def _update_foreground(self) -> None:
        if not hasattr(self, "timer"):
            return
        visible = self.isVisible() and not self.isMinimized()
        self.hub.manager.set_foreground(visible)
        if visible:
            if not self.timer.isActive():
                self.timer.start(TICK_MS)
        else:
            self.timer.stop()
            _trim_working_set()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self._update_foreground()

    def hideEvent(self, e) -> None:  # noqa: N802
        super().hideEvent(e)
        self._update_foreground()

    def changeEvent(self, e) -> None:  # noqa: N802
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            self._update_foreground()

    def nativeEvent(self, event_type, message):  # noqa: N802
        if event_type == b"windows_generic_MSG":
            msg = w.MSG.from_address(int(message))
            hub = getattr(self, "hub", None)
            if msg.message == WM_DEVICECHANGE and hub is not None:
                hub.manager.request_scan()
            elif msg.message == WM_SHOW_REQUEST:
                log.info("opened again: showing the window")
                QTimer.singleShot(0, self.bring_to_front)
        return super().nativeEvent(event_type, message)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        toast = getattr(self, "toast", None)
        if toast is not None and toast.isVisible():
            self.toast.move((self.width() - self.toast.width()) // 2, self.height() - self.toast.height() - 24)

    # ------------------------------------------------------------------ pads
    def _pad_added(self, pad: Pad) -> None:
        tile = ControllerTile(pad.info.title, pad.info.model)
        tile.clicked.connect(lambda _=False, p=pad: self.select_pad(p))
        self.group.addButton(tile)
        self.tiles[pad.key] = tile
        # keep tiles ordered by slot
        ordered = sorted(self.tiles.items(), key=lambda kv: self.hub.manager.pads[kv[0]].info.slot
                         if kv[0] in self.hub.manager.pads else 99)
        for _k, t in ordered:
            self.tile_box.removeWidget(t)
        for _k, t in ordered:
            self.tile_box.addWidget(t)
        self.no_pads.hide()
        self._update_tiles()
        if self.current is None and self.stack.currentWidget() is self.empty:
            self.select_pad(pad)

    def _pad_removed(self, pad: Pad) -> None:
        tile = self.tiles.pop(pad.key, None)
        if tile is not None:
            self.group.removeButton(tile)
            tile.deleteLater()
        self.no_pads.setVisible(not self.tiles)
        if self.current is pad:
            self.current = None
            pads = self.hub.pads()
            if pads:
                self.select_pad(pads[0])
            elif self.stack.currentWidget() is self.pad_pages:
                self.show_page("empty")

    def _blocked(self, blocked: list) -> None:
        if blocked:
            b = blocked[0]
            self.toast.show_text(f"{b.model.label} ({b.connection.value.upper()}): {b.reason}", "warn")

    def select_pad(self, pad: Pad) -> None:
        self.current = pad
        tile = self.tiles.get(pad.key)
        if tile is not None:
            tile.setChecked(True)
        self.pad_pages.set_pad(pad)
        self.stack.setCurrentWidget(self.pad_pages)
        self._refresh_header()

    def show_page(self, which: str) -> None:
        page = {"empty": self.empty, "drivers": self.drivers, "settings": self.settings_page}[which]
        if which == "empty" and self.hub.pads():
            self.select_pad(self.hub.pads()[0])
            return
        if which == "drivers":
            self.nav_drivers.setChecked(True)
        elif which == "settings":
            self.nav_settings.setChecked(True)
        else:
            checked = self.group.checkedButton()
            if checked is not None:
                self.group.setExclusive(False)
                checked.setChecked(False)
                self.group.setExclusive(True)
        self.stack.setCurrentWidget(page)
        if which == "drivers":
            self.drivers.on_shown()
        self._refresh_header()

    def _on_tab(self, idx: int) -> None:
        self.pad_pages.setCurrentIndex(idx)

    def _refresh_header(self) -> None:
        page = self.stack.currentWidget()
        on_pad = page is self.pad_pages and self.current is not None
        for wdg in (self.link_pill, self.batt_pill, self.tab_row_w):
            wdg.setVisible(on_pad)
        self.remap_pill.setVisible(on_pad and self.hub.remap_enabled(self.current))
        if on_pad:
            info = self.current.info
            self.title.setText(info.model.label)
            self.link_pill.set("USB" if info.connection is Connection.USB else "Bluetooth", theme.TEXT_DIM)
        else:
            self.title.setText({self.empty: "Welcome", self.drivers: "Drivers & Firmware",
                                self.settings_page: "Settings"}.get(page, ""))

    # ------------------------------------------------------------------ tick
    def _tick(self) -> None:
        if self.stack.currentWidget() is self.pad_pages and self.current is not None:
            self.pad_pages.tick()
            b = self.current.state.battery
            self.batt_pill.set(battery_text(b), battery_color(b))
        now = time.monotonic()
        if now - self._side_t > 0.5:
            self._side_t = now
            self._update_tiles()

    def _update_tiles(self) -> None:
        for key, tile in self.tiles.items():
            pad = self.hub.manager.pads.get(key)
            if pad is None:
                continue
            b = pad.state.battery
            sub = ("USB" if pad.info.connection is Connection.USB else "Bluetooth") + f" · {battery_text(b)}"
            if self.hub.remap_enabled(pad):
                sub += " · remap"
            lb = pad.lightbar
            tile.update_info(sub, b, QColor(*lb) if lb else None)
            self._battery_alert(pad)
        self.nav_drivers.set_badge(self.drivers.badge())

    def _background_tick(self) -> None:
        if not self.timer.isActive():
            self._update_tiles()
        lines = []
        for pad in self.hub.pads():
            est = self.hub.battery_estimate(pad)
            extra = f" ({est.text()})" if est is not None and est.text() else ""
            lines.append(f"{pad.info.title}: {battery_text(pad.state.battery)}{extra}")
        self.tray.setToolTip("DualShock PC Hub" + ("\n" + "\n".join(lines) if lines else ""))

    def _battery_alert(self, pad: Pad) -> None:
        b = pad.state.battery
        if b.level is None or b.charging or b.wired:
            self._low_alerted.discard(pad.key)
            return
        if b.level <= 15 and pad.key not in self._low_alerted and self.hub.settings.get("battery_alerts", True):
            self._low_alerted.add(pad.key)
            self.tray.showMessage("Controller battery low", f"{pad.info.title} is at {b.level}%.", app_icon(), 6000)


def _trim_working_set() -> None:
    """Hand idle memory back to Windows while we sit in the tray."""
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetProcessWorkingSetSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
        k32.SetProcessWorkingSetSize(k32.GetCurrentProcess(), ctypes.c_size_t(-1).value, ctypes.c_size_t(-1).value)
    except (OSError, ctypes.ArgumentError):
        pass
