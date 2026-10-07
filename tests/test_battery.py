"""Battery time-to-full / time-left estimates."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dshub.core.battery import BatteryTracker  # noqa: E402
from dshub.core.state import Battery, Model  # noqa: E402


def charging(level: int) -> Battery:
    return Battery(level=level, charging=True, wired=True)


def test_typical_estimate_before_any_data() -> None:
    est = BatteryTracker(Model.DS5).estimate(charging(50))
    assert est.to_full and not est.learned and est.minutes and 80 < est.minutes < 160
    assert est.text().startswith("full in ~")


def test_learns_this_controllers_charge_rate() -> None:
    t, now = BatteryTracker(Model.DS4), 0.0
    for level in (40, 50, 60, 70):  # a step every 6 minutes = 10 %/6 min
        t.update(charging(level), now)
        now += 6 * 60
    assert t.charge_rate is not None and abs(t.charge_rate - 10 / 6) < 0.05
    est = t.estimate(charging(70), now=18 * 60)  # right when it stepped up to 70 %
    assert est.learned and not est.text().startswith("full in ~")
    # 10 % fast + 20 % tapered: 6 min + 12 min * 1.6
    assert abs(est.minutes - (6 + 12 * 1.6)) < 0.5


def test_unplugging_restarts_timing_and_learns_drain() -> None:
    t, now = BatteryTracker(Model.DS4), 0.0
    t.update(charging(80), now)
    for level in (80, 70, 60):  # on battery: lose 10 % every 40 min
        t.update(Battery(level=level), now)
        now += 40 * 60
    assert t.drain_rate is not None and abs(t.drain_rate - 10 / 40) < 0.01
    left = t.estimate(Battery(level=60), now=80 * 60)  # right when it dropped to 60 %
    assert not left.to_full and abs(left.minutes - 240) < 1


def test_full_and_unknown_levels_give_no_estimate() -> None:
    t = BatteryTracker(Model.DS3)
    assert t.estimate(Battery(level=100, full=True, wired=True)).text() == ""
    assert t.estimate(Battery(level=None, charging=True, wired=True)).text() == ""  # DS3 while charging


def test_learned_rates_round_trip() -> None:
    t = BatteryTracker(Model.DS5, {"charge_rate": 0.9, "drain_rate": None})
    assert t.estimate(charging(10)).learned
    assert BatteryTracker(Model.DS5, t.learned()).charge_rate == 0.9


def test_stick_recentring_keeps_full_range() -> None:
    from dshub.core.pads.base import _recentre_axis

    assert _recentre_axis(0.06, 0.06) == 0.0  # the drifted rest point becomes the true centre
    assert _recentre_axis(1.0, 0.06) == 1.0 and _recentre_axis(-1.0, 0.06) == -1.0  # full tilt both ways
    assert abs(_recentre_axis(0.53, 0.06) - 0.5) < 1e-9  # halfway is still halfway on the short side


def test_estimate_counts_down_between_level_steps() -> None:
    t = BatteryTracker(Model.DS5, {"charge_rate": 0.5, "drain_rate": None})
    t.update(charging(55), 0.0)
    t.update(charging(65), 600.0)  # stepped into 60-70 % (reported as 65)
    at_step = t.estimate(charging(65), now=600.0).minutes
    later = t.estimate(charging(65), now=600.0 + 10 * 60).minutes  # 10 min later: ~5 % more
    assert abs(at_step - later - 10) < 0.01
    stuck = t.estimate(charging(65), now=600.0 + 60 * 60)  # far longer than the step should take
    assert stuck.text() == "full soon"


def test_flags_a_controller_that_charges_slowly() -> None:
    assert BatteryTracker(Model.DS5, {"charge_rate": 0.16}).slow_charge_factor() > 3.4
    assert BatteryTracker(Model.DS5, {"charge_rate": 0.5}).slow_charge_factor() is None
    assert BatteryTracker(Model.DS5).slow_charge_factor() is None
