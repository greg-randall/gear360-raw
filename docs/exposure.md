# Exposure

How shutter speed and ISO are set on the SM-R210 through `st` commands, and why no real exposure is longer than about 1/6 s even when the camera says 1 s or 30 s. How to send `st` commands is in [commands.md](commands.md); read [safety.md](safety.md) before trying the long-exposure paths, since most of them hang the camera until a reboot.

## Shutter speed with setvar TV

```
st cap capdtm setvar TV <n> 4
```

`n = round(16 × log2(1/t))`, i.e. APEX Tv × 16. Checked against the EXIF of a bracket: TV 0, 16, 32 … 207 gave exactly 1 s, 1/2, 1/4 … 1/8000.

| TV | 0 | 16 | 32 | 48 | 63 | 79 | 95 | 111 | 127 | 143 | 159 | 175 | 191 | 207 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| shutter | 1 s | 1/2 | 1/4 | 1/8 | 1/15 | 1/30 | 1/60 | 1/125 | 1/250 | 1/500 | 1/1000 | 1/2000 | 1/4000 | 1/8000 |

`setvar TV` can't go below 0 this way. `setvar TV -16 4` gives `Invalid argument[3]=-16`. `setvar TV 0xFFFFFFF0 4` is accepted, but the value is read with strtol and clamped to 0x7fffffff, not −16. `getvar TV_MIN`, `BULBTIME` and `EXPOSURE_TIME` all read 0. The 16-bit form the app itself uses (e.g. `setvar TV 0xFFB0 4`, see below) is untested.

Internally the RTOS sets exposure in microseconds: a normal 1 s shot logs `SetVideoConfig : m_uiExposureTimeStill(1000000)`.

## setusr values

```
st cap capdtm setusr <setting> <value>
```

The value is `(setting index << 16) | option index`. The values we use:

| setusr | value | meaning |
|---|---|---|
| 0 (DIALMODE) | `0x00000004` | DIALMODE_SHUTTERSPEED (see below) |
| 1 (SHOOTINGMODE) | `0x00010004` | SHOOTINGMODE_MANUAL |
| 5 (ISO) | `0x00050001` | ISO 100 (`…0a` = ISO 800, `…00` = AUTO) |
| 30 (ISONR) | `0x001E0000` | high-ISO NR off |
| 31 (LTNR) | `0x001F0000` | long-exposure NR off |
| 64 (ISOAUTOMAX) | `0x00400000` | Auto-ISO max 125 |
| 117 (ADJUSTSHUTTERTYPE) | `0x00750001` | ADJUSTSHUTTERTYPE_ROLLING (default `0x00750000` = MECHA) |

DIALMODE has SMARTAUTO at index 1, so `setusr 0 4` (used in the 2021 scripts) selects SHUTTERSPEED, not MANUAL; MANUAL is 5. The 2021 shots still came out as Manual in EXIF because SHOOTINGMODE was set to 4 (MANUAL). Whether DIALMODE should also be 5 is untested.

## Option tables

The RTOS stores each setting's option names as a list in enum order. The order was checked against values known from 2021 (SHOOTINGMODE PROGRAM = 1 and MANUAL = 4, ISO 100 = 1 and 800 = 10, ISOAUTOMAX 125 = 0 and 1600 = 11, ISONR MID = 2), and every one matches.

| Setting | Options (index) |
|---|---|
| 4 IMAGEQUALITY | 0 SUPERFINE, 1 FINE, 2 NORMAL, 3 RAW, 4 RAW_SUPERFINE, 5 RAW_FINE, 6 RAW_NORMAL, 7 SRAW |
| 1 SHOOTINGMODE | 0 SMARTAUTO, 1 PROGRAM, 2 APERTURE, 3 SHUTTERSPEED, 4 MANUAL, 5 IMODE, 6 BULB, 7 CUSTOM, … |
| 0 DIALMODE | 0 MOVIE, 1 SMARTAUTO, 2 PROGRAM, 3 APERTURE, 4 SHUTTERSPEED, 5 MANUAL, 6 IMODE, … |
| 2 IMAGESIZE | 0–14 the NX sizes (28M … 2M), 15 DUAL (current), 16 DUAL_SMALL, 17 DUAL_WIDE, 18 SINGLE, 19 SINGLE_WIDE |
| 123 RAW_SAVE | OFF, ON |
| RAWQUALITY / RAW_BIT / RAW_PACK / SSIF_RAW | LOSSLESS/LOSSY, 14BIT/12BIT, PACK/UNPACK, OFF/ON |

So Bulb is `setusr 1 0x00010006`. For getting raws, see [raw-capture.md](raw-capture.md).

## The ~1/6 s cap

