"""Record a short demo video of the app window - rendered offscreen, never from the screen.

Scripted input on stand-in pads (no real devices are opened), an isolated settings
folder, a virtual clock so animations run at video speed, and Qt Multimedia to
encode the MP4 (no ffmpeg install needed). The stick, button and touchpad input is
scripted. Usage (from the project root, with the .venv):

    python tools/record_demo.py demo.mp4 [frames-dir]

``frames-dir`` optionally receives a few PNG stills for checking the result.
"""

import glob
import math
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dshub-demo-")  # never touch the user's real settings
OUT = os.path.abspath(sys.argv[1])
CHECK_DIR = sys.argv[2] if len(sys.argv) > 2 else None
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run from anywhere
FPS = 30
DURATION = 12.7
M = 32  # margin around the window

CLOCK = [1000.0]
time.perf_counter = lambda: CLOCK[0]  # the UI's fades/rates follow video time, not render time
time.monotonic = lambda: CLOCK[0]

from PySide6.QtCore import QEventLoop, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter,  # noqa: E402
                           QPainterPath, QPen, QRadialGradient)
from PySide6.QtMultimedia import (QMediaCaptureSession, QMediaFormat, QMediaRecorder, QVideoFrame,  # noqa: E402
                                  QVideoFrameInput)
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
for f in glob.glob(r"C:\Windows\Fonts\segoeui*.ttf") + glob.glob(r"C:\Windows\Fonts\SegUIVar.ttf"):
    QFontDatabase.addApplicationFont(f)
app.setFont(QFont("Segoe UI", 9))

from dshub.core.pads.base import Pad  # noqa: E402
from dshub.core.pads.ds3 import DualShock3XInput  # noqa: E402
from dshub.core.pads.ds4 import DualShock4  # noqa: E402
from dshub.core.pads.ds5 import DualSense  # noqa: E402
from dshub.core.state import Battery, Button, Connection, ControllerInfo, ControllerState, Model, Touch  # noqa: E402
from dshub.ui import theme  # noqa: E402
from dshub.ui.hub import Hub  # noqa: E402
from dshub.ui.window import MainWindow  # noqa: E402

theme.apply(app)


class DemoPad(Pad):
    """A stand-in controller: same capabilities as the real class, input set by the script."""

    def __init__(self, info: ControllerInfo, caps, rate_hz: float) -> None:
        super().__init__(info, key=f"demo-{info.slot}")
        self.caps, self.rate_hz = caps, rate_hz

    def _open(self) -> None: ...

    def _close(self) -> None: ...

    def _poll(self):
        return None


hub = Hub()  # not started: no device scanning
win = MainWindow(hub)
win.resize(1180, 740)
win.show()

# typical models, links, firmware and report rates (no real addresses)
specs = [
    (Model.DS4, "build Sep 17 2021", "hid", DualShock4.caps, 500, Battery(level=100, full=True, wired=True)),
    (Model.DS5, "06.30", "hid", DualSense.caps, 250, Battery(level=95, charging=True, wired=True)),
    (Model.DS3, None, "dshidmini-xinput", DualShock3XInput.caps, 62, Battery(level=100, full=True, wired=True)),
]
pads = []
for slot, (model, fw, backend, caps, rate, battery) in enumerate(specs, 1):
    info = ControllerInfo(uid=f"demo{slot}", model=model, connection=Connection.USB, name=model.label,
                          firmware=fw, backend=backend, slot=slot)
    pad = DemoPad(info, caps, rate)
    pad.state = ControllerState(battery=battery)
    pad.battery0 = battery
    hub.manager.pads[pad.key] = pad
    hub._on_added(pad)  # noqa: SLF001 - same path a real hotplug takes
    pads.append(pad)
ds4, ds5, ds3 = pads
win.select_pad(ds4)


def ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def env(t: float, a: float, b: float, ramp: float = 0.4) -> float:
    return ease((t - a) / ramp) * ease((b - t) / ramp)


STICKS = (0.8, 4.2)
PRESSES = ((4.45, 4.75, Button.SQUARE), (4.95, 5.25, Button.TRIANGLE), (5.45, 5.75, Button.CROSS))
TOUCH = (6.2, 8.1)
CLICK_DS5, CLICK_DS3 = 9.1, 11.1
CURSOR_IN = 8.4


def ds4_state(t: float) -> ControllerState:
    e = env(t, *STICKS)
    tt = t - STICKS[0]
    r = 0.88 * e
    lx, ly = r * math.sin(2 * math.pi * 0.55 * tt), -r * math.cos(2 * math.pi * 0.55 * tt)
    rx, ry = 0.75 * e * math.sin(2 * math.pi * 0.7 * tt), 0.5 * e * math.sin(2 * math.pi * 1.4 * tt)
    touches = (Touch(), Touch())
    if TOUCH[0] <= t <= TOUCH[1]:
        s = ease((t - TOUCH[0]) / (TOUCH[1] - TOUCH[0]))
        touches = (Touch(active=True, id=1, x=0.12 + 0.76 * s, y=0.5 - 0.3 * math.sin(2 * math.pi * s)), Touch())
    pressed = frozenset(b for a, z, b in PRESSES if a <= t < z)
    return ControllerState(buttons=pressed, lx=lx, ly=ly, rx=rx, ry=ry, touches=touches, battery=ds4.battery0)


# --------------------------------------------------------------------------- cursor
ARROW = [(0, 0), (0, 17), (4.2, 13), (7.2, 19.6), (9.6, 18.6), (6.6, 12.2), (12.2, 12.2)]


