"""Remap profiles: what each physical input drives, stored as JSON."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dshub.config import profiles_dir
from dshub.core.state import Button

log = logging.getLogger(__name__)

# Virtual Xbox 360 outputs (value = XUSB button bit; triggers are special).
PAD_TARGETS: dict[str, int] = {
    "dpad_up": 0x0001, "dpad_down": 0x0002, "dpad_left": 0x0004, "dpad_right": 0x0008,
    "start": 0x0010, "back": 0x0020, "ls": 0x0040, "rs": 0x0080, "lb": 0x0100, "rb": 0x0200,
    "guide": 0x0400, "a": 0x1000, "b": 0x2000, "x": 0x4000, "y": 0x8000,
    "lt": 0, "rt": 0,
}
PAD_TARGET_LABELS = {
    "a": "Xbox A", "b": "Xbox B", "x": "Xbox X", "y": "Xbox Y", "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT",
    "ls": "Left stick click", "rs": "Right stick click", "back": "Back / View", "start": "Start / Menu",
    "guide": "Guide", "dpad_up": "D-pad Up", "dpad_down": "D-pad Down", "dpad_left": "D-pad Left",
    "dpad_right": "D-pad Right",
}
MOUSE_TARGETS = {"left": "Left click", "right": "Right click", "middle": "Middle click", "x1": "Mouse back",
                 "x2": "Mouse forward", "wheel_up": "Scroll up", "wheel_down": "Scroll down"}

DEFAULT_BUTTONS: dict[Button, str] = {
    Button.CROSS: "a", Button.CIRCLE: "b", Button.SQUARE: "x", Button.TRIANGLE: "y",
    Button.L1: "lb", Button.R1: "rb", Button.L3: "ls", Button.R3: "rs",
    Button.SELECT: "back", Button.START: "start", Button.PS: "guide", Button.TOUCHPAD: "back",
    Button.DPAD_UP: "dpad_up", Button.DPAD_DOWN: "dpad_down", Button.DPAD_LEFT: "dpad_left",
    Button.DPAD_RIGHT: "dpad_right",
}


@dataclass
class Binding:
    """What a physical button does.

    kind: "pad" (virtual Xbox output), "key", "mouse" or "none".
    """

    kind: str = "pad"
    target: str = ""

    def label(self) -> str:
        if self.kind == "pad":
            return PAD_TARGET_LABELS.get(self.target, self.target)
        if self.kind == "key":
            return f"Key {self.target}"
        if self.kind == "mouse":
            return MOUSE_TARGETS.get(self.target, self.target)
        return "Disabled"


@dataclass
class StickConfig:
    mode: str = "left"  # "left" | "right" (virtual stick) | "mouse" | "wasd" | "arrows" | "none"
    deadzone: float = 0.08
    anti_deadzone: float = 0.0
    sensitivity: float = 1.0  # also mouse speed multiplier
    invert_y: bool = False


@dataclass
class TriggerConfig:
    target: str = "lt"  # "lt" | "rt" | "none"
    deadzone: float = 0.02


@dataclass
class Profile:
    name: str = "Default"
    buttons: dict[str, Binding] = field(default_factory=lambda: {
        b.value: Binding("pad", t) for b, t in DEFAULT_BUTTONS.items()})
    left_stick: StickConfig = field(default_factory=lambda: StickConfig(mode="left"))
    right_stick: StickConfig = field(default_factory=lambda: StickConfig(mode="right"))
    l2: TriggerConfig = field(default_factory=lambda: TriggerConfig("lt"))
    r2: TriggerConfig = field(default_factory=lambda: TriggerConfig("rt"))
    rumble: float = 1.0  # strength multiplier for game rumble forwarded to the pad

    def binding(self, button: Button) -> Binding:
        return self.buttons.get(button.value) or Binding("none", "")

    # ---------------------------------------------------------- persistence
    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> Profile:
        p = cls(name=data.get("name", "Profile"))
        if "buttons" in data:
            p.buttons = {k: Binding(**v) for k, v in data["buttons"].items()}
        for attr, typ in (("left_stick", StickConfig), ("right_stick", StickConfig),
                          ("l2", TriggerConfig), ("r2", TriggerConfig)):
            if attr in data:
                setattr(p, attr, typ(**data[attr]))
        p.rumble = float(data.get("rumble", 1.0))
        return p


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "profile"


class ProfileStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or profiles_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def names(self) -> list[str]:
        names = []
        for f in sorted(self.root.glob("*.json")):
            try:
                names.append(json.loads(f.read_text("utf-8")).get("name", f.stem))
            except (OSError, ValueError):
                log.warning("skipping unreadable profile %s", f)
        if "Default" not in names:
            names.insert(0, "Default")
        return names

    def load(self, name: str) -> Profile:
        path = self.root / f"{_slug(name)}.json"
        if path.exists():
            try:
                return Profile.from_json(json.loads(path.read_text("utf-8")))
            except (OSError, ValueError, TypeError):
                log.exception("bad profile %s, using defaults", path)
        return Profile(name=name)

    def save(self, profile: Profile) -> None:
        path = self.root / f"{_slug(profile.name)}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(profile.to_json(), indent=2), "utf-8")
        tmp.replace(path)

    def delete(self, name: str) -> None:
        (self.root / f"{_slug(name)}.json").unlink(missing_ok=True)
