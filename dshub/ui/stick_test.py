"""Stick test: measure what a controller's sticks really send.

Opened from the Live page. While it is open it listens to every report (full
rate, like remapping does) and shows, per stick:

* the connection: reports per second and, where the controller numbers its
  reports (DS4/DS5), how many really got lost on the way,
* resting offset and noise (off-centre / jitter: leave the sticks alone),
* return to centre: where it lands each time you let go (a stick that lands
  somewhere different every time feels inconsistent near the centre),
* reach (rotate the stick around its edge): does full tilt reach 100% everywhere.

Then it says in plain words what's normal, what isn't, and what to change.
The last result per controller model is saved to the app's data folder.
"""

from __future__ import annotations

import html
import math
import re
import statistics
import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dshub.config import data_dir
from dshub.core.pads.base import LossCounter, Pad
from dshub.core.state import Connection, ControllerState
from dshub.ui import theme
from dshub.ui.widgets import Card, font, label

BINS = 72  # 5-degree sectors for the reach outline
OFF_CENTRE = 0.035  # rest offsets above this are worth calibrating (healthy pads rest within ~3%)
LANDING_SPREAD = 0.025  # landing spots further apart than this make the centre feel inconsistent
SETTLE_S = 0.25  # after letting go, the stick has settled by then
WARN = "#ffb840"
DIRECTIONS = ("left", "up-left", "up", "up-right", "right", "down-right", "down", "down-left")


