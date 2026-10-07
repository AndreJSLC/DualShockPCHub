"""Frameless top-level window on a Windows 11 acrylic backdrop.

We keep the native window styles (so we still get the DWM drop shadow,
rounded corners, Aero Snap and min/max animations) and simply tell Windows
that the whole window is client area by answering ``WM_NCCALCSIZE``.
``WM_NCHITTEST`` then gives us resize edges and a draggable title strip.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import sys

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from dshub.ui import theme

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
HTCLIENT, HTCAPTION = 1, 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 10, 11, 12, 13, 14, 15, 16, 17

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_TRANSIENTWINDOW = 3  # acrylic
DWMWCP_ROUND = 2


class DWM_BLURBEHIND(ctypes.Structure):
    _fields_ = [("dwFlags", w.DWORD), ("fEnable", w.BOOL), ("hRgnBlur", w.HRGN), ("fTransitionOnMaximized", w.BOOL)]


def _enable_per_pixel_alpha(hwnd: int) -> bool:
    """Make DWM honour our window's alpha channel.

    Without this, every transparent pixel Qt paints reaches the screen as solid
    black and nothing behind the window (backdrop or desktop) can show through.
    An empty blur region turns on alpha without the legacy Vista blur.
    """
    gdi = ctypes.windll.gdi32
    gdi.CreateRectRgn.restype = w.HRGN
    gdi.DeleteObject.argtypes = [w.HGDIOBJ]
    ctypes.windll.dwmapi.DwmEnableBlurBehindWindow.argtypes = [w.HWND, ctypes.c_void_p]
    rgn = gdi.CreateRectRgn(0, 0, -1, -1)
    try:
        bb = DWM_BLURBEHIND(0x1 | 0x2, True, rgn, False)  # DWM_BB_ENABLE | DWM_BB_BLURREGION
        return ctypes.windll.dwmapi.DwmEnableBlurBehindWindow(w.HWND(hwnd), ctypes.byref(bb)) == 0
    finally:
        gdi.DeleteObject(rgn)


class MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", w.RECT * 3), ("lppos", ctypes.c_void_p)]


def _dwm_set(hwnd: int, attr: int, value: int) -> bool:
    v = ctypes.c_int(value)
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(w.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v)) == 0


class AcrylicWindow(QWidget):
    RESIZE_BORDER = 6
    TITLE_HEIGHT = 46

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("root")
        self.backdrop = False
        self.alpha_ok = False
        self.transparency = theme.DEFAULT_TRANSPARENCY
        self.glass_style = theme.DEFAULT_GLASS_STYLE
        self._native_ok = sys.platform == "win32" and QGuiApplication.platformName() == "windows"
        if self._native_ok:
            self._apply_native(int(self.winId()))
        else:  # pragma: no cover - the app is Windows-only, but keep it runnable
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint)

    def _apply_native(self, hwnd: int) -> None:
        user32 = ctypes.windll.user32
        GWL_STYLE = -16
        WS_CAPTION, WS_THICKFRAME, WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00C00000, 0x00040000, 0x00020000, 0x00010000
        user32.GetWindowLongW.restype = ctypes.c_long
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        _dwm_set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
        _dwm_set(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
        margins = MARGINS(-1, -1, -1, -1)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(w.HWND(hwnd), ctypes.byref(margins))
        self.alpha_ok = _enable_per_pixel_alpha(hwnd)
        self.backdrop = _dwm_set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_TRANSIENTWINDOW) and self.alpha_ok
        SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE | NOMOVE | NOZORDER | FRAMECHANGED
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FLAGS)

    # ----------------------------------------------------------------- native
    def nativeEvent(self, event_type, message):  # noqa: N802 - Qt override
        if not self._native_ok or event_type != b"windows_generic_MSG":
            return super().nativeEvent(event_type, message)
        msg = w.MSG.from_address(int(message))
        if msg.message == WM_NCCALCSIZE and msg.wParam:
            if self.isMaximized():
                # A maximised borderless window overhangs the monitor by the
                # frame thickness; pull the client rect back in.
                params = NCCALCSIZE_PARAMS.from_address(msg.lParam)
                user32 = ctypes.windll.user32
                dpi = user32.GetDpiForWindow(msg.hWnd)
                frame = (user32.GetSystemMetricsForDpi(32, dpi) + user32.GetSystemMetricsForDpi(92, dpi))
                r = params.rgrc[0]
                r.left += frame
                r.top += frame
                r.right -= frame
                r.bottom -= frame
            return True, 0
        if msg.message == WM_NCHITTEST:
            return True, self._hit_test(self.mapFromGlobal(QCursor.pos()))
        return super().nativeEvent(event_type, message)

    def _hit_test(self, p: QPoint) -> int:
        x, y, wdt, hgt, b = p.x(), p.y(), self.width(), self.height(), self.RESIZE_BORDER
        if not self.isMaximized():
            left, right, top, bottom = x < b, x >= wdt - b, y < b, y >= hgt - b
            if top and left:
                return HTTOPLEFT
            if top and right:
                return HTTOPRIGHT
            if bottom and left:
                return HTBOTTOMLEFT
            if bottom and right:
                return HTBOTTOMRIGHT
            if left:
                return HTLEFT
            if right:
                return HTRIGHT
            if top:
                return HTTOP
            if bottom:
                return HTBOTTOM
        if y < self.TITLE_HEIGHT:
            child = self.childAt(p)
            while child is not None and child is not self:
                if isinstance(child, QAbstractButton) or child.property("interactive"):
                    return HTCLIENT
                child = child.parentWidget()
            return HTCAPTION
        return HTCLIENT

    def set_transparency(self, value: float) -> None:
        self.transparency = max(0.0, min(1.0, value))
        self.update()

    def set_glass_style(self, style: str) -> None:
        """"frosted": Windows acrylic blur behind the glass; "clear": plain smoked glass."""
        self.glass_style = "clear" if style == "clear" else "frosted"
        if self._native_ok and self.alpha_ok:
            _dwm_set(int(self.winId()), DWMWA_SYSTEMBACKDROP_TYPE,
                     DWMSBT_TRANSIENTWINDOW if self.glass_style == "frosted" else 1)
        self.update()

    # ----------------------------------------------------------------- paint
    def paintEvent(self, _event) -> None:  # noqa: N802
        from dshub.ui.glass import backdrop_pixmap

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        see_through = self.alpha_ok and (self.backdrop or self.glass_style == "clear")
        p.drawPixmap(0, 0, backdrop_pixmap(self.width(), self.height(), self.devicePixelRatioF(),
                                           not see_through, round(self.transparency, 2), self.glass_style))
        if not see_through:  # no DWM corners/shadow: draw our own rim
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
            p.setPen(QPen(theme.HAIRLINE_STRONG, 1))
            p.drawPath(path)
