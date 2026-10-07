"""Application state shared by every page: pads, settings, profiles, remaps.

Device-manager callbacks arrive on the scan thread; re-emitting them as Qt
signals on this QObject (which lives on the GUI thread) hops them over.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from dshub.config import Settings
from dshub.core.battery import BatteryTracker, Estimate
from dshub.core.manager import DeviceManager
from dshub.core.pads.base import Pad
from dshub.core.vigem import ViGEmError, bus_available
from dshub.mapping.engine import RemapSession
from dshub.mapping.profile import Profile, ProfileStore

log = logging.getLogger(__name__)

DEFAULT_LIGHTBAR = (20, 60, 255)


class Hub(QObject):
    padAdded = Signal(object)
    padRemoved = Signal(object)
    blockedChanged = Signal(list)
    remapChanged = Signal(object)  # pad
    toast = Signal(str, str)  # text, level: "info" | "ok" | "warn" | "error"

    _added = Signal(object)
    _removed = Signal(object)
    _blocked = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings()
        self.profiles = ProfileStore()
        self.manager = DeviceManager()
        self.sessions: dict[str, RemapSession] = {}
        self.trackers: dict[str, BatteryTracker] = {}
        # Battery levels move slowly: sampling every 10 s is plenty and costs nothing.
        self._battery_timer = QTimer(self, interval=10_000, timeout=self._track_batteries)
        self._battery_timer.setTimerType(Qt.TimerType.VeryCoarseTimer)
        self._added.connect(self._on_added)
        self._removed.connect(self._on_removed)
        self._blocked.connect(self.blockedChanged)
        self.manager.on_added.append(self._added.emit)
        self.manager.on_removed.append(self._removed.emit)
        self.manager.on_blocked_changed.append(self._blocked.emit)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.manager.start()
        self._battery_timer.start()

    def shutdown(self) -> None:
        for session in list(self.sessions.values()):
            session.close()
        self.sessions.clear()
        if self.settings.get("unhide_on_quit", True):
            self._unhide_all()
        self.manager.stop()

    def pads(self) -> list[Pad]:
        return self.manager.ordered()

    # ------------------------------------------------------------ hotplug
    def _on_added(self, pad: Pad) -> None:
        conf = self.settings.pad(pad.info.uid)
        self.trackers[pad.key] = BatteryTracker(pad.info.model, conf.get("battery_rates"))
        if pad.caps.lightbar:
            rgb = conf.get("lightbar", list(DEFAULT_LIGHTBAR))
            pad.set_lightbar(tuple(rgb) if rgb else None)
        if pad.caps.player_leds and conf.get("player"):
            pad.set_player_led(int(conf["player"]))
        if pad.caps.battery_saver and conf.get("battery_saver"):
            pad.set_battery_saver(True)
        if conf.get("stick_centers"):
            pad.set_stick_centers(tuple(conf["stick_centers"]))
        if conf.get("remap") or conf.get("hidden"):
            self.set_remap(pad, True, quiet=True)
        if conf.get("hidden"):
            self._hide_ids(pad, quiet=True)  # re-assert: USB and BT links have different ids
        self.padAdded.emit(pad)

    def _on_removed(self, pad: Pad) -> None:
        self.trackers.pop(pad.key, None)
        session = self.sessions.pop(pad.key, None)
        if session is not None:
            session.close()
        self.padRemoved.emit(pad)

    # ------------------------------------------------------------ profiles
    def profile_name(self, pad: Pad) -> str:
        return self.settings.pad(pad.info.uid).get("profile", "Default")

    def profile_for(self, pad: Pad) -> Profile:
        return self.profiles.load(self.profile_name(pad))

    def set_profile(self, pad: Pad, name: str) -> None:
        self.settings.pad(pad.info.uid)["profile"] = name
        self.settings.save()
        session = self.sessions.get(pad.key)
        if session is not None:
            session.set_profile(self.profiles.load(name))

    def save_profile(self, profile: Profile) -> None:
        self.profiles.save(profile)
        for key, session in self.sessions.items():
            pad = self.manager.pads.get(key)
            if pad is not None and self.profile_name(pad) == profile.name:
                session.set_profile(profile)

    # ------------------------------------------------------------ remap
    def remap_enabled(self, pad: Pad) -> bool:
        return pad.key in self.sessions

    def set_remap(self, pad: Pad, on: bool, quiet: bool = False) -> bool:
        conf = self.settings.pad(pad.info.uid)
        if not on:
            session = self.sessions.pop(pad.key, None)
            if session is not None:
                session.close()
            conf["remap"] = False
            self.settings.save()
            self.remapChanged.emit(pad)
            return True
        if pad.key in self.sessions:
            return True
        if not bus_available():
            if not quiet:
                self.toast.emit("ViGEmBus isn't installed, so a virtual controller can't be created. "
                                "See Drivers & Firmware.", "error")
            return False
        try:
            self.sessions[pad.key] = RemapSession(pad, self.profile_for(pad))
        except (ViGEmError, OSError) as exc:
            log.exception("remap start failed")
            if not quiet:
                self.toast.emit(f"Couldn't start the virtual controller: {exc}", "error")
            return False
        conf["remap"] = True
        self.settings.save()
        self.remapChanged.emit(pad)
        if not quiet:
            self.toast.emit(f"{pad.info.title} now drives a virtual Xbox 360 controller", "ok")
        return True

    # ------------------------------------------------------------ outputs
    def set_lightbar(self, pad: Pad, rgb: tuple[int, int, int] | None) -> None:
        pad.set_lightbar(rgb)
        self.settings.pad(pad.info.uid)["lightbar"] = list(rgb) if rgb else None
        self.settings.save()

    def set_player(self, pad: Pad, n: int) -> None:
        pad.set_player_led(n)
        self.settings.pad(pad.info.uid)["player"] = n
        self.settings.save()

    # ------------------------------------------------------------ HidHide
    @staticmethod
    def hid_instance_id(pad: Pad) -> str | None:
        path = getattr(pad, "path", None)
        if path is None:
            return None
        from dshub.system import hidhide

        return hidhide.instance_id_for_hid_path(path)

    def hidden(self, pad: Pad) -> bool:
        return bool(self.settings.pad(pad.info.uid).get("hidden"))

    def can_hide(self, pad: Pad) -> str | None:
        """None when hiding is possible, otherwise the reason it isn't."""
        if getattr(pad, "path", None) is None:
            return ("A DS3 in XInput mode can't be hidden reliably. Switch it to exclusive mode first: "
                    "Steam and games then ignore it and only this app reads it.")
        if pad.info.backend == "dshidmini-ds4w":
            return "Already exclusive: Steam and games ignore this DS3, only this app reads it."
        from dshub.system import hidhide

        if not hidhide.installed():
            return "Needs the HidHide driver. Install it from Drivers & Firmware (then restart Windows)."
        return None

    def _hide_ids(self, pad: Pad, quiet: bool = False) -> bool:
        from dshub.system import hidhide

        iid = self.hid_instance_id(pad)
        if not iid:
            return False
        try:
            hidhide.hide_from_others([iid])
        except hidhide.HidHideError as exc:
            log.warning("HidHide hide failed: %s", exc)
            if not quiet:
                self.toast.emit(self._hidhide_message(exc), "error")
            return False
        conf = self.settings.pad(pad.info.uid)
        conf["hidden_ids"] = sorted(set(conf.get("hidden_ids", [])) | {iid})
        self.settings.save()
        return True

    def set_hidden(self, pad: Pad, on: bool) -> bool:
        from dshub.system import hidhide

        conf = self.settings.pad(pad.info.uid)
        if on:
            reason = self.can_hide(pad)
            if reason:
                self.toast.emit(reason, "error")
                return False
            if not self.set_remap(pad, True) or not self._hide_ids(pad):
                return False
            conf["hidden"] = True
            self.settings.save()
            self.toast.emit("Hidden from Steam and games; they now only see the virtual Xbox controller. "
                            "Unplug and replug the controller (or switch it off and on) so apps that already "
                            "had it open let go.", "ok")
        else:
            ids = conf.get("hidden_ids", [])
            try:
                if ids:
                    hidhide.unhide(ids)
            except hidhide.HidHideError as exc:
                self.toast.emit(self._hidhide_message(exc), "error")
                return False
            conf["hidden"] = False
            conf["hidden_ids"] = []
            self.settings.save()
            self.toast.emit("The real controller is visible to every app again.", "ok")
        self.remapChanged.emit(pad)
        return True

    def _unhide_all(self) -> None:
        ids = [i for c in self.settings.data.get("pads", {}).values() if c.get("hidden")
               for i in c.get("hidden_ids", [])]
        if not ids:
            return
        try:
            from dshub.system import hidhide

            hidhide.unhide(ids)
        except Exception:  # noqa: BLE001 - quitting; the next start re-hides anyway
            log.exception("unhide on quit failed")

    @staticmethod
    def _hidhide_message(exc: Exception) -> str:
        from dshub.system import hidhide

        if isinstance(exc, hidhide.HidHideUnavailable):
            return "HidHide isn't running yet. If you just installed it, restart Windows."
        if isinstance(exc, hidhide.HidHideBusy):
            return "HidHide is busy: close the HidHide Configuration Client or DS4Windows, then try again."
        return f"HidHide: {exc}"

    # ------------------------------------------------------------ battery estimates
    def _track_batteries(self) -> None:
        for pad in self.pads():
            tracker = self.trackers.get(pad.key)
            if tracker is not None and tracker.update(pad.state.battery):
                self.settings.pad(pad.info.uid)["battery_rates"] = tracker.learned()
                self.settings.save()

    def battery_estimate(self, pad: Pad) -> Estimate | None:
        tracker = self.trackers.get(pad.key)
        return tracker.estimate(pad.state.battery) if tracker is not None else None

    def set_battery_saver(self, pad: Pad, on: bool) -> None:
        pad.set_battery_saver(on)
        self.settings.pad(pad.info.uid)["battery_saver"] = on
        self.settings.save()

    def set_stick_centers(self, pad: Pad, centers: tuple[float, float, float, float] | None) -> None:
        pad.set_stick_centers(centers)
        self.settings.pad(pad.info.uid)["stick_centers"] = list(centers) if centers else None
        self.settings.save()

    def slow_charge_factor(self, pad: Pad) -> float | None:
        tracker = self.trackers.get(pad.key)
        return tracker.slow_charge_factor() if tracker is not None else None