The "1 s" raw is really exposed for about 0.173 s. This was measured on a raw bracket (ISO 100, Manual: 1 s, 1/15, 1/250, 1/4000, 1/8000) as pixel-by-pixel ratios between consecutive raws, on pixels unclipped in both, black 4096 subtracted:

| Step | Expected | Measured (median, IQR) |
|---|---|---|
| 1/250 → 1/4000 | ×16.0 | ×16.2 (14.1–18.3) |
| 1/15 → 1/250 | ×16.7 | ×15.5 (13.6–17.5) |
| "1 s" → 1/15 | ×15.0 | ×2.59 (2.46–2.73), 12.5 M px |

1/15 × 2.59 ≈ 0.173 s. The JPEG EXIF still says 1 s, because EXIF records the request, not the exposure. `tools/raw2dng.py` copies ExposureTime from the JPEG, so DNGs of requests above ~1/6 s carry the requested value, not the real one.

### Why: the A7 exposure setter

Decompiled from the A7 firmware in Ghidra, the S5K2M8 driver's exposure setter `FUN_802428dc(this, mode, exp_us)` (with helper `FUN_802432d8`):

```
lines = exp_us × 480 000 000 / 1 000 000 / line_length
lines clamped to [6, frame_length − 6]
upper limit 4 × frame_length − 6 in capture modes 0x16, 0x23, 0x24
writes 0x0202 = lines & 0xFFFF
writes 0x0340 = frame_length × k & 0xFFFF, k = lines/frame_length + 1, rounded to 1, 2 or 4 in those modes
```

- The pixel clock is 480 MHz, which matches the sensor's PLL registers.
- It never touches 0x0702/0x0704 (the Samsung long-exposure shifters), and no code anywhere loads 0x702 as a constant.
- Still capture runs at 24.004 fps (41.66 ms/frame), so 4 frames ≈ 0.167 s, a ratio of 2.50 against 1/15, inside the measured IQR. The inference is that the still capture uses the 4× mode, so every request above ~1/6 s gives ~1/6 s.
- A raw series at 1/8, 1/4, 1/2 and 1 s would confirm it (predicted: 1/8 honoured, the rest flat at ~0.167 s). Not done yet.

### realexp

`st cap cis realexp <us>` converts a requested exposure into the real one, for the current sensor mode (output in the A7 log). In live view (frame_length 3470 × 9.617 µs/line):

| Requested µs | Real µs |
|---|---|
| 30 000 000 | 33 312 |
| 1 000 000 | 33 312 |
| 166 667 | 33 312 |
| 30 000 | 29 994 |
| 10 000 | 9 991 |

Requests are rounded to whole 9.617 µs lines, and anything longer is cut to (3470 − 6) lines = 33 313 µs, so live view is a 1× mode. Even 30 s gets no special path. It shows the mechanism, not the still-mode cap.

## The app's own shutter setting

```
st app set tv <v>
```

`<v>` takes the values from the app's usage text: `30s … 10s … 2.5s, 1.6s, 1.3s, 1s, 0.8s … 0.3s`, and plain numbers mean 1/x. The app converts to APEX and writes `VARIABLE_TV` as a 16-bit signed value: 30 s → `0xFFB0` (−80/16 = 32 s), 10 s → `0xFFCB`, 2.5 s → `0xFFEB`, 1.3 s → `0xFFFB`.

Which capture path runs depends on long-exposure NR (setusr 31), not on the shutter value:

| App shutter | LTNR | Path in the A7 log | Result |
|---|---|---|---|
| 1/8, 1/4, 0.5 s, 1.3 s, 2.5 s, 10 s, 30 s | OFF | `SetVideoConfig`, sensor mode 22 "Video Full for still capture (2912x2896)", 24 fps, `Video STill Exp time = <request>` | JPEG in ~1 s, clamped (≈1/6 s) |
| 30 s | ON (default after reboot) | `CMaterial_PP_Core_Still_LTNR_Image`, `SetStillConfig m_uiExposureTimeStill(32000000)`, `capExposure 32000 ms`, sensor "UD(2880x2880)" still mode | hangs after `SensorCb(2)`; reboot needed |

App `1s` (TV 0) programmed `Video STill Exp time = 125000` (1/8 s), while 0.5 s got 500000. This isn't explained and wasn't re-tested.

From the app's disassembly (`tools/appdisasm.py`), `UI_Operate_Start_Capture` sets common parameters and makes one `UI_Mm_Camera_Start_Capture()` call, with no long-exposure special case. `UI_Mm_Camera_Set_Bulb_Shot_Time(t)` and `UI_Mm_Camera_Stop_Long_Press_Capture()` exist but have no direct caller (likely NX leftovers). So the long exposure is decided entirely in the A7.

