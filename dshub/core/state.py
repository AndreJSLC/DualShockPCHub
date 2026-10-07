"""Unified, model-agnostic controller state.

Every backend (DS3 / DS4 / DS5, USB or Bluetooth) normalises its raw reports
into a ``ControllerState`` so the UI and the remapping engine never have to
know which pad produced the input.

Conventions
-----------
* Sticks are floats in ``[-1.0, 1.0]``; ``+x`` is right and ``+y`` is *down*
  (same as the raw HID axis, so drawing code can map it straight to screen
  space).
* Triggers and DS3 pressure values are floats in ``[0.0, 1.0]``.
* Touch coordinates are normalised to ``[0.0, 1.0]`` over the touchpad surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Model(str, Enum):
    DS2 = "ds2"  # through a PS2-to-USB adapter
    DS3 = "ds3"
    DS4 = "ds4"
    DS5 = "ds5"
    DS5_EDGE = "ds5edge"

    @property
    def label(self) -> str:
        return {
            Model.DS2: "DualShock 2",
            Model.DS3: "DualShock 3",
            Model.DS4: "DualShock 4",
            Model.DS5: "DualSense",
            Model.DS5_EDGE: "DualSense Edge",
        }[self]

    @property
    def short(self) -> str:
        return {Model.DS2: "DS2", Model.DS3: "DS3", Model.DS4: "DS4", Model.DS5: "DS5", Model.DS5_EDGE: "Edge"}[self]


class Connection(str, Enum):
    USB = "usb"
    BLUETOOTH = "bt"


class Button(str, Enum):
    CROSS = "cross"
    CIRCLE = "circle"
    SQUARE = "square"
    TRIANGLE = "triangle"
    L1 = "l1"
    R1 = "r1"
    L2 = "l2"  # digital click of the trigger (analog value lives in ControllerState.l2)
    R2 = "r2"
    L3 = "l3"
    R3 = "r3"
    SELECT = "select"  # DS3 Select / DS4 Share / DS5 Create
    START = "start"  # DS3 Start / DS4+DS5 Options
    PS = "ps"
    TOUCHPAD = "touchpad"  # touchpad click (DS4/DS5)
    MUTE = "mute"  # DS5 only
    DPAD_UP = "dpad_up"
    DPAD_DOWN = "dpad_down"
    DPAD_LEFT = "dpad_left"
    DPAD_RIGHT = "dpad_right"
    # DualSense Edge extras
    FN_L = "fn_l"
    FN_R = "fn_r"
    PADDLE_L = "paddle_l"
    PADDLE_R = "paddle_r"

    def label_for(self, model: Model) -> str:
        """Human label as printed on the given controller."""
        if self is Button.SELECT:
            return {Model.DS2: "Select", Model.DS3: "Select", Model.DS4: "Share"}.get(model, "Create")
        if self is Button.START:
            return "Start" if model in (Model.DS2, Model.DS3) else "Options"
        return _LABELS[self]


_LABELS = {
    Button.CROSS: "Cross",
    Button.CIRCLE: "Circle",
    Button.SQUARE: "Square",
    Button.TRIANGLE: "Triangle",
    Button.L1: "L1",
    Button.R1: "R1",
    Button.L2: "L2",
    Button.R2: "R2",
    Button.L3: "L3",
    Button.R3: "R3",
    Button.SELECT: "Select",
    Button.START: "Start",
    Button.PS: "PS",
    Button.TOUCHPAD: "Touchpad",
    Button.MUTE: "Mute",
    Button.DPAD_UP: "D-pad Up",
    Button.DPAD_DOWN: "D-pad Down",
    Button.DPAD_LEFT: "D-pad Left",
    Button.DPAD_RIGHT: "D-pad Right",
    Button.FN_L: "Fn Left",
    Button.FN_R: "Fn Right",
    Button.PADDLE_L: "Left Paddle",
    Button.PADDLE_R: "Right Paddle",
}

#: Buttons physically present on each model (what the artwork should draw).
MODEL_BUTTONS: dict[Model, frozenset[Button]] = {
    # The DS2 has no PS button (its ANALOG button never reaches the PC).
    Model.DS2: frozenset(
        b for b in Button if b not in (Button.PS, Button.TOUCHPAD, Button.MUTE, Button.FN_L, Button.FN_R,
                                       Button.PADDLE_L, Button.PADDLE_R)
    ),
    Model.DS3: frozenset(
        b for b in Button if b not in (Button.TOUCHPAD, Button.MUTE, Button.FN_L, Button.FN_R,
                                       Button.PADDLE_L, Button.PADDLE_R)
    ),
    Model.DS4: frozenset(
        b for b in Button if b not in (Button.MUTE, Button.FN_L, Button.FN_R, Button.PADDLE_L,
                                       Button.PADDLE_R)
    ),
    Model.DS5: frozenset(b for b in Button if b not in (Button.FN_L, Button.FN_R, Button.PADDLE_L,
                                                         Button.PADDLE_R)),
    Model.DS5_EDGE: frozenset(Button),
}


class Axis(str, Enum):
    """Analog inputs, used by the remapping engine."""

    LX = "lx"
    LY = "ly"
    RX = "rx"
    RY = "ry"
    L2 = "l2"
    R2 = "r2"


@dataclass(frozen=True, slots=True)
class Touch:
    active: bool = False
    id: int = 0
    x: float = 0.0  # 0..1 left -> right
    y: float = 0.0  # 0..1 top -> bottom


@dataclass(slots=True)
class Battery:
    level: int | None = None  # 0..100, None when unknown
    charging: bool = False
    full: bool = False  # plugged in and fully charged
    wired: bool = False  # running on cable power


@dataclass(slots=True)
class ControllerState:
    buttons: frozenset[Button] = frozenset()
    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    l2: float = 0.0
    r2: float = 0.0
    #: DS3 only: analog pressure for face buttons, D-pad, L1/R1 (0..1).
    pressure: dict[Button, float] = field(default_factory=dict)
    touches: tuple[Touch, Touch] = (Touch(), Touch())
    gyro: tuple[float, float, float] = (0.0, 0.0, 0.0)  # raw-ish units, for display only
    accel: tuple[float, float, float] = (0.0, 0.0, 0.0)
    battery: Battery = field(default_factory=Battery)
    timestamp: float = 0.0  # time.perf_counter() when the report was parsed

    def pressed(self, button: Button) -> bool:
        return button in self.buttons

    def axis(self, axis: Axis) -> float:
        return getattr(self, axis.value)


@dataclass(slots=True)
class ControllerInfo:
    """Static-ish description of a connected pad (shown in the sidebar)."""

    uid: str  # stable id: serial / MAC when known, otherwise the HID path
    model: Model
    connection: Connection
    name: str
    serial: str | None = None  # MAC address for Sony pads
    firmware: str | None = None
    backend: str = "hid"  # "hid" | "dshidmini-xinput" | "xinput" ...
    slot: int = 0  # 1-based display slot ("DS3 1", "DS4 2")
    notes: list[str] = field(default_factory=list)  # warnings shown in the UI

    @property
    def title(self) -> str:
        return f"{self.model.short} {self.slot}"
