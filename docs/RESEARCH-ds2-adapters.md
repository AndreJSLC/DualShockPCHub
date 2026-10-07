# DualShock 2 through PS2-to-USB adapters: IDs, mappings, report layouts

*Researched 2026-10-07. Sources: Linux `drivers/hid` (hid-ids.h, hid-quirks.c, hid-pl.c, hid-sjoy.c), SDL_GameControllerDB and SDL's built-in DB, RetroArch autoconfig files and its `input/connect` drivers, DsHidMini docs, usb.ids, and forum posts that include descriptor dumps. Anything marked **[UNVERIFIED]** could not be confirmed from a primary source.*

These adapters show up as plain HID joysticks (usage page 0x01, usage 0x04 or 0x05). None needs a driver for basic input. There is no standard layout: the **VID:PID chooses the mapping family**, and the HID report descriptor (where we can read it) gives the byte offsets.

**Notation.** `B#` = HID Button usage number (usage page 0x09), 1-based. That equals the DirectInput button index + 1 and the SDL `bN` index + 1. The SDL GUID `03000000vvvv0000pppp000000000000` holds VID and PID little-endian (hex chars 8-11 and 16-19). On Windows, SDL `aN` is the N-th axis the device has, in the fixed order X, Y, Z, Rx, Ry, Rz, Slider0, Slider1 (SDL_dinputjoystick.c sorts by DIJOFS offset). So on a 4-axis X/Y/Z/Rz device, a2 = Z and a3 = Rz. RetroArch's dinput axis numbers are fixed: 0 = X, 1 = Y, 2 = Z, 3 = Rx, 4 = Ry, 5 = Rz.

---

## 1. Adapters

| Adapter | VID:PID | Product / vendor strings seen | Pads per USB device | Family (§2) | Sources |
|---|---|---|---|---|---|
| Generic "Twin USB" dual PS1/PS2 adapter (PantherLord/PCS chipset, also sold as GreenAsia; most common cheap dual adapter) | 0810:0001 | `Twin USB Joystick` (hid-pl, DsHidMini). usb.ids: "Dual PSX Adaptor". `Twin USB Gamepad` **[UNVERIFIED]** | **2**: report IDs 1/2, two top-level collections, so Windows shows `&COL01` and `&COL02` | P | [1][2][3][7][9][11][12] |
| PCS dual "PCS" adapter | 0810:0002 | usb.ids: "Dual PCS Adaptor" | 2 **[UNVERIFIED]** (hid-pl FF only) | P? **[UNVERIFIED]** | [1][3][9] |
| Single-port PCS "PSX to PS3/PC" adapter | 0810:0003 | usb.ids "PlayStation Gamepad". SDL names: "USB Gamepad", "PlayStation Adapter". RetroArch: "PSX to PS3 Controller Adapter" | 1 | P | [5][8][9][10] |
| GreenAsia / MY-POWER "2In1" adapter | 0e8f:0003 | `MY-POWER CO.,LTD. 2In1 USB Joystick`, `GreenAsia Inc.    USB Joystick     `, `GASIA USB Gamepad` | 1 **[UNVERIFIED]** | S | [3][6][5] |
| WiseGroup MP-8866 "Super Dual Box" (sold by Mayflash and others) | 0925:8866 | `MP-8866 Dual USB Joypad`, manufacturer `WiseGroup.,Ltd` | **2**: report IDs 1/2 | W | [1][2][4][6][13][14] |
| WiseGroup MP-8800 Quad Joypad | 0925:8800 | usb.ids "MP-8800 Quad Joypad" | **4** (MULTI_INPUT) | W | [1][2][5][9] |
| SmartJoy PLUS (Gamtec/WiseGroup, sold by Lik-Sang) | 0925:0005 | `Gamtec.,Ltd SmartJoy PLUS Adapter` | 1 | W | [1][4][5][6] |
| Super Joy Box 3 | 0925:8888 | SDL name "PS2 Controller" | 1 | W | [1][4][5] |
| Mayflash Super Joy Box 3 Pro (Mayflash SKU PC037) | 6666:8801 | SDL name "USB Controller" | 1 | W | [1][4][5][17] |
| Super Dual Box Pro / SmartJoy Dual PLUS | 6666:8802, 6677:8802 | `WiseGroup.,Ltd SmartJoy Dual PLUS Adapter`. SDL: "TigerGame PlayStation Adapter" | **2** (MULTI_INPUT) | W, D-pad on buttons | [1][2][4][6][15] |
| Super Joy Box 5 Pro / TigerGame | 6666:8804 | `WiseGroup.,Ltd TigerGame PS/PS2 Game Controller Adapter` | **4** ("4 psx/ps2 to usb") | W, D-pad on buttons | [1][4][5][6][18] |
| WiseGroup Smart Joy PSX / "boom PSX to PC" | 6666:0667 | usb.ids "WiseGroup Smart Joy PSX, PS-PC Smart JoyPad" | 1 **[UNVERIFIED]** | Outlier | [5][8][9] |
| EMS "USB2" PS2 Controller Converter (Play.com) | 0b43:0003 | usb.ids "PS2 Controller Converter". SDL "EMS Production PS2 Adapter" | **2** (MULTI_INPUT) | P, D-pad on buttons | [1][4][5][9] |
| ShanWan PS1/PS2 USB adapter (e.g. Retro Fighters Defender PS receiver) | 2563:0575 | `ShanWan` / `USB WirelessGamepad ` (trailing space) | 1 | S, **pressure bytes** | [5][12] |
| Brook PS2 adapter | 0c12:0ef1 (SDL); 0c12:08f1 (gist) **[UNVERIFIED which is current]** | SDL "Brook PS2 Adapter" | 1 | Outlier (analog L2/R2) | [5][10] |
| Zeroplus PSX Vibration Feedback Converter | 0c12:0005, 0c12:0030 | `Zeroplus PS Vibration Feedback Converter ` | 1 | Outlier | [6][9] |
| Other SDL-listed PS adapters | 04d9:0002, 04d9:0f16, 05e3:0596, 0f30:010a and 19fa:8d91 ("3 In 1 Conversion Box"), 1a15:2262, 22ba:0107, 056e:2005 and 0925:1802 (Elecom), 0d9d:3011 (Sanwa), 16d0:0d04-0d07 (Bliss-Box 4-Play, one PID per port) | SDL names only | 1 each **[UNVERIFIED]** | see §2.4 | [5] |
| Mayflash "PC033" | **not found** | - | - | Mayflash's PC adapters sit on WiseGroup IDs (PC037 = Super Joy Box 3 Pro, PC035 = 3-in-1 Magic Joy Box); PC033's ID is **[UNVERIFIED]** | [17][19] |
| Hori PS2-to-PC adapter | **not found** | No Hori PS2-to-USB PC adapter turned up in any database | - | - | - |

