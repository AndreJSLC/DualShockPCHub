"""Turns a physical pad's state into virtual Xbox / keyboard / mouse output.

A ``RemapSession`` is attached to one ``Pad`` as a state listener, so it runs
on that pad's reader thread right after each report is parsed.  Mouse
movement from a stick is integrated on a small timer thread instead, so the
cursor keeps gliding even when the pad sends no new reports.
"""

from __future__ import annotations

import logging
import math
import threading

from dshub.core.pads.base import Pad
from dshub.core.state import Button, ControllerState
from dshub.core.vigem import X360Pad
from dshub.mapping import sendinput
from dshub.mapping.profile import PAD_TARGETS, Profile, StickConfig

log = logging.getLogger(__name__)

STICK_KEYS = {
    "wasd": ("W", "A", "S", "D"),
    "arrows": ("Up", "Left", "Down", "Right"),
}


def shape_stick(x: float, y: float, cfg: StickConfig) -> tuple[float, float]:
    """Radial deadzone + anti-deadzone + sensitivity curve, keeps direction."""
    mag = math.hypot(x, y)
    if mag <= cfg.deadzone or mag == 0:
        return 0.0, 0.0
    norm = min((mag - cfg.deadzone) / (1.0 - cfg.deadzone), 1.0)
    if cfg.anti_deadzone:
        norm = cfg.anti_deadzone + (1.0 - cfg.anti_deadzone) * norm
    norm = min(norm ** (1.0 / max(cfg.sensitivity, 0.1)), 1.0)
    sx, sy = x / mag * norm, y / mag * norm
    return sx, (-sy if cfg.invert_y else sy)


def _axis16(v: float) -> int:
    return max(-32768, min(32767, int(round(v * 32767))))


class RemapSession:
    MOUSE_HZ = 125
    MOUSE_SPEED = 18.0  # pixels per tick at full deflection, sensitivity 1.0

    def __init__(self, pad: Pad, profile: Profile, virtual_pad: bool = True) -> None:
        self.pad = pad
        self.profile = profile
        self._vpad: X360Pad | None = None
        if virtual_pad:
            self._vpad = X360Pad(rumble_callback=self._on_rumble)
        self._held_keys: set[str] = set()  # "key:W" / "mouse:left" currently held down
        self._last: ControllerState | None = None
        self._last_report: tuple | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._mouse_thread = threading.Thread(target=self._mouse_loop, name="remap-mouse", daemon=True)
        self._mouse_thread.start()
        pad.add_listener(self._on_state)

    @property
    def virtual_serial(self) -> int | None:
        return self._vpad.serial if self._vpad else None

    def set_profile(self, profile: Profile) -> None:
        with self._lock:
            self.profile = profile
            self._last_report = None
            self._release_all()

    # ------------------------------------------------------------------ input
    def _on_state(self, _pad: Pad, st: ControllerState) -> None:
        with self._lock:
            self._last = st
            prof = self.profile
            buttons = 0
            lt = rt = 0.0
            wanted: set[str] = set()

            for button in st.buttons:
                bind = prof.binding(button)
                if bind.kind == "pad":
                    if bind.target == "lt":
                        lt = 1.0
                    elif bind.target == "rt":
                        rt = 1.0
                    else:
                        buttons |= PAD_TARGETS.get(bind.target, 0)
                elif bind.kind in ("key", "mouse"):
                    wanted.add(f"{bind.kind}:{bind.target}")

            # Triggers (analog). The L2/R2 *digital* bits are handled above
            # only when the user rebinds them to something else.
            for value, cfg in ((st.l2, prof.l2), (st.r2, prof.r2)):
                v = 0.0 if value <= cfg.deadzone else (value - cfg.deadzone) / (1.0 - cfg.deadzone)
                if cfg.target == "lt":
                    lt = max(lt, v)
                elif cfg.target == "rt":
                    rt = max(rt, v)

            sticks = {"left": (0.0, 0.0), "right": (0.0, 0.0)}
            for (x, y), cfg in (((st.lx, st.ly), prof.left_stick), ((st.rx, st.ry), prof.right_stick)):
                sx, sy = shape_stick(x, y, cfg)
                if cfg.mode in sticks:
                    ox, oy = sticks[cfg.mode]
                    sticks[cfg.mode] = (max(-1, min(1, ox + sx)), max(-1, min(1, oy + sy)))
                elif cfg.mode in STICK_KEYS:
                    up, left, down, right = STICK_KEYS[cfg.mode]
                    if sy < -0.5:
                        wanted.add(f"key:{up}")
                    if sy > 0.5:
                        wanted.add(f"key:{down}")
                    if sx < -0.5:
                        wanted.add(f"key:{left}")
                    if sx > 0.5:
                        wanted.add(f"key:{right}")

            self._apply_held(wanted)
            if self._vpad is not None:
                (lx, ly), (rx, ry) = sticks["left"], sticks["right"]
                # Our sticks are +y down; XInput is +y up.
                report = (buttons, int(lt * 255), int(rt * 255),
                          _axis16(lx), _axis16(-ly), _axis16(rx), _axis16(-ry))
                if report != self._last_report:  # jitter inside the deadzone costs no driver call
                    self._last_report = report
                    self._vpad.submit(*report)

    def _apply_held(self, wanted: set[str]) -> None:
        for item in self._held_keys - wanted:
            self._emit(item, False)
        for item in wanted - self._held_keys:
            self._emit(item, True)
        self._held_keys = wanted

    @staticmethod
    def _emit(item: str, down: bool) -> None:
        kind, _, target = item.partition(":")
        try:
            if kind == "key" and target in sendinput.KEYS:
                sendinput.key(sendinput.KEYS[target], down)
            elif kind == "mouse":
                sendinput.mouse_button(target, down)
        except OSError:
            log.exception("SendInput failed")

    def _release_all(self) -> None:
        self._apply_held(set())

    # ------------------------------------------------------------------ mouse
    def _mouse_loop(self) -> None:
        period = 1.0 / self.MOUSE_HZ
        carry = [0.0, 0.0]
        while not self._stop.wait(period):
            st, prof = self._last, self.profile
            if st is None:
                continue
            dx = dy = 0.0
            for (x, y), cfg in (((st.lx, st.ly), prof.left_stick), ((st.rx, st.ry), prof.right_stick)):
                if cfg.mode != "mouse":
                    continue
                sx, sy = shape_stick(x, y, StickConfig(deadzone=cfg.deadzone, invert_y=cfg.invert_y))
                speed = self.MOUSE_SPEED * cfg.sensitivity
                # Squared response: precise near centre, fast at the edge.
                mag = math.hypot(sx, sy)
                dx += sx * mag * speed
                dy += sy * mag * speed
            carry[0] += dx
            carry[1] += dy
            ix, iy = int(carry[0]), int(carry[1])
            if ix or iy:
                carry[0] -= ix
                carry[1] -= iy
                sendinput.mouse_move(ix, iy)

    # ------------------------------------------------------------------ rumble
    def _on_rumble(self, large: float, small: float) -> None:
        k = self.profile.rumble
        self.pad.set_rumble(large * k, small * k)

    def close(self) -> None:
        self.pad.remove_listener(self._on_state)
        self._stop.set()
        self._mouse_thread.join(timeout=1)
        with self._lock:
            self._release_all()
        if self._vpad is not None:
            self._vpad.close()
            self._vpad = None
        try:
            self.pad.set_rumble(0, 0)
        except OSError:
            pass
