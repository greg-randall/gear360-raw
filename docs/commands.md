# Camera commands

How shell and `st` debug commands reach the Gear 360's hardware, how to send them over Wi-Fi, how the command catalogue in [`commands.csv`](../commands.csv) is organised, and which commands we found most useful.

Read [safety.md](safety.md) before running anything outside the `read` class. Several commands in the catalogue hang the camera app or have lost the camera.

## How `st` reaches the RTOS

The camera runs Tizen Linux on an A9 core and Samsung's capture firmware on a T-Kernel RTOS on an A7 core. It shares most of its firmware with the Samsung NX1/NX500, so the NX `st` tool works on it.

1. `/usr/bin/st` is a 4.8 KB stub that calls `shell_sndmsg()` in `libshell-command.so`. That library holds the built-in command table (gpio, hdmi, dump/readl/writel, pmu, log, LCD, clk, util, firmware, devman, stlcd, bat, rtc, misc, …).
2. `st key` and `st app` go to the camera app (`di-camera-app`) through a SysV message queue. All 10 `st app` commands we ran returned nothing to the shell; we think the app prints to the Linux system log (dlog) instead, so read `dlogutil -d -v time` after an `st app` command.
3. `st cap …` is passed as text to the A7 core: `shell_capture.cpp` sends the whole command line with `mcb_send()` in `libmulticore-bridge.so`, message type `SHELL_COMMAND`, over `/dev/d5_ipcc`.
4. On the RTOS, `CDebugConsoleProxy` receives it and hands it to the registered subcommand: `capdtm` → `CDataManagementService`, `capt` → `CCaptureDebugParser`, `seq`, `log`, `path`, and so on.

So any `st cap <anything>` text goes straight to the RTOS parser. Many RTOS commands print only to the A7 capture log, which `st cap log` dumps; check it after each one.

`st cap help` lists 17 RTOS subcommands: `back capdtm capmm capt cis fd fenx iq iqr live lockinfo log obj path ref seq ut`. `st cap ref help` shows a T-Kernel console (`mem/tsk/sem/…`, `ref reboot`, `ref stack`, `ref reg`).

## Sending commands

