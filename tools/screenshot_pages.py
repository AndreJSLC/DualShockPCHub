"""Still screenshots of the Drivers and Settings pages for the README - rendered offscreen.

Stand-in pads for the sidebar (no real device is opened), an isolated settings folder,
the same backdrop as the demo video, and every address / ID / user path scrubbed from
the widgets' text before the grab.  Usage: python tools/screenshot_pages.py docs/images [HEIGHT]
"""

import glob
import os
import re
import socket
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
REAL_USER = os.environ.get("USERNAME", "")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dshub-shot-")  # never touch the user's real settings
OUT = sys.argv[1]
WIN_W, WIN_H = 1180, int(sys.argv[2]) if len(sys.argv) > 2 else 740
M = 32
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPainterPath, \
    QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLabel, QWidget  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
for f in glob.glob(r"C:\Windows\Fonts\segoeui*.ttf") + glob.glob(r"C:\Windows\Fonts\SegUIVar.ttf"):
    QFontDatabase.addApplicationFont(f)
for f in ("seguisym.ttf", "SegoeIcons.ttf", "segmdl2.ttf"):  # symbol fallback (the checklist's check marks)
    QFontDatabase.addApplicationFont(rf"C:\Windows\Fonts\{f}")
QFont.insertSubstitutions("Segoe UI", ["Segoe UI Symbol"])  # Windows falls back on its own; offscreen doesn't
app.setFont(QFont("Segoe UI", 9))

from dshub.core.pads.base import Pad  # noqa: E402
from dshub.core.pads.ds3 import DualShock3XInput  # noqa: E402
from dshub.core.pads.ds4 import DualShock4  # noqa: E402
from dshub.core.pads.ds5 import DualSense  # noqa: E402
from dshub.core.state import Battery, Connection, ControllerInfo, ControllerState, Model  # noqa: E402
from dshub.ui import theme  # noqa: E402
from dshub.ui.hub import Hub  # noqa: E402
from dshub.ui.window import MainWindow  # noqa: E402

theme.apply(app)


class StandInPad(Pad):
    """Same capabilities as the real class; nothing is opened or read."""

    def __init__(self, info: ControllerInfo, caps) -> None:
        super().__init__(info, key=f"shot-{info.slot}")
        self.caps = caps

    def _open(self) -> None: ...

    def _close(self) -> None: ...

    def _poll(self):
        return None


hub = Hub()  # not started: no device scanning, no virtual controllers
win = MainWindow(hub)
win.resize(WIN_W, WIN_H)
win.show()
specs = [
    (Model.DS4, "build Sep 17 2021", "hid", DualShock4.caps, Battery(level=100, full=True, wired=True)),
    (Model.DS5, "06.30", "hid", DualSense.caps, Battery(level=95, charging=True, wired=True)),
    (Model.DS3, None, "dshidmini-xinput", DualShock3XInput.caps, Battery(level=100, full=True, wired=True)),
]
for slot, (model, fw, backend, caps, battery) in enumerate(specs, 1):
    info = ControllerInfo(uid=f"shot{slot}", model=model, connection=Connection.USB, name=model.label,
                          firmware=fw, backend=backend, slot=slot)
    pad = StandInPad(info, caps)
    pad.state = ControllerState(battery=battery)
    hub.manager.pads[pad.key] = pad
    hub._on_added(pad)  # noqa: SLF001 - same path a real hotplug takes
win._tick()  # noqa: SLF001


def pump(seconds: float, until=None) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if until is not None and until():
            return
        time.sleep(0.02)


# --------------------------------------------------------------------------- privacy scrub
def _short_name(path: str) -> str:
    """The 8.3 form of a folder name (C:\\Users\\JOHNSM~1), which also turns up in paths."""
    import ctypes

    buf = ctypes.create_unicode_buffer(260)
    return os.path.basename(buf.value) if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 260) else ""


