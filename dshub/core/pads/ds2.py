"""DualShock 2 through a PS2-to-USB adapter.

The adapters are generic HID gamepads, so we read each one's report
descriptor to find its buttons/axes and then translate the adapter's button
numbering to PS2 buttons with a per-adapter mapping (``ADAPTERS``), falling
back to the most common layout. Two-port adapters send each pad under its own
report id; each becomes its own controller ("DS2 1", "DS2 2").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dshub.core import hid_descriptor as H
from dshub.core.pads.base import Capabilities, hat_to_dpad
from dshub.core.pads.hidpad import HidPad
from dshub.core.state import Battery, Button, ControllerInfo, ControllerState

PS2_NAMES = {
    "triangle": Button.TRIANGLE, "circle": Button.CIRCLE, "cross": Button.CROSS, "square": Button.SQUARE,
    "l1": Button.L1, "r1": Button.R1, "l2": Button.L2, "r2": Button.R2, "select": Button.SELECT,
    "start": Button.START, "l3": Button.L3, "r3": Button.R3, "up": Button.DPAD_UP, "down": Button.DPAD_DOWN,
    "left": Button.DPAD_LEFT, "right": Button.DPAD_RIGHT,
}
AXES = {"x": H.USAGE_X, "y": H.USAGE_Y, "z": H.USAGE_Z, "rx": H.USAGE_RX, "ry": H.USAGE_RY, "rz": H.USAGE_RZ,
        "slider": H.USAGE_SLIDER, "dial": H.USAGE_DIAL}


@dataclass(frozen=True)
class Mapping:
    """How an adapter numbers things. Button numbers are HID usages (1-based)."""

    buttons: dict[int, str]
    lx: str = "x"
    ly: str = "y"
    rx: str = "z"
    ry: str = "rz"
    invert: tuple[str, ...] = ()  # axes reported upside down
    dpad_hat: bool = True  # D-pad as a hat switch (else as buttons in ``buttons``)


_FACE = {1: "triangle", 2: "circle", 3: "cross", 4: "square", 11: "l3", 12: "r3"}
_DPAD_BUTTONS = {13: "up", 14: "right", 15: "down", 16: "left"}

#: Family P - PCS / "Twin USB" (the most common layout; also the default for unknown adapters).
DEFAULT = Mapping(buttons={**_FACE, 5: "l2", 6: "r2", 7: "l1", 8: "r1", 9: "select", 10: "start"},
                  rx="rz", ry="z")
FAMILY_P_DPAD_BUTTONS = Mapping(buttons={**DEFAULT.buttons, **_DPAD_BUTTONS}, rx="rz", ry="z", dpad_hat=False)
#: Family W - WiseGroup / Mayflash / SmartJoy: Start and Select swapped, right stick on Z (x) / Rz (y).
FAMILY_W = Mapping(buttons={**_FACE, 5: "l2", 6: "r2", 7: "l1", 8: "r1", 9: "start", 10: "select"},
                   rx="z", ry="rz")
FAMILY_W_DPAD_BUTTONS = Mapping(buttons={**FAMILY_W.buttons, **_DPAD_BUTTONS}, rx="z", ry="rz", dpad_hat=False)
#: Family S - ShanWan / GreenAsia "2In1": L1/R1 before L2/R2.
FAMILY_S = Mapping(buttons={**_FACE, 5: "l1", 6: "r1", 7: "l2", 8: "r2", 9: "select", 10: "start"},
                   rx="rz", ry="z")


@dataclass(frozen=True)
class Adapter:
    name: str
    vid: int
    pid: int
    mapping: Mapping = DEFAULT
    #: When the VID/PID is also used by ordinary gamepads, the product string must contain one of these.
    product_hints: tuple[str, ...] = ()
    pads: int = 1  # pads per HID device (two-port adapters use report ids 1 and 2)


#: Known adapters (docs/RESEARCH-ds2-adapters.md). Two-port boxes show up on Windows as one HID
#: collection per port, each with its own report id, so ``pads`` is informational.
ADAPTERS: list[Adapter] = [
    Adapter("Twin USB", 0x0810, 0x0001, DEFAULT, ("twin usb", "dual psx"), pads=2),
    Adapter("PCS dual", 0x0810, 0x0002, DEFAULT, pads=2),
    Adapter("PSX to PC", 0x0810, 0x0003, DEFAULT, ("playstation", "psx", "ps2")),
    Adapter("EMS USB2", 0x0B43, 0x0003, FAMILY_P_DPAD_BUTTONS, pads=2),
    Adapter("GreenAsia 2In1", 0x0E8F, 0x0003, FAMILY_S, ("2in1", "greenasia", "gasia")),
    Adapter("Super Dual Box", 0x0925, 0x8866, FAMILY_W, pads=2),
    Adapter("Quad Joypad", 0x0925, 0x8800, FAMILY_W, pads=4),
    Adapter("SmartJoy PLUS", 0x0925, 0x0005, FAMILY_W),
    Adapter("Super Joy Box 3", 0x0925, 0x8888, FAMILY_W),
    Adapter("Super Joy Box 3 Pro", 0x6666, 0x8801, FAMILY_W),
    Adapter("Super Dual Box Pro", 0x6666, 0x8802, FAMILY_W_DPAD_BUTTONS, pads=2),
    Adapter("SmartJoy Dual PLUS", 0x6677, 0x8802, FAMILY_W_DPAD_BUTTONS, pads=2),
    Adapter("Super Joy Box 5 Pro", 0x6666, 0x8804, FAMILY_W_DPAD_BUTTONS, pads=4),
    # ShanWan 2563:0575 is also used by plenty of ordinary PC/PS3-style pads: only claim it when the
    # product string says it's a PS adapter.
    Adapter("ShanWan PS adapter", 0x2563, 0x0575, FAMILY_S, ("ps2", "ps1", "playstation")),
]

#: Product strings that identify PS2 adapters we don't have an exact entry for.
NAME_HINTS = ("twin usb", "ps2", "playstation 2", "psx", "smartjoy", "super dual box", "dual box")


def find_adapter(vid: int, pid: int, product: str) -> Adapter | None:
    product_l = (product or "").lower()
    for a in ADAPTERS:
        if a.vid == vid and a.pid == pid:
            if not a.product_hints or any(h in product_l for h in a.product_hints):
                return a
            return None  # a known ID shared with ordinary gamepads, and this isn't the adapter
    if any(h in product_l for h in NAME_HINTS):
        return Adapter(product or "PS2 adapter", vid, pid)
    return None


@dataclass
class _Bound:
    """Descriptor fields resolved for one pad (one report id)."""

    buttons: dict[Button, H.Field] = field(default_factory=dict)
    sticks: dict[str, H.Field | None] = field(default_factory=dict)
    hat: H.Field | None = None


class DualShock2(HidPad):
    caps = Capabilities()  # wired, no battery; rumble/pressure vary by adapter and aren't used yet

    def __init__(self, info: ControllerInfo, path: bytes, adapter: Adapter, report_id: int | None) -> None:
        super().__init__(info, path)
        self.key = f"{path.decode(errors='ignore')}#{report_id or 0}"
        self.adapter, self.report_id = adapter, report_id
        self._layout: H.Layout | None = None
        self._bound = _Bound()

    def _handshake(self) -> None:
        desc = self.dev.get_report_descriptor()
        self._layout = H.parse(desc)
        rid = self.report_id or 0
        m = self.adapter.mapping
        buttons = self._layout.buttons(rid)
        self._bound.buttons = {PS2_NAMES[name]: buttons[n] for n, name in m.buttons.items() if n in buttons}
        self._bound.sticks = {k: self._layout.axis(rid, AXES[getattr(m, k)]) for k in ("lx", "ly", "rx", "ry")}
        self._bound.hat = self._layout.axis(rid, H.USAGE_HAT) if m.dpad_hat else None
        if m.dpad_hat and self._bound.hat is None and all(n in buttons for n in _DPAD_BUTTONS):
            # no hat switch after all: these adapters send the D-pad as buttons 13-16
            for n, name in _DPAD_BUTTONS.items():
                self._bound.buttons[PS2_NAMES[name]] = buttons[n]

    def _poll(self) -> ControllerState | None:
        data = self._read()
        if data is None or self._layout is None:
            return None
        base = 0
        if self._layout.uses_report_ids:
            if data[0] != (self.report_id or data[0]):
                return None  # the other port's report
            base = 1
        b = self._bound
        pressed = {btn for btn, f in b.buttons.items() if f.read(data, base)}
        if b.hat is not None:
            hat = b.hat.read(data, base) - b.hat.logical_min
            if 0 <= hat <= 7:
                up, right, down, left = hat_to_dpad(hat)
                pressed |= {n for flag, n in ((up, Button.DPAD_UP), (right, Button.DPAD_RIGHT),
                                              (down, Button.DPAD_DOWN), (left, Button.DPAD_LEFT)) if flag}
        inv = self.adapter.mapping.invert

        def axis(key: str) -> float:
            f = b.sticks.get(key)
            if f is None:
                return 0.0
            v = f.normalized(data, base)
            v = -v if key in inv else v
            return 0.0 if abs(v) < 0.01 else v

        l2, r2 = (1.0 if Button.L2 in pressed else 0.0), (1.0 if Button.R2 in pressed else 0.0)
        return ControllerState(buttons=frozenset(pressed), lx=axis("lx"), ly=axis("ly"), rx=axis("rx"),
                               ry=axis("ry"), l2=l2, r2=r2, battery=Battery(wired=True))
