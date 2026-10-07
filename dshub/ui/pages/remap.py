"""Remap page: pick a button (click it or press it), choose what it does."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from dshub.core.pads.base import Pad
from dshub.core.state import MODEL_BUTTONS, Button, Model
from dshub.mapping import sendinput
from dshub.mapping.profile import (DEFAULT_BUTTONS, MOUSE_TARGETS, PAD_TARGET_LABELS, Binding, Profile,
                                   StickConfig)
from dshub.ui import theme
from dshub.ui.flat_view import FlatView
from dshub.ui.hub import Hub
from dshub.ui.widgets import Card, Segmented, Toggle, hbox, label

KINDS = ["pad", "key", "mouse", "none"]
KIND_LABELS = ["Controller", "Keyboard", "Mouse", "Off"]
STICK_MODES = [("left", "Left stick"), ("right", "Right stick"), ("mouse", "Mouse"), ("wasd", "WASD keys"),
               ("arrows", "Arrow keys"), ("none", "Disabled")]
QT_TO_NAME = {Qt.Key.Key_Space: "Space", Qt.Key.Key_Return: "Enter", Qt.Key.Key_Enter: "Enter",
              Qt.Key.Key_Escape: "Esc", Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Backspace: "Backspace",
              Qt.Key.Key_Shift: "Shift", Qt.Key.Key_Control: "Ctrl", Qt.Key.Key_Alt: "Alt",
              Qt.Key.Key_Up: "Up", Qt.Key.Key_Down: "Down", Qt.Key.Key_Left: "Left", Qt.Key.Key_Right: "Right",
              Qt.Key.Key_Insert: "Insert", Qt.Key.Key_Delete: "Delete", Qt.Key.Key_Home: "Home",
              Qt.Key.Key_End: "End", Qt.Key.Key_PageUp: "Page Up", Qt.Key.Key_PageDown: "Page Down",
              Qt.Key.Key_CapsLock: "Caps Lock"}


class KeyCaptureDialog(QDialog):
    """"Press a key" modal; returns the friendly key name."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Press a key")
        self.setModal(True)
        self.key_name: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        msg = label("Press the key you want this button to send…", "h2")
        lay.addWidget(msg)
        lay.addWidget(label("Esc cancels.", "dim"))
        self.resize(360, 120)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.reject()
            return
        name = QT_TO_NAME.get(Qt.Key(k))
        if name is None:
            if Qt.Key.Key_F1 <= k <= Qt.Key.Key_F12:
                name = f"F{k - Qt.Key.Key_F1 + 1}"
            else:
                text = e.text().upper()
                name = text if text in sendinput.KEYS else None
        if name:
            self.key_name = name
            self.accept()