Open: whether a stock 30 s shot (phone app or camera menu, default settings) also hangs.

## Every long-exposure path hangs

Each of these ends the same way: the readout starts without waiting for the exposure (34–48 ms after `capExposure` on the Bulb, LTNR and rolling-shutter tests), then the capture hangs after readout at the switch to "post still" mode 8 (`SensorCb(2)`, then silence in the A7 log). No JPEG and no raw are written. Only a reboot recovers.

- Bulb (`setusr 1 0x00010006`, then `st key push s1; push s2; sleep 5; release s2; release s1`): always programs 30 s (`SetStillConfig m_uiExposureTimeStill(30000000)`, BULBTIME var = 0). It hung with the self-timer on, and again with the self-timer and LTNR both off. Key release logs nothing, and `capt bulb stop` gives `CAPTURE_COMMAND_BULB_STOP` but never reaches the "force trg SH" path in the A7's BulbStop.
- LTNR still path (LTNR on, app 10 s or 30 s): hangs the same way with the raw dump on or off, and the still frame never reaches the dump. The 10 s exposure was never programmed into the sensor.
- `st cap capt single start`: fires a capture directly on the capture processor, then stalls at the same point.
- Rolling shutter type (`setusr 117 0x00750001`): accepted, and it changes the code path (`capExposure : m_eDriveMode(4) eCapOption(1)`), but with LTNR on and 10 s it still hangs.

What was tried to un-stick it without a reboot, all without success:

| Command | Result |
|---|---|
| `st cap capt stop 1` / `0` / `-1` | `CAPTURE_COMMAND_STILL_STOP (0x0)`, then only `SetDriveMode(Single)` |
| `st cap capt stop 2` | `Change3AState: STILL_CAPTURING => IDLE (stopEmergently)`, AE restarts, app still stuck |
| `st cap capt stop 3` / `4` / `5` | `[SVC_NX] StopExposure`; nothing followed |
| `st cap capt stop 6` | LOCK3A_CANCEL → `3A_UNLOCK_FAIL : CapState:3` |
| `st cap capt liveview start` | live view, AE and AWB run again, but the app never gets `CAPTURE_READY` and stays on "Capturing" |
| `st cap capt bulb stop` | accepted, no effect (side effect: SHOOTINGMODE → PROGRAM) |
| `st cap capt sts s1cancel` | queued another CAPTURE_COMMAND_STILL_NORMAL plus `Invalid Parameter (0x1040002)` |
| `st cap cis md 10` | sensors switch cleanly to mode 10, console responsive, still stuck |
| `st cap capt init` | re-prints the usrlist table, no recovery |

While hung, `st cap ref tsk` showed no task blocked or spinning (the capture workers are idle waiting for messages), and `st cap ref int` showed the SSIF, PP and AWB interrupt counts frozen, so no frames reach the SoC. The A7 hasn't crashed; the still path waits for a frame-done event that never comes and no command supplies it. Restarting only di-camera-app would leave the A7 state stuck. A remote reboot works; see [safety.md](safety.md).

## The sensor: Samsung ISOCELL S5K2M8

There's no public datasheet. The evidence that this is the sensor:

