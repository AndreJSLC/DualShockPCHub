"""Drivers & Firmware: component status, one-click install/update, DS3
Bluetooth checklist, conflicts and firmware pointers.

Nothing here runs in the background: the page scans when it is opened and
talks to the network only when the user asks (or right after opening, to
fill in "latest version").  Installers run only from a button click, after
a confirmation, with Windows' own UAC prompt.
"""

from __future__ import annotations

import logging
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from dshub.core.state import Model
from dshub.ui import tasks, theme
from dshub.ui.hub import Hub
from dshub.ui.widgets import Card, Pill, hbox, label

log = logging.getLogger(__name__)

STATUS_STYLE = {
    "ok": ("Up to date", theme.OK),
    "outdated": ("Update available", theme.WARN),
    "missing": ("Not installed", theme.TEXT_FAINT),
    "broken": ("Needs repair", theme.BAD),
    "unknown": ("Unknown", theme.TEXT_FAINT),
}
SEVERITY_COLOR = {"error": theme.BAD, "warning": theme.WARN, "info": theme.ACCENT}


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear(item.layout())


def _vt(v: str | None) -> tuple[int, ...]:
    from dshub.system.drivers import version_tuple

    return version_tuple(v)


class ComponentCard(Card):
    def __init__(self, page: DriversPage, comp) -> None:
        super().__init__()
        self.page, self.comp = page, comp
        text, col = STATUS_STYLE.get(comp.status, STATUS_STYLE["unknown"])
        title = label(comp.name, "h2")
        self.pill = Pill(text, col)
        head = hbox(title, self.pill, None)
        self.action = QPushButton()
        self.action.setProperty("kind", "primary")
        self.action.clicked.connect(self._act)
        notes_btn = QPushButton("Release notes")
        notes_btn.setProperty("kind", "ghost")
        notes_btn.clicked.connect(lambda: webbrowser.open(comp.release_url or comp.homepage))
        head.addWidget(notes_btn)
        head.addWidget(self.action)
        self.lay.addLayout(head)
        purpose = label(comp.purpose, "dim")
        purpose.setWordWrap(True)
        self.lay.addWidget(purpose)
        ver = f"Installed {comp.installed_version}" if comp.installed_version else "Not installed"
        if comp.latest_version:
            ver += f"   ·   Latest {comp.latest_version}"
            if comp.published:
                ver += f" ({comp.published[:10]})"
        self.lay.addWidget(label(ver, "faint"))
        for line in list(comp.problems) + list(comp.notes):
            lab = label(f"• {line}", "faint")
            lab.setWordWrap(True)
            self.lay.addWidget(lab)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background: rgba(255,255,255,0.08); border: none; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: {theme.ACCENT.name()}; border-radius: 2px; }}")
        self.progress.hide()
        self.lay.addWidget(self.progress)
        self._set_action()

    def _set_action(self) -> None:
        c = self.comp
        label_ = None
        if c.id == "bthps3" and c.installed and _vt(c.installed_version) < (3,):
            label_ = "Remove old version"
        elif c.status == "missing" and not c.optional:
            label_ = "Install"
        elif c.status == "missing" and c.optional:
            label_ = "Install (optional)"
        elif c.status == "outdated":
            label_ = f"Update to {c.latest_version}" if c.latest_version else "Update"
        elif c.status == "broken":
            label_ = "Repair"
        self.action.setVisible(label_ is not None)
        if label_:
            self.action.setText(label_)
            self.action.setEnabled(bool(c.download_url) or label_ == "Remove old version")
            if not c.download_url and label_ != "Remove old version":
                self.action.setToolTip("Waiting for the latest-version check…")

    def _act(self) -> None:
        if self.action.text() == "Remove old version":
            self.page.uninstall(self)
        else:
            self.page.install(self)