PROFILE = os.environ.get("USERPROFILE", "")
SECRETS = [s for s in {REAL_USER, socket.gethostname(), os.path.basename(PROFILE), _short_name(PROFILE)} if s]
PATTERNS = [
    (re.compile(r" ?\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"), ""),  # MAC addresses: left out
    (re.compile(r"\b[0-9A-Fa-f]{12}\b"), "XXXXXXXXXXXX"),  # bare 12-digit addresses
    (re.compile(r"\b(?:USB|HID|BTHENUM|BTHPS3BUS|BTHLEDEVICE|SWD|ROOT|NEFARIUS)\\[^\s<\"']+", re.I), "<device id>"),
    (re.compile(r"\{[0-9A-Fa-f-]{36}\}"), "{…}"),
]
found: list[str] = []


def scrub(text: str) -> str:
    out = text
    for pat, rep in PATTERNS:
        out = pat.sub(rep, out)
    for s in SECRETS:
        out = re.sub(r" ?\(" + re.escape(s) + r"\)", "", out, flags=re.I)  # "adapter (PC-NAME)"
        out = re.sub(re.escape(s), "user", out, flags=re.I)
    if out != text:
        found.append(f"{text!r} -> {out!r}")
    return out


def scrub_widgets(root: QWidget) -> None:
    for w in root.findChildren(QWidget):
        if isinstance(w, (QLabel, QAbstractButton)) and w.text():
            new = scrub(w.text())
            if new != w.text():
                w.setText(new)
        if w.toolTip():
            w.setToolTip(scrub(w.toolTip()))
        if isinstance(w, QComboBox):
            for i in range(w.count()):
                t = w.itemText(i)
                if scrub(t) != t:
                    w.setItemText(i, scrub(t))


def all_text(root: QWidget) -> list[str]:
    out = []
    for w in root.findChildren(QWidget):
        if isinstance(w, (QLabel, QAbstractButton)) and w.text():
            out.append(w.text())
        if isinstance(w, QComboBox):
            out += [w.itemText(i) for i in range(w.count())]
    return out


# --------------------------------------------------------------------------- composition (as the demo video)
W, H = WIN_W + 2 * M, WIN_H + 2 * M


def backdrop() -> QImage:
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    bp = QPainter(img)
    bp.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor(28, 34, 60))
    g.setColorAt(0.55, QColor(14, 14, 22))
    g.setColorAt(1, QColor(8, 8, 12))
    bp.fillRect(img.rect(), g)
    glow = QRadialGradient(QPointF(W * 0.18, H * 0.12), W * 0.55)
    glow.setColorAt(0, QColor(31, 134, 242, 60))
    glow.setColorAt(1, QColor(31, 134, 242, 0))
    bp.fillRect(img.rect(), glow)
    bp.setPen(Qt.PenStyle.NoPen)
    for i in range(14):  # soft shadow under the window
        bp.setBrush(QColor(0, 0, 0, 9))
        bp.drawRoundedRect(QRectF(M - i, M - i + 8, WIN_W + 2 * i, WIN_H + 2 * i), 10 + i, 10 + i)
    bp.end()
    return img


def shoot(name: str) -> None:
    pump(0.3)
    scrub_widgets(win)
    pump(0.2)
    img = backdrop()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(M, M, WIN_W, WIN_H), 8, 8)
    p.setClipPath(clip)
    p.drawImage(M, M, win.grab().toImage())
    p.end()
    path = os.path.join(OUT, f"{name}.png")
    img.save(path)
    print("saved", path)


os.makedirs(OUT, exist_ok=True)
win.show_page("drivers")
pump(90, until=lambda: win.drivers.components and not win.drivers._busy and win.drivers.refresh_btn.isEnabled())
print("drivers status:", win.drivers.status.text())
shoot("drivers")
win.show_page("settings")
shoot("settings")

print("scrubbed:", *found, sep="\n  ") if found else print("scrubbed: nothing needed")
leftover = [t for t in all_text(win) if any(s.lower() in t.lower() for s in SECRETS)
            or any(p.search(t) for p, _ in PATTERNS[:3])]
print("leftover sensitive text:", leftover or "none")
hub.manager.pads.clear()