- The A7 firmware has the driver class `CS5K2M8SXDriver`, `CIQ_SensorIF_S5K2M8SX` and the string `S5K2M8SX`. The "IMAGE SENSOR INFORMATION [SONY IMX147]" banner is almost certainly a leftover label (the IMX147 is a 20.7 MP 1/2.3" parallel-interface sensor, which doesn't fit).
- Published specs for the ISOCELL 2M8: 4208×3120 (13 MP), 1.34 µm pixels, 1/2.6". Each lens's 2912×2896 raw fits inside 4208×3120.
- The live register dump (`st cap cis rd_table`, in video mode) fits a 4208×3120 SMIA-style sensor: crop x 648–3575, y 116–3007 (0x344–0x34a), output 960×960 (0x34c/0x34e, binned).
- PLL pre-div 6 and multiplier 120 (0x304/0x306) give 480 MHz from a 24 MHz clock (the clock is assumed). `line_length_pck` 0x342 = 4616 and `frame_length_lines` 0x340 = 3470; 4616 / 480 MHz = 9.617 µs per line, and 3470 lines matches `st cap cis expinfo`. So the register map is standard SMIA++.

Exposure in that map is `coarse_integration_time` (0x0202, in lines) × line time, and `frame_length_lines` (0x0340) must be at least the exposure plus a margin. Both are 16-bit. While the camera was hung after the LTNR test, the registers read: 0x0342 = 0x1900 (6400 pck, 13.33 µs/line), 0x0340 = 0x0D47 (3399 lines), 0x0202 = 0x03FA (1018 lines = 13.6 ms), 0x0702/0x0704 = 0. With that line length the standard-register ceiling is 65535 × 13.33 µs ≈ 0.87 s.

Useful `st cap cis` commands found in the handler strings: `regr ADDR`, `regw ADDR DATA`, `fpga_regr` / `fpga_regw` / `fpga_sync` (the FPGA that merges the two sensors), `testpattern`, `temp`, `temp_log`, `sensor_rst` / `init` / `sleep` / `wakeup`, `realexp`, `chipid` (wants `a` or `b`, one per sensor). Register reads take the sensor letter, e.g. `regr a 0x0704`.

## Ideas for longer exposures (untested)

Neither has been tested properly, and both mean writing sensor registers by hand. The one write we attempted, to 0x0704 (below), ended with the camera powered off.

- Long-exposure shifters 0x0702 (frame-length shift) and 0x0704 (coarse-integration shift). An S5K3M5 phone driver enters "long shutter" mode by writing 0x0702 = 0x0704 = 0x0600 (×64) and reaches 32 s. The firmware never uses them, and whether the S5K2M8 honours them is unverified.
- A longer line length. The A7 setter clamps the line count to 16 bits but takes the line length from the current mode. Raising 0x0342 `line_length_pck` (with 0x0340 to match) lengthens each line, so in theory the ceiling is 65535 lines × 65535 pck ÷ 480 MHz ≈ 8.9 s. Risks: the FPGA or capture side may expect fixed line timing, so this could break readout or hang the A7, and the firmware rewrites 0x0342 on mode changes.

The one register write tried so far went badly. A single request chained `regr a 0x0704`, `regw a 0x0704 0x0100`, a read-back, `regw a 0x0704 0` and a read-back. No reply came back and the camera was found powered off. Whether the write crashed it is unknown, since nothing in the chain was logged. Send `regr` and `regw` as separate requests so the log shows which step failed.

A safer first write test is the test pattern, which is visible, harmless and reversible. Try the built-in `st cap cis testpattern` first. Then `regw a 0x0601 2` should show colour bars on lens a in live view, and `regw a 0x0601 0` undoes it. This checks the `regw` syntax and whether writes reach the sensor at all.

[`sensor-data/`](../sensor-data/) has Samsung's preliminary datasheet for the S5K3L6, a sibling sensor (1/3" 13 MP, same family and era). It isn't our sensor, but the registers we use match it: 0x0100 mode_select, 0x0104 grouped_parameter_hold, 0x0136 EXTCLK, 0x0200 / 0x0202 fine / coarse integration time, 0x0204 analogue gain, 0x020E digital gain, PLL 0x0301–0x030F, 0x0340, 0x0342, crop/output 0x0344–0x034F, 0x0900 binning. It gives integration time = (coarse_integration_time × line_length_pck + fine_integration_time) × pixel-clock period. It documents no 0x0702/0x0704, but its register list is cut down, so that neither proves nor disproves the S5K2M8 has them. Test pattern registers: 0x0601 test_pattern_mode (0 = off, 1 = solid colour, 2 = colour bars, 3 = fade-to-grey bars), 0x0602–0x0609 solid-colour R / Gr / B / Gb values, 0x060A–0x0611 cursors.

## In practice

Treat ~1/6 s as the longest real exposure. For darker frames, raise ISO on the slowest frame (e.g. 1/6 s at ISO 400–800) or average several 1/6 s frames.

Source: [Shutter speed: `st cap capdtm setvar TV <n> 4`](lab-notebook.md#shutter-speed-st-cap-capdtm-setvar-tv-n-4), [`setusr` values used and what they mean](lab-notebook.md#setusr-values-used-and-what-they-mean-decoded-from-the-xlsx-enum-lists), [Option tables (st numbering)](lab-notebook.md#option-tables-st-numbering--order-checked-against-known-values), [Long exposure tests](lab-notebook.md#long-exposure-tests-2026-10-10), [Recovering from the Bulb hang](lab-notebook.md#recovering-from-the-bulb-hang-what-the-capt-commands-do-2026-10-10), [Image sensor identified: Samsung ISOCELL S5K2M8](lab-notebook.md#image-sensor-identified-samsung-isocell-s5k2m8-2026-10-11), [A7 firmware in Ghidra: how exposure reaches the sensor](lab-notebook.md#a7-firmware-in-ghidra-how-exposure-reaches-the-sensor-2026-10-11), [Long exposures are capped at ~1/6 s: measured](lab-notebook.md#long-exposures-are-capped-at-16-s-measured-2026-10-12), [Sibling-sensor datasheet: S5K3L6](lab-notebook.md#sibling-sensor-datasheet-s5k3l6-2026-10-11)
