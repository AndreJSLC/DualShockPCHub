"""Inventory, update check, download and install of the controller driver stack.

What we track (see docs/RESEARCH-drivers.md for the reasoning):

* DsHidMini  - DualShock 3 driver (USB + Bluetooth), by Nefarius.
* BthPS3     - Bluetooth profile/filter driver the DS3 needs to connect wirelessly.
* ViGEmBus   - virtual Xbox 360 / DS4 bus used by remapping (retired, still the standard).
* HidHide    - optional: hides the physical pad when a remapper is in use.
* .NET 10 Desktop Runtime - required by the DsHidMini v3 setup and ControlApp.

Detection is read-only and fast: Uninstall registry keys, Nefarius' own
registry keys, INF files in the driver store and the live device tree. It never
queries WMI ``Win32_Product`` (that triggers MSI self-repair of every package).
Downloads and installs only happen when the UI calls ``download``/``install``
after an explicit user click; installers run with their normal UI via UAC.
"""

from __future__ import annotations

import json
import os
import re
import sys
import winreg
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

from . import _cfgmgr as cm
from . import bluetooth, elevate

# Network, hashing and subprocess modules are imported inside the functions that need them,
# so importing this module (and the app) stays light.
Status = Literal["ok", "outdated", "missing", "broken", "unknown"]
USER_AGENT = "DualShockPCHub/0.1 (+https://github.com/AndreJSLC/DualShockPCHub)"
_TIMEOUT = 20


@dataclass(slots=True)
class Component:
    id: str
    name: str
    purpose: str
    needed_for: tuple[str, ...]
    homepage: str
    publisher: str  # expected Authenticode signer (substring of the certificate subject)
    repo: str | None = None  # GitHub "owner/name"
    release_tag: str | None = None  # pin a tag instead of "latest" (retired projects)
    asset_regex: str | None = None
    uninstall_names: tuple[str, ...] = ()  # regexes matched against DisplayName
    vendor_key: str | None = None  # HKLM\SOFTWARE\Nefarius Software Solutions e.U.\<key>
    inf_names: tuple[str, ...] = ()  # original INF names in the driver store
    inf_install: bool = False  # True when a bare INF install (no setup) is a real install
    optional: bool = False
    install_hint: str = ""

    # Filled by scan() / check_latest()
    installed_version: str | None = None
    bound_version: str | None = None  # version loaded on a present device, if any
    uninstall_command: str | None = None
    latest_version: str | None = None
    download_url: str | None = None
    download_name: str | None = None
    download_size: int | None = None
    download_sha256: str | None = None
    release_url: str | None = None
    published: str | None = None
    status: Status = "unknown"
    problems: list[str] = field(default_factory=list)  # health-check failures
    notes: list[str] = field(default_factory=list)

    @property
    def installed(self) -> bool:
        return self.installed_version is not None

    @property
    def update_available(self) -> bool:
        return bool(self.latest_version and self.installed_version
                     and version_tuple(self.latest_version) > version_tuple(self.installed_version))


