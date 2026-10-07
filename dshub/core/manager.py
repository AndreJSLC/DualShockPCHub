"""Discovers Sony pads, starts/stops their reader threads, tracks hotplug.

The manager is UI-agnostic: it runs a background scan loop and reports
changes through plain callbacks.  The Qt layer adapts those to signals.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

import hid

from dshub.core import hid_descriptor, winapi
from dshub.core.pads.ds2 import DualShock2, find_adapter
from dshub.core.pads.base import Pad
from dshub.core.pads.ds3 import (DS4W_PID, DS4W_VID, DSHM_XINPUT_IDS, PID_DS3, XINPUT_HID_GENERIC, DualShock3DS4Mode,
                                 DualShock3Hid, DualShock3XInput)
from dshub.core.pads.ds4 import PIDS as DS4_PIDS
from dshub.core.pads.ds4 import DualShock4
from dshub.core.pads.ds5 import PID_DS5, PID_EDGE, DualSense
from dshub.core.pads.hidpad import is_bluetooth_path
from dshub.core.state import Connection, ControllerInfo, Model

log = logging.getLogger(__name__)

SONY_VID = 0x054C


@dataclass
class Blocked:
    """A pad we can see but cannot open (another app holds it exclusively)."""

    model: Model
    connection: Connection
    reason: str


class DeviceManager:
    #: Fallback re-scan period. Hotplug is normally driven by request_scan()
    #: (WM_DEVICECHANGE), so this only catches missed notifications.
    SCAN_INTERVAL_S = 30.0
    SCAN_INTERVAL_BACKGROUND_S = 120.0

    def __init__(self) -> None:
        self.pads: dict[str, Pad] = {}
        self.blocked: list[Blocked] = []
        self.on_added: list[Callable[[Pad], None]] = []
        self.on_removed: list[Callable[[Pad], None]] = []
        self.on_blocked_changed: list[Callable[[list[Blocked]], None]] = []
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failed_paths: dict[str, int] = {}
        self._wake = threading.Event()
        self._rid_cache: dict[bytes, list[int | None]] = {}
        self.foreground = True

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="pad-scan", daemon=True)
        self._thread.start()

    def request_scan(self) -> None:
        """Rescan soon (called on WM_DEVICECHANGE); bursts coalesce."""
        self._wake.set()

    def set_foreground(self, foreground: bool) -> None:
        """UI visible -> full-rate pads; hidden -> low-power sampling."""
        self.foreground = foreground
        with self._lock:
            for pad in self.pads.values():
                pad.set_active(foreground)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)
        with self._lock:
            for pad in list(self.pads.values()):
                pad.stop()
            self.pads.clear()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan()
            except Exception:  # noqa: BLE001 - never let hotplug die
                log.exception("scan failed")
            period = self.SCAN_INTERVAL_S if self.foreground else self.SCAN_INTERVAL_BACKGROUND_S
            if self._wake.wait(period):
                self._wake.clear()
                # Device arrival fires several notifications; let them settle.
                self._stop.wait(0.4)
                self._wake.clear()

    # ------------------------------------------------------------- scanning
    def _next_slot(self) -> int:
        used = {p.info.slot for p in self.pads.values()}
        n = 1
        while n in used:
            n += 1
        return n

    def scan(self) -> None:
        with self._lock:
            removed = [p for p in self.pads.values() if not p.alive]
            for pad in removed:
                pad.stop()
                del self.pads[pad.key]
        for pad in removed:
            self._emit(self.on_removed, pad)

        devices = hid.enumerate()  # one pass over all HID devices, filtered below
        found = (self._discover_hid(devices) + self._discover_ds4w(devices) + self._discover_ds2(devices)
                 + self._discover_xinput())
        blocked: list[Blocked] = []
        for factory, key, model, conn in found:
            if key in self.pads:
                continue
            pad = factory()
            pad.set_active(self.foreground)
            try:
                pad.start()
            except OSError as exc:
                self._failed_paths[key] = self._failed_paths.get(key, 0) + 1
                blocked.append(Blocked(model, conn, f"Can't open the device ({exc}). Another app such as "
                                                    "DS4Windows, DSX or Steam may have exclusive access."))
                continue
            self._failed_paths.pop(key, None)
            if pad.info.serial and pad.info.uid != pad.info.serial and pad.info.model is not Model.DS3:
                # USB DS4/DualSense only reveal their MAC after the handshake; key settings on it so
                # they follow the controller across ports and USB/Bluetooth.
                pad.info.uid = pad.info.serial
            with self._lock:
                # Same physical pad on USB *and* Bluetooth: keep the USB link.
                dup = next((p for p in self.pads.values()
                            if pad.info.serial and p.info.serial == pad.info.serial), None)
                if dup is not None:
                    if dup.info.connection is Connection.USB:
                        pad.stop()
                        continue
                    dup.stop()
                    del self.pads[dup.key]
                    pad.info.slot = dup.info.slot
                    self._emit(self.on_removed, dup)
                self.pads[key] = pad
            self._emit(self.on_added, pad)

        if [(b.model, b.connection) for b in blocked] != [(b.model, b.connection) for b in self.blocked]:
            self.blocked = blocked
            self._emit(self.on_blocked_changed, blocked)

    def _make_info(self, model: Model, conn: Connection, backend: str) -> ControllerInfo:
        return ControllerInfo(uid="", model=model, connection=conn, name=model.label, backend=backend,
                              slot=self._next_slot())

    def _discover_hid(self, devices: list[dict]) -> list[tuple]:
        out = []
        seen: set[bytes] = set()
        for d in (d for d in devices if d["vendor_id"] == SONY_VID):
            path = d["path"]
            if path in seen or d.get("usage_page") not in (0x01, None) or d.get("usage") not in (0x04, 0x05, None):
                continue
            seen.add(path)
            pid = d["product_id"]
            conn = Connection.BLUETOOTH if is_bluetooth_path(path) else Connection.USB
            key = path.decode(errors="ignore")
            serial = (d.get("serial_number") or "").replace(":", "").upper()
            mac = ":".join(serial[i:i + 2] for i in range(0, 12, 2)) if len(serial) == 12 else None

            if pid in DS4_PIDS:
                model, cls, kw = Model.DS4, DualShock4, {}
            elif pid in (PID_DS5, PID_EDGE):
                model, cls, kw = (Model.DS5_EDGE if pid == PID_EDGE else Model.DS5), DualSense, \
                    {"edge": pid == PID_EDGE}
            elif pid == PID_DS3:
                nodes = [n for n in winapi.dshidmini_devices() if n.mode in (3, None)]
                model, cls, kw = Model.DS3, DualShock3Hid, {"devnode": nodes[0].instance_id if nodes else None}
            else:
                continue

            def factory(cls=cls, model=model, conn=conn, path=path, mac=mac, kw=kw):
                info = self._make_info(model, conn, "hid")
                info.serial = mac
                info.uid = mac or path.decode(errors="ignore")
                return cls(info, path, **kw)

            out.append((factory, key, model, conn))
        return out

    def _discover_ds4w(self, devices: list[dict]) -> list[tuple]:
        """DS3s that DsHidMini exposes in its vendor-defined DS4Windows mode."""
        devices = [d for d in devices if d["vendor_id"] == DS4W_VID and d["product_id"] == DS4W_PID]
        if not devices:
            return []
        nodes = [n for n in winapi.dshidmini_devices() if n.mode == 4]
        out, seen = [], set()
        for d in devices:
            path = d["path"]
            if path in seen:
                continue
            seen.add(path)
            node = nodes.pop(0) if nodes else None
            conn = Connection.BLUETOOTH if node and node.bluetooth else Connection.USB

            def factory(path=path, node=node, conn=conn):
                info = self._make_info(Model.DS3, conn, "dshidmini-ds4w")
                info.serial = node.mac if node else None
                info.uid = info.serial or (node.instance_id if node else path.decode(errors="ignore"))
                if node and node.driver_version:
                    info.notes.append(f"DsHidMini {node.driver_version} · DS4Windows mode")
                return DualShock3DS4Mode(info, path, devnode=node.instance_id if node else None)

            out.append((factory, path.decode(errors="ignore"), Model.DS3, conn))
        return out

    def _discover_ds2(self, devices: list[dict]) -> list[tuple]:
        """DualShock 2s on PS2-to-USB adapters (generic HID gamepads)."""
        out, seen = [], set()
        for d in devices:
            if d["vendor_id"] in (SONY_VID, DS4W_VID) or d.get("usage_page") != 0x01 or d.get("usage") not in (4, 5):
                continue
            adapter = find_adapter(d["vendor_id"], d["product_id"], d.get("product_string") or "")
            path = d["path"]
            if adapter is None or path in seen:
                continue
            seen.add(path)
            for rid in self._pad_report_ids(path):
                def factory(path=path, adapter=adapter, rid=rid):
                    info = self._make_info(Model.DS2, Connection.USB, "ps2-adapter")
                    info.uid = f"{path.decode(errors='ignore')}#{rid or 0}"
                    info.notes.append(f"{adapter.name} adapter")
                    return DualShock2(info, path, adapter, rid)

                out.append((factory, f"{path.decode(errors='ignore')}#{rid or 0}", Model.DS2, Connection.USB))
        return out

    def _pad_report_ids(self, path: bytes) -> list[int | None]:
        """Report ids that carry a pad (two-port adapters: 1 and 2); [None] without report ids."""
        cached = self._rid_cache.get(path)
        if cached is not None:
            return cached
        ids: list[int | None] = [None]
        dev = hid.device()
        try:
            dev.open_path(path)
            layout = hid_descriptor.parse(dev.get_report_descriptor())
            if layout.uses_report_ids:
                ids = [rid for rid in layout.report_ids() if layout.buttons(rid)] or [None]
        except (OSError, ValueError):
            pass
        finally:
            dev.close()
        self._rid_cache[path] = ids
        return ids

    def _discover_xinput(self) -> list[tuple]:
        """DS3s that DsHidMini exposes in XInput mode."""
        try:
            xi = winapi.xinput()
        except OSError:
            return []
        devnodes = [d for d in winapi.dshidmini_devices() if d.mode == 5]
        out = []
        for slot in range(4):
            if xi.get_state(slot) is None:
                continue
            ids = xi.ids(slot)
            if ids in DSHM_XINPUT_IDS:
                node = devnodes.pop(0) if devnodes else None
            elif ids == XINPUT_HID_GENERIC and devnodes:
                node = devnodes.pop(0)
            else:
                continue
            conn = Connection.BLUETOOTH if node and node.bluetooth else Connection.USB

            def factory(slot=slot, node=node, conn=conn, ids=ids):
                info = self._make_info(Model.DS3, conn, "dshidmini-xinput")
                info.serial = node.mac if node else None
                info.uid = info.serial or (node.instance_id if node else f"xinput:{slot}")
                if node and node.driver_version:
                    info.notes.append(f"DsHidMini {node.driver_version} · XInput mode")
                return DualShock3XInput(info, slot, node.instance_id if node else None, ids)

            out.append((factory, f"xinput:{slot}", Model.DS3, conn))
        return out

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _emit(callbacks, *args) -> None:
        for cb in tuple(callbacks):
            try:
                cb(*args)
            except Exception:  # noqa: BLE001
                log.exception("manager callback failed")

    def ordered(self) -> list[Pad]:
        with self._lock:
            return sorted(self.pads.values(), key=lambda p: p.info.slot)
