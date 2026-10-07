"""Command line for the system layer.

    python -m dshub.system                      # status report (drivers, pads, conflicts)
    python -m dshub.system --online             # ...including latest versions
    python -m dshub.system set-ds3-mode MAC MODE [INSTANCE_ID]   # elevated helper: save + restart
    python -m dshub.system restart-device INSTANCE_ID           # elevated helper: restart only

The frozen app forwards ``--system ...`` here (see ``main``).
"""

from __future__ import annotations

import sys

from . import bluetooth, conflicts, drivers, ds3_pairing


def _status(online: bool) -> int:
    comps = drivers.scan()
    if online:
        drivers.check_latest(comps)
    print("Drivers")
    for c in comps:
        latest = f" -> {c.latest_version}" if c.update_available else ""
        print(f"  {c.name:26} {c.status:9} {c.installed_version or '-'}{latest}")
        for line in c.problems:
            print(f"      ! {line}")
    print("\nBluetooth")
    for r in bluetooth.radios():
        print(f"  {r.manufacturer} {r.address} ({r.name})")
    print("\nDualShock 3")
    for p in ds3_pairing.devices():
        print(f"  {p.mac} via {p.connection}: host={p.paired_host} mode={p.hid_mode} "
              f"battery={p.battery} driver={p.driver} {p.driver_version}")
    print("\nDS3 Bluetooth checklist")
    for chk in ds3_pairing.bluetooth_readiness():
        mark = {True: "ok ", False: "XX ", None: "?? "}[chk.ok]
        print(f"  {mark} {chk.title}: {chk.detail}")
        if chk.fix and not chk.ok:
            print(f"        fix: {chk.fix}")
    print("\nConflicts")
    for c in conflicts.scan(comps):
        print(f"  [{c.severity}] {c.title}: {c.detail}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--system":
        args = args[1:]
    # Elevated helper steps (run via UAC by ds3_pairing.set_hid_mode).
    if args[:1] == ["set-ds3-mode"] and len(args) >= 3:
        ds3_pairing.write_hid_mode(args[1], args[2])
        return ds3_pairing.restart_device(args[3]) if len(args) > 3 else 0
    if args[:1] == ["restart-device"] and len(args) == 2:
        return ds3_pairing.restart_device(args[1])
    return _status(online="--online" in args)


if __name__ == "__main__":
    sys.exit(main())
