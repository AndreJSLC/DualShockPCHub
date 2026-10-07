"""Stick diagnostics: lost-report counting, full-resolution dedupe, landing spread."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dshub.core.pads import ds4, ds5  # noqa: E402
from dshub.core.pads.base import LossCounter  # noqa: E402


def test_loss_counter_counts_skipped_sequence_numbers_across_wraparound() -> None:
    c = LossCounter()
    for seq in (61, 62, 63, 0, 1, 4, 5):  # 6-bit DS4 counter wraps 63 -> 0; 2 and 3 went missing
        c.see(seq, 64)
    assert c.received == 7 and c.lost == 2


def test_one_step_stick_moves_reach_listeners() -> None:
    for mod in (ds4, ds5):
        data = [0] * 64
        data[1:5] = [128, 128, 128, 128]
        last = (127, 128, 128, 128)  # left stick moved by one step
        sig = mod.signature(data, 1)
        assert mod.unchanged(data, 1, sig, sig, last, tol=1)  # UI: ignore one-step jitter
        assert not mod.unchanged(data, 1, sig, sig, last, tol=0)  # remapping: every step counts


def test_landing_spread_from_flicks() -> None:
    from dshub.ui.stick_test import StickStats

    s, t = StickStats(), 0.0
    for x in (0.04, -0.04, 0.0, 0.04, -0.04):
        s.add(t, 0.0, -0.9)  # flick up...
        s.add(t + 0.05, x, 0.0)  # ...and let go: lands at x
        s.settle(t + 0.1, x, 0.0)  # too early: still settling
        s.settle(t + 0.4, x, 0.0)
        t += 1.0
    mx, my, spread = s.landing()
    assert len(s.landings) == 5 and abs(mx) < 0.01 and abs(spread - 0.04) < 0.005


def test_sweeping_through_the_middle_is_not_rest_jitter() -> None:
    from dshub.ui.stick_test import StickStats

    s, t = StickStats(), 0.0
    for i in range(400):  # flicks: passes through the centre zone at speed, never settles
        x = 0.15 if i % 2 else -0.9
        s.add(t, x, 0.0)
        s.settle(t + 0.01, x, 0.0)
        t += 0.02
    assert s.rest_noise() is None  # nothing counted as rest
    for k in range(80):  # then left alone at a slightly off-centre spot
        s.settle(t + 0.3 + k * 0.033, 0.02, 0.0)
    assert abs(s.rest_offset() - 0.02) < 1e-9 and s.rest_noise() < 1e-9