def catalog() -> list[Component]:
    """Fresh, unscanned component descriptions (safe to mutate)."""
    return [
        Component(
            id="dshidmini", name="DsHidMini",
            purpose="DualShock 3 driver for USB and Bluetooth (pressure buttons, battery, rumble).",
            needed_for=("DS3",), homepage="https://docs.nefarius.at/projects/DsHidMini/",
            publisher="Nefarius Software Solutions e.U.", repo="nefarius/DsHidMini",
            asset_regex=r"^Nefarius_DsHidMini_Drivers_x64_arm64_v(\d+\.\d+\.\d+)\.msi$",
            uninstall_names=(r"DsHidMini",), vendor_key="Nefarius DsHidMini Driver",
            inf_names=("dshidmini.inf",), inf_install=True,  # 2.x shipped as a bare INF
            install_hint="Installs over older versions; needs the .NET 10 Desktop Runtime. "
                         "Reboot if setup asks.",
        ),
        Component(
            id="bthps3", name="BthPS3",
            purpose="Bluetooth profile + filter driver that lets the DS3 (and Navigation/Move) "
                    "connect wirelessly.",
            needed_for=("DS3 Bluetooth",), homepage="https://docs.nefarius.at/projects/BthPS3/",
            publisher="Nefarius Software Solutions e.U.", repo="nefarius/BthPS3",
            asset_regex=r"^Nefarius_BthPS3_Drivers_x64_arm64_v(\d+\.\d+\.\d+)\.msi$",
            uninstall_names=(r"BthPS3",), vendor_key="Nefarius BthPS3 Bluetooth Drivers",
            inf_names=("bthps3.inf", "bthps3psm.inf"),
            install_hint="Coming from 2.x: uninstall the old version and reboot first, then install "
                         "and reboot again. Never pair a DS3 through Windows' Bluetooth dialog.",
        ),
        Component(
            id="vigembus", name="ViGEmBus",
            purpose="Virtual Xbox 360 / DualShock 4 controller bus used for remapping and emulation.",
            needed_for=("Remapping",), homepage="https://docs.nefarius.at/projects/ViGEm/",
            publisher="Nefarius Software Solutions e.U.", repo="nefarius/ViGEmBus",
            release_tag="v1.22.0",
            asset_regex=r"^ViGEmBus_(\d+\.\d+\.\d+)_x64_x86_arm64\.exe$",
            uninstall_names=(r"ViGEm Bus Driver",), inf_names=("vigembus.inf",),
            install_hint="Retired upstream (Nov 2023) but stable; 1.22.0 is the final release.",
        ),
        Component(
            id="hidhide", name="HidHide",
            purpose="Hides the physical pad from games while a remapper is active, preventing "
                    "double input.",
            needed_for=("Optional",), homepage="https://docs.nefarius.at/projects/HidHide/",
            publisher="Nefarius Software Solutions e.U.", repo="nefarius/HidHide",
            asset_regex=r"^HidHide_(\d+\.\d+\.\d+)_x64\.exe$",
            uninstall_names=(r"^HidHide",), vendor_key="HidHide", inf_names=("hidhide.inf",),
            optional=True,
            install_hint="Needed for \"Hide the real controller from Steam & games\" on the Remap "
                         "page. Its setup asks for a restart.",
        ),
        Component(
            id="dotnet-desktop", name=".NET 10 Desktop Runtime",
            purpose="Runtime required by the DsHidMini v3 setup and its ControlApp.",
            needed_for=("DS3",), homepage="https://dotnet.microsoft.com/download/dotnet/10.0",
            publisher="Microsoft Corporation",
            install_hint="Install before DsHidMini, otherwise its setup stops with error 9001.",
        ),
    ]


# ----------------------------------------------------------------- versions
def version_tuple(v: str | None) -> tuple[int, ...]:
    """``"setup-v3.17.1-r1"`` -> ``(3, 17, 1)``; ``"2.6.174.0"`` -> ``(2, 6, 174)``."""
    if not v:
        return ()
    m = re.search(r"(\d+(?:\.\d+)*)", v)
    if not m:
        return ()
    parts = tuple(int(p) for p in m.group(1).split("."))
    return parts[:3]


# --------------------------------------------------------------- detection
@dataclass(slots=True)
class UninstallEntry:
    name: str
    version: str | None
    publisher: str | None
    uninstall: str | None
    location: str | None


_UNINSTALL_ROOTS = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)


def _value(key, name: str):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def uninstall_entries() -> list[UninstallEntry]:
    out: list[UninstallEntry] = []
    for hive, path in _UNINSTALL_ROOTS:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as key:
                        name = _value(key, "DisplayName")
                        if name:
                            out.append(UninstallEntry(
                                name, _value(key, "DisplayVersion"), _value(key, "Publisher"),
                                _value(key, "UninstallString"), _value(key, "InstallLocation")))
                except OSError:
                    continue
    return out


def _vendor_version(product: str) -> str | None:
    for view in (0, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                rf"SOFTWARE\Nefarius Software Solutions e.U.\{product}",
                                0, winreg.KEY_READ | view) as key:
                v = _value(key, "Version")
                if v:
                    return str(v)
        except OSError:
            continue
    return None


_DRIVERVER = re.compile(r"^\s*DriverVer\s*=\s*[^,]*,\s*([\d.]+)", re.IGNORECASE | re.MULTILINE)