The camera has to be on its own hotspot, at `192.168.43.1`, with the SD card mod installed (see [raw-capture.md](raw-capture.md#install)).

ottokiksmaler's mod provides `cgi-bin/execute`, which runs its `rawcmd` parameter as a root shell command and returns HTML:

```
curl -s -G http://192.168.43.1:8888/cgi-bin/execute --data-urlencode "rawcmd=<command>"
```

Strip the HTML and NUL/CR bytes from its output.

Our `cgi-bin/run` (in `camera-www/cgi-bin/run`) returns plain text and can also collect the log lines a command produced. Its parameters are `cmd` (the command), `a7=1` (also return the new A7 capture-log lines) and `dlog=1` (also return the new dlog lines, where `st app` output goes):

```
GET /cgi-bin/run?cmd=<urlencoded>&a7=1&dlog=1
```

The command runs under `bash -c`. The response has the headers `X-Exit-Code` and `X-Duration-Ms`, and the body has sections starting with `@@REPLY`, `@@A7` and `@@DLOG`. It strips ANSI colour codes, `T2EX >> ` prompts from the T-Kernel console and other non-printable bytes. The web UI's Commands tab and debug panel use this CGI.

Send one command per request when trying anything risky, so a crash shows which step caused it.

## Getting help on the camera

There's no universal `--help`. What worked:

- `st` with no arguments lists the built-ins (`st help` shows 31).
- Most Linux built-ins accept `st <cmd> help`; some print usage when given no or wrong arguments.
- `st app help` and `dfmstool -h`.
- `st cap <sub> help` works for `capt`, `seq`, `iq`, `path`, `ref`, `ut` and `back`.
- `cis`, `live`, `fenx`, `obj`, `fd` and `log` printed nothing for `help`. We guess, unverified, that some print to the A7 log instead, so check `st cap log` straight after.
- Some print their options only when called without an argument, e.g. `st cap capt stop` → `1 : normal stop / 2 : not used / 3, 4 : illegal stop`.
- Many hidden `st cap` subcommands have help text only in the RTOS image strings, e.g. `st cap capt quality [sfine / fine / normal / raw / rawsfine / rawfine / rawnormal / sraw]` and `st cap seq dump [on/off] [names…]`.

## The catalogue

[`commands.csv`](../commands.csv) has one row per known command: 400 rows, with risk `read` 195, `set` 87, `action` 86, `never` 27, and 5 mixed (`read/set`, `set/never`, `set/action`).

| Column | Meaning |
|---|---|
| `family` | Group: `st top level`, `st app`, `st cap capt (CCaptureDebugParser)`, `st cap seq (capture sequencer)`, `st cap iq (IQ debug)`, `st cap capdtm (DataManagementService)`, `st cap live (live-view debug)`, `Other st cap subcommands`, `Other tools` |
| `command` | Command with argument pattern. `a \| b` means alternatives; `[..]` / `<..>` are arguments |
| `run` | The exact command line `runcommands.py` sends; blank means it won't run the row |
| `description` | What it does, from the help text or firmware strings |
| `risk` | `read` / `set` / `action` / `never` (see below); `read/set` means it depends on the argument |
| `source` | Where we found it, e.g. `libshell-command.so`, `di-camera-app`, `RTOS chunk-05`, `tool`, `help output` |
| `tested` | blank = not run; `yes` = ran and behaved as described; `partial` = ran, with unexpected or incomplete output; `failed` = error or hang |
| `tested_date` | Date of the last run (YYYY-MM-DD) |
| `result_notes` | What came back: output summary, surprises, argument quirks |
| `log` | Number of the camera-log file holding the raw output. Blank in this repo, because the camera logs aren't published (they contain the camera's Wi-Fi details) |

Where the commands come from: the `st` built-ins from the usage strings in `/usr/lib/libshell-command.so`; `st app …` from the strings of the camera app `di-camera-app` (the Gear 360's own set, not the NX `st app nx …` documented upstream); `st cap …` from the help text in the RTOS image; plus the camera's own tools `dfmstool`, `prefman`, `dlogutil` and `systemctl`.

## Risk classes

- `read`: help, status and dumps to the console. Safe to run in bulk, with the exceptions in [safety.md](safety.md#commands-that-lost-the-camera).
- `set`: changes a setting reversibly. Read the current value first and restore it afterwards.
- `action`: triggers a capture, test, file dump or hardware action. Run one at a time, supervised; it may hang the camera app and need a reboot.
- `never`: writes firmware, flash or calibration, changes voltages or clocks, reboots, formats or factory-resets. Don't run. The full list is in [safety.md](safety.md#never-run-these).

## runcommands.py

`tools/runcommands.py` runs catalogue rows through the `execute` CGI and records the results. For each selected row it snapshots the A7 log, sends the command, collects the reply and the new A7 log lines (and, for `st app` rows or with `--dlog`, the new dlog lines from a full `dlogutil -d -v time '*:V'` dump before and after), saves everything to the next free `camera-logs/NN_<slug>.txt`, and writes `tested`, `tested_date`, `result_notes` and `log` back to `commands.csv` straight away.

```
python3 tools/runcommands.py --dry-run
python3 tools/runcommands.py --family "st cap" --match help
python3 tools/runcommands.py --family "st top level" --skip "^st (misc|thread|log afinfo|firmware|readl|dump)"
```

| Option | Effect |
|---|---|
| `--family` | only rows whose family starts with this |
| `--match REGEX` | only rows whose `run` command matches |
| `--skip REGEX` | leave out rows whose `run` command matches |
| `--allow` | extra risk classes to allow, e.g. `set` or `set,action` |
| `--yes` | don't ask for confirmation on `set`/`action` rows |
| `--retest` | also re-run rows that already have a `tested` value |
| `--dry-run` | list what would run, then stop |
| `--dlog` | capture new dlog lines for every row, not just `st app` rows |
| `--timeout` | seconds per camera request (default 120) |
| `--haiku` / `--model` | classify each row with Claude Haiku as it runs (`claude -p --model haiku`, 30-60 s per row); off by default |

Safety behaviour:

- Only `read` rows run by default, and only rows with a `run` value.
- `set` and `action` rows need `--allow` and a y/n confirmation per command, unless `--yes`.
- `never` and `unknown` rows are never run, whatever `--allow` says.
- It checks the camera answers `echo ok` before starting. If a request times out or fails, the row is marked `failed`, the error is logged, and the camera is probed with `echo ok` (15 s). If the probe answers the run continues; if not, the CSV is saved and the runner exits naming the command.
- With `--haiku`, commands that Haiku spots in help output are added to the CSV with risk `unknown`, so they can't run until someone classifies them.

## Useful commands

### Exposure and settings

`st cap capdtm setvar TV <n> 4` sets the shutter speed, with `n = round(16 × log2(1/t))` (APEX Tv × 16). This was checked against EXIF from 1 s to 1/8000:

| TV | 0 | 16 | 32 | 48 | 63 | 79 | 95 | 111 | 127 | 143 | 159 | 175 | 191 | 207 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| shutter | 1 s | 1/2 | 1/4 | 1/8 | 1/15 | 1/30 | 1/60 | 1/125 | 1/250 | 1/500 | 1/1000 | 1/2000 | 1/4000 | 1/8000 |

Negative values are refused (`setvar TV -16 4` gives `Invalid argument[3]=-16`), and `0xFFFFFFF0` is clamped to 0x7fffffff, so 1 s is the longest request through this route. The camera app's own `st app set tv <v>` writes TV as a 16-bit signed value (30 s → `0xFFB0`); whether `setvar TV 0xFFB0 4` works is untested. EXIF records the request, and the real exposure is capped at about 1/6 s: see [exposure.md](exposure.md).

`st cap capdtm setusr <setting> <value>` changes a user setting, and `getusr <setting>` / `usrlist` read them back. The value is `(setting index << 16) | option index`. The RTOS stores each setting's option names in enum order, and that order matched every value known from 2021:

| Setting | Options (index) |
|---|---|
| 4 IMAGEQUALITY | 0 SUPERFINE, 1 FINE, 2 NORMAL, 3 RAW, 4 RAW_SUPERFINE, 5 RAW_FINE, 6 RAW_NORMAL, 7 SRAW |
| 1 SHOOTINGMODE | 0 SMARTAUTO, 1 PROGRAM, 2 APERTURE, 3 SHUTTERSPEED, 4 MANUAL, 5 IMODE, 6 BULB, 7 CUSTOM, … |
| 0 DIALMODE | 0 MOVIE, 1 SMARTAUTO, 2 PROGRAM, 3 APERTURE, 4 SHUTTERSPEED, 5 MANUAL, 6 IMODE, … |
| 2 IMAGESIZE | 0-14 the NX sizes (28M … 2M), 15 DUAL (current), 16 DUAL_SMALL, 17 DUAL_WIDE, 18 SINGLE, 19 SINGLE_WIDE |
| 123 RAW_SAVE | OFF, ON |

Values we have used:

| Command | Meaning |
|---|---|
| `st cap capdtm setusr 0 0x00000004` | DIALMODE 4 = SHUTTERSPEED (used by the 2021 scripts and the mod) |
| `st cap capdtm setusr 1 0x00010004` | SHOOTINGMODE_MANUAL |
| `st cap capdtm setusr 5 0x00050001` | ISO 100 (`…0a` = ISO 800, `…00` = AUTO) |
| `st cap capdtm setusr 30 0x001E0000` | high-ISO NR off |
| `st cap capdtm setusr 31 0x001F0000` | long-exposure NR off |
| `st cap capdtm setusr 64 0x00400000` | Auto-ISO max 125 |
| `st cap capdtm setusr 4 0x00040000` | IMAGEQUALITY SUPERFINE (the normal setting) |

The 2021 shots came out as Manual in EXIF because SHOOTINGMODE was 4. Whether DIALMODE should also be 5 is untested. Don't use `setusr 4` RAW options (they hang the app) or `setusr 1 0x00010006` (Bulb, also hangs); see [safety.md](safety.md).

`st cap lockinfo` prints the live 3A state (Av, Tv, ShSpdNum/Den, ISO, …), e.g. Av 36 (F2.2), Tv 81 (1/30), ISO 800. `st key click s2` presses the shutter. `st app set timer off` turns the 5 s self-timer off.

### Raw dump

| Command | Effect |
|---|---|
| `st cap seq dump on ssif` | every shot also writes the raw sensor frame to the SD root ([raw-capture.md](raw-capture.md)) |
| `st readl 0x8196a1c8` | read the post-processing dump flag; 0x10 = ssif dump on |
| `st writel 0x8196a1c8 0` | clear the flag: the clean way to turn the dump off, only after `readl` shows 0x10 |
| `st cap seq dump off ssif` | don't use: writes 0xFFFFFFEF to the flag and photos turn green until a reboot |

### Colour

| Command | Output |
|---|---|
| `st cap iq awb wbgain` | live AWB gains per lens, 256 = 1.0 |
| `st cap iq awb adjgain` | per-unit Adj and Diff gains per lens, 65536 = 1.0 |
| `st cap iq awb deltae` | the FrontCC colour matrix, RGB2YCC, the 19-point tone curve and the factory delta E check |

See [dng-colour.md](dng-colour.md) for what these values mean.

### Sensor

| Command | Output |
|---|---|
| `st cap cis expinfo` | sensor mode, exposure (µs, HD count × HD period), frame length, VD time, analog and digital gains; A7 log only |
| `st cap cis realexp <us>` | `Input time` vs `Real time` for a requested exposure in the current sensor mode (A7 log) |
| `st cap cis regr a 0x0342` | read a sensor register (`CIS_READ ADDRESS : 0x%04x, DATA : 0x%04x`); our tests named the sensor (`a`) before the address |
| `st cap cis info` | sensor info and per-mode frame rates; prints `SONY IMX147`, although the driver class is `CS5K2M8SXDriver` |

`st cap cis regw` writes sensor registers. The one test of it, chained with reads in a single request, ended with the camera powered off. See [safety.md](safety.md).

### Capture control

| Command | Result |
|---|---|
| `st cap capt stop` | prints the options: `1 : normal stop / 2 : not used / 3, 4 : illegal stop` |
| `st cap capt stop 1` (also `0`, `-1`) | `CAPTURE_COMMAND_STILL_STOP (0x0)`, then only `SetDriveMode(Single)` |
| `st cap capt stop 2` | `STILL_STOP (0x1)`: emergency stop, `Change3AState: STILL_CAPTURING => IDLE (stopEmergently)` |
| `st cap capt stop 3` (also `4`, `5`) | `STILL_STOP (0x2/0x3/0x4)`: `[SVC_NX] StopExposure` |
| `st cap capt liveview start` | sends dummy live-view callbacks and puts the capture state back to IDLE |
| `st cap capt status` | prints the usage plus a status dump (clocks and voltages) in the A7 log |

None of these recovered a hung capture. See [safety.md](safety.md#things-that-hang-the-camera-app).

### RTOS and calibration

| Command | Output |
|---|---|
| `st cap log` | the A7 capture log |
| `st cap ref tsk` | the T-Kernel task list (48 tasks, e.g. AeMain, AwbMain, LvTask, FrmCap, MCB_Receiver) and their wait states |
| `st cap ref int` | interrupt counts (in our runs only SSIF, PP and AWB were non-zero) |
| `st util dump` | writes `/mnt/mmc/dump.tgz` (an uncompressed tar despite the name): the prefman adjust partitions and both lens EEPROMs (`eeprom_a.bin`, `eeprom_b.bin`); catalogued as `action` |
| `dfmstool -a` | all factory adjust data (618 lines), including the per-lens EEPROM fields |
| `dfmstool -l` | factory process marks (pass / no-test / error per test) |
| `dfmstool -O <ID>` | one adjust item as an 8-byte integer, e.g. `dfmstool -O EEPA_OPTICAL_AXIS_01`; the float64 lens values need `-r` or the `st util dump` copy |

Source: [How `st` commands reach the RTOS (2026-10-10)](lab-notebook.md#how-st-commands-reach-the-rtos-2026-10-10), [Hidden `st cap` debug commands in the RTOS](lab-notebook.md#hidden-st-cap-debug-commands-in-the-rtos), [Option tables (st numbering) — order checked against known values](lab-notebook.md#option-tables-st-numbering--order-checked-against-known-values), [Shutter speed: `st cap capdtm setvar TV <n> 4`](lab-notebook.md#shutter-speed-st-cap-capdtm-setvar-tv-n-4), [`setusr` values used and what they mean (decoded from the xlsx enum lists)](lab-notebook.md#setusr-values-used-and-what-they-mean-decoded-from-the-xlsx-enum-lists), [Camera session 1 — read-only checks (2026-10-10)](lab-notebook.md#camera-session-1--read-only-checks-2026-10-10), [Camera web UI v1 (2026-10-10)](lab-notebook.md#camera-web-ui-v1-2026-10-10), [Long exposure tests (2026-10-10)](lab-notebook.md#long-exposure-tests-2026-10-10), [Recovering from the Bulb hang: what the `capt` commands do (2026-10-10)](lab-notebook.md#recovering-from-the-bulb-hang-what-the-capt-commands-do-2026-10-10), [Camera colour pipeline from `st cap iq awb` (2026-10-10)](lab-notebook.md#camera-colour-pipeline-from-st-cap-iq-awb-2026-10-10), [`st util dump`: pref + lens EEPROM dump (2026-10-10)](lab-notebook.md#st-util-dump-pref--lens-eeprom-dump-2026-10-10), [Command-testing batch 2: stopped early (2026-10-10)](lab-notebook.md#command-testing-batch-2-stopped-early-2026-10-10), [Command-testing batch 3: stopped early at `st thread` (2026-10-11)](lab-notebook.md#command-testing-batch-3-stopped-early-at-st-thread-2026-10-11), [A7 firmware in Ghidra: how exposure reaches the sensor (2026-10-11)](lab-notebook.md#a7-firmware-in-ghidra-how-exposure-reaches-the-sensor-2026-10-11), [Long exposures are capped at ~1/6 s: measured (2026-10-12)](lab-notebook.md#long-exposures-are-capped-at-16-s-measured-2026-10-12)