Look-alikes that are **not** PS2 adapters and must not be claimed: 0e8f:3010 (Mayflash Saturn), 0e8f:3013 (HuiJia/Mayflash SNES/N64; both have MULTI_INPUT quirks), 0079:0006 (DragonRise "PC TWIN SHOCK" generic pad), 0925:03e8 (Wii Classic adapter).

---

## 2. Button / axis / D-pad mapping families

Every family uses the same face-button order: **B1 Triangle, B2 Circle, B3 Cross, B4 Square**. Families differ in shoulder order, Select/Start order and which axis is the right stick.

### 2.1 Family P: PCS / "Twin USB" (0810:0001, 0810:0003, 0b43:0003, 04d9:0002, 04d9:0f16)

| PS2 | Tri | Cir | Cross | Sq | L2 | R2 | L1 | R1 | Select | Start | L3 | R3 | Analog |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HID | B1 | B2 | B3 | B4 | B5 | B6 | B7 | B8 | **B9** | **B10** | B11 | B12 | not reported |

- D-pad: hat switch (0 = up, clockwise to 7 = up-left). On EMS 0b43:0003 the D-pad is buttons instead: B13 Up, B14 Right, B15 Down, B16 Left.
- Sticks: LX = X, LY = Y, **RX = Rz, RY = Z**. That is SDL `rightx:a3, righty:a2` on Windows and Linux, RetroArch dinput `r_x=5 (Rz), r_y=2 (Z)`, and matches the 0810:0001 descriptor (§3.1).
- 0810:0003 on Windows reads `rightx:a4, righty:a2` in SDL, so that device exposes an extra axis. RX = Rz still holds, but read the descriptor **[UNVERIFIED]**.

