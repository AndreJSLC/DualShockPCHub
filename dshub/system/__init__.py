"""System integration: drivers, firmware, DS3 pairing and conflict detection (no UI imports).

Every function here is safe to call from a worker thread and does nothing until
called: no import-time scans, no background threads, no polling. Network access
happens only in ``drivers.check_latest``/``drivers.download``; anything that
changes the system (installers, uninstallers, the DS3 mode helper) runs elevated
through UAC and is only ever called from an explicit user action.

Submodules load on first use (``from dshub.system import drivers``), keeping the
app's startup and memory light.
"""

from importlib import import_module

__all__ = ["bluetooth", "conflicts", "drivers", "ds3_pairing", "elevate", "firmware", "hidhide"]


def __getattr__(name: str):
    if name in __all__:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
