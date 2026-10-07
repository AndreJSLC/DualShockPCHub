"""Minimal HID report-descriptor parser for generic gamepads.

PS2-to-USB adapters (and other DirectInput pads) describe their input
reports with a HID report descriptor. We only need the *input* fields:
where each button / axis / hat lives in the report, and its logical range.
This walks the descriptor's short items (USB HID 1.11, section 6.2.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

GENERIC_DESKTOP = 0x01
BUTTON_PAGE = 0x09
USAGE_X, USAGE_Y, USAGE_Z, USAGE_RX, USAGE_RY, USAGE_RZ = 0x30, 0x31, 0x32, 0x33, 0x34, 0x35
USAGE_SLIDER, USAGE_DIAL, USAGE_HAT = 0x36, 0x37, 0x39


@dataclass(frozen=True)
class Field:
    report_id: int
    bit_offset: int  # from the first data byte (after the report id, if any)
    bit_size: int
    usage_page: int
    usage: int
    logical_min: int
    logical_max: int

    def read(self, data: bytes | list[int], base: int) -> int:
        """Extract this field from a report whose data starts at byte ``base``."""
        start = base * 8 + self.bit_offset
        value = 0
        for i in range(self.bit_size):
            byte, bit = divmod(start + i, 8)
            if byte < len(data) and data[byte] >> bit & 1:
                value |= 1 << i
        if self.logical_min < 0 and value & (1 << (self.bit_size - 1)):
            value -= 1 << self.bit_size  # sign-extend
        return value

    def normalized(self, data, base: int) -> float:
        """Axis value in -1..1 (centre 0), clamped."""
        lo, hi = self.logical_min, self.logical_max
        if hi <= lo:
            return 0.0
        v = (self.read(data, base) - lo) / (hi - lo)
        return max(-1.0, min(1.0, v * 2.0 - 1.0))


@dataclass
class Layout:
    fields: list[Field] = field(default_factory=list)
    uses_report_ids: bool = False

    def report_ids(self) -> list[int]:
        return sorted({f.report_id for f in self.fields})

    def for_report(self, report_id: int) -> list[Field]:
        return [f for f in self.fields if f.report_id == report_id]

    def buttons(self, report_id: int) -> dict[int, Field]:
        """Button number (1-based, HID usage) -> field."""
        return {f.usage: f for f in self.for_report(report_id) if f.usage_page == BUTTON_PAGE}

    def axis(self, report_id: int, usage: int) -> Field | None:
        return next((f for f in self.for_report(report_id)
                     if f.usage_page == GENERIC_DESKTOP and f.usage == usage), None)


def _signed(value: int, size: int) -> int:
    bits = size * 8
    return value - (1 << bits) if size and value & (1 << (bits - 1)) else value


def parse(descriptor: bytes | list[int]) -> Layout:
    data = bytes(descriptor)
    out = Layout()
    g = {"page": 0, "lmin": 0, "lmax": 0, "size": 0, "count": 0, "rid": 0}
    stack: list[dict] = []
    usages: list[int] = []
    umin = umax = None
    offsets: dict[int, int] = {}  # report id -> next input bit offset
    i = 0
    while i < len(data):
        prefix = data[i]
        if prefix == 0xFE:  # long item: skip
            i += 3 + (data[i + 1] if i + 1 < len(data) else 0)
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        kind = (prefix >> 2) & 0x03  # 0 main, 1 global, 2 local
        tag = prefix >> 4
        raw = int.from_bytes(data[i + 1:i + 1 + size], "little") if size else 0
        i += 1 + size
        if kind == 1:  # global
            if tag == 0x0:
                g["page"] = raw
            elif tag == 0x1:
                g["lmin"] = _signed(raw, size)
            elif tag == 0x2:
                g["lmax"] = _signed(raw, size) if g["lmin"] < 0 else raw
            elif tag == 0x7:
                g["size"] = raw
            elif tag == 0x8:
                g["rid"] = raw
                out.uses_report_ids = True
            elif tag == 0x9:
                g["count"] = raw
            elif tag == 0xA:
                stack.append(dict(g))
            elif tag == 0xB and stack:
                g = stack.pop()
        elif kind == 2:  # local
            if tag == 0x0:
                usages.append(raw)
            elif tag == 0x1:
                umin = raw
            elif tag == 0x2:
                umax = raw
        elif kind == 0:  # main
            if tag == 0x8:  # Input
                constant = bool(raw & 0x01)
                variable = bool(raw & 0x02)
                rid = g["rid"]
                offset = offsets.get(rid, 0)
                expanded = list(usages)
                if umin is not None and umax is not None:
                    expanded += list(range(umin, umax + 1))
                for n in range(g["count"]):
                    if not constant and variable:
                        if expanded:
                            usage = expanded[n] if n < len(expanded) else expanded[-1]
                            page = usage >> 16 if usage > 0xFFFF else g["page"]
                            out.fields.append(Field(rid, offset, g["size"], page, usage & 0xFFFF,
                                                    g["lmin"], g["lmax"]))
                    offset += g["size"]
                offsets[rid] = offset
            if tag in (0x8, 0x9, 0xB, 0xA):  # Input/Output/Feature/Collection reset locals
                usages, umin, umax = [], None, None
    return out