def tile_point(pad) -> QPointF:
    tile = win.tiles[pad.key]
    pt = tile.mapTo(win, QPoint(int(tile.width() * 0.45), tile.height() // 2))
    return QPointF(pt.x() + M, pt.y() + M)


PARK = QPointF(M + 1180 * 0.55, M + 740 * 0.8)


def cursor_at(t: float) -> tuple[QPointF | None, float, float]:
    """(position, opacity, click ring progress or -1)."""
    if t < CURSOR_IN:
        return None, 0.0, -1
    a, b = PARK, tile_point(ds5)
    pos = a
    if t >= CLICK_DS5 - 0.55:
        pos = a + (b - a) * ease((t - (CLICK_DS5 - 0.55)) / 0.5)
    if t >= CLICK_DS3 - 0.55:
        c = tile_point(ds3)
        pos = b + (c - b) * ease((t - (CLICK_DS3 - 0.55)) / 0.5)
    ring = -1.0
    for click in (CLICK_DS5, CLICK_DS3):
        if 0 <= t - click < 0.3:
            ring = (t - click) / 0.3
    return pos, ease((t - CURSOR_IN) / 0.25), ring


def draw_cursor(p: QPainter, pos: QPointF, opacity: float, ring: float) -> None:
    p.setOpacity(opacity)
    if ring >= 0:
        p.setPen(QPen(QColor(255, 255, 255, int(180 * (1 - ring))), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(pos, 6 + 14 * ring, 6 + 14 * ring)
    path = QPainterPath()
    path.moveTo(pos.x() + ARROW[0][0], pos.y() + ARROW[0][1])
    for x, y in ARROW[1:]:
        path.lineTo(pos.x() + x, pos.y() + y)
    path.closeSubpath()
    p.setPen(QPen(QColor(0, 0, 0), 1.2))
    p.setBrush(QColor(255, 255, 255))
    p.drawPath(path)
    p.setOpacity(1.0)


# --------------------------------------------------------------------------- composition
W, H = 1180 + 2 * M, 740 + 2 * M
backdrop = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
bp = QPainter(backdrop)
bp.setRenderHint(QPainter.RenderHint.Antialiasing)
g = QLinearGradient(0, 0, W, H)
g.setColorAt(0, QColor(28, 34, 60))
g.setColorAt(0.55, QColor(14, 14, 22))
g.setColorAt(1, QColor(8, 8, 12))
bp.fillRect(backdrop.rect(), g)
glow = QRadialGradient(QPointF(W * 0.18, H * 0.12), W * 0.55)
glow.setColorAt(0, QColor(31, 134, 242, 60))
glow.setColorAt(1, QColor(31, 134, 242, 0))
bp.fillRect(backdrop.rect(), glow)
bp.setPen(Qt.PenStyle.NoPen)
for i in range(14):  # soft shadow under the window
    bp.setBrush(QColor(0, 0, 0, 9))
    bp.drawRoundedRect(QRectF(M - i, M - i + 8, 1180 + 2 * i, 740 + 2 * i), 10 + i, 10 + i)
bp.end()
clip = QPainterPath()
clip.addRoundedRect(QRectF(M, M, 1180, 740), 8, 8)


def compose(t: float) -> QImage:
    img = backdrop.copy()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setClipPath(clip)
    p.drawImage(M, M, win.grab().toImage())
    p.setClipping(False)
    pos, opacity, ring = cursor_at(t)
    if pos is not None:
        draw_cursor(p, pos, opacity, ring)
    p.end()
    return img


# --------------------------------------------------------------------------- encoder
session = QMediaCaptureSession()
vin = QVideoFrameInput()
session.setVideoFrameInput(vin)
rec = QMediaRecorder()
session.setRecorder(rec)
fmt = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
fmt.setVideoCodec(QMediaFormat.VideoCodec.H264)
rec.setMediaFormat(fmt)
rec.setQuality(QMediaRecorder.Quality.VeryHighQuality)
rec.setVideoFrameRate(FPS)
rec.setVideoResolution(QSize(W, H))
rec.setOutputLocation(QUrl.fromLocalFile(OUT))
errors = []
rec.errorOccurred.connect(lambda e, s: errors.append((e, s)))


def wait_for(signal, ms: int) -> None:
    loop = QEventLoop()
    signal.connect(loop.quit)
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    signal.disconnect(loop.quit)


rec.record()
checks = {int(s * FPS) for s in (2.6, 4.6, 5.1, 5.6, 5.8, 7.2, 9.2, 12.3)}
selected = set()
for i in range(int(DURATION * FPS)):
    t = i / FPS
    CLOCK[0] = 1000.0 + t
    if t >= CLICK_DS5 and "ds5" not in selected:
        selected.add("ds5")
        win.select_pad(ds5)
    if t >= CLICK_DS3 and "ds3" not in selected:
        selected.add("ds3")
        win.select_pad(ds3)
    ds4.state = ds4_state(t)
    for pad in pads:
        pad.raw_reports = int(pad.rate_hz * t)
    win._tick()  # noqa: SLF001
    app.processEvents()
    img = compose(t)
    if CHECK_DIR and i in checks:
        img.save(os.path.join(CHECK_DIR, f"frame_{t:05.2f}.png"))
    frame = QVideoFrame(img.convertToFormat(QImage.Format.Format_RGBA8888))
    frame.setStartTime(int(i * 1_000_000 / FPS))
    frame.setEndTime(int((i + 1) * 1_000_000 / FPS))
    while not vin.sendVideoFrame(frame):
        wait_for(vin.readyToSendVideoFrame, 2000)
        if errors:
            break
    if errors:
        break

rec.stop()
for _ in range(50):
    if rec.recorderState() == QMediaRecorder.RecorderState.StoppedState:
        break
    wait_for(rec.recorderStateChanged, 200)
print("errors:", errors)
print("state:", rec.recorderState(), "| actual location:", rec.actualLocation().toLocalFile())
hub.manager.pads.clear()