def driver_store_versions() -> dict[str, list[str]]:
    """Original INF name (lower-case) -> DriverVer versions staged in the driver store."""
    repo = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "DriverStore" / "FileRepository"
    found: dict[str, list[str]] = {}
    try:
        folders = list(repo.iterdir())
    except OSError:
        return found
    for folder in folders:
        name = folder.name.split(".inf_", 1)[0] + ".inf"
        inf = folder / name
        try:
            raw = inf.read_bytes()[:16384]
        except OSError:
            continue
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("latin-1")
        m = _DRIVERVER.search(text)
        if m:
            found.setdefault(name.lower(), []).append(m.group(1))
    return found


def _bound_version(*needles: str) -> str | None:
    for node in cm.find_devices(*needles):
        if node.driver_version and (node.driver_provider or "").startswith("Nefarius"):
            return node.driver_version
    return None


def _desktop_runtime_versions() -> list[str]:
    path = r"SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.WindowsDesktop.App"
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | view) as key:
                return [winreg.EnumValue(key, i)[0] for i in range(winreg.QueryInfoKey(key)[1])]
        except OSError:
            continue
    # Fall back to the files on disk.
    base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "dotnet" / "shared" / \
        "Microsoft.WindowsDesktop.App"
    try:
        return [p.name for p in base.iterdir() if p.is_dir()]
    except OSError:
        return []


def scan() -> list[Component]:
    """Local inventory of every component (no network). Takes well under a second."""
    entries = uninstall_entries()
    store = driver_store_versions()
    comps = catalog()
    for c in comps:
        if c.id == "dotnet-desktop":
            tens = sorted((v for v in _desktop_runtime_versions() if v.startswith("10.")),
                          key=version_tuple)
            c.installed_version = tens[-1] if tens else None
            c.status = "ok" if c.installed_version else "missing"
            continue

        # Installed = registered by its setup (Uninstall entry / Nefarius key). Driver packages
        # alone don't count: uninstallers often leave them staged in the driver store.
        registered: list[str] = []
        for e in entries:
            if any(re.search(rx, e.name, re.IGNORECASE) for rx in c.uninstall_names):
                if e.version:
                    registered.append(e.version)
                c.uninstall_command = c.uninstall_command or e.uninstall
        if c.vendor_key and (v := _vendor_version(c.vendor_key)):
            registered.append(v)
        staged = [v for inf in c.inf_names for v in store.get(inf.lower(), [])]

        if c.id == "dshidmini":
            c.bound_version = _bound_version("VID_054C&PID_0268", "VID_054C&PID_042F", "BTHPS3BUS")
        elif c.id == "vigembus":
            c.bound_version = _bound_version("NEFARIUS\\VIGEMBUS")
        elif c.id == "hidhide":
            c.bound_version = _bound_version("ROOT\\HIDHIDE", "HIDHIDE")

        if registered:
            c.installed_version = max(registered, key=version_tuple)
        elif c.inf_install and staged:
            c.installed_version = max(staged, key=version_tuple)
        elif c.bound_version:
            c.installed_version = c.bound_version
        elif staged:
            c.notes.append(f"Driver files from an earlier {c.name} ({max(staged, key=version_tuple)}) "
                           "are still in Windows' driver store; installing the latest version "
                           "replaces them.")

        if c.id == "bthps3" and c.installed:
            _check_bthps3(c)

        c.status = "ok" if c.installed else "missing"
        if c.problems:
            c.status = "broken"
    _annotate(comps)
    return comps


def _check_bthps3(c: Component) -> None:
    services = {s: service_exists(s) for s in ("BthPS3", "BthPS3PSM")}
    if not services["BthPS3"]:
        c.problems.append("The BthPS3 driver service is not registered.")
    if not services["BthPS3PSM"]:
        c.problems.append("The BthPS3PSM filter service is not registered.")
    elif "BthPS3PSM" not in bluetooth.bluetooth_class_lower_filters():
        c.problems.append("The BthPS3PSM filter is not attached to the Bluetooth class.")
    svc = bluetooth.bthps3_local_service()
    if not svc.registered or not svc.enabled:
        c.problems.append("The BthPS3 Bluetooth service is not enabled on the radio.")
    node = bluetooth.bthps3_enumerator()
    if node is None or not node.present:
        c.problems.append(
            "\"Nefarius Bluetooth PS Enumerator\" is missing, so the PC cannot accept DS3 "
            "Bluetooth connections. This typically happens after a Windows build upgrade; "
            "reinstalling the latest BthPS3 recreates it.")
    else:
        c.bound_version = node.driver_version
        if node.problem_code:
            c.problems.append(f"The BthPS3 enumerator reports device problem code {node.problem_code}.")
    if not bluetooth.radios():
        c.notes.append("No Bluetooth radio detected (or it is turned off).")


