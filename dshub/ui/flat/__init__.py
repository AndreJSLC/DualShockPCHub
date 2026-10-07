"""Flat, straight-on controller drawings (the clean emulator-style look).

Each model module builds a ``FlatLayout`` from simple geometry (circles,
rounded rectangles, smooth curves) in its own drawing units; ``FlatView``
renders it and animates it from live input.
"""

from __future__ import annotations

import importlib
from functools import lru_cache

from dshub.core.state import Model
from dshub.ui.flat.layout import FlatLayout

_MODULES = {Model.DS2: "ds2", Model.DS3: "ds3", Model.DS4: "ds4", Model.DS5: "ds5", Model.DS5_EDGE: "ds5edge"}


@lru_cache(maxsize=None)
def layout_for(model: Model) -> FlatLayout | None:
    """The flat drawing for ``model``, or None while that model has no drawing yet."""
    name = _MODULES.get(model)
    if name is None:
        return None
    try:
        module = importlib.import_module(f"dshub.ui.flat.{name}")
    except ModuleNotFoundError as exc:
        if exc.name == f"dshub.ui.flat.{name}":
            return None
        raise
    return module.build()


__all__ = ["FlatLayout", "layout_for"]
