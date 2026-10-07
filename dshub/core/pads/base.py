"""Common machinery for a connected pad: reader thread, listeners, outputs."""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from dshub.core.state import ControllerInfo, ControllerState

log = logging.getLogger(__name__)

StateListener = Callable[["Pad", ControllerState], None]


@dataclass(frozen=True, slots=True)
class Capabilities:
    lightbar: bool = False
    rumble: bool = False
    player_leds: bool = False
    touchpad: bool = False
    motion: bool = False
    pressure: bool = False
    adaptive_triggers: bool = False
    battery_saver: bool = False  # DualSense: power-save mode for the lights, motors and sensors


class LossCounter:
    """Reports lost on the way, from the sequence number the controller stamps on each one.

    Timing our own reads can't tell this: when the app is briefly busy, reports
    wait in Windows' buffer and nothing is lost. A skipped sequence number is.
    """

    def __init__(self) -> None:
        self.received = 0
        self.lost = 0
        self._last: int | None = None

    def see(self, seq: int, modulo: int) -> None:
        if self._last is not None:
            self.lost += (seq - self._last - 1) % modulo
        self._last = seq
        self.received += 1


class Pad(ABC):
    """A physical controller. Subclasses implement ``_poll`` and the outputs.

    ``_poll`` runs on a dedicated thread and returns a freshly parsed
    ``ControllerState`` (or ``None`` when no new report arrived before its
    timeout).  Listeners (the remapping engine) are called on that same
    thread, straight after parsing, to keep input latency minimal.  The UI
    does *not* listen; it samples ``pad.state`` from a timer instead.
    """

    caps = Capabilities()
    #: In low-power mode (window hidden and nobody listening) we only sample
    #: one report this often - enough to keep the battery readout fresh.
    IDLE_PERIOD_S = 2.0

    def __init__(self, info: ControllerInfo, key: str) -> None:
        self.info = info
        self.key = key  # identity used by the manager for hotplug diffing
        self.state = ControllerState()
        self.alive = True
        self.reports = 0  # reports that carried new input
        self.raw_reports = 0  # every report received (report-rate readout)
        self.loss: LossCounter | None = None  # set while a diagnostic counts lost reports
        self._listeners: list[StateListener] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._active = True
        self._centers: tuple[float, float, float, float] | None = None  # lx, ly, rx, ry rest offsets
        self._wake = threading.Event()
        self._lightbar: tuple[int, int, int] | None = None
        self._rumble = (0.0, 0.0)
        self._player = 0

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._open()
        self._thread = threading.Thread(target=self._run, name=f"pad-{self.info.title}", daemon=True)
        self._thread.start()

    def set_active(self, active: bool) -> None:
        """Full-rate reading (UI visible) vs. low-power sampling (UI hidden)."""
        self._active = active
        if active:
            self._wake.set()

    @property
    def low_power(self) -> bool:
        return not self._active and not self._listeners

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        try:
            self._close()
        except Exception:  # noqa: BLE001 - closing a vanished device can throw anything
            log.debug("close failed for %s", self.info.title, exc_info=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            if self.low_power:
                self._wake.wait(self.IDLE_PERIOD_S)
                self._wake.clear()
                if self._stop.is_set():
                    return
            try:
                st = self._poll()
            except OSError:
                log.info("%s disconnected", self.info.title)
                self.alive = False
                return
            except Exception:  # noqa: BLE001 - a bad report must not kill the reader
                log.exception("parse error on %s", self.info.title)
                time.sleep(0.05)
                continue
            if st is None:
                continue
            if self._centers is not None:
                _recentre(st, self._centers)
            st.timestamp = time.perf_counter()
            self.state = st
            self.reports += 1
            for fn in tuple(self._listeners):
                try:
                    fn(self, st)
                except Exception:  # noqa: BLE001
                    log.exception("listener failed")

    def set_stick_centers(self, centers: tuple[float, float, float, float] | None) -> None:
        """Rest position of (lx, ly, rx, ry) to treat as the true centre (None: raw)."""
        self._centers = centers

    @property
    def stick_centers(self) -> tuple[float, float, float, float] | None:
        return self._centers

    def add_listener(self, fn: StateListener) -> None:
        if fn not in self._listeners:
            self._listeners.append(fn)
        self._wake.set()

    def remove_listener(self, fn: StateListener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    # ---------------------------------------------------------------- outputs
    @property
    def lightbar(self) -> tuple[int, int, int] | None:
        return self._lightbar

    @property
    def player_led(self) -> int:
        return self._player

    def set_lightbar(self, rgb: tuple[int, int, int] | None) -> None:
        if self.caps.lightbar:
            self._lightbar = rgb
            self._send_output()

    def set_rumble(self, strong: float, weak: float) -> None:
        if self.caps.rumble:
            self._rumble = (max(0.0, min(1.0, strong)), max(0.0, min(1.0, weak)))
            self._send_output()

    def set_battery_saver(self, on: bool) -> None:
        if self.caps.battery_saver:
            self._saver = on
            self._send_output()

    @property
    def battery_saver(self) -> bool:
        return getattr(self, "_saver", False)

    def set_player_led(self, n: int) -> None:
        if self.caps.player_leds:
            self._player = n
            self._send_output()

    # ---------------------------------------------------------------- abstract
    @abstractmethod
    def _open(self) -> None: ...

    @abstractmethod
    def _close(self) -> None: ...

    @abstractmethod
    def _poll(self) -> ControllerState | None: ...

    def _send_output(self) -> None:  # noqa: B027 - optional for input-only pads
        pass


def stick(v: int) -> float:
    """0..255 HID axis -> -1..1 with a tiny dead-centre snap."""
    f = (v - 127.5) / 127.5
    return 0.0 if abs(f) < 0.008 else max(-1.0, min(1.0, f))


def hat_to_dpad(hat: int) -> tuple[bool, bool, bool, bool]:
    """HID hat switch (0=N, clockwise, 8=released) -> (up, right, down, left)."""
    if hat > 7:
        return False, False, False, False
    return (
        hat in (7, 0, 1),
        hat in (1, 2, 3),
        hat in (3, 4, 5),
        hat in (5, 6, 7),
    )


def s16(data, i: int) -> int:
    v = data[i] | (data[i + 1] << 8)
    return v - 0x10000 if v & 0x8000 else v


def _recentre_axis(v: float, c: float) -> float:
    """Move the centre to ``c`` and rescale each side so full tilt still reaches +-1."""
    if v >= c:
        return min(1.0, (v - c) / (1.0 - c)) if c < 1.0 else 0.0
    return max(-1.0, (v - c) / (1.0 + c)) if c > -1.0 else 0.0


def _recentre(st, centers: tuple[float, float, float, float]) -> None:
    cx, cy, dx, dy = centers
    st.lx, st.ly = _recentre_axis(st.lx, cx), _recentre_axis(st.ly, cy)
    st.rx, st.ry = _recentre_axis(st.rx, dx), _recentre_axis(st.ry, dy)
