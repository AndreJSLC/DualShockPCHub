"""Where settings and profiles live, plus the small app-wide settings file."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "DualShockPCHub"


def data_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def profiles_dir() -> Path:
    return data_dir() / "profiles"


class Settings:
    """Tiny JSON-backed key/value store (per-controller choices, window prefs)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "settings.json"
        try:
            self.data: dict = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    def pad(self, uid: str) -> dict:
        """Mutable per-controller section (profile, remap toggle, lightbar)."""
        return self.data.setdefault("pads", {}).setdefault(uid, {})

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), "utf-8")
            tmp.replace(self.path)
        except OSError:
            log.exception("could not save settings")
