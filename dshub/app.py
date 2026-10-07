"""Entry point: ``python -m dshub`` (or the packaged DualShockPCHub.exe).

Flags:
  --tray      start hidden in the tray (used by "Start with Windows")
  --system …  run a dshub.system command (the app re-launches itself elevated
              with this flag for admin-only actions such as changing DS3 mode)
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import logging.handlers
import os
import sys

MUTEX_NAME = "Local\\DualShockPCHub.SingleInstance"
WINDOW_TITLE = "DualShock PC Hub"
#: Posted by a second launch; the running copy answers by showing its window (see MainWindow.nativeEvent).
SHOW_MESSAGE = "DualShockPCHub.ShowWindow"


def _setup_logging() -> None:
    from dshub.config import data_dir

    handler = logging.handlers.RotatingFileHandler(data_dir() / "dshub.log", maxBytes=512_000, backupCount=1,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def _already_running() -> bool:
    """Single instance: if we're already open, bring that window up instead."""
    if os.environ.get("DSHUB_ALLOW_MULTI"):  # dev/test only: smoke-test a build next to a running copy
        return False
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW(None, False, MUTEX_NAME)
    if k32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
        return False
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wt.HWND
    user32.FindWindowW.argtypes = (wt.LPCWSTR, wt.LPCWSTR)
    user32.PostMessageW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if hwnd:
        # Ask the running copy to show itself. Forcing its window visible from here (ShowWindow)
        # left Qt believing it was still hidden in the tray, so it came up as an empty window.
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        user32.AllowSetForegroundWindow(pid.value)  # the user just launched us: pass the focus on
        user32.PostMessageW(hwnd, user32.RegisterWindowMessageW(SHOW_MESSAGE), 0, 0)
    return True


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--system" in argv:
        from dshub.system.__main__ import main as system_main

        return system_main([a for a in argv if a != "--system"])

    if _already_running():
        return 0
    _setup_logging()
    # Per-monitor DPI awareness before any window exists.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        pass
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DualShockPCHub")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("DualShock PC Hub")
    app.setQuitOnLastWindowClosed(False)

    from dshub.ui import theme
    from dshub.ui.hub import Hub
    from dshub.ui.window import MainWindow, app_icon

    theme.apply(app)
    app.setWindowIcon(app_icon())
    hub = Hub()
    win = MainWindow(hub)
    hub.start()
    if "--tray" not in argv:
        win.show()
    code = app.exec()
    hub.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