class DriversPage(QWidget):
    def __init__(self, hub: Hub, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hub = hub
        self.components: list = []
        self.cards: dict[str, ComponentCard] = {}
        self._busy = False
        self._loaded_online = False

        body = QVBoxLayout()
        body.setSpacing(14)
        body.setContentsMargins(4, 0, 12, 20)

        self.refresh_btn = QPushButton("Check for updates")
        self.refresh_btn.clicked.connect(lambda: self.refresh(online=True))
        self.status = label("", "dim")
        self.reboot_pill = Pill("Restart required", theme.WARN)
        self.reboot_pill.hide()
        body.addLayout(hbox(self.refresh_btn, self.status, None, self.reboot_pill))

        body.addWidget(label("DUALSHOCK 3 OVER BLUETOOTH", "section"))
        self.checklist = Card()
        body.addWidget(self.checklist)

        body.addWidget(label("DRIVERS", "section"))
        self.comp_box = QVBoxLayout()
        self.comp_box.setSpacing(10)
        body.addLayout(self.comp_box)

        self.conf_title = label("THINGS TO CHECK", "section")
        body.addWidget(self.conf_title)
        self.conf_box = QVBoxLayout()
        self.conf_box.setSpacing(8)
        body.addLayout(self.conf_box)

        body.addWidget(label("DS3 MODE", "section"))
        self.mode_card = Card()
        body.addWidget(self.mode_card)

        body.addWidget(label("FIRMWARE", "section"))
        self.fw_box = QVBoxLayout()
        self.fw_box.setSpacing(10)
        body.addLayout(self.fw_box)
        body.addStretch(1)

        inner = QWidget()
        inner.setLayout(body)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 0, 8, 0)
        lay.addWidget(scroll)

        self._render_firmware()

    # ------------------------------------------------------------------ loading
    def on_shown(self) -> None:
        if not self.components and not self._busy:
            self.refresh(online=not self._loaded_online)

    def refresh(self, online: bool = False) -> None:
        if self._busy:
            return
        self._busy = True
        self.refresh_btn.setEnabled(False)
        self.status.setText("Checking this PC…")

        def work(_report):
            from dshub.system import conflicts, drivers, ds3_pairing

            comps = drivers.scan()
            result = {"components": comps, "conflicts": conflicts.scan(comps),
                      "checks": ds3_pairing.bluetooth_readiness(), "ds3": ds3_pairing.devices(),
                      "reboot": drivers.reboot_pending()}
            return result

        def done(res):
            self._apply(res)
            if online:
                self._check_online()
            else:
                self._finish("")

        tasks.run(work, done, self._failed)

    def _check_online(self) -> None:
        self.status.setText("Looking up the latest official releases…")

        def work(_report):
            from dshub.system import drivers

            return drivers.check_latest(self.components)

        def done(comps):
            self._loaded_online = True
            self.components = comps
            self._render_components()
            outdated = [c for c in comps if c.status in ("outdated", "missing", "broken") and not c.optional]
            self._finish("Everything is up to date." if not outdated else
                         f"{len(outdated)} item{'s' if len(outdated) != 1 else ''} need attention.")

        tasks.run(work, done, self._failed)

    def _failed(self, exc: Exception) -> None:
        log.error("drivers page task failed: %s", exc)
        self._finish(f"Couldn't finish the check: {exc}")

    def _finish(self, text: str) -> None:
        self._busy = False
        self.refresh_btn.setEnabled(True)
        self.status.setText(text)

    # ------------------------------------------------------------------ render
    def _apply(self, res: dict) -> None:
        self.components = res["components"]
        self.reboot_pill.setVisible(bool(res["reboot"]))
        self._render_components()
        self._render_conflicts(res["conflicts"])
        self._render_checks(res["checks"])
        self._render_modes(res["ds3"])

    def _render_components(self) -> None:
        _clear(self.comp_box)
        self.cards.clear()
        for comp in self.components:
            card = ComponentCard(self, comp)
            self.cards[comp.id] = card
            self.comp_box.addWidget(card)

    def _render_checks(self, checks) -> None:
        _clear(self.checklist.lay)
        for chk in checks:
            mark = {True: ("✓", theme.OK), False: ("✕", theme.BAD), None: ("•", theme.TEXT_FAINT)}[chk.ok]
            icon = QLabel(mark[0])
            icon.setFixedWidth(18)
            icon.setStyleSheet(f"color: {mark[1].name()}; font-size: 15px; font-weight: 700;")
            title = label(chk.title, "h2")
            title.setStyleSheet("font-size: 13px;")
            detail = label(chk.detail, "dim")
            detail.setWordWrap(True)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(title)
            col.addWidget(detail)
            if chk.ok is False and chk.fix:
                fix = label(chk.fix, "faint")
                fix.setWordWrap(True)
                col.addWidget(fix)
            row = QHBoxLayout()
            row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            row.addLayout(col, 1)
            if chk.ok is False and chk.action and chk.action.startswith("component:"):
                cid = chk.action.split(":", 1)[1]
                btn = QPushButton("Fix")
                btn.clicked.connect(lambda _=False, cid=cid: self._fix_component(cid))
                row.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
            self.checklist.lay.addLayout(row)

    def _render_conflicts(self, conflicts) -> None:
        _clear(self.conf_box)
        self.conf_title.setVisible(bool(conflicts))
        for c in conflicts:
            card = Card(padding=12)
            dot = Pill(c.severity.title(), SEVERITY_COLOR.get(c.severity, theme.ACCENT))
            card.lay.addLayout(hbox(label(c.title, "h2"), None, dot))
            for text, role in ((c.detail, "dim"), (c.fix, "faint")):
                if text:
                    lab = label(text, role)
                    lab.setWordWrap(True)
                    card.lay.addWidget(lab)
            if c.action and c.action.startswith("url:"):
                url = c.action[4:]
                btn = QPushButton("Open")
                btn.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
                card.lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
            elif c.action and c.action.startswith("component:"):
                cid = c.action.split(":", 1)[1]
                btn = QPushButton("Go to driver")
                btn.clicked.connect(lambda _=False, cid=cid: self._fix_component(cid))
                card.lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
            self.conf_box.addWidget(card)

    def _render_modes(self, ds3_devices) -> None:
        from dshub.system import ds3_pairing

        _clear(self.mode_card.lay)
        if not ds3_devices:
            self.mode_card.lay.addWidget(label("No DS3 connected. Plug one in with a USB cable.", "dim"))
            return
        for dev in ds3_devices:
            name = f"DS3 {dev.mac or ''} · {dev.connection.upper()}"
            current = dev.hid_mode or "Unknown"
            self.mode_card.lay.addWidget(label(name, "h2"))
            box = QComboBox()
            for mode in ds3_pairing.HID_MODES.values():
                box.addItem(mode, mode)
            box.setCurrentText(current)
            help_lab = label(ds3_pairing.HID_MODE_HELP.get(current, ""), "dim")
            help_lab.setWordWrap(True)
            box.currentTextChanged.connect(lambda m, h=help_lab: h.setText(ds3_pairing.HID_MODE_HELP.get(m, "")))
            apply = QPushButton("Apply")
            v3 = _vt(dev.driver_version) >= (3,)
            apply.setEnabled(v3 and bool(dev.mac))
            if not v3:
                apply.setToolTip("Changing the mode from here needs DsHidMini 3.x (install it above).")
            apply.clicked.connect(lambda _=False, d=dev, b=box: self._set_mode(d, b.currentText()))
            self.mode_card.lay.addLayout(hbox(label(f"Current: {current}", "dim"), None, box, apply))
            self.mode_card.lay.addWidget(help_lab)
            if not v3:
                self.mode_card.lay.addWidget(label("Mode switching here needs DsHidMini 3.x.", "faint"))

    def _render_firmware(self) -> None:
        from dshub.system import firmware

        _clear(self.fw_box)
        for model in (Model.DS5, Model.DS4, Model.DS3):
            tool = firmware.tool_for(model)
            card = Card(padding=14)
            card.lay.addLayout(hbox(label(model.label, "h2"), None, label(tool.name, "faint")))
            summary = label(tool.summary, "dim")
            summary.setWordWrap(True)
            card.lay.addWidget(summary)
            buttons = []
            if tool.download_url:
                dl = QPushButton("Get Sony's updater")
                dl.clicked.connect(lambda _=False, u=tool.download_url: webbrowser.open(u))
                buttons.append(dl)
            if tool.page_url:
                pg = QPushButton("Official page")
                pg.setProperty("kind", "ghost")
                pg.clicked.connect(lambda _=False, u=tool.page_url: webbrowser.open(u))
                buttons.append(pg)
            if buttons:
                card.lay.addLayout(hbox(*buttons, None))
            self.fw_box.addWidget(card)

    # ------------------------------------------------------------------ actions
    def _fix_component(self, cid: str) -> None:
        card = self.cards.get(cid)
        if card is None:
            return
        if not card.comp.download_url and card.action.text() != "Remove old version":
            self.hub.toast.emit("Looking up the latest version first…", "info")
            self.refresh(online=True)
            return
        card._act()

    def install(self, card: ComponentCard) -> None:
        c = card.comp
        if self._busy or not c.download_url:
            return
        size = f" ({c.download_size / 1_048_576:.1f} MB)" if c.download_size else ""
        msg = (f"Install {c.name} {c.latest_version or ''}?\n\n"
               f"DualShock PC Hub will download the official installer{size} from "
               f"{c.release_url or c.homepage}, check that it is signed by {c.publisher}, and run it.\n\n"
               "Windows will ask for administrator permission. A restart may be needed afterwards.")
        if c.install_hint:
            msg += f"\n\n{c.install_hint}"
        if QMessageBox.question(self, f"Install {c.name}", msg) != QMessageBox.StandardButton.Yes:
            return
        self._busy = True
        self.refresh_btn.setEnabled(False)
        card.action.setEnabled(False)
        card.progress.setRange(0, 0)
        card.progress.show()
        self.status.setText(f"Downloading {c.name}…")

        def on_progress(done: int, total: int) -> None:
            if total:
                card.progress.setRange(0, total)
                card.progress.setValue(done)

        def work(report):
            from dshub.system import drivers

            path = drivers.download(c, progress=report)
            return drivers.install(c, path, wait=True)

        def done(code):
            card.progress.hide()
            self._busy = False
            self._after_installer(c.name, code)

        def failed(exc):
            card.progress.hide()
            self._busy = False
            self._report_error(c.name, exc)

        tasks.run(work, done, failed, on_progress)
        self.status.setText(f"Downloading {c.name}… then Windows will ask for permission.")

    def uninstall(self, card: ComponentCard) -> None:
        c = card.comp
        if self._busy:
            return
        if QMessageBox.question(
                self, f"Remove {c.name}",
                f"Remove {c.name} {c.installed_version}?\n\nThis runs its own uninstaller. Restart Windows "
                "afterwards, then come back here to install the latest version.") != QMessageBox.StandardButton.Yes:
            return
        self._busy = True

        def work(_report):
            from dshub.system import drivers

            return drivers.uninstall(c, wait=True)

        tasks.run(work, lambda code: self._after_installer(c.name, code, removing=True),
                  lambda exc: self._report_error(c.name, exc))

    def _after_installer(self, name: str, code, removing: bool = False) -> None:
        self._busy = False
        verb = "removed" if removing else "installed"
        if code in (0, None):
            self.hub.toast.emit(f"{name} {verb}.", "ok")
        elif code in (3010, 1641):
            self.hub.toast.emit(f"{name} {verb}. Restart Windows to finish.", "warn")
            self.reboot_pill.show()
        elif code == 1602:
            self.hub.toast.emit(f"{name}: setup was cancelled.", "info")
        else:
            self.hub.toast.emit(f"{name} setup ended with code {code}.", "error")
        self.components = []
        self.refresh(online=True)

    def _report_error(self, name: str, exc: Exception) -> None:
        from dshub.system import elevate

        self._busy = False
        self.refresh_btn.setEnabled(True)
        if isinstance(exc, elevate.ElevationCancelled):
            self.hub.toast.emit("Administrator permission was declined, so nothing was changed.", "info")
        else:
            self.hub.toast.emit(f"{name}: {exc}", "error")
        self.status.setText("")
        self.refresh(online=False)

    def _set_mode(self, dev, mode: str) -> None:
        from dshub.system import ds3_pairing

        if QMessageBox.question(
                self, "Change DS3 mode",
                f"Switch this DS3 to {mode} mode?\n\nThe controller restarts briefly and Windows asks for "
                "administrator permission.") != QMessageBox.StandardButton.Yes:
            return

        def work(_report):
            ds3_pairing.set_hid_mode(dev.mac, mode, dev.instance_id)

        tasks.run(work, lambda _r: (self.hub.toast.emit(f"DS3 switched to {mode}.", "ok"), self.refresh()),
                  lambda exc: self._report_error("DS3 mode", exc))

    def badge(self) -> QColor | None:
        """Colour for the sidebar dot (None when everything is fine)."""
        if any(c.status == "broken" for c in self.components):
            return theme.BAD
        if any(c.status in ("outdated", "missing") and not c.optional for c in self.components):
            return theme.WARN
        return None