### 2.2 Family W: WiseGroup / Mayflash / SmartJoy (0925:8866, 8800, 8888, 0005, 1802; 6666:8801, 8802, 8804; 6677:8802; 05e3:0596; 1a15:2262)

| PS2 | Tri | Cir | Cross | Sq | L2 | R2 | L1 | R1 | Select | Start | L3 | R3 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HID | B1 | B2 | B3 | B4 | B5 | B6 | B7 | B8 | **B10** | **B9** | B11 | B12 |

- Start and Select are swapped compared with Family P. SDL, RetroArch dinput/udev/hid and the SmartJoy configs all agree.
- D-pad: hat on 0925:8866, 8800, 8888, 0005 and 6666:8801. Buttons **B13 Up, B14 Right, B15 Down, B16 Left** on 6666:8802, 6677:8802, 6666:8804 and 1a15:2262.
- Sticks: LX = X, LY = Y, **RX = Z, RY = Rz**. The MP-8866 descriptor declares X, Y, Z, Rz (§3.2), SDL maps it `rightx:a2 (Z), righty:a3 (Rz)`, and RetroArch agrees.
- 0925:8868 appears in SDL with L1 = B6 and R2 = B7. That looks like a bad entry **[UNVERIFIED]**.

### 2.3 Family S: "PS3-style" order (2563:0575 ShanWan, 0e8f:0003 MY-POWER 2In1)

| PS2 | Tri | Cir | Cross | Sq | L1 | R1 | L2 | R2 | Select | Start | L3 | R3 | PS/Home |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HID | B1 | B2 | B3 | B4 | **B5** | **B6** | **B7** | **B8** | B9 | B10 | B11 | B12 | B13 (ShanWan) |

- D-pad: hat. Sticks: 0e8f:0003 uses RX = Z, RY = Rz (RetroArch dinput axes 2 and 5; SDL Windows `a2/a5`). ShanWan uses SDL `a2/a3`; the usages are **[UNVERIFIED]**, so read the descriptor.
- 0e8f:0003 is also used by real pads (Piranha Xtreme, König, MaxFire Blaze2), and SDL lists one of them with the Family P layout. Key the mapping on the product string, not the ID alone.

### 2.4 Outliers (SDL Windows entries; single community entries, so **[UNVERIFIED]**)

| VID:PID | Mapping (HID button numbers) |
|---|---|
| 0e8f:1006, 0e8f:1009 ("Sony DualShock 2"), 6666:0667 | Like P, but Select B9, **L3 B10, R3 B11, Start B12**. 6666:0667 has the D-pad on B13-B16. RX/RY vary: a5/a2 (1006), a3/a2 (1009), a2/a3 (0667) |
| 0f30:010a, 19fa:8d91 (3-in-1 Conversion Box) | W buttons (Start B9, Select B10) with P axes (RX a3, RY a2) |
| 0c12:0ef1 Brook | Sq B1, Cross B2, Cir B3, Tri B4, L1 B5, R1 B6, **L2/R2 = axes a3/a4**, Start B10, L3 B11, R3 B12, Select B14, RX a2, RY a5 |
| 22ba:0107 Technology Innovation | Cross B1, Cir B2, Tri B3, Sq B4, L1 B5, R1 B6, L2 B7, R2 B8, Select B9, Start B10 |
| 056e:2005 Elecom P301U | Sq B1, Tri B2, Cross B3, Cir B4, L1 B5, R1 B6, L2 B7, R2 B8, L3 B9, R3 B10, Select B11, Start B12 |
| 0c12:0005 Zeroplus (RetroArch udev) | P face/shoulders, Start B9, L3 B10, R3 B11, Select B12. The SDL Windows entry is self-contradictory (B1 used twice) |
| 16d0:0d04-0d07 Bliss-Box 4-Play PSX/DS2 | Sq B1, Cross B2, Tri B3, Cir B4, Select B5, Start B6, L1 B7, R1 B8, L2 B9, R2 B10, D-pad B11 Up/B12 Down/B13 Left/B14 Right, L3 B15, R3 B16, RX a3, RY a4 |

No SDL entry for any of these adapters carries an axis-inversion flag (`~`). Y follows the HID convention (0 = up, 255 = down), the same as raw DualShock 2 data.

---

## 3. Raw input reports (as hidapi returns them on Windows)

hidapi puts the report ID in byte 0 for numbered reports. For unnumbered reports it strips the 0x00 that Windows prepends. All axes are 8-bit unsigned, centred on 0x7F or 0x80.

