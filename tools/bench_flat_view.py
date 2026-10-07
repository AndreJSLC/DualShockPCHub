"""Measure what the flat controller view costs, and check it still draws the same.

    python tools/bench_flat_view.py bench               # ms/frame: full repaint, sticks moving, busy
    python tools/bench_flat_view.py snap OUT_DIR        # rest grabs of every model at 760x500 and 1100x720
    python tools/bench_flat_view.py diff DIR_A DIR_B    # compare two snapshot sets pixel by pixel

The bench repaints exactly the regions each ``set_state`` asks for, as the real
window does. Take a ``snap`` before and after a renderer change and ``diff``
them: the look at rest should stay pixel-identical.
"""
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QRegion  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from dshub.core.state import Button, ControllerState, Model, Touch  # noqa: E402
from dshub.ui.flat_view import FlatView  # noqa: E402

app = QApplication(sys.argv)
MODELS = [Model.DS2, Model.DS3, Model.DS4, Model.DS5, Model.DS5_EDGE]
SIZES = [(760, 500), (1100, 720)]


def make(model, w, h):
    v = FlatView(model)
    v.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    v.resize(w, h)
    v.show()
    app.processEvents()
    return v


def grab(v, region=None):
    img = QImage(v.width(), v.height(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    v.render(p, QPoint(0, 0), region or QRegion(), QWidget.RenderFlag.DrawChildren)
    p.end()
    return img


def snap(out):
    os.makedirs(out, exist_ok=True)
    for m in MODELS:
        for w, h in SIZES:
            v = make(m, w, h)
            grab(v).save(os.path.join(out, f"{m.value}_{w}x{h}_rest.png"))
            v.set_player_leds(2)  # rest with LEDs on, too
            grab(v).save(os.path.join(out, f"{m.value}_{w}x{h}_leds.png"))
    print("snapped", out)


def diff(a, b):
    worst = 0
    for name in sorted(os.listdir(a)):
        ia, ib = QImage(os.path.join(a, name)), QImage(os.path.join(b, name))
        if ia.size() != ib.size():
            print(name, "SIZE DIFFERS")
            continue
        ba = bytes(ia.convertToFormat(QImage.Format.Format_ARGB32).constBits())
        bb = bytes(ib.convertToFormat(QImage.Format.Format_ARGB32).constBits())
        n = sum(1 for i in range(0, len(ba), 4) if ba[i:i + 4] != bb[i:i + 4])
        mx = max((abs(x - y) for x, y in zip(ba, bb)), default=0) if n else 0
        worst = max(worst, n)
        print(f"{name:28} differing pixels: {n:6}  max channel delta: {mx}")
    print("WORST", worst)


def state(i, busy):
    t = i / 60
    return ControllerState(
        buttons=frozenset({Button.CROSS, Button.L1, Button.DPAD_UP} if busy and i % 20 < 12 else ()),
        lx=math.sin(t * 3) * .8, ly=math.cos(t * 3) * .8, rx=math.cos(t * 2) * .5, ry=.3,
        l2=(math.sin(t) + 1) / 2 if busy else 0.0,
        touches=(Touch(busy, 1, (math.sin(t) + 1) / 2, .5), Touch()))


def bench():
    for m in (Model.DS3, Model.DS4, Model.DS5):
        for w, h in SIZES:
            v = make(m, w, h)
            captured = []
            orig_update = v.update

            def update(*args):  # record what each set_state asks to repaint
                captured.append(args[0] if args and isinstance(args[0], QRegion) else QRegion(v.rect()))
                orig_update(*args)

            v.update = update
            img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)

            def paint(region):
                p = QPainter(img)
                v.render(p, QPoint(0, 0), region, QWidget.RenderFlag.DrawChildren)
                p.end()

            for i in range(30):
                v.set_state(state(i, True))
                paint(QRegion(v.rect()))
            rows = []
            n = 200
            t0 = time.perf_counter()
            for _ in range(n):
                paint(QRegion(v.rect()))
            rows.append(("full", (time.perf_counter() - t0) / n))
            for label, busy in (("sticks", False), ("busy", True)):
                t0 = time.perf_counter()
                for i in range(n):
                    captured.clear()
                    v.set_state(state(i, busy))
                    reg = QRegion()
                    for r in captured:
                        reg = reg.united(r)
                    if not reg.isEmpty():
                        paint(reg)
                rows.append((label, (time.perf_counter() - t0) / n))
            print(f"{m.value:4} {w}x{h:<4} " + "  ".join(f"{k} {s * 1000:5.2f} ms" for k, s in rows))


if __name__ == "__main__":
    {"snap": lambda: snap(sys.argv[2]), "diff": lambda: diff(sys.argv[2], sys.argv[3]), "bench": bench}[sys.argv[1]]()
