"""Detect software that fights over PlayStation pads, and broken driver states.

Each finding is a ``Conflict`` with a severity, a plain-language explanation
and a suggested fix. ``action`` lets the UI attach a button, e.g.
``"component:bthps3"`` (open that driver on the Drivers page) or ``"url:..."``.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import _cfgmgr as cm
from . import drivers as drv

Severity = Literal["error", "warning", "info"]

DEVPKEY_Device_CompatibleIds = cm.DevPropKey("a45c254e-df1c-4efd-8020-67d146a850e0", 4)
_SONY_PADS = ("VID_054C&PID_0268", "VID_054C&PID_05C4", "VID_054C&PID_09CC", "VID_054C&PID_0BA0",
              "VID_054C&PID_0CE6", "VID_054C&PID_0DF2", "VID_054C&PID_042F")


@dataclass(slots=True)
class Conflict:
    id: str
    severity: Severity
    title: str
    detail: str
    fix: str
    action: str | None = None


# ----------------------------------------------------------------- processes
class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


def running_processes() -> set[str]:
    """Lower-case executable names of all running processes."""
    if sys.platform != "win32":
        return set()
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snap in (0, wintypes.HANDLE(-1).value):
        return set()
    names: set[str] = set()
    entry = _ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return names


_REMAPPERS = {
    "ds4windows.exe": "DS4Windows",
    "dsx.exe": "DSX (DualSenseX)",
    "dualsensex.exe": "DualSenseX",
    "inputmapper.exe": "InputMapper",
    "rewasd.exe": "reWASD",
    "rewasdengine.exe": "reWASD",
    "scpservice.exe": "ScpToolkit service",
    "scpmonitor.exe": "ScpToolkit monitor",
}


# --------------------------------------------------------------------- scan
def scan(components: list[drv.Component] | None = None) -> list[Conflict]:
    """All current findings, most severe first. Local only; takes well under a second."""
    comps = {c.id: c for c in (components or drv.scan())}
    procs = running_processes()
    found: list[Conflict] = []

    # Broken / outdated drivers --------------------------------------------
    bt = comps.get("bthps3")
    if bt and bt.status == "broken":
        found.append(Conflict(
            "bthps3-broken", "error", "DS3 Bluetooth is broken (BthPS3)",
            " ".join(bt.problems),
            "Uninstall BthPS3, reboot, install the latest BthPS3, reboot again.",
            "component:bthps3"))
    ds = comps.get("dshidmini")
    if ds and ds.installed and drv.version_tuple(ds.installed_version) < (3,):
        found.append(Conflict(
            "dshidmini-old", "warning", "DsHidMini is very old",
            f"Version {ds.installed_version} is from 2021. Version 3 is stable and fixes many "
            "Bluetooth, battery and pairing issues.",
            "Install DsHidMini 3.x over the old one (no uninstall needed).", "component:dshidmini"))

    # Pads not on the expected driver ------------------------------------------
    for node in cm.find_devices("VID_054C&PID_0268"):
        if node.instance_id.upper().startswith("USB\\") and \
                not (node.driver_provider or "").startswith("Nefarius"):
            found.append(Conflict(
                "ds3-driver", "error", "DualShock 3 is not using DsHidMini",
                f"It is bound to '{node.service or 'no driver'}' "
                f"({node.driver_provider or 'unknown provider'}), so Windows cannot read it properly.",
                "Install DsHidMini; it replaces generic/ScpToolkit drivers automatically.",
                "component:dshidmini"))

    # ScpToolkit ---------------------------------------------------------------
    found.extend(_scp_toolkit())
    found.extend(_hijacked_bluetooth_radio())

    # Remappers that grab pads -------------------------------------------------
    for exe, name in _REMAPPERS.items():
        if exe in procs:
            found.append(Conflict(
                f"running:{exe}", "warning", f"{name} is running",
                f"{name} may open your controllers exclusively (the hub then sees no input) and "
                "games can receive input twice if both apps emulate a controller.",
                f"Close {name} while using DualShock PC Hub, or disable it for the pads you "
                "configure here."))
    if "steam.exe" in procs:
        found.append(Conflict(
            "steam-input", "info", "Steam is running",
            "Steam Input can also remap PlayStation pads inside Steam games. With DsHidMini in "
            "XInput mode and Microsoft GameInput installed, Steam may show one DS3 twice.",
            "If a game sees two controllers, turn off Steam Input for that game, or use SXS mode "
            "for the DS3."))

    # HidHide ------------------------------------------------------------------
    hh = comps.get("hidhide")
    if hh and hh.installed:
        found.append(Conflict(
            "hidhide", "info", "HidHide is installed",
            "If HidHide hides a controller, only allow-listed apps can see it.",
            "Add DualShock PC Hub to HidHide's allowed applications if a pad does not show up "
            "here.", "url:https://docs.nefarius.at/projects/HidHide/"))

    # VirtualPad (DSX's commercial Nefarius driver) -------------------------------
    for node in cm.find_devices("NEFARIUS\\VIRTUALPAD"):
        if "EXPIRED" in node.name.upper():
            found.append(Conflict(
                "virtualpad-expired", "info", "Nefarius VirtualPad license expired",
                "DSX (Paliverse) installed this emulation driver. It does not affect DualShock "
                "PC Hub, DsHidMini or BthPS3, and nothing here needs it.",
                "If you no longer use DSX, uninstall \"Nefarius VirtualPad Driver Runtime\" in "
                "Settings > Apps (and DSX itself from Steam). If you still use DSX, reinstalling "
                "DSX renews the license."))

    rank = {"error": 0, "warning": 1, "info": 2}
    return sorted(found, key=lambda c: rank[c.severity])


def _scp_toolkit() -> list[Conflict]:
    services = [s for s in ("ScpVBus", "Ds3Service", "ScpDsxService", "BthDongle", "Ds3Controller",
                            "Ds4Controller") if drv.service_exists(s)]
    folder = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / \
        "Nefarius Software Solutions" / "ScpToolkit"
    winusb_pads = [n for n in cm.find_devices(*_SONY_PADS)
                   if (n.service or "").lower() in ("winusb", "libusbk", "libusb0")]
    if services or winusb_pads:
        return [Conflict(
            "scptoolkit", "error", "ScpToolkit drivers are active",
            "ScpToolkit (abandoned since 2016) replaces controller and Bluetooth drivers and breaks "
            "DsHidMini/BthPS3. Found: " + ", ".join(services + [n.name for n in winusb_pads]) + ".",
            "Uninstall ScpToolkit with its 'Clean Wipe' tool, reboot, then reinstall DsHidMini and "
            "BthPS3.")]
    if folder.exists():
        return [Conflict(
            "scptoolkit-leftovers", "info", "ScpToolkit leftovers found",
            f"{folder} still exists, but no ScpToolkit drivers or services are active.",
            "Safe to delete that folder.")]
    return []


def _hijacked_bluetooth_radio() -> list[Conflict]:
    """A Bluetooth dongle bound to WinUSB/libusb (ScpToolkit/Zadig style) disables Windows Bluetooth."""
    out = []
    for iid in cm.device_ids(present_only=True):
        svc = (cm.get_property(iid, cm.DEVPKEY_Device_Service) or "").lower()
        if svc not in ("winusb", "libusbk", "libusb0"):
            continue
        compat = " ".join(cm.get_property(iid, DEVPKEY_Device_CompatibleIds) or ()).upper()
        if "CLASS_E0&SUBCLASS_01&PROT_01" in compat:
            node = cm.describe(iid)
            out.append(Conflict(
                "radio-hijacked", "error", "Bluetooth adapter is on a generic USB driver",
                f"{node.name} uses {svc}, so Windows Bluetooth (and BthPS3) cannot use it.",
                "In Device Manager, update its driver back to the vendor/Microsoft Bluetooth driver "
                "(or uninstall the device and tick 'delete driver'), then reboot."))
    return out


if __name__ == "__main__":  # python -m dshub.system.conflicts
    for c in scan():
        print(f"[{c.severity:7}] {c.title}\n          {c.detail}\n          fix: {c.fix}")