### 3.1 0810:0001 Twin USB: 8 bytes, report ID = port

Source: a 202-byte descriptor posted on the FreeBSD forum [11]. The post does not name the device, but it is two identical 101-byte collections, and 0810:0001 has a 202-byte descriptor and 8-byte low-speed packets [12]. RetroArch's `connect_ps2adapter.c` parses the same order, offset by a 1-byte prefix [10].

| Byte | Content |
|---|---|
| 0 | Report ID: 1 = port 1, 2 = port 2 |
| 1 | Z = **right stick Y** |
| 2 | Rz = **right stick X** |
| 3 | X = left stick X |
| 4 | Y = left stick Y |
| 5 | bits 0-3 hat (0-7; >7 = centred, null state); bit 4 Triangle (B1), bit 5 Circle (B2), bit 6 Cross (B3), bit 7 Square (B4) |
| 6 | bit 0 L2, 1 R2, 2 L1, 3 R1, 4 Select, 5 Start, 6 L3, 7 R3 (B5-B12) |
| 7 | 8 vendor-defined bits (ignore) |

Output (rumble): one 4-byte output report per port (report ID 1/2): `[0, 0, strong, weak]`, max 0x7F (hid-pl). There is no interrupt OUT endpoint, so it goes as SET_REPORT on the control pipe [3][12]. DsHidMini's table for this device lists 5 axes and 10 bytes, which conflicts with its own "8-byte packets" line and with the descriptor; trust the descriptor.

### 3.2 0925:8866 MP-8866: 7 bytes, report ID = port

Source: the 188-byte descriptor dump on linux-usb (2 × 94 bytes) [13].

| Byte | Content |
|---|---|
| 0 | Report ID 1/2 |
| 1 | B1-B8: Triangle, Circle, Cross, Square, L2, R2, L1, R1 (bit 0 first) |
| 2 | bits 0-3 B9-B12: Start, Select, L3, R3; bits 4-7 hat (0-7, >7 centred) |
| 3-6 | X (LX), Y (LY), Z (**RX**), Rz (**RY**) |

Output: a 3-byte vendor report (usage 0xFF00:01). hid-sjoy writes `[0x01, weak on/off, strong 0-255]` for this family [4]. Other single-port WiseGroup boxes (0925:0005, 0925:8888, 6666:8801) probably use the same body without the report ID **[UNVERIFIED]**.

### 3.3 2563:0575 ShanWan: 27 bytes, no report ID, **exposes pressure**

Source: DsHidMini, from a live device [12b].

| Byte | Content |
|---|---|
| 0 | bit 0 Triangle, 1 Circle, 2 Cross, 3 Square, 4 L1, 5 R1, 6 L2, 7 R2 |
| 1 | bit 0 Select, 1 Start, 2 L3, 3 R3, 4 PS; bits 5-7 always 1 (mask 0x1F) |
| 2 | low nibble hat, 0 = up clockwise, 0x0F = neutral |
| 3-6 | LX, LY, RX, RY (rest 0x7F) |
| 7-18 | Pressure 0-255: Right, Left, Up, Down, Triangle, Circle, Cross, Square, L1, R1, L2, R2 |
| 19-26 | Ignore (not motion) |

Rumble: 8 bytes on interrupt OUT, `02 08 <right 0-255> <left 0-255> FF 00 00 00`. While no pad is linked the write is never acknowledged, so use a short timeout [12b].

### 3.4 0810:0003 single PCS adapter: inferred

RetroArch's `connect_psxadapter.c` reads buttons at the same relative place as the 0810:0001 driver, and it detects digital mode from a stick byte equal to 0x7F [10]. That fits the §3.1 layout **without** the report-ID byte: Z, Rz, X, Y, hat|B1-4, B5-12, vendor. RetroArch's analog-axis offsets in that file look copied from the dual driver, so treat this layout as **[UNVERIFIED]** and confirm it with the descriptor.

### 3.5 Pressure-sensitive buttons