class RemapPage(QWidget):
    def __init__(self, hub: Hub, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hub = hub
        self.pad: Pad | None = None
        self.profile: Profile = Profile()
        self.selected: Button | None = None
        self._prev_buttons: frozenset = frozenset()
        self._last_state = None
        self._loading = False

        self.view = FlatView(Model.DS4)
        self.view.buttonClicked.connect(self.select)
        hint = label("Click a button on the controller, or just press it, to rebind it.", "dim")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left = QVBoxLayout()
        left.addWidget(self.view, 1)
        left.addWidget(hint)

        panel = QVBoxLayout()
        panel.setSpacing(12)
        panel.setContentsMargins(0, 0, 12, 0)  # room for the scrollbar

        # --- remap on/off + profile
        top = Card()
        top.lay.addWidget(label("VIRTUAL CONTROLLER", "section"))
        self.toggle = Toggle()
        self.toggle.toggled.connect(self._on_toggle)
        self.toggle_text = label("Off", "h2")
        top.lay.addLayout(hbox(self.toggle_text, None, self.toggle))
        self.toggle_note = label("", "dim")
        self.toggle_note.setWordWrap(True)
        top.lay.addWidget(self.toggle_note)
        self.hide_toggle = Toggle()
        self.hide_toggle.toggled.connect(self._on_hide)
        self.hide_toggle.setToolTip("Uses the HidHide driver. While on, only DualShock PC Hub can see this "
                                    "controller; games get the virtual Xbox controller instead.")
        top.lay.addLayout(hbox(label("Hide from Steam & games", "h2"), None, self.hide_toggle))
        self.hide_note = label("", "faint")
        self.hide_note.setWordWrap(True)
        top.lay.addWidget(self.hide_note)
        self.exclusive_btn = QPushButton("Switch DS3 to exclusive mode…")
        self.exclusive_btn.clicked.connect(self._ds3_exclusive)
        top.lay.addWidget(self.exclusive_btn, 0, Qt.AlignmentFlag.AlignLeft)
        top.lay.addSpacing(4)
        top.lay.addWidget(label("PROFILE", "section"))
        self.profile_box = QComboBox()
        self.profile_box.currentTextChanged.connect(self._on_profile_chosen)
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self._new_profile)
        del_btn = QPushButton("Delete")
        del_btn.setProperty("kind", "ghost")
        del_btn.clicked.connect(self._delete_profile)
        top.lay.addLayout(hbox(self.profile_box, new_btn, del_btn))
        panel.addWidget(top)

        # --- selected button
        sel = Card()
        self.sel_title = label("No button selected", "h2")
        sel.lay.addWidget(self.sel_title)
        self.kind = Segmented(KIND_LABELS)
        self.kind.changed.connect(self._on_kind)
        sel.lay.addWidget(self.kind)
        self.target = QComboBox()
        self.target.currentIndexChanged.connect(self._on_target)
        self.capture = QPushButton("Press a key…")
        self.capture.clicked.connect(self._capture_key)
        sel.lay.addLayout(hbox(self.target, self.capture))
        self.reset_btn = QPushButton("Reset this button")
        self.reset_btn.setProperty("kind", "ghost")
        self.reset_btn.clicked.connect(self._reset_button)
        sel.lay.addWidget(self.reset_btn, 0, Qt.AlignmentFlag.AlignLeft)
        panel.addWidget(sel)
        self.sel_card = sel

        # --- sticks
        sticks = Card()
        sticks.lay.addWidget(label("STICKS", "section"))
        self.stick_mode: dict[str, QComboBox] = {}
        self.stick_dz: dict[str, QSlider] = {}
        self.stick_sens: dict[str, QSlider] = {}
        for side in ("left", "right"):
            mode = QComboBox()
            for key, text in STICK_MODES:
                mode.addItem(text, key)
            mode.currentIndexChanged.connect(self._on_sticks)
            dz = self._slider(0, 40)
            sens = self._slider(25, 300)
            self.stick_mode[side], self.stick_dz[side], self.stick_sens[side] = mode, dz, sens
            sticks.lay.addLayout(hbox(label(f"{side.title()} →", "dim"), mode))
            sticks.lay.addLayout(hbox(label("Deadzone", "faint"), dz, spacing=10))
            sticks.lay.addLayout(hbox(label("Sensitivity", "faint"), sens, spacing=10))
        panel.addWidget(sticks)

        # --- triggers + rumble
        trig = Card()
        trig.lay.addWidget(label("TRIGGERS & RUMBLE", "section"))
        self.l2_dz = self._slider(0, 40)
        self.r2_dz = self._slider(0, 40)
        self.rumble = self._slider(0, 100)
        trig.lay.addLayout(hbox(label("L2 deadzone", "faint"), self.l2_dz, spacing=10))
        trig.lay.addLayout(hbox(label("R2 deadzone", "faint"), self.r2_dz, spacing=10))
        trig.lay.addLayout(hbox(label("Game rumble", "faint"), self.rumble, spacing=10))
        reset_all = QPushButton("Reset whole profile to defaults")
        reset_all.setProperty("kind", "ghost")
        reset_all.clicked.connect(self._reset_profile)
        trig.lay.addWidget(reset_all, 0, Qt.AlignmentFlag.AlignLeft)
        panel.addWidget(trig)
        panel.addStretch(1)

        panel_w = QWidget()
        panel_w.setLayout(panel)
        scroll = QScrollArea()
        scroll.setWidget(panel_w)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(372)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 12, 12)
        lay.setSpacing(12)
        lay.addLayout(left, 1)
        lay.addWidget(scroll)

        hub.remapChanged.connect(lambda p: p is self.pad and self._sync_toggle())

    def _slider(self, lo: int, hi: int) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.valueChanged.connect(self._on_sliders)
        return s

    # ------------------------------------------------------------------ binding
    def set_pad(self, pad: Pad | None) -> None:
        self.pad = pad
        self._last_state = None
        if pad is None:
            return
        self.view.set_model(pad.info.model)
        self._loading = True
        self.profile_box.clear()
        self.profile_box.addItems(self.hub.profiles.names())
        self.profile_box.setCurrentText(self.hub.profile_name(pad))
        self._loading = False
        self._load_profile(self.hub.profile_name(pad))
        self._sync_toggle()
        self.select(None)

    def _sync_toggle(self) -> None:
        if self.pad is None:
            return
        hidden = self.hub.hidden(self.pad)
        self.hide_toggle.blockSignals(True)
        self.hide_toggle.setChecked(hidden)
        self.hide_toggle.blockSignals(False)
        try:
            reason = None if hidden else self.hub.can_hide(self.pad)
        except Exception as exc:  # noqa: BLE001 - a system-module problem must not break the page
            reason = str(exc)
        self.hide_toggle.setEnabled(hidden or reason is None)
        self.exclusive_btn.setVisible(self.pad.info.backend == "dshidmini-xinput")
        self.hide_note.setText(reason or ("Only this app sees the real controller." if hidden else
                                          "Steam and games won't see the real controller, only the virtual one."))
        on = self.hub.remap_enabled(self.pad)
        self.toggle.blockSignals(True)
        self.toggle.setChecked(on)
        self.toggle.blockSignals(False)
        session = self.hub.sessions.get(self.pad.key)
        self.toggle_text.setText("On" if on else "Off")
        if on and session is not None:
            self.toggle_note.setText(f"Games see this pad as an Xbox 360 controller (virtual #{session.virtual_serial}),"
                                     " using the bindings below. Keyboard and mouse bindings work everywhere.")
        else:
            note = "Games see the controller as it is. Turn this on to use your bindings."
            if self.pad.info.model is Model.DS3 and self.pad.info.backend == "dshidmini-xinput":
                note += (" This DS3 is already an Xbox pad (DsHidMini XInput mode), so games would see two "
                         "controllers. Use “Switch DS3 to exclusive mode” below first.")
            self.toggle_note.setText(note)

    def _load_profile(self, name: str) -> None:
        self.profile = self.hub.profiles.load(name)
        self._loading = True
        for side, cfg in (("left", self.profile.left_stick), ("right", self.profile.right_stick)):
            box = self.stick_mode[side]
            box.setCurrentIndex(max(0, box.findData(cfg.mode)))
            self.stick_dz[side].setValue(round(cfg.deadzone * 100))
            self.stick_sens[side].setValue(round(cfg.sensitivity * 100))
        self.l2_dz.setValue(round(self.profile.l2.deadzone * 100))
        self.r2_dz.setValue(round(self.profile.r2.deadzone * 100))
        self.rumble.setValue(round(self.profile.rumble * 100))
        self._loading = False
        self.select(self.selected)

    def _save(self) -> None:
        self.hub.save_profile(self.profile)

    # ------------------------------------------------------------------ selection
    def select(self, button: Button | None) -> None:
        if button is not None and self.pad is not None and button not in MODEL_BUTTONS[self.pad.info.model]:
            return
        self.selected = button
        self.view.set_selected(button)
        enabled = button is not None
        for wdg in (self.kind, self.target, self.capture, self.reset_btn):
            wdg.setEnabled(enabled)
        if button is None:
            self.sel_title.setText("No button selected")
            self.target.clear()
            return
        model = self.pad.info.model if self.pad else Model.DS4
        bind = self.profile.binding(button)
        self.sel_title.setText(f"{button.label_for(model)}  →  {bind.label()}")
        self._loading = True
        self.kind.set_index(KINDS.index(bind.kind) if bind.kind in KINDS else 3)
        self._fill_targets(bind.kind, bind.target)
        self._loading = False

    def _fill_targets(self, kind: str, current: str) -> None:
        self.target.blockSignals(True)
        self.target.clear()
        if kind == "pad":
            for key, text in PAD_TARGET_LABELS.items():
                self.target.addItem(text, key)
        elif kind == "key":
            for name in sendinput.KEYS:
                self.target.addItem(name, name)
        elif kind == "mouse":
            for key, text in MOUSE_TARGETS.items():
                self.target.addItem(text, key)
        idx = self.target.findData(current)
        self.target.setCurrentIndex(max(0, idx))
        self.target.blockSignals(False)
        self.target.setVisible(kind != "none")
        self.capture.setVisible(kind == "key")

    def _on_kind(self, idx: int) -> None:
        if self._loading or self.selected is None:
            return
        kind = KINDS[idx]
        self._fill_targets(kind, "")
        target = self.target.currentData() or ""
        self._set_binding(Binding(kind, target))

    def _on_target(self, _idx: int) -> None:
        if self._loading or self.selected is None:
            return
        self._set_binding(Binding(KINDS[self.kind.index], self.target.currentData() or ""))

    def _set_binding(self, bind: Binding) -> None:
        self.profile.buttons[self.selected.value] = bind
        self._save()
        model = self.pad.info.model if self.pad else Model.DS4
        self.sel_title.setText(f"{self.selected.label_for(model)}  →  {bind.label()}")

    def _capture_key(self) -> None:
        dlg = KeyCaptureDialog(self.window())
        if dlg.exec() and dlg.key_name and self.selected is not None:
            self._fill_targets("key", dlg.key_name)
            self._set_binding(Binding("key", dlg.key_name))

    def _reset_button(self) -> None:
        if self.selected is None:
            return
        default = DEFAULT_BUTTONS.get(self.selected)
        self.profile.buttons[self.selected.value] = Binding("pad", default) if default else Binding("none", "")
        self._save()
        self.select(self.selected)

    def _reset_profile(self) -> None:
        if QMessageBox.question(self, "Reset profile",
                                f"Reset every binding in “{self.profile.name}” to the defaults?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.profile = Profile(name=self.profile.name)
        self._save()
        self._load_profile(self.profile.name)

    # ------------------------------------------------------------------ sliders
    def _on_sticks(self, _i: int = 0) -> None:
        self._on_sliders()

    def _on_sliders(self, _v: int = 0) -> None:
        if self._loading:
            return
        for side, attr in (("left", "left_stick"), ("right", "right_stick")):
            setattr(self.profile, attr, StickConfig(
                mode=self.stick_mode[side].currentData(),
                deadzone=self.stick_dz[side].value() / 100,
                sensitivity=self.stick_sens[side].value() / 100,
                invert_y=getattr(self.profile, attr).invert_y,
                anti_deadzone=getattr(self.profile, attr).anti_deadzone,
            ))
        self.profile.l2.deadzone = self.l2_dz.value() / 100
        self.profile.r2.deadzone = self.r2_dz.value() / 100
        self.profile.rumble = self.rumble.value() / 100
        self._save()

    # ------------------------------------------------------------------ profiles
    def _on_profile_chosen(self, name: str) -> None:
        if self._loading or not name or self.pad is None:
            return
        self.hub.set_profile(self.pad, name)
        self._load_profile(name)

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        name = name.strip()
        if not ok or not name or self.pad is None:
            return
        prof = Profile.from_json({**self.profile.to_json(), "name": name})
        self.hub.save_profile(prof)
        self._loading = True
        self.profile_box.clear()
        self.profile_box.addItems(self.hub.profiles.names())
        self.profile_box.setCurrentText(name)
        self._loading = False
        self.hub.set_profile(self.pad, name)
        self._load_profile(name)

    def _delete_profile(self) -> None:
        name = self.profile_box.currentText()
        if name == "Default" or self.pad is None:
            self.hub.toast.emit("The Default profile can be reset but not deleted.", "info")
            return
        if QMessageBox.question(self, "Delete profile", f"Delete “{name}”?") != QMessageBox.StandardButton.Yes:
            return
        self.hub.profiles.delete(name)
        self.hub.set_profile(self.pad, "Default")
        self.set_pad(self.pad)

    def _on_toggle(self, on: bool) -> None:
        if self.pad is None:
            return
        if not on and self.hub.hidden(self.pad):
            # A hidden controller without a virtual pad would vanish from games entirely.
            self.hub.set_hidden(self.pad, False)
        if not self.hub.set_remap(self.pad, on):
            self._sync_toggle()

    def _on_hide(self, on: bool) -> None:
        if self.pad is not None:
            self.hub.set_hidden(self.pad, on)
            self._sync_toggle()

    def _ds3_exclusive(self) -> None:
        from dshub.core import winapi
        from dshub.ui import tasks

        node = getattr(self.pad, "devnode", None) if self.pad else None
        mac_raw = winapi.devnode_property(node, winapi.DEVPKEY_BLUETOOTH_ADDRESS) if node else None
        mac = mac_raw.decode("utf-16-le", "ignore").rstrip("\0") if mac_raw else None
        if not node or not mac:
            self.hub.toast.emit("Couldn't identify this DS3. Reconnect it by USB and try again.", "error")
            return
        text = ("Switch this DS3 to DsHidMini's “DS4Windows” mode?\n\n"
                "Steam and games will ignore the real controller and only DualShock PC Hub reads it; "
                "games get the virtual Xbox controller instead.\n\n"
                "Windows will ask for administrator permission and the DS3 restarts. You can switch back on "
                "the Drivers & Firmware page (DS3 mode → XInput).")
        if QMessageBox.question(self, "DS3 exclusive mode", text) != QMessageBox.StandardButton.Yes:
            return

        def work(_report):
            from dshub.system import ds3_pairing

            return ds3_pairing.set_hid_mode(mac, "DS4Windows", node)

        uid = self.pad.info.uid

        def done(active_now):
            self.hub.settings.pad(uid)["remap"] = True  # the DS3 keeps its uid (MAC) in the new mode
            self.hub.settings.save()
            if active_now:
                self.hub.toast.emit("DS3 switched to exclusive mode. It reconnects in a moment with the "
                                    "virtual Xbox controller on.", "ok")
            else:
                self.hub.toast.emit("Saved. Unplug and replug the DS3 (or turn it off and on) to switch to "
                                    "exclusive mode.", "info")
            self.hub.manager.request_scan()

        def failed(exc):
            from dshub.system import elevate

            if isinstance(exc, elevate.ElevationCancelled):
                self.hub.toast.emit("Administrator permission was declined; nothing changed.", "info")
            else:
                self.hub.toast.emit(f"Couldn't switch the DS3 mode: {exc}", "error")

        tasks.run(work, done, failed)

    # ------------------------------------------------------------------ tick
    def tick(self) -> None:
        pad = self.pad
        if pad is None:
            return
        st = pad.state
        if st is self._last_state:
            return
        self._last_state = st
        self.view.set_state(st)
        pressed = st.buttons - self._prev_buttons
        self._prev_buttons = st.buttons
        if pressed and self.window().isActiveWindow():
            # Physically pressing a button selects it for rebinding.
            choice = next((b for b in pressed if b in MODEL_BUTTONS[pad.info.model]), None)
            if choice is not None and choice is not self.selected:
                self.select(choice)
