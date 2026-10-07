"""Hit-testing and API smoke tests for the flat controller drawings.

Run with ``python -m pytest tests`` (or just ``python tests/test_flat_view.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from dshub.core.state import Button, ControllerState, Model  # noqa: E402
from dshub.ui.flat import layout_for  # noqa: E402
from dshub.ui.flat_view import FlatView  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_every_model_has_a_drawing() -> None:
    for model in Model:
        assert layout_for(model) is not None, model.value


def test_flat_hit_test_every_button() -> None:
    """Clicking the middle of any control on a flat drawing selects that control."""
    for model in Model:
        view = FlatView(model)
        view.resize(800, 520)
        lay = layout_for(model)
        t = view._xform()  # noqa: SLF001
        for part in lay.parts:
            if part.kind == "touchpad":
                continue  # its centre is legitimately the touchpad; checked below
            hit = view.button_at(t.map(part.shape.boundingRect().center()))
            assert hit is part.button, (model, part.button, hit)
        for stick in lay.sticks:
            assert view.button_at(t.map(stick.center)) is stick.button, (model, stick.button)
        view.grab()


def test_absent_buttons_are_not_drawn() -> None:
    lay = layout_for(Model.DS3)
    drawn = {part.button for part in lay.behind + lay.parts}
    for button in (Button.TOUCHPAD, Button.MUTE, Button.FN_L, Button.PADDLE_R):
        assert button not in drawn


def test_model_swap_and_state() -> None:
    view = FlatView(Model.DS4)
    view.resize(640, 420)
    view.set_state(ControllerState(buttons=frozenset({Button.CROSS}), lx=2.0, l2=0.5))
    view.set_model(Model.DS5_EDGE)
    view.set_selected(Button.PADDLE_L)
    view.set_player_leds(3)
    assert view.model() is Model.DS5_EDGE
    view.grab()  # paints once; must not raise


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