- **Not exposed** on 0810:0001 (4 axes, 12 buttons, 8 vendor bits; DsHidMini: "DualShock 2 pressure is not forwarded") or on 0925:8866 (4 axes, 12 buttons).
- **Exposed** on ShanWan 2563:0575 (12 bytes, §3.3).
- **Claimed by the vendor** for Super Joy Box 3 Pro, Super Dual Box Pro and Super Joy Box 5 Pro. The retail text describes the Super Dual Box Pro's pressure as an axis assignable to two of the 12 buttons. How it shows up in the HID report is **[UNVERIFIED]** and may need the vendor driver.
- Brook 0c12:0ef1 reports L2/R2 as axes in SDL. Whether those are real pressure values is **[UNVERIFIED]**.
- raphnet's PS1/PS2-to-USB adapter does not support pressure yet ("Not at the moment") [16].

---

## 4. Recommended default mapping for unknown adapters

Base it on what most SDL DB entries for these adapters share, and on the most common chipset (0810, Family P):

| PS2 | Default HID source | Fallback / notes |
|---|---|---|
| Triangle, Circle, Cross, Square | B1, B2, B3, B4 | Identical across families P, W and S |
| L2, R2, L1, R1 | B5, B6, B7, B8 | Family S (PS3-style) uses L1 B5, R1 B6, L2 B7, R2 B8 |
| Select, Start | B9, B10 | WiseGroup VIDs 0x0925, 0x6666, 0x6677: Start B9, Select B10 |
| L3, R3 | B11, B12 | |
| D-pad | Hat switch (0 = N, clockwise; >7 = centred) | No hat and 16 buttons: B13 Up, B14 Right, B15 Down, B16 Left. Hat centred and X/Y pinned at 0x00/0xFF: digital mode (§5) |
| Left stick | X, Y | No inversion |
| Right stick | **RX = Rz, RY = Z** (Family P) | For WiseGroup VIDs and 0e8f:0003 use RX = Z, RY = Rz |
| Analog button | Not reported | Only LED state can be inferred (digital-mode heuristic) |

Selection order: (1) exact VID:PID plus product-string table (§1/§2); (2) VID-level family (0x0810 P, 0x0925/0x6666/0x6677 W, 0x2563 S); (3) the default above. Give the user overrides for "swap Start/Select", "swap L1/L2 rows" and "swap right-stick axes", or a press-each-button calibration step. Many IDs are reused by unrelated pads.

---

## 5. Quirks

1. **One USB device, several pads.** Linux sets `HID_QUIRK_MULTI_INPUT` on 0810:0001 (with `SKIP_OUTPUT_REPORTS`), 0925:8800 and 6677:8802 (both with `NOGET`). hid-sjoy sets it through driver_data on 0925:8866, 0b43:0003 (both with `SKIP_OUTPUT_REPORTS`) and on 6666:8802 and 6666:8804 (with `NOGET` and `SKIP_OUTPUT_REPORTS`). 6666:8801 is `NOGET` only [2][4]. On Windows each top-level collection becomes its own HID path (`...&col01`, `...&col02`), so hidapi enumerates one entry per pad. Group the entries by the shared instance path to know they are one adapter. The port is the report ID or the collection index.
2. **NOGET (WiseGroup family).** The original MP-8866 commit says "HID_QUIRK_NOGET is necessary for it to respond to input" [14]. Today's kernel keeps NOGET on 0925:8800, 6666:8801, 8802, 8804 and 6677:8802. Never call `hid_get_input_report` or `hid_get_feature_report` on these; only read interrupt reports.
3. **Analog vs digital mode.** If the pad's ANALOG LED is off (or it is a PS1 digital pad), 0810-family adapters report the D-pad on X/Y as 0x00/0xFF, leave the hat centred and park the right stick at 0x7F. RetroArch detects this with `data == 0x7F` and maps the D-pad from the axes; its udev Twin USB config maps the D-pad to axes [10][7]. Prompt the user to press ANALOG. Some "Pro" boxes claim to be able to force analog mode **[UNVERIFIED]**.
4. **Hat neutral value.** The descriptor declares logical 0-7 with the Null State flag, so any value >7 (typically 0x0F, sometimes 0x08) means centred.
5. **Reused IDs.** 0810:0001 is "reused by countless non-adapter gamepads" [12]; 0810:0003 by the Trust GM-1520 pad [8]; 0e8f:0003 by Piranha Xtreme, König and MaxFire pads [3][9]; 2563:0575 by ShanWan pads and the iPega PG-9099 [5][12b]; 0c12:0005 by Intec Xbox and InterAct pads [9][5]. Confirm with the product string and descriptor shape (for example two collections, 12 buttons, 4 axes) before labelling a device "DualShock 2".
6. **0810:0001 probes the pad only at USB power-up.** Plug the controller in first, then replug USB. A missing diode (D3) on some boards under-powers the pad, and wireless receivers often fail [12].
7. **Report sizes and rate.** 0810:0001 is low-speed, 8-byte reports every 10 ms. MP-8866 sends 7 bytes. ShanWan sends 27 bytes (Windows ReadFile gives 28, with the leading 0). Polling hidapi faster than about 100 Hz gains nothing on the 0810 parts.
8. **Rumble on 0810:0001.** hid-pl drives force feedback through the first port's output report only; the motor maximum is 0x7F [3].