def service_exists(name: str) -> bool:
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                       rf"SYSTEM\CurrentControlSet\Services\{name}"))
        return True
    except OSError:
        return False


def _annotate(comps: list[Component]) -> None:
    by_id = {c.id: c for c in comps}
    ds = by_id["dshidmini"]
    if ds.installed and version_tuple(ds.installed_version) < (3,):
        ds.notes.append("Version 2.x is from 2021. v3 adds a config file, the ControlApp, "
                        "a Bluetooth diagnostic wizard and many fixes.")
    bt = by_id["bthps3"]
    if bt.installed and version_tuple(bt.installed_version) < (3,):
        bt.notes.append("BthPS3 3.x adds automatic recovery from stale Bluetooth registration and "
                        "suspend/resume fixes.")
    if not by_id["dotnet-desktop"].installed:
        by_id["dotnet-desktop"].notes.append("Needed before installing or upgrading to DsHidMini v3.")


# ------------------------------------------------------------ update check
def _http_json(url: str) -> dict | list:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.load(resp)


def _fill_from_github(c: Component) -> None:
    url = (f"https://api.github.com/repos/{c.repo}/releases/tags/{c.release_tag}" if c.release_tag
           else f"https://api.github.com/repos/{c.repo}/releases/latest")
    release = _http_json(url)
    rx = re.compile(c.asset_regex or r".")
    for asset in release.get("assets", []):
        m = rx.match(asset.get("name", ""))
        if not m:
            continue
        c.latest_version = m.group(1) if m.groups() else release.get("tag_name")
        c.download_url = asset.get("browser_download_url")
        c.download_name = asset.get("name")
        c.download_size = asset.get("size")
        digest = asset.get("digest") or ""
        c.download_sha256 = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None
        break
    else:
        c.latest_version = release.get("tag_name")
        c.notes.append("Latest release has no installer matching the expected file name.")
    c.release_url = release.get("html_url")
    c.published = (release.get("published_at") or "")[:10] or None


def _fill_dotnet(c: Component) -> None:
    meta = _http_json("https://dotnetcli.blob.core.windows.net/dotnet/release-metadata/10.0/releases.json")
    latest = meta.get("latest-release")
    for rel in meta.get("releases", []):
        if rel.get("release-version") != latest:
            continue
        desktop = rel.get("windowsdesktop") or {}
        for f in desktop.get("files", []):
            if f.get("rid") == "win-x64" and f.get("name", "").endswith(".exe"):
                c.latest_version = desktop.get("version") or latest
                c.download_url = f.get("url")
                c.download_name = f.get("url", "").rsplit("/", 1)[-1] or None
                c.release_url = "https://dotnet.microsoft.com/download/dotnet/10.0"
                c.published = rel.get("release-date")
                return
    c.release_url = c.homepage


def _fill_latest(c: Component) -> None:
    try:
        if c.repo:
            _fill_from_github(c)
        elif c.id == "dotnet-desktop":
            _fill_dotnet(c)
    except (OSError, ValueError) as exc:  # URLError and TimeoutError are OSErrors
        c.notes.append(f"Could not check for updates: {exc}")
        return
    # A newer .NET patch is not worth nagging about; only a missing runtime matters.
    if c.status == "ok" and c.update_available and c.id != "dotnet-desktop":
        c.status = "outdated"


