"""Keyboard and mouse injection via SendInput (scan codes, so games see it)."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w

_u32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x8
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_WHEEL = 0x0800
MOUSE_BUTTON_FLAGS = {
    "left": (0x0002, 0x0004, 0),
    "right": (0x0008, 0x0010, 0),
    "middle": (0x0020, 0x0040, 0),
    "x1": (0x0080, 0x0100, 1),
    "x2": (0x0080, 0x0100, 2),
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _U)]


_u32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
_u32.MapVirtualKeyW.argtypes = [w.UINT, w.UINT]

# Keys that need the E0 "extended" prefix when sent as scan codes.
_EXTENDED_VK = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x6F, 0xA3, 0xA5}


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    _u32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def key(vk: int, down: bool) -> None:
    # Media/volume keys only work as virtual keys (their bare scan codes
    # collide with letters), everything else goes out as a scan code.
    scan = 0 if 0xA6 <= vk <= 0xB7 else _u32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
    flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
    if vk in _EXTENDED_VK:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(0 if scan else vk, scan, flags if scan else (0 if down else KEYEVENTF_KEYUP), 0, 0)
    _send(inp)


def mouse_button(name: str, down: bool) -> None:
    if name in ("wheel_up", "wheel_down"):
        if down:
            inp = INPUT(type=INPUT_MOUSE)
            inp.mi = MOUSEINPUT(0, 0, w.DWORD(120 if name == "wheel_up" else -120).value, MOUSEEVENTF_WHEEL, 0, 0)
            _send(inp)
        return
    dn, up, data = MOUSE_BUTTON_FLAGS[name]
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(0, 0, data, dn if down else up, 0, 0)
    _send(inp)


def mouse_move(dx: int, dy: int) -> None:
    if dx or dy:
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, 0)
        _send(inp)


# Friendly key names shown in the UI -> virtual-key codes.
KEYS: dict[str, int] = {
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    **{f"F{n}": 0x6F + n for n in range(1, 13)},
    "Space": 0x20, "Enter": 0x0D, "Esc": 0x1B, "Tab": 0x09, "Backspace": 0x08,
    "Shift": 0xA0, "Ctrl": 0xA2, "Alt": 0xA4, "Right Shift": 0xA1, "Right Ctrl": 0xA3, "Right Alt": 0xA5,
    "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
    "Insert": 0x2D, "Delete": 0x2E, "Home": 0x24, "End": 0x23, "Page Up": 0x21, "Page Down": 0x22,
    "Caps Lock": 0x14, "Win": 0x5B, "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA,
    "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
    "Volume Up": 0xAF, "Volume Down": 0xAE, "Mute": 0xAD, "Play/Pause": 0xB3, "Next Track": 0xB0,
    "Prev Track": 0xB1,
}
KEY_NAMES = {v: k for k, v in KEYS.items()}