---

## Sources

1. Linux `drivers/hid/hid-ids.h`: https://github.com/torvalds/linux/blob/master/drivers/hid/hid-ids.h
2. Linux `drivers/hid/hid-quirks.c`: https://github.com/torvalds/linux/blob/master/drivers/hid/hid-quirks.c
3. Linux `drivers/hid/hid-pl.c` (0810:0001, 0e8f:0003 strings, FF): https://github.com/torvalds/linux/blob/master/drivers/hid/hid-pl.c
4. Linux `drivers/hid/hid-sjoy.c` (WiseGroup/EMS quirks, FF): https://github.com/torvalds/linux/blob/master/drivers/hid/hid-sjoy.c
5. SDL_GameControllerDB: https://github.com/mdqinc/SDL_GameControllerDB/blob/master/gamecontrollerdb.txt and SDL built-in DB: https://github.com/libsdl-org/SDL/blob/main/src/joystick/SDL_gamepad_db.h
6. RetroArch autoconfig (dinput/udev/hid/android `.cfg`: Twin_USB_Joystick, 2In1_USB_Joystick, MP-8866_Dual_USB_Joypad, wisegroup_ltd_smartjoy_dual_plus_adapter, Gamtec SmartJoy_PLUS, MY-POWER 2In1, Zeroplus, DualShock2_WiseGroup, Bliss-Box): https://github.com/libretro/retroarch-joypad-autoconfig
7. RetroArch udev Twin USB config: https://github.com/libretro/retroarch-joypad-autoconfig/blob/master/udev/Twin_USB_Joystick.cfg
8. Gamepad VID/PID list (nondebug gist): https://gist.github.com/nondebug/aec93dff7f0f1969f4cc2291b24a3171
9. usb.ids: http://www.linux-usb.org/usb.ids
10. RetroArch `connect_ps2adapter.c`, `connect_psxadapter.c`, `joypad_connection.h`: https://github.com/libretro/RetroArch/tree/master/input/connect
11. FreeBSD forum, 202-byte dual-joystick descriptor: https://forums.freebsd.org/threads/usbhid-accessing-multiple-joysticks-in-one-report.53155/
12. DsHidMini, Twin USB adapter notes: https://github.com/nefarius/DsHidMini/blob/master/docs/TWIN_USB_ADAPTER.md. 12b: ShanWan adapter: https://github.com/nefarius/DsHidMini/blob/master/docs/THIRD_PARTY_HID_ADAPTER.md
13. linux-usb list, MP-8866 descriptor dump: https://www.spinics.net/lists/usb/msg05323.html
14. Kernel commit "USB: Wisegroup MP-8866 Dual USB Joypad": https://git.gitlab.arm.com/linux-arm/linux-vs/-/commit/e65335ef187c9cbc50bbc56be0fe966b593beb49
15. Kernel commit "HID: add support for Super Dual Box Pro": https://android-kvm.googlesource.com/linux/+/66ebf66e497094f2c3fb3107d309c6a753beb0ff
16. raphnet PS1/PS2 to USB adapter: https://www.raphnet-tech.com/products/psx_to_usb/index.php
17. Super Joy Box 3 Pro drivers (Mayflash PC037): https://archive.org/details/super-joy-box-3-pro-drivers
18. ArcadeControls forum (Super Joybox 5, 4 ports): https://forum.arcadecontrols.com/index.php/topic,66238.0.html
19. Mayflash 3 in 1 Magic Joy Box (PC035): https://www.mayflash.com/product/PC035.html
20. SDL DirectInput axis ordering: https://github.com/libsdl-org/SDL/blob/main/src/joystick/windows/SDL_dinputjoystick.c