def check_latest(components: list[Component]) -> list[Component]:
    """Look up the newest official release of each component (network, in parallel)."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(components) or 1) as pool:
        list(pool.map(_fill_latest, components))
    return components


# ---------------------------------------------------------- download/install
class DownloadError(RuntimeError):
    pass


def downloads_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DualShockPCHub" / "downloads"
    base.mkdir(parents=True, exist_ok=True)
    return base


def download(c: Component, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None, dest: Path | None = None) -> Path:
    """Download the component's official installer and verify size + SHA-256 when published."""
    if not c.download_url:
        raise DownloadError(f"No download is known for {c.name}; run check_latest() first.")
    dest = dest or downloads_dir()
    target = dest / (c.download_name or c.download_url.rsplit("/", 1)[-1])
    partial = target.with_suffix(target.suffix + ".part")
    import hashlib
    import urllib.request

    req = urllib.request.Request(c.download_url, headers={"User-Agent": USER_AGENT})
    sha = hashlib.sha256()
    done = 0
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp, open(partial, "wb") as out:
            total = int(resp.headers.get("Content-Length") or c.download_size or 0)
            while chunk := resp.read(256 * 1024):
                if cancelled and cancelled():
                    raise DownloadError("Download cancelled.")
                out.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except OSError as exc:  # includes URLError and timeouts
        partial.unlink(missing_ok=True)
        raise DownloadError(f"Download failed: {exc}") from exc
    except DownloadError:
        partial.unlink(missing_ok=True)
        raise
    if c.download_size and done != c.download_size:
        partial.unlink(missing_ok=True)
        raise DownloadError(f"Size mismatch: got {done} bytes, expected {c.download_size}.")
    if c.download_sha256 and sha.hexdigest() != c.download_sha256:
        partial.unlink(missing_ok=True)
        raise DownloadError("SHA-256 mismatch; the file was not saved.")
    partial.replace(target)
    return target


@dataclass(frozen=True, slots=True)
class Signature:
    valid: bool
    status: str
    subject: str


def verify_signature(path: Path) -> Signature:
    """Authenticode check via PowerShell (no extra dependencies)."""
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:DSHUB_FILE; "
              "[pscustomobject]@{Status=[string]$s.Status; "
              "Subject=[string]$s.SignerCertificate.Subject} | ConvertTo-Json -Compress")
    env = dict(os.environ, DSHUB_FILE=str(path))
    import subprocess

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=60, env=env, creationflags=flags)
        data = json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return Signature(False, "Unknown", "")
    status = data.get("Status") or "Unknown"
    return Signature(status == "Valid", status, data.get("Subject") or "")


class UntrustedInstaller(RuntimeError):
    pass


def install(c: Component, path: Path, wait: bool = True) -> int | None:
    """Run a downloaded installer elevated, after checking it is signed by the expected publisher.

    Call only in response to a user action; the installer shows its own UI.
    """
    sig = verify_signature(path)
    if not sig.valid or c.publisher not in sig.subject:
        raise UntrustedInstaller(
            f"{path.name} is not validly signed by {c.publisher} (status {sig.status}, "
            f"signer {sig.subject or 'none'}). Not running it.")
    return elevate.run_installer(path, wait=wait)


def uninstall(c: Component, wait: bool = True) -> int | None:
    """Run the component's registered uninstaller elevated (user-initiated only)."""
    if not c.uninstall_command:
        raise RuntimeError(f"{c.name} has no registered uninstaller.")
    return elevate.run_uninstall_string(c.uninstall_command, wait=wait)


def _boot_time_utc() -> datetime:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    return datetime.now(timezone.utc) - timedelta(milliseconds=kernel32.GetTickCount64())


def _vendor_reboot_pending(product: str) -> bool:
    """Nefarius setups set RebootPending=1 but never clear it after the restart.

    Only trust the flag when its ``RebootPendingSince`` timestamp is newer than
    the current boot.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"SOFTWARE\Nefarius Software Solutions e.U.\{product}") as key:
            if not _value(key, "RebootPending"):
                return False
            since = _value(key, "RebootPendingSince") or ""
    except OSError:
        return False
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", str(since))
    if not m:
        return True  # no timestamp to compare: believe the flag
    set_at = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    return set_at > _boot_time_utc()


def reboot_pending() -> bool:
    """True when Windows (or a Nefarius setup, since the last boot) is waiting for a restart."""
    for path in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
                 r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"):
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path))
            return True
        except OSError:
            continue
    return any(_vendor_reboot_pending(p) for p in ("Nefarius DsHidMini Driver",
                                                    "Nefarius BthPS3 Bluetooth Drivers"))


if __name__ == "__main__":  # quick manual check: python -m dshub.system.drivers [--online]
    comps = scan()
    if "--online" in sys.argv:
        check_latest(comps)
    for comp in comps:
        print(f"{comp.name:26} {comp.status:9} installed={comp.installed_version} "
              f"bound={comp.bound_version} latest={comp.latest_version}")
        for line in comp.problems + comp.notes:
            print("    -", line)
    print("reboot pending:", reboot_pending())
