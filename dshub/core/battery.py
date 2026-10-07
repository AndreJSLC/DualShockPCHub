"""Time-to-full and time-left estimates from how a pad's battery level moves.

Controllers only report coarse levels (DS4/DualSense: 10 % steps; DS3: five
steps, and nothing at all while charging). So we time the moments the level
*changes*: the gap between two changes gives the real charge (or drain) rate
of this particular controller and battery. Until we have seen one full step,
we fall back to typical figures for the model, then to what we learned about
this controller last time (rates are persisted per controller).

Between two level changes the estimate keeps counting down with the clock
(it doesn't sit on "full in 50 min" for the hour a 10 % step can take).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from dshub.core.state import Battery, Model

#: Typical minutes for an empty -> full charge, and hours of play on a full battery.
TYPICAL_CHARGE_MIN = {Model.DS2: 120.0, Model.DS3: 120.0, Model.DS4: 120.0, Model.DS5: 180.0, Model.DS5_EDGE: 150.0}
TYPICAL_RUNTIME_H = {Model.DS2: 25.0, Model.DS3: 25.0, Model.DS4: 7.0, Model.DS5: 7.0, Model.DS5_EDGE: 6.0}
TAPER_FROM = 80  # Li-ion charging slows down for the last stretch (constant-voltage phase)
TAPER_FACTOR = 1.6
SLOW_CHARGE = 2.0  # charging this many times slower than typical is worth telling the user


def _step_range(model: Model, b: Battery) -> tuple[float, float]:
    """The span of real charge behind a coarse reported level."""
    v = float(b.level)
    if v >= 100:
        return 100.0, 100.0
    if model in (Model.DS5, Model.DS5_EDGE):
        return v - 5.0, v + 5.0  # 10 % steps, reported mid-step
    if model is Model.DS4:
        return (v, v + 10.0) if b.wired else (v, v + 12.5)
    return v, v  # unknown granularity: no countdown


def _minutes_to_full(level: float, rate: float) -> float:
    fast = max(0.0, TAPER_FROM - level)
    slow = 100.0 - max(level, TAPER_FROM)
    return fast / rate + slow / rate * TAPER_FACTOR


@dataclass
class Estimate:
    minutes: float | None  # None: can't tell
    to_full: bool  # True: time until full; False: time until empty
    learned: bool  # True when based on this controller's own measured rate
    overdue: bool = False  # took longer than expected to reach the next step

    def text(self) -> str:
        if self.minutes is None:
            return ""
        if self.overdue and self.to_full:
            return "full soon"
        m = max(1, round(self.minutes))
        h, mm = divmod(m, 60)
        span = f"{h} h {mm:02d} min" if h else f"{mm} min"
        approx = "" if self.learned else "~"
        return f"full in {approx}{span}" if self.to_full else f"{approx}{span} left"


class BatteryTracker:
    def __init__(self, model: Model, learned: dict | None = None) -> None:
        self.model = model
        # %/minute, learned on previous runs (may be None)
        self.charge_rate: float | None = (learned or {}).get("charge_rate")
        self.drain_rate: float | None = (learned or {}).get("drain_rate")
        self._level: int | None = None
        self._charging: bool | None = None
        self._changed_at: float | None = None  # when the level last changed (same mode)
        self._seen_at: float | None = None  # since when we've been looking at the current level
        self._stepped = False  # True: we saw it step into this level (so it's at the step's start)

    def learned(self) -> dict:
        return {"charge_rate": self.charge_rate, "drain_rate": self.drain_rate}

    def update(self, b: Battery, now: float | None = None) -> bool:
        """Feed the latest reading; returns True when a rate was (re)learned."""
        now = time.monotonic() if now is None else now
        charging = b.charging and not b.full
        if b.level is None or charging != self._charging:
            # mode switch (plugged in / unplugged) or no level: restart timing
            self._level, self._charging, self._changed_at = b.level, charging, None
            self._seen_at, self._stepped = now, False
            return False
        if self._level is None:
            self._level, self._changed_at = b.level, None
            self._seen_at, self._stepped = now, False
            return False
        if b.level == self._level:
            return False
        learned = False
        step = b.level - self._level
        if self._changed_at is not None and (step > 0) == charging:
            minutes = (now - self._changed_at) / 60.0
            if minutes > 0.5:  # ignore bounces between two adjacent levels
                rate = abs(step) / minutes
                if charging:
                    if b.level <= TAPER_FROM:  # learn the fast part; the taper is modelled
                        self.charge_rate = rate if self.charge_rate is None else 0.6 * rate + 0.4 * self.charge_rate
                        learned = True
                else:
                    self.drain_rate = rate if self.drain_rate is None else 0.6 * rate + 0.4 * self.drain_rate
                    learned = True
        self._level, self._changed_at = b.level, now
        self._seen_at, self._stepped = now, True
        return learned

    def slow_charge_factor(self) -> float | None:
        """How many times slower than typical this controller charges (None: normal or unknown)."""
        if not self.charge_rate:
            return None
        factor = (100.0 / TYPICAL_CHARGE_MIN[self.model]) / self.charge_rate
        return factor if factor >= SLOW_CHARGE else None

    def _elapsed_min(self, b: Battery, now: float | None) -> float | None:
        if self._seen_at is None or b.level != self._level:
            return None
        now = time.monotonic() if now is None else now
        return max(0.0, now - self._seen_at) / 60.0

    def estimate(self, b: Battery, now: float | None = None) -> Estimate:
        if b.full:
            return Estimate(None, True, False)
        if b.charging:
            if b.level is None:
                return Estimate(None, True, False)
            rate = self.charge_rate or 100.0 / TYPICAL_CHARGE_MIN[self.model]
            lo, hi = _step_range(self.model, b)
            level, overdue = (lo + hi) / 2, False
            elapsed = self._elapsed_min(b, now)
            if elapsed is not None and hi > lo:
                start = lo if self._stepped else level  # just stepped in vs. found it mid-step
                level = start + elapsed * (rate if start < TAPER_FROM else rate / TAPER_FACTOR)
                if level > hi - 0.5:
                    level, overdue = hi - 0.5, True
            return Estimate(_minutes_to_full(level, rate), True, self.charge_rate is not None, overdue)
        if b.level is None or b.wired:
            return Estimate(None, False, False)
        rate = self.drain_rate or 100.0 / (TYPICAL_RUNTIME_H[self.model] * 60.0)
        level = float(b.level)
        elapsed = self._elapsed_min(b, now)
        if elapsed is not None:
            lo, hi = _step_range(self.model, b)
            level = max(level - (hi - lo) / 2, level - elapsed * rate)
        return Estimate(level / rate, False, self.drain_rate is not None)