def _direction(bin_index: int) -> str:
    """Name of the direction a reach bin points to (screen coordinates: +y is down)."""
    a = (bin_index + 0.5) / BINS * 360.0  # 0 deg = left, increasing towards up
    return DIRECTIONS[int((a + 22.5) // 45) % 8]


def _warn(text: str) -> str:
    return f"<span style='color:{WARN}'>{text}</span>"


class StickStats:
    def __init__(self) -> None:
        self.reach = [0.0] * BINS
        self.rest: deque[tuple[float, float]] = deque(maxlen=600)
        self.trail: deque[tuple[float, float]] = deque(maxlen=90)
        self.landings: deque[tuple[float, float]] = deque(maxlen=40)  # where it settles after each release
        self._armed = False  # pushed out past half way since the last landing
        self._inside_since: float | None = 0.0  # when it last came back under 20% tilt (None: out)

    def add(self, t: float, x: float, y: float) -> None:
        r = math.hypot(x, y)
        if r > 0.25:
            b = int((math.atan2(y, x) + math.pi) / (2 * math.pi) * BINS) % BINS
            self.reach[b] = max(self.reach[b], r)
        if r < 0.2:
            if self._inside_since is None:
                self._inside_since = t
        else:
            self._inside_since = None
            if r > 0.5:
                self._armed = True
        self.trail.append((x, y))

    def settle(self, now: float, x: float, y: float) -> None:
        """UI timer (~30 Hz): sample the resting position once the stick has settled in the middle,
        and note where it landed after each flick."""
        if self._inside_since is None or now - self._inside_since <= SETTLE_S or math.hypot(x, y) >= 0.2:
            return
        self.rest.append((x, y))
        if self._armed:
            self.landings.append((x, y))
            self._armed = False

    def landing(self) -> tuple[float, float, float] | None:
        """(mean x, mean y, spread): spread = furthest landing from their average."""
        if len(self.landings) < 4:
            return None
        xs, ys = zip(*self.landings)
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        return mx, my, max(math.hypot(x - mx, y - my) for x, y in self.landings)

    # -------------------------------------------------- derived numbers (all 0..1 or per second)
    def rest_offset(self) -> float | None:
        if len(self.rest) < 60:
            return None
        xs, ys = zip(*self.rest)
        return math.hypot(statistics.fmean(xs), statistics.fmean(ys))

    def rest_noise(self) -> float | None:
        if len(self.rest) < 60:
            return None
        xs, ys = zip(*self.rest)
        return math.hypot(statistics.pstdev(xs), statistics.pstdev(ys))

    def reach_avg(self) -> tuple[float, float]:
        seen = [r for r in self.reach if r > 0]
        return (statistics.fmean(seen) if seen else 0.0), len(seen) / BINS

    def weakest(self) -> tuple[float, str] | None:
        """Lowest full-tilt reach and the direction it's in (smoothed over 3 sectors)."""
        if self.reach_avg()[1] <= 0.6:
            return None
        best = None
        for i in range(BINS):
            ring = [self.reach[(i + k) % BINS] for k in (-1, 0, 1)]
            if all(r > 0 for r in ring):
                r = statistics.fmean(ring)
                if best is None or r < best[0]:
                    best = (r, _direction(i))
        return best


class StickPlotBig(QWidget):
    def __init__(self, title: str, stats: StickStats, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title, self.stats = title, stats
        self.setMinimumSize(260, 260)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height()) - 16
        c = QPointF(self.width() / 2, self.height() / 2)
        rad = size / 2
        p.setPen(QPen(theme.HAIRLINE_STRONG, 1))
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawEllipse(c, rad, rad)
        p.setPen(QPen(theme.HAIRLINE, 1, Qt.PenStyle.DashLine))
        p.drawEllipse(c, rad * 0.5, rad * 0.5)
        p.drawLine(QPointF(c.x() - rad, c.y()), QPointF(c.x() + rad, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - rad), QPointF(c.x(), c.y() + rad))
        # measured reach outline
        path = QPainterPath()
        first = True
        for i, r in enumerate(self.stats.reach):
            if r <= 0:
                first = True
                continue
            a = (i + 0.5) / BINS * 2 * math.pi - math.pi
            pt = QPointF(c.x() + math.cos(a) * r * rad, c.y() + math.sin(a) * r * rad)
            if first:
                path.moveTo(pt)
                first = False
            else:
                path.lineTo(pt)
        p.setPen(QPen(theme.OK, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # trail + dot
        trail = list(self.stats.trail)
        for i, (x, y) in enumerate(trail):
            a = (i + 1) / max(1, len(trail))
            col = QColor(theme.ACCENT)
            col.setAlphaF(0.08 + 0.4 * a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(c.x() + x * rad, c.y() + y * rad), 2.2, 2.2)
        if trail:
            x, y = trail[-1]
            p.setBrush(theme.ACCENT)
            p.drawEllipse(QPointF(c.x() + x * rad, c.y() + y * rad), 6, 6)
        p.setPen(theme.TEXT_DIM)
        p.setFont(font(12))
        p.drawText(QRectF(0, 0, self.width(), 18), Qt.AlignmentFlag.AlignHCenter, self.title)


class StickTestDialog(QDialog):
    def __init__(self, pad: Pad, parent: QWidget | None = None, hub=None) -> None:
        super().__init__(parent)
        self.pad, self.hub = pad, hub
        self.setWindowTitle(f"Stick test - {pad.info.title}")
        self.resize(760, 640)
        self.left, self.right = StickStats(), StickStats()
        self._raw0, self._t0 = pad.raw_reports, time.perf_counter()
        self._rate = 0.0
        self._plain = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label(f"Stick test · {pad.info.model.label} ({pad.info.connection.value.upper()})", "h1"))
        steps = label("1. Leave both sticks alone for 3 seconds.   2. Rotate each stick slowly around its edge, "
                      "twice.   3. Flick each stick in different directions and let it snap back, about 6 times.",
                      "dim")
        steps.setWordWrap(True)
        lay.addWidget(steps)
        plots = QHBoxLayout()
        self.plot_l, self.plot_r = StickPlotBig("Left stick", self.left), StickPlotBig("Right stick", self.right)
        plots.addWidget(self.plot_l)
        plots.addWidget(self.plot_r)
        lay.addLayout(plots, 1)
        card = Card()
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.TextFormat.RichText)
        card.lay.addWidget(self.result)
        lay.addWidget(card)
        buttons = QHBoxLayout()
        reset = QPushButton("Start over")
        reset.clicked.connect(self._reset)
        self.calibrate = QPushButton("Calibrate centre")
        self.calibrate.setToolTip("Leave both sticks alone, then click: their resting point becomes the true "
                                  "centre (each side is rescaled so full tilt still reaches 100%).")
        self.calibrate.clicked.connect(self._calibrate)
        self.uncalibrate = QPushButton("Clear calibration")
        self.uncalibrate.setProperty("kind", "ghost")
        self.uncalibrate.clicked.connect(self._clear_calibration)
        self.uncalibrate.setVisible(pad.stick_centers is not None)
        copy = QPushButton("Copy results")
        copy.setProperty("kind", "ghost")
        copy.setToolTip("Copies the results as text, to paste into a message or an issue.")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self._plain))
        close = QPushButton("Close")
        close.setProperty("kind", "primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(self.uncalibrate)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        buttons.addWidget(self.calibrate)
        buttons.addWidget(reset)
        buttons.addWidget(close)
        lay.addLayout(buttons)

        pad.loss = LossCounter()  # counts reports lost on the way (DS4/DS5; others leave it at 0)
        pad.add_listener(self._on_state)  # full-rate reading while the test is open
        self._timer = QTimer(self, interval=33, timeout=self._refresh)
        self._timer.start()

    def _on_state(self, _pad: Pad, st: ControllerState) -> None:
        t = time.perf_counter()  # reader thread; deque appends are thread-safe
        self.left.add(t, st.lx, st.ly)
        self.right.add(t, st.rx, st.ry)

    def _calibrate(self) -> None:
        if self.hub is None:
            return
        rest_l, rest_r = list(self.left.rest), list(self.right.rest)
        if len(rest_l) < 60 or len(rest_r) < 60:
            self.calibrate.setText("Leave the sticks alone a moment…")
            QTimer.singleShot(1500, lambda: self.calibrate.setText("Calibrate centre"))
            return
        old = self.pad.stick_centers or (0.0, 0.0, 0.0, 0.0)

        def centre(st: StickStats, rows, ox, oy):
            """Average landing spot if we have several (the best estimate), else the resting average.
            Samples are already calibrated by the old centres, so add those back."""
            land = st.landing()
            if land is not None:
                return land[0] + ox, land[1] + oy
            xs, ys = zip(*rows)
            return statistics.fmean(xs) + ox, statistics.fmean(ys) + oy

        lx, ly = centre(self.left, rest_l, old[0], old[1])
        rx, ry = centre(self.right, rest_r, old[2], old[3])
        self.hub.set_stick_centers(self.pad, (lx, ly, rx, ry))
        self.uncalibrate.setVisible(True)
        self.calibrate.setText("Calibrated ✓")
        QTimer.singleShot(1800, lambda: self.calibrate.setText("Calibrate centre"))
        self._reset()

    def _clear_calibration(self) -> None:
        if self.hub is not None:
            self.hub.set_stick_centers(self.pad, None)
        self.uncalibrate.setVisible(False)
        self._reset()

    def _reset(self) -> None:
        self.left.__init__()
        self.right.__init__()
        self.pad.loss = LossCounter()

    def done(self, r: int) -> None:  # noqa: D401 - Qt override: always detach the listener
        self.pad.remove_listener(self._on_state)
        self.pad.loss = None
        self._timer.stop()
        self._save()
        super().done(r)

    def _save(self) -> None:
        """Keep the last result per model, so it can be compared later (DS4 vs DS5...)."""
        if not self._plain or self.left.reach_avg()[1] + self.right.reach_avg()[1] < 0.3:
            return
        reach = lambda st: " ".join(f"{r:.2f}" for r in st.reach)  # noqa: E731
        lands = lambda st: " ".join(f"({x:+.3f},{y:+.3f})" for x, y in st.landings)  # noqa: E731
        text = (f"{time.strftime('%Y-%m-%d %H:%M')}  {self.pad.info.model.label}  "
                f"{self.pad.info.connection.value}  calibrated={self.pad.stick_centers is not None}\n"
                f"{self._plain}\n\nreach bins (5 deg from left, towards up):\nL {reach(self.left)}\n"
                f"R {reach(self.right)}\nlandings:\nL {lands(self.left)}\nR {lands(self.right)}\n")
        try:
            (data_dir() / f"stick-test-{self.pad.info.model.value}.txt").write_text(text, "utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------ verdict
    def _refresh(self) -> None:
        now = time.perf_counter()
        if now - self._t0 >= 1.0:
            self._rate = (self.pad.raw_reports - self._raw0) / (now - self._t0)
            self._raw0, self._t0 = self.pad.raw_reports, now
        self.plot_l.update()
        self.plot_r.update()
        st_now = self.pad.state
        self.left.settle(now, st_now.lx, st_now.ly)
        self.right.settle(now, st_now.rx, st_now.ry)
        rows: list[str] = [self._connection_row()]
        tips: list[str] = []
        calibrated = self.pad.stick_centers is not None
        for name, st in (("Left", self.left), ("Right", self.right)):
            off, noise = st.rest_offset(), st.rest_noise()
            parts = []
            if off is None:
                parts.append("leave it alone a moment to measure its centre")
            elif off > OFF_CENTRE:
                parts.append(_warn(f"rests {off * 100:.1f}% off-centre") + " (healthy: under 3%)")
                tips.append(f"{name} stick rests {off * 100:.1f}% off-centre. That makes it respond differently "
                            "in each direction, which feels uneven. Leave the sticks alone and press "
                            "<b>Calibrate centre</b>.")
            else:
                parts.append(f"centred ({off * 100:.1f}% off{', calibrated' if calibrated else ''})")
            if noise is not None:
                if noise > 0.02:
                    parts.append(_warn(f"jittery at rest (±{noise * 100:.1f}%)"))
                    tips.append(f"{name} stick wobbles by itself: set its deadzone to about "
                                f"{round((off + 3 * noise) * 100 + 2)}% on the Remap page.")
                else:
                    parts.append("steady at rest")
            land = st.landing()
            if land is None:
                parts.append(f"flick it and let go ({len(st.landings)}/4)")
            elif land[2] > LANDING_SPREAD:
                spread = land[2]
                parts.append(_warn(f"lands in a different spot each time you let go (up to {spread * 100:.1f}% "
                                   "from its average)"))
                dz = round((spread + 3 * (noise or 0.0)) * 100 + 2)
                tips.append(f"{name} stick doesn't come back to the same spot when you let go: it lands up to "
                            f"{spread * 100:.1f}% away from its average. So each time, it has to travel a different "
                            "distance before the game reacts, which feels inconsistent. <b>Calibrate centre</b> "
                            f"aims at the average spot; also set its deadzone to about {dz}% on the Remap page to "
                            "cover the rest.")
            else:
                parts.append(f"comes back to the same spot (within {land[2] * 100:.1f}%)")
            weakest = st.weakest()
            if weakest is None:
                parts.append("now rotate it slowly around the edge")
            else:
                r, where = weakest
                if r >= 0.95:
                    parts.append("full tilt reaches 100% all the way round")
                else:
                    parts.append(_warn(f"full tilt only reaches {r * 100:.0f}% towards {where}"))
                    tips.append(f"{name} stick tops out at {r * 100:.0f}% towards {where}, so games never see full "
                                "speed that way. Raise its sensitivity a little on the Remap page.")
            rows.append(f"<b>{name} stick:</b> " + " · ".join(parts))
        if tips:
            rows.append("<b>What to do:</b><br>" + "<br>".join(f"• {t}" for t in tips))
        elif all(st.rest_offset() is not None and st.weakest() is not None and st.landing() is not None
                 for st in (self.left, self.right)):
            rows.append("<b>Verdict:</b> the connection and both sticks look healthy.")
        text = "<br>".join(rows)
        self.result.setText(text)
        self._plain = html.unescape(re.sub(r"<[^>]+>", "", text.replace("<br>", "\n")))

    def _connection_row(self) -> str:
        bt = self.pad.info.connection is Connection.BLUETOOTH
        head = f"<b>Connection:</b> {self._rate:.0f} reports/s over {'Bluetooth' if bt else 'USB'}"
        if bt and 0 < self._rate < 100:
            head += " · " + _warn("low: the pad is probably in Bluetooth compatibility mode")
        loss = self.pad.loss
        if loss is None or loss.received < 200:
            return head  # this controller doesn't number its reports (DS3, DS2), or still counting
        if loss.lost * 100 <= loss.received:  # under 1%: nothing you could feel
            return head + f" · none lost ({loss.received} checked)" if not loss.lost else \
                head + f" · {loss.lost} of {loss.received} lost (fine)"
        fix = ("Keep the controller within about 2 m of the Bluetooth adapter with nothing in between; a USB 3 "
               "device or Wi-Fi router next to the adapter interferes. A USB cable avoids it completely." if bt else
               "Plug the controller straight into a port on the back of the PC (not a hub or front-panel port), "
               "or try another cable.")
        return head + " · " + _warn(f"{loss.lost * 100 / loss.received:.1f}% of reports lost on the way") + \
            "<br>&nbsp;&nbsp;That feels like stutter. " + fix
