# PlayStation controllers on Windows: drivers, firmware and protocol notes

*Researched 2026-10-05. Version numbers, dates and file names come from the GitHub REST API, the projects' sources and READMEs, docs.nefarius.at and Sony's CDN. Anything marked **[UNVERIFIED]** could not be confirmed from a primary source.*

This is the knowledge base behind `dshub/system/`. The app's Drivers page, the DS3 Bluetooth checklist and the conflict detector all implement what is written here.

---

## 1. TL;DR

| Pad | USB | Bluetooth | What you need |
|---|---|---|---|
| DualShock 3 / SIXAXIS / Navigation | DsHidMini | DsHidMini + BthPS3 | Both drivers; the pad is paired over USB, never through Windows' Bluetooth dialog |
| DualShock 4 (v1 / v2) | Works natively (HID) | Works natively | Nothing; ViGEmBus only if a remapper emulates an Xbox pad |
| DualSense / DualSense Edge | Works natively (HID) | Works natively | Sony's *PlayStation Accessories* app for firmware updates |

**Recommended stack:**

| Component | Version (date) | Why | Download |
|---|---|---|---|
| **DsHidMini** | **3.20.1** (2026-10-02) | DS3/SIXAXIS/Navigation driver, USB and Bluetooth; ships ControlApp, IPC | [Nefarius_DsHidMini_Drivers_x64_arm64_v3.20.1.msi](https://github.com/nefarius/DsHidMini/releases/download/setup-v3.20.1/Nefarius_DsHidMini_Drivers_x64_arm64_v3.20.1.msi) |
| **BthPS3** | **3.2.0** (2026-09-27) | Bluetooth profile driver plus PSM filter for the DS3 | [Nefarius_BthPS3_Drivers_x64_arm64_v3.2.0.msi](https://github.com/nefarius/BthPS3/releases/download/setup-v3.2.0/Nefarius_BthPS3_Drivers_x64_arm64_v3.2.0.msi) |
| .NET Desktop Runtime x64 | 10.0.x | Required by the DsHidMini v3 setup and ControlApp; without it the MSI fails with error 9001 | [dotnet.microsoft.com](https://dotnet.microsoft.com/download/dotnet/10.0) |
| ViGEmBus | 1.22.0 (2023-11-02, retired) | Virtual Xbox 360 / DS4 bus used for remapping. Retired but stable; it is the final release | [ViGEmBus_1.22.0_x64_x86_arm64.exe](https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe) |
| HidHide | 1.5.230.0 (2024-05-11) | Optional: hides the physical pad so games only see the remapped one | [HidHide_1.5.230_x64.exe](https://github.com/nefarius/HidHide/releases/download/v1.5.230.0/HidHide_1.5.230_x64.exe) |
| PlayStation Accessories (Sony) | 2.2.1 | DualSense / Edge firmware updates (USB or Bluetooth) | [Installer](https://fwupdater.dl.playstation.net/fwupdater/PlayStationAccessoriesInstaller.exe) · [Page](https://controller.dl.playstation.net/controller/lang/en/2100004.html) |
| nefcon (troubleshooting) | 1.21.0 (2026-09-24) | Toggles Bluetooth services and class filters | [nefcon_v1.21.0.zip](https://github.com/nefarius/nefcon/releases/download/v1.21.0/nefcon_v1.21.0.zip) |

**Ecosystem status, October 2026:**

- **DsHidMini and BthPS3 both made big v3 releases in September 2026.** They are stable.
- **ViGEmBus was archived** in November 2023. It still works.
- **HidHide is maintained** but has had no release since 1.5.230.
- **DS4Windows:** the schmaldeo fork was archived on 2026-03-05 and the Ryochan7 repository returns 404.
- **Sony renamed its DualSense firmware updater** to "PlayStation Accessories".

---

## 2. DualShock 3: how it works on Windows

### 2.1 DsHidMini

**Releases.** The latest stable release is `setup-v3.20.1` (2026-10-02). Earlier stable releases:

- `setup-v3.17.1-r1` (2026-09-29)
- `setup-v3.15.0` (2026-09-24)
- `setup-v3.5.1` (2024-11-04, labelled "BETA" in its notes)

Release assets are named `Nefarius_DsHidMini_Drivers_x64_arm64_v<X.Y.Z>.msi`. The 2.x series shipped as zips, e.g. `dshidmini_v2.2.282.0.zip`.

**What v3 changed compared with 2.2.x:**

- **Packaging:** a signed MSI for x64 and ARM64. Requires Windows 10 1809 or newer.
- **Configuration file** at `%ProgramData%\DsHidMini\DsHidMini.json`.
  - It has a `Global` section and a `Devices` section; device keys are the pad's MAC as 12 uppercase hex digits.
  - The driver hot-reloads the file, **except the HID mode** (see §2.5).
  - v2 kept its settings in device properties, which the DSHMC tool wrote.
- **ControlApp** (WPF, .NET 10) replaces the deprecated DSHMC tool.
- **HID modes:** `SDF`, `GPJ`, `SXS`, `DS4Windows`, `XInput` (the default) and `CGP` (Common Gamepad, new in 3.15).
- **New settings:**
  - `DevicePairingMode` (`Auto` | `Custom` | `Disabled`)
  - `CustomPairingAddress`
  - `BluetoothOutputReportTransport`
  - `QuickDisconnectCombo` (default L1+R1+PS held for 1 s)
  - `WirelessIdleTimeoutPeriodMs` (default 300000)
  - `AutoRestartOnHidModeMismatch`
  - `IPCEnabled`
- **IPC and SDK:** shared-memory IPC with a .NET SDK (`Nefarius.DsHidMini.IPC` on NuGet). It provides raw reports in any mode, motion data, `SetHostAddress` / `PairToCurrentHost`, LEDs, rumble and disconnect.
- **Other additions:**
  - Calibrated motion
  - Battery reporting in XInput mode
  - Navigation controller support
  - Genuine-pad detection
  - Bluetooth diagnostic wizard (3.17.1)
  - Diagnostics export (3.20.1)

**Upgrading from 2.2:** run the newer setup on top of the old version. The release notes say "Previous versions do **not** have to be removed manually beforehand". Reboot if setup asks. It flags a pending reboot under `HKLM\Software\Nefarius Software Solutions e.U.\Nefarius DsHidMini Driver\RebootPending`. Settings are not migrated from v2's device properties **[UNVERIFIED]**.

**`nssmkig.sys` / `igfilter.inf`** is part of DsHidMini, not of a third-party app:

- The DsHidMini INF adds `LowerFilters = WUDFRd, nssmkig` to the DS3 devnode. The INF names it "Nefarius HID Devices filter driver".
- It is closed-source. The source suggests it reads the HID mode property at device start (issue #374). Its exact role is **[UNVERIFIED]**.
- **Keep it.**

### 2.2 BthPS3

**Releases.** The latest is `setup-v3.2.0` (2026-09-27), asset `Nefarius_BthPS3_Drivers_x64_arm64_v3.2.0.msi`. Earlier releases:

- v3.0.0 (2026-09-25)
- v2.17.0 (2025-02-26)

Up to v2.9 the assets were named `BthPS3Setup_x64.msi` / `BthPS3Setup_ARM64.msi`.

**What v3 changed:**

- Support for BTHX/BthMini radios (Intel PCIe).
- **Automatic recovery from stale PSM registration** (PR #149). This adds the settings `PsmRegistrationRetryDelay=5` and `PsmRegistrationRetryLimit=60`.
- Fixes for suspend and hibernate.
- A new installer with two methods: "Modern hot-plug" and "Legacy sequential".
- ETW diagnostics (3.2.0).

**Architecture:**

- `BthPS3PSM` is a Bluetooth **class** lower filter on `{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}`. It attaches only when the radio's transport is USB or BTHX.
- The installer registers a Bluetooth local service, `BthPS3Service` `{1cb831ea-79cd-4508-b0fc-85f7c85ae8e0}`, via `BluetoothSetLocalServiceInfo`; the installer calls it as `nefconc --enable-bluetooth-service`.
- Windows then creates `BTHENUM\{1cb831ea-…}_LOCALMFG…`, which shows up as **"Nefarius Bluetooth PS Enumerator"** and loads `BthPS3.sys`.
- That enumerator is the L2CAP server and the bus that creates `BTHPS3BUS\{53f88889-1aaf-4353-a047-556b69ec6da6}&Dev&VID_054C&PID_0268`, which DsHidMini binds to.

**Defaults** in `HKLM\SYSTEM\CurrentControlSet\Services\BthPS3\Parameters`:

| Setting | Default |
|---|---|
| `RawPDO` | 0 — must stay 0; 1 is only for Shibari and stops DsHidMini binding |
| `HidePDO` | 0 |
| `AdminOnlyPDO` | 0 |
| `ExclusivePDO` | 1 |
| `ChildIdleTimeout` | 10000 |
| `AutoEnableFilter` | 1 |
| `AutoDisableFilter` | 1 |
| `AutoEnableFilterDelay` | 10 |
| `IsSIXAXISSupported` | 1 |
| `IsNAVIGATIONSupported` | 1 |
| `IsMOTIONSupported` | 0 |
| `IsWIRELESSSupported` | 0 |

**Rules:**

- Use genuine Sony pads.
- **Never pair through Windows' Bluetooth dialog.** If you did, remove that entry.
- UAC must be enabled.
- USB pairing is the only supported method.

**Adapters:**

- The documented working list includes CSR 0A12:0001, ASUS BT400, Realtek RTL8761B, TP-Link UB400/UB500, Broadcom BCM20702, Intel 8087:07DC and Intel PCIe (on v3).
- Broadcom BCM20703 does not work.
- **MediaTek, AzureWave and Qualcomm are not listed either way.** Their behaviour, including the MediaTek `MTKBTFilterX64` lower filter, is **[UNVERIFIED]**.
- Radios below LMP 3 (Bluetooth 2.0+EDR) fail with `STATUS_DEVICE_POWER_FAILURE`.

**Known failure: the enumerator disappears.** BthPS3 issue #26 ("Driver not retained when migrating from Windows 11 22000 to 22449 and likely all build upgrades"):

- After a Windows build upgrade, "Nefarius Bluetooth PS Enumerator" is gone, even though the LocalServices registry entry survives.
- The fix is: uninstall BthPS3, reboot, install, reboot. `python -m dshub.system` then shows whether the enumerator is back.
- If it still doesn't appear, toggle the local service with nefcon **[UNVERIFIED workaround]**, then turn Bluetooth off and on:

  ```
  nefconc --disable-bluetooth-service --service-name BthPS3Service --service-guid 1cb831ea-79cd-4508-b0fc-85f7c85ae8e0
  nefconc --enable-bluetooth-service  --service-name BthPS3Service --service-guid 1cb831ea-79cd-4508-b0fc-85f7c85ae8e0
  ```

- **Insider builds hit this repeatedly.** `drivers.scan()` reports BthPS3 as `broken` in this state.
- Issue #127 (Windows 11 25H2, "filter driver access failed") ended the same way: the filter was not loaded, and a reinstall fixed it.

### 2.3 Pairing a DS3 for Bluetooth

1. **Over USB, DsHidMini writes the host address into the pad.**
   - It reads the radio address with `BluetoothGetRadioInfo` and sends **SET_REPORT Feature 0xF5** (wValue `0x03F5`).
   - The payload is 8 bytes: `01 00 A0 A1 A2 A3 A4 A5`, MAC most significant byte first.
   - It skips the write when the pad already stores that address.
   - The pad's own MAC is in GET Feature **0xF2** (17 bytes, MAC at offsets 4–9).
2. **Which setting controls it:** v3 uses `DevicePairingMode` (`Auto` by default; `Custom` uses `CustomPairingAddress`). v2.2 always auto-pairs on USB.
3. **Unplug the cable and press PS.** The pad then connects to the stored host.
4. **Enable input with Feature 0xF4:** `42 0C 00 00` starts input on USB, `42 0B 00 00` stops it, and `42 03 00 00` is used on Bluetooth.

**Clones (SHANWAN, PANHAI, Gasia):**

- BthPS3 matches pads by their Bluetooth name. The default `SIXAXISSupportedNames` already includes "PLAYSTATION(R)3 Controller", "PLAYSTATION(R)3Conteroller-PANHAI", the SHANWAN name, "PS3 GamePad", "PS3 Wireless Controller" and others.
- For an unknown clone, add its exact name to that REG_MULTI_SZ value.
- DsHidMini v3 officially supports only genuine DS3 and Navigation pads, plus two USB adapters.

**Can a user-mode app send 0xF4 or 0xF5? No, not while DsHidMini owns the device.**

- The physical pad sits under UMDF (`WUDFRd`), and the HID collections apps see are virtual.
- DsHidMini only answers a few feature requests: report 0x00 in SXS mode, report 0x12 in DS4Windows mode, and the force-feedback reports.
- So an app has to work through DsHidMini instead:
  - device properties (§2.4)
  - the JSON config
  - ControlApp
  - the IPC SDK

### 2.4 DsHidMini device properties (readable without admin)

The keys come from `dshmguid.h` (v2.2.282 and v3). DualShock PC Hub reads them in `dshub/system/ds3_pairing.py`.

| Key | Name | Type | Notes |
|---|---|---|---|
| `{A92F26CA-EDA7-4B1D-9DB2-27B68AA5A2EB},1` | `DEVPKEY_BluetoothRadio_Address` | UINT64 | Host address stored in the pad (read via GET 0xF5) |
| `{2BD67D8B-8BEB-48D5-87E0-6CDA3428040A},1` | `DEVPKEY_Bluetooth_DeviceAddress` | STRING | The pad's own MAC |
| `{3FECF510-CC94-4FBE-8839-738201F84D59},2` | `RO_BatteryStatus` | BYTE | See the next table |
| `{3FECF510-…},3` | `RO_LastPairingStatus` | NTSTATUS | v2; deprecated in v3 |
| `{3FECF510-…},4` | `RO_IdentificationData` | BINARY | Raw Feature 0x01 |
| `{3FECF510-…},5` | `RO_LastHostRequestStatus` | NTSTATUS | v3 |
| `{3FECF510-…},6…16` | v3 extras | — | IpcSlotIndex, DeviceAddressSynthesized, identification/clone heuristics, DeviceType, motion calibration, OutputReportStatus, InputReportMetricsVersion |
| `{6D293077-C3D6-4062-9597-BE4389404C02},2` | `RW_HidDeviceMode` | BYTE | v2: 1 SDF, 2 GPJ, 3 SXS, 4 DS4Windows, 5 XInput (v3 adds 6 CGP; v3 keeps the mode in the JSON file) |
| `{6D293077-…},3…6` | v2 output-rate / dedup / idle timeout | — | `,4` = OutputRateControlPeriodMs, default 150 |

DS3 battery byte values:

| Value | Meaning |
|---|---|
| `0x00` | Empty |
| `0x01` | Dying |
| `0x02` | Low |
| `0x03` | Medium |
| `0x04` | High |
| `0x05` | Full |
| `0xEE` | Charging |
| `0xEF` | Charged |

Linux maps levels 0–5 to 0, 1, 25, 50, 75 and 100 %.

Device interface GUIDs:

- v2: `{399ED672-E0BD-4FB3-AB0C-4955B56FB86A}`
- v3: `{16F3FE42-B710-4F67-B6EE-9A8D249C9CE5}`

### 2.5 DsHidMini HID modes: what a hidapi app can read

| Mode | VID:PID | Input report | Pressure | Battery | Motion |
|---|---|---|---|---|---|
| SDF | 054C:0268 | 0x01, 39 bytes | Yes | Device property only | No |
| GPJ | 054C:0268 (2 devices) | 0x01 gamepad + 0x02 joystick | Yes (report 2) | No | No |
| CGP | 054C:0268 | 10 bytes | No | No | No |
| **SXS** | 054C:0268 | 12 bytes, no report ID | Via **GetFeature(0x00)** (49-byte raw DS3 report) | Byte 30 of that report | Bytes 41–48 |
| DS4Windows | **7331:0001** vendor-defined | 0x01, 64 bytes, DS4 layout | L2/R2 only | Byte 30 | No |
| XInput (default) | **045E:02FF** behind `xinputhid` | 17 bytes | No | Battery-strength byte (3.15+) | No |

**SDF report layout (39 bytes):**

| Byte(s) | Contents |
|---|---|
| 1–4 | Sticks |
| 5 | Hat (low nibble, 8 = released); Triangle, Circle, Cross, Square in bits 4–7 |
| 6 | Select, L3, R3, Start, L2, R2, L1, R1 |
| 7 | PS (bit 0) |
| 8–9 | L2 / R2 analog |
| 10–19 | Pressure: Up, Right, Down, Left, L1, R1, Triangle, Circle, Cross, Square |

**SXS report layout (12 bytes, no report ID):**

| Byte(s) | Contents |
|---|---|
| 0 | Triangle, Circle, Cross, Square, L2, R2, L1, R1 |
| 1 | Start 0x01, Select 0x02, L3, R3, PS 0x10 |
| 3 | Hat |
| 4–7 | Sticks |
| 8–11 | Inverted (255 − value) Circle, Cross, L2, R2 |

**XInput mode and hidapi:**

- Reading XInput mode through hidapi is **[UNVERIFIED]**. Use the XInput API instead.
- In practice `XInputGetCapabilitiesEx` reports the DS3 on this machine as VID/PID 7331:0002.

**Best mode for a custom app: SXS.** It gives buttons and sticks in the report, plus pressure, battery and motion through feature 0x00. It is also Steam's native DS3 layout. The feature 0x00 offsets come from the source, not from hardware testing **[UNVERIFIED on hardware]**.

**Changing the mode in v3:**

1. Set `Devices["<MAC>"].HidDeviceMode = "SXS"` in `DsHidMini.json`. Writing to ProgramData probably needs admin **[UNVERIFIED]**.
2. Restart the device with `pnputil /restart-device "<instance id>"` (admin), or re-plug it. The HID mode is *not* hot-reloaded.

`ds3_pairing.set_hid_mode()` does both steps through one UAC prompt.

---

## 3. ViGEmBus, HidHide, VirtualPad

**ViGEmBus:**

- Archived on 2023-11-02 after a trademark conflict.
- v1.22.0 ("It's dead, Jim") is the last release. Its driver is unchanged from 1.21.442; only the updater was removed.
- The end-of-life notice says there is "no impact on existing installations except for the updater components".
- Safe to keep, and still required by DS4Windows 3.x and by this app's controller emulation.

**HidHide:**

- Maintained, but the last release is still v1.5.230.0 (x64 only). Its setup removes the old version and reboots.
- Open issue #215: on 25H2 the config UI/CLI can crash with `ERROR_INVALID_PARAMETER` when the whitelist registry data is corrupt.
- The fix from that thread: uninstall, delete `HKLM\SYSTEM\CurrentControlSet\Services\HidHide` as SYSTEM, reinstall.
- **If HidHide hides a pad, add DualShock PC Hub (or `python.exe`) to its allowed applications, or the hub cannot see that pad.**

**Nefarius VirtualPad (`nssvpd`, "Virtual Gamepad Emulation Bus G2"):**

- Nefarius's commercial successor to ViGEm, licensed to business partners. DSX v3 (Paliverse) installs it.
- "LICENSE EXPIRED" only affects DSX. Paliverse's fix is to set the clock to automatic, or reinstall so DSX renews the license.
- It does not affect DsHidMini, BthPS3 or native DS4/DS5 use. Leave it, or uninstall "Nefarius VirtualPad Driver Runtime" if you don't use DSX.
- The meaning of "G2" is **[UNVERIFIED]**.

**Bundled installers:**

- The DsHidMini MSI bundles igfilter, ControlApp, nefcon and its updater.
- Its optional "BthPS3 Wireless Drivers" feature only opens the BthPS3 download.
- There is no single all-in-one installer.
- Nefarius update manifests are at `https://vicius.api.nefarius.systems/api/nefarius/<DsHidMini|BthPS3|HidHide>/updates.json`.

### HidHide integration (`dshub/system/hidhide.py`)

Everything below comes from HidHide's source at tag `v1.5.230.0`.

**No admin needed.**

- The control device `\\.\HidHide` is created world-accessible (`SDDL_DEVOBJ_SYS_ALL_ADM_RWX_WORLD_RWX_RES_RWX`), and `HidHideCLI` runs as `asInvoker`. Hiding and unhiding therefore never trigger a UAC prompt.
- The device is **exclusive**: only one handle can be open at a time. Open it, act, and close it straight away. If HidHide's Configuration Client or DS4Windows has it open, the open fails.

**The driver is the source of truth.**

- `HKLM\SYSTEM\CurrentControlSet\Services\HidHide\Parameters` holds `WhitelistedFullImageNames`, `BlacklistedDeviceInstancePaths`, `Active` and `WhitelistedInverse`. It is protected with deny-all ACEs, so apps cannot read it.
- Read and write through IOCTLs instead: `CTL_CODE(0x8001, 2048+n, METHOD_BUFFERED, FILE_READ_DATA)`. The GET/SET pairs for the whitelist, blacklist, active and inverse flags are `0x80016000`–`0x8001601C`.
- **List format:** each string is NUL-terminated, followed by one final NUL. An empty list is a single NUL. This is exactly what `HidHideCLI` sends.
- **Booleans** are exactly 1 byte.
- `GET_*` accepts an output buffer larger than needed. We read lists in one call because the zero-length size probe fails on some 25H2 builds (HidHide #215).

**What to hide:** the HID *child* instance ID, e.g. `HID\VID_054C&PID_09CC&MI_03\8&1A2B3C4D&0&0000`. Matching is case-insensitive. HidHide only filters the HIDClass, XboxComposite and XnaComposite setup classes. Use `cm.interface_instance_id()` to map a hidapi path to its instance ID.

**What to allow:** the NT image path of the process that opens the pad, e.g. `\Device\HarddiskVolume3\Python312\pythonw.exe`. Matching is exact and case-insensitive; folders and wildcards don't work.

- Under a venv the real process is the base interpreter, which allows every script run with that Python.
- A frozen build allows only `DualShockPCHub.exe`.
- `QueryFullProcessImageNameW(..., PROCESS_NAME_NATIVE)` returns the path in the stored form.

**Timing:** access is checked only when a handle is opened. Apps that already hold the pad, Steam above all, keep it until the controller reconnects (replug, or Bluetooth off/on).

**DS3 under DsHidMini v3:**

- The XInput-mode child is `HID\VID_045E&PID_02FF&IG_00\…` in **HIDClass**, below the `xinputhid` filter, so HidHide attaches to it. (v2 used its own "Nefarius HID Devices" class, which HidHide never filtered.)
- HidHide's FAQ calls hiding XInput devices "not reliable".
- **The cleaner way to make the DS3 visible to nothing but our app is DsHidMini's *DS4Windows* mode.** Its vendor-defined `7331:0001` device is ignored by Steam and games. The hub reads it through hidapi (DS4 report layout) and feeds the virtual Xbox pad. HidHide isn't needed at all.

**Caveats:**

- Last release is 1.5.230 (2024). Master has unreleased fixes (#217).
- #215: the client and CLI crash on 25H2 build 26200.
- #208: entries from other apps can disappear. We only ever add or remove our own entries.

---

## 4. DS4Windows and other remappers

- **schmaldeo/DS4Windows:** archived 2026-03-05 with a "DISCONTINUATION" notice. The last release is v3.9.9 (2025-01-06).
- **Ryochan7/DS4Windows:** returns 404.
- **hbashton/DS4Windows ("DS4Windows 5"):** an active community fork created 2026-05-29.
  - Stable release: v4.0.2.3.
  - Pre-releases are unsigned release candidates that replace ViGEmBus with VIIPER + usbip-win2.
  - Trustworthiness **[UNVERIFIED]**.
- **One remapper per pad.** DSX, DS4Windows, Steam Input and DualShock PC Hub emulating the same pad means double input. Use HidHide to hide the physical device and allow only the remapper.

---

## 5. Firmware

**DualSense and DualSense Edge.** Sony's official Windows app is **PlayStation Accessories** v2.2.1, formerly "Firmware updater for DualSense wireless controller".

- [Page](https://controller.dl.playstation.net/controller/lang/en/2100004.html), which the old `…/fwupdater.html` URL redirects to.
- [Installer](https://fwupdater.dl.playstation.net/fwupdater/PlayStationAccessoriesInstaller.exe): about 77 MB.
- It updates over USB or Bluetooth. For the Edge it also manages profiles.
- The old `FWupdaterInstaller.exe` URL now returns 404.

Newest firmware per hardware type, from the community list `Paliverse/DualSense-List-of-Firmwares` (2026-06-10). Each binary was confirmed to exist on Sony's CDN, but the "latest" status is **[UNVERIFIED]**:

| Hardware type | Firmware |
|---|---|
| DualSense 000E | 0x0641 |
| DualSense 0004 | 0x0630 |
| DualSense 000B | 0x0630 |
| DualSense Edge 0044 | 0x0217 |

**DualShock 4 and DualShock 3:** Sony offers no PC updater. Only a console can update them.

---

## 6. Conflicts and pitfalls

- **Duplicate DS3 in Steam.** DsHidMini XInput mode, plus Steam, plus Microsoft GameInput shows one DS3 twice. This is a Steam/SDL bug, fixed upstream in SDL `c4cfb739` (2026-09-21) but not yet shipped in Steam. Workarounds: use SXS mode, uninstall GameInput, or disable Steam Input for Xbox pads.
- **DsHidMini's DS4Windows mode** exposes a vendor device, 7331:0001, that only DS4Windows reads, so HidHide is not needed in that mode.
- **Steam and DS4Windows.** Steam ignores DS4 pads while DS4Windows is running, unless DS4Windows runs under a renamed executable.
- **ScpToolkit (abandoned 2016)** replaces pad and Bluetooth dongle drivers with WinUSB/libusbK. This breaks DsHidMini and BthPS3. Use its Clean Wipe tool, reboot, then reinstall the Nefarius drivers. Leftover files with no active drivers are harmless.
- **Windows-paired DS3s.** A DS3 paired through Settings → Bluetooth breaks BthPS3 pairing. Remove that entry.

---

## 7. HID protocol reference (for the hidapi backend)

All offsets below include the report ID at byte 0.

### DualShock 3, USB report 0x01 (49 bytes)

| Bytes | Contents |
|---|---|
| 2 | Select 0x01, L3 0x02, R3 0x04, Start 0x08, Up 0x10, Right 0x20, Down 0x40, Left 0x80 |
| 3 | L2 0x01, R2 0x02, L1 0x04, R1 0x08, Triangle 0x10, Circle 0x20, Cross 0x40, Square 0x80 |
| 4 | PS 0x01 |
| 6–9 | LX, LY, RX, RY |
| 14–25 | Pressure: Up, Right, Down, Left, L2, R2, L1, R1, Triangle, Circle, Cross, Square |
| 30 | Battery (see §2.4) |
| 41–48 | Accelerometer X/Y/Z and gyro Z, big-endian |

### DualShock 4

| | USB | Bluetooth |
|---|---|---|
| Input report | 0x01, 64 bytes | 0x11, 78 bytes: +2 offset and a trailing CRC32. The pad starts with a minimal 0x01 report until feature **0x02** (or 0x05) is read. |
| Buttons | Byte 5: hat (low nibble), Square 0x10, Cross 0x20, Circle 0x40, Triangle 0x80. Byte 6: L1, R1, L2, R2, Share, Options, L3, R3. Byte 7: PS bit 0, touchpad bit 1. | Same, +2 |
| Triggers | Bytes 8 and 9 | +2 |
| Battery | Byte 30 | Byte 32 |

- **Battery byte:** the low nibble is the level in tens of percent and bit 4 means cable connected. When wired, 11 = full and 14/15 = error.
- **Firmware:** feature **0xA3**. `hw_version` is LE16 at byte 35 and `fw_version` is LE16 at byte 41.

### DualSense

| | USB | Bluetooth |
|---|---|---|
| Input report | 0x01, 64 bytes | 0x31, 78 bytes: +1 offset and a CRC32. Read feature **0x05** to switch the pad to it. |
| Status byte | Byte 53 | Byte 54 |

- **Status byte:** the low nibble is the level in tens of percent. The high nibble is 0 discharging, 1 charging, 2 full, or 0xA/0xB/0xF for errors.
- **Firmware:** feature **0x20**. Build date is at bytes 1–11 and build time at 12–19; `hw_version` is LE32 at 24, `fw_version` LE32 at 28 and `update_version` LE16 at 44.
- **Pairing info:** feature 0x09.

### References

- Linux [`hid-sony.c`](https://github.com/torvalds/linux/blob/master/drivers/hid/hid-sony.c)
- Linux [`hid-playstation.c`](https://github.com/torvalds/linux/blob/master/drivers/hid/hid-playstation.c)
- [dsremap reverse-engineering notes](https://dsremap.readthedocs.io/en/latest/reverse.html)
- DsHidMini `Ds3Types.h`, `HID.FeatureReport.c`, `dshmguid.h`

---

## 8. Auto-download endpoints (used by `drivers.check_latest`)

Send a `User-Agent` header. Unauthenticated GitHub API calls are limited to 60 per hour per IP. Each GitHub release asset also carries a `digest` (`sha256:…`), which `drivers.download` verifies.

| Component | Endpoint | Asset regex |
|---|---|---|
| DsHidMini | `https://api.github.com/repos/nefarius/DsHidMini/releases/latest` | `^Nefarius_DsHidMini_Drivers_x64_arm64_v(\d+\.\d+\.\d+)\.msi$` |
| BthPS3 | `https://api.github.com/repos/nefarius/BthPS3/releases/latest` | `^Nefarius_BthPS3_Drivers_x64_arm64_v(\d+\.\d+\.\d+)\.msi$` |
| HidHide | `https://api.github.com/repos/nefarius/HidHide/releases/latest` | `^HidHide_(\d+\.\d+\.\d+)_x64\.exe$` |
| ViGEmBus (frozen) | `https://api.github.com/repos/nefarius/ViGEmBus/releases/tags/v1.22.0` | `^ViGEmBus_(\d+\.\d+\.\d+)_x64_x86_arm64\.exe$` |
| nefcon | `https://api.github.com/repos/nefarius/nefcon/releases/latest` | `^nefcon_v(\d+\.\d+\.\d+)\.zip$` |
| .NET 10 Desktop | `https://dotnetcli.blob.core.windows.net/dotnet/release-metadata/10.0/releases.json` | `windowsdesktop.files[rid=win-x64]` |
| PlayStation Accessories | Fixed URL; detect changes via HEAD `ETag` / `Last-Modified` | — |

**Installed-version detection:**

- Uninstall registry keys (`DisplayName`/`DisplayVersion`).
- Nefarius's `HKLM\SOFTWARE\Nefarius Software Solutions e.U.\<product>\Version`.
- `DriverVer` in the driver store INF files.
- The live device tree (cfgmgr32).
- **Never** WMI `Win32_Product`: enumerating it triggers MSI self-repair of every installed package.

---

## Sources

- GitHub API: [DsHidMini releases](https://api.github.com/repos/nefarius/DsHidMini/releases) · [BthPS3 releases](https://api.github.com/repos/nefarius/BthPS3/releases)
- [nefarius/DsHidMini](https://github.com/nefarius/DsHidMini): README, driver sources, `dshmguid.h`, `docs/XINPUTHID.md`, `docs/STEAM_GAMEINPUT_DUPLICATES.md`, setup scripts, IPC SDK README
- DsHidMini docs: [How to install](https://docs.nefarius.at/projects/DsHidMini/v3/How-to-Install/) · [FAQ](https://docs.nefarius.at/projects/DsHidMini/v3/FAQ/) · [HID modes](https://docs.nefarius.at/projects/DsHidMini/v3/HID-Device-Modes-Explained/)
- [nefarius/BthPS3](https://github.com/nefarius/BthPS3): INFs, `BthPS3.h`, installer custom actions, BthPS3Util; [issue #26](https://github.com/nefarius/BthPS3/issues/26), [issue #127](https://github.com/nefarius/BthPS3/issues/127), [PR #149](https://github.com/nefarius/BthPS3/pull/149)
- BthPS3 docs: [How to install](https://docs.nefarius.at/projects/BthPS3/How-to-Install/) · [Compatible devices](https://docs.nefarius.at/projects/BthPS3/Compatible-Bluetooth-Devices/) · [FAQ](https://docs.nefarius.at/projects/BthPS3/Frequently-Asked-Questions/)
- [nefarius/nefcon](https://github.com/nefarius/nefcon) · [ViGEmBus](https://github.com/nefarius/ViGEmBus) · [ViGEm end of life](https://docs.nefarius.at/projects/ViGEm/End-of-Life/) · [HidHide](https://github.com/nefarius/HidHide) ([issue #215](https://github.com/nefarius/HidHide/issues/215)) · [VirtualPad](https://docs.nefarius.at/projects/VirtualPad/)
- [schmaldeo/DS4Windows](https://github.com/schmaldeo/DS4Windows) · [hbashton/DS4Windows](https://github.com/hbashton/DS4Windows)
- [Sony PlayStation Accessories](https://controller.dl.playstation.net/controller/lang/en/2100004.html) · [Paliverse/DualSense-List-of-Firmwares](https://github.com/Paliverse/DualSense-List-of-Firmwares)
- Linux [`hid-sony.c`](https://github.com/torvalds/linux/blob/master/drivers/hid/hid-sony.c) · [`hid-playstation.c`](https://github.com/torvalds/linux/blob/master/drivers/hid/hid-playstation.c) · [commit d829674](https://github.com/torvalds/linux/commit/d829674d29d7eb99aeb3ad11eba61d06cda7aff4)
