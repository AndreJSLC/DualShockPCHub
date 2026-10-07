"""DualShock 3 status and Bluetooth readiness, read from DsHidMini's device properties.

Under DsHidMini a user-mode app cannot send the DS3's 0xF4/0xF5 feature reports
(the driver owns the USB device), but the driver publishes everything we need
as PnP properties: the pad's MAC, the host address stored in the pad, the last
pairing result, the battery byte and (v2) the HID mode. Pairing itself is done
by DsHidMini whenever the pad is plugged in over USB (``DevicePairingMode``
``Auto`` in v3), so "pairing" for the user is: plug in once, unplug, press PS.

Property keys come from DsHidMini's ``dshmguid.h`` (v2.2.282 and v3).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dshub.core.state import Battery

from . import _cfgmgr as cm
from . import bluetooth, drivers, elevate

_DSHM_RO = "3fecf510-cc94-4fbe-8839-738201f84d59"
_DSHM_RW_V2 = "6d293077-c3d6-4062-9597-be4389404c02"

KEY_HOST_ADDRESS = cm.DevPropKey("a92f26ca-eda7-4b1d-9db2-27b68aa5a2eb", 1)  # UINT64, stored in pad
KEY_BATTERY = cm.DevPropKey(_DSHM_RO, 2)  # BYTE, raw DS3 battery status
KEY_LAST_PAIRING_STATUS = cm.DevPropKey(_DSHM_RO, 3)  # NTSTATUS (v2)
KEY_LAST_HOST_REQUEST_STATUS = cm.DevPropKey(_DSHM_RO, 5)  # NTSTATUS (v3)
KEY_HID_MODE_V2 = cm.DevPropKey(_DSHM_RW_V2, 2)  # BYTE (v2 only; v3 uses the JSON file)

HID_MODES = {1: "SDF", 2: "GPJ", 3: "SXS", 4: "DS4Windows", 5: "XInput", 6: "CGP"}
HID_MODE_HELP = {
    "SDF": "Single DirectInput gamepad with pressure axes (good for emulators).",
    "GPJ": "Gamepad + joystick pair; pressure on the second device.",
    "SXS": "Sony SIXAXIS layout, Steam's native DS3 mode. Exposes pressure, battery and motion.",
    "DS4Windows": "Looks like a DS4 to DS4Windows (vendor-defined device).",
    "XInput": "Appears as an Xbox 360 controller to games (default). No pressure or motion.",
    "CGP": "Common gamepad layout (v3.15+).",
}

#: DS3 battery byte -> (percent, charging, full); Linux maps 0..5 to 0/1/25/50/75/100.
_BATTERY_LEVELS = {0x00: 0, 0x01: 1, 0x02: 25, 0x03: 50, 0x04: 75, 0x05: 100}
DS3_IDS = ("VID_054C&PID_0268", "VID_054C&PID_042F")  # DualShock 3 / Navigation


def battery_from_status(raw: int | None, wired: bool) -> Battery:
    if raw is None:
        return Battery(level=None, wired=wired)
    if raw == 0xEE:
        return Battery(level=None, charging=True, wired=True)
    if raw == 0xEF:
        return Battery(level=100, full=True, wired=True)
    return Battery(level=_BATTERY_LEVELS.get(raw), wired=wired)


@dataclass(slots=True)
class Ds3Device:
    instance_id: str
    connection: str  # "usb" | "bt"
    name: str
    mac: str | None  # the pad's own Bluetooth address
    paired_host: str | None  # host address stored inside the pad
    battery_raw: int | None
    battery: Battery
    hid_mode: str | None
    driver: str | None
    driver_version: str | None
    last_pairing_ok: bool | None
    is_navigation: bool = False

    @property
    def paired_to_this_pc(self) -> bool | None:
        host = bluetooth.host_address()
        if not host or not self.paired_host:
            return None
        return host.upper() == self.paired_host.upper()


def _hid_mode(instance_id: str, mac: str | None) -> str | None:
    if mac:
        mode = config_hid_mode(mac)
        if mode:
            return mode
    raw = cm.get_property(instance_id, KEY_HID_MODE_V2)
    return HID_MODES.get(raw) if isinstance(raw, int) else None


def devices() -> list[Ds3Device]:
    """Every DS3/Navigation pad currently connected through DsHidMini (USB or Bluetooth)."""
    out: list[Ds3Device] = []
    for node in cm.find_devices(*DS3_IDS):
        iid = node.instance_id.upper()
        if iid.startswith("USB\\"):
            connection = "usb"
        elif iid.startswith("BTHPS3BUS\\"):
            connection = "bt"
        else:
            continue  # HID child collections etc.
        mac = bluetooth.format_mac(cm.get_property(node.instance_id, cm.DEVPKEY_Bluetooth_DeviceAddress))
        host_raw = cm.get_property(node.instance_id, KEY_HOST_ADDRESS)
        status = cm.get_property(node.instance_id, KEY_LAST_HOST_REQUEST_STATUS)
        if status is None:
            status = cm.get_property(node.instance_id, KEY_LAST_PAIRING_STATUS)
        raw_batt = cm.get_property(node.instance_id, KEY_BATTERY)
        driver = "DsHidMini" if (node.driver_provider or "").startswith("Nefarius") else node.service
        out.append(Ds3Device(
            instance_id=node.instance_id,
            connection=connection,
            name=node.name,
            mac=mac,
            paired_host=bluetooth.format_mac(host_raw) if isinstance(host_raw, int) and host_raw else None,
            battery_raw=raw_batt if isinstance(raw_batt, int) else None,
            battery=battery_from_status(raw_batt if isinstance(raw_batt, int) else None,
                                        wired=connection == "usb"),
            hid_mode=_hid_mode(node.instance_id, mac),
            driver=driver,
            driver_version=node.driver_version,
            last_pairing_ok=None if status is None else status == 0,
            is_navigation="PID_042F" in iid,
        ))
    return out


# ----------------------------------------------------------- v3 config file
def config_path() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "DsHidMini" / "DsHidMini.json"


def read_config() -> dict | None:
    try:
        return json.loads(config_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _mac_key(mac: str) -> str:
    return "".join(c for c in mac if c.isalnum()).upper()


def config_hid_mode(mac: str) -> str | None:
    """HID mode for a pad from the v3 JSON config (device override, else global default)."""
    cfg = read_config()
    if not cfg:
        return None
    dev = (cfg.get("Devices") or {}).get(_mac_key(mac)) or {}
    return dev.get("HidDeviceMode") or (cfg.get("Global") or {}).get("HidDeviceMode")


def write_hid_mode(mac: str, mode: str) -> None:
    """Create or update ``DsHidMini.json`` with a per-pad HID mode, keeping every other setting.

    DsHidMini v3 runs on built-in defaults until this file exists (the
    ControlApp creates it on first save). Standard users may create files in
    ``%ProgramData%\\DsHidMini``; a file created by an elevated process needs
    admin to change (PermissionError).
    """
    if mode not in HID_MODES.values():
        raise ValueError(f"unknown HID mode {mode!r}")
    path = config_path()
    if not path.parent.is_dir():
        raise FileNotFoundError("DsHidMini 3.x is not installed (no %ProgramData%\\DsHidMini).")
    cfg = read_config()
    if cfg is None:
        if path.exists():
            raise RuntimeError(f"{path} is not valid JSON; refusing to overwrite it.")
        cfg = {"Global": {"HidDeviceMode": "XInput"}, "Devices": {}}  # XInput = the driver default
    cfg.setdefault("Devices", {}).setdefault(_mac_key(mac), {})["HidDeviceMode"] = mode
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def restart_device(instance_id: str) -> int:
    """Restart a device so DsHidMini picks up a new HID mode (needs admin)."""
    done = subprocess.run(["pnputil", "/restart-device", instance_id], capture_output=True, timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return done.returncode


def set_hid_mode(mac: str, mode: str, instance_id: str | None = None) -> bool:
    """Switch a DS3 to another DsHidMini HID mode. User-initiated only.

    Writes the config (without admin when allowed), then restarts the pad if
    ``instance_id`` is given, which needs admin: at most one UAC prompt in
    total. Returns True when the new mode is active now, False when it is saved
    and applies the next time the pad reconnects (e.g. the restart prompt was
    declined). Raises ``elevate.ElevationCancelled`` only if saving itself needed
    admin and was declined.
    """
    if elevate.is_admin():
        write_hid_mode(mac, mode)
        return bool(instance_id) and restart_device(instance_id) == 0
    try:
        write_hid_mode(mac, mode)
    except PermissionError:
        args = ["set-ds3-mode", _mac_key(mac), mode] + ([instance_id] if instance_id else [])
        code = elevate.run_elevated(*system_cli(args))  # one prompt does both steps
        if code:
            raise RuntimeError(f"The elevated helper failed (exit code {code}).")
        return bool(instance_id)
    if not instance_id:
        return False
    try:
        return elevate.run_elevated(*system_cli(["restart-device", instance_id])) == 0
    except elevate.ElevationCancelled:
        return False  # saved; applies when the pad reconnects


def system_cli(args: list[str]) -> tuple[str, str]:
    """(program, params) that runs ``python -m dshub.system <args>`` (or the frozen app with --system)."""
    if getattr(sys, "frozen", False):
        return sys.executable, subprocess.list2cmdline(["--system", *args])
    return sys.executable, subprocess.list2cmdline(["-m", "dshub.system", *args])


# ------------------------------------------------------- Bluetooth readiness
@dataclass(slots=True)
class Check:
    id: str
    title: str
    ok: bool | None  # None = cannot tell yet / not applicable
    detail: str
    fix: str | None = None
    action: str | None = None  # e.g. "component:bthps3" for the UI to wire a button
    extra: dict = field(default_factory=dict)


def bluetooth_readiness() -> list[Check]:
    """Ordered checklist for getting a DS3 working over Bluetooth on this PC."""
    checks: list[Check] = []
    radio_list = bluetooth.radios()
    radio = radio_list[0] if radio_list else None
    checks.append(Check(
        "radio", "Bluetooth adapter", radio is not None,
        f"{radio.manufacturer} adapter {radio.address} ({radio.name})" if radio
        else "No Bluetooth adapter found, or Bluetooth is turned off.",
        None if radio else "Turn Bluetooth on in Windows Settings, or plug in a USB Bluetooth dongle.",
    ))

    comps = {c.id: c for c in drivers.scan()}
    bt = comps["bthps3"]
    if not bt.installed:
        bt_detail, bt_fix = "Not installed.", "Install BthPS3 from the Drivers page, then reboot."
    elif bt.status == "broken":
        bt_detail = " ".join(bt.problems)
        bt_fix = "Uninstall BthPS3, reboot, then install the latest version and reboot again."
    elif drivers.version_tuple(bt.installed_version) < (3,):
        bt_detail = f"Version {bt.installed_version} works, but 3.x recovers from Windows updates."
        bt_fix = "Uninstall the old version and reboot, then install the latest and reboot again."
    else:
        bt_detail, bt_fix = f"Version {bt.installed_version}, running.", None
    checks.append(Check("bthps3", "BthPS3 Bluetooth driver", bt.status == "ok", bt_detail, bt_fix,
                        "component:bthps3", {"version": bt.installed_version}))

    ds = comps["dshidmini"]
    ds_current = ds.installed and drivers.version_tuple(ds.installed_version) >= (3,)
    checks.append(Check(
        "dshidmini", "DsHidMini driver", ds_current,
        f"Version {ds.installed_version}." if ds_current else
        (f"Version {ds.installed_version} is from 2021; 3.x is needed for reliable Bluetooth."
         if ds.installed else "Not installed."),
        None if ds_current else "Install DsHidMini 3.x from the Drivers page (it installs over "
                                "older versions).",
        "component:dshidmini",
    ))

    pads = devices()
    usb = [p for p in pads if p.connection == "usb"]
    wireless = [p for p in pads if p.connection == "bt"]
    if not usb and wireless:
        checks.append(Check("paired", "Pad knows this PC", True,
                            "Connected over Bluetooth, so it is paired to this PC."))
    elif not usb:
        checks.append(Check(
            "paired", "Pad knows this PC", None,
            "Connect the DS3 with a USB cable once so DsHidMini can store this PC's address.",
        ))
    for p in usb:
        ok = p.paired_to_this_pc
        checks.append(Check(
            f"paired:{p.mac}", f"DS3 {p.mac or ''} paired to this PC", ok,
            f"Stored host {p.paired_host or 'unknown'}; this PC is {radio.address if radio else 'unknown'}.",
            None if ok else "Unplug and re-plug the USB cable; DsHidMini pairs automatically. "
                            "In ControlApp, check that pairing mode is Auto.",
        ))

    stale = _windows_paired_ds3([p.mac for p in pads if p.mac])
    checks.append(Check(
        "no-windows-pairing", "No Windows-paired DS3 entry", not stale,
        "None found." if not stale else "Windows has its own pairing for: " + ", ".join(stale),
        None if not stale else "Remove those devices in Settings > Bluetooth & devices. "
                               "DS3 pads must only be paired over USB.",
    ))
    if any(p.connection == "bt" for p in pads):
        checks.append(Check("connected", "DS3 connected over Bluetooth", True, "Working."))
    return checks


def _windows_paired_ds3(macs: list[str]) -> list[str]:
    hits: list[str] = []
    wanted = {_mac_key(m) for m in macs}
    for iid in cm.device_ids(present_only=False):
        up = iid.upper()
        if not up.startswith("BTHENUM\\DEV_"):
            continue
        mac = up[len("BTHENUM\\DEV_"):].split("\\", 1)[0]
        name = cm.get_property(iid, cm.DEVPKEY_Device_FriendlyName) or ""
        if mac in wanted or "PLAYSTATION(R)3" in name.upper():
            hits.append(bluetooth.format_mac(mac) or mac)
    return hits
