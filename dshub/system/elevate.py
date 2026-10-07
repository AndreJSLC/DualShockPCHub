"""Run a program elevated (UAC prompt) and optionally wait for its exit code.

Every call site must be a direct result of the user clicking something: the UAC
prompt is the consent step, and nothing in DualShock PC Hub elevates on its own.
"""

from __future__ import annotations

import ctypes
import shlex
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

ERROR_CANCELLED = 1223
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1
INFINITE = 0xFFFFFFFF


class ElevationCancelled(RuntimeError):
    """The user dismissed the UAC prompt."""


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def run_elevated(program: str, params: str = "", wait: bool = True, cwd: str | None = None) -> int | None:
    """Start ``program`` via the "runas" verb. Returns the exit code (or None if not waiting)."""
    if sys.platform != "win32":
        raise OSError("elevation is only implemented on Windows")
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = program
    info.lpParameters = params
    info.lpDirectory = cwd
    info.nShow = SW_SHOWNORMAL
    # use_last_error: capture GetLastError right after the call (ERROR_CANCELLED = UAC "No").
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        if err == ERROR_CANCELLED:
            raise ElevationCancelled("UAC prompt was dismissed")
        raise ctypes.WinError(err)
    if not info.hProcess:
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        if not wait:
            return None
        kernel32.WaitForSingleObject(info.hProcess, INFINITE)
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def run_installer(path: Path, wait: bool = True) -> int | None:
    """Launch an .msi/.exe installer elevated with its normal UI (the user clicks through it)."""
    path = Path(path)
    if path.suffix.lower() == ".msi":
        return run_elevated("msiexec.exe", f'/i "{path}"', wait=wait)
    return run_elevated(str(path), "", wait=wait, cwd=str(path.parent))


def run_uninstall_string(command: str, wait: bool = True) -> int | None:
    """Run an Uninstall registry ``UninstallString`` elevated (MSI ``/I`` is turned into ``/X``)."""
    parts = shlex.split(command, posix=False)
    if not parts:
        raise ValueError("empty uninstall command")
    program, args = parts[0].strip('"'), parts[1:]
    if program.lower().endswith("msiexec.exe") or program.lower() == "msiexec":
        args = ["/X" + a[2:] if a.upper().startswith("/I{") else a for a in args]
        args = ["/X" if a.upper() == "/I" else a for a in args]
    return run_elevated(program, subprocess.list2cmdline(args), wait=wait)
