# Lab notebook

This is the project's working notebook, kept in date order with its dead ends, corrections and guesses. For the cleaned-up version of each topic, start with the [README](../README.md) and the other files in `docs/`.

Not published with this repo, but referred to below:
- `camera-logs/NN_*.txt`: raw output of every camera command we ran (they contain the camera's Wi-Fi details). The findings from each are written up here.
- `resources/`: the original 2021 project folder (photos, SD card backups, upstream clones).
- `sample-code/`: our clones of the upstream repos and forks (all linked in the README credits) and saved copies of the relevant GitHub issue threads.
- `firmware/`: Samsung's R210 firmware and source bundle. Get them from https://nxfiles.nx.tc/files/Gear360/R210_2017/ and unpack the firmware with ge0rg's `slp-firmware.py` (https://github.com/ge0rg/samsung-nx-hacks).
- `calibration/`: decompiles and disassembly of Samsung code. Rebuild them from your own firmware copy with `tools/disasm.py`, `tools/a7disasm.py`, `tools/appdisasm.py` and `tools/ghidra_scripts/DecompileAt.java`.
- `captures/`: our photos and raw dumps. A selection is attached to the GitHub Release.
- `TODO.md`, `COMMANDS.md`: the project's task list and command-catalogue guide. The catalogue itself is `commands.csv`, and its guide is now [commands.md](commands.md).

---

# Gear 360 (2017, SM-R210) hacking: project notes

We first worked on this camera in October 2021: an SD-card mod from ottokiksmaler, manual shutter control through `st cap capdtm setvar TV`, 14-stop JPEG brackets merged to HDR, and dual-fisheye stitching in PTGui and Hugin. RAW capture never worked then. The project restarted on 2026-10-10, and everything below dates from then on.

## Key findings from 2021 (verified)

### Shutter speed: `st cap capdtm setvar TV <n> 4`

`n = round(16 × log2(1/t))`, i.e. APEX Tv × 16. Verified against the EXIF of a 2021 14-shot bracket (360_0166–0179): TV 0,16,32…207 produced exactly 1 s, 1/2, 1/4 … 1/8000.

**Caveat (2026-10-12):** that check was against EXIF, which records the requested time. Measured from raw files, anything requested above ~1/6 s is really ~1/6 s; see "Long exposures are capped at ~1/6 s: measured" below.

| TV | 0 | 16 | 32 | 48 | 63 | 79 | 95 | 111 | 127 | 143 | 159 | 175 | 191 | 207 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| shutter | 1 s | 1/2 | 1/4 | 1/8 | 1/15 | 1/30 | 1/60 | 1/125 | 1/250 | 1/500 | 1/1000 | 1/2000 | 1/4000 | 1/8000 |

Our 2021 scratch notes had this table wrong in places; the values above are the corrected ones.

### `setusr` values used and what they mean (decoded from the xlsx enum lists)

| setusr | value | meaning |
|---|---|---|
| 0 (DIALMODE) | `0x00000004` | DIALMODE_SHUTTERSPEED (see the correction under "Option tables") |
| 1 (SHOOTINGMODE) | `0x00010004` | SHOOTINGMODE_MANUAL |
| 5 (ISO) | `0x00050001` | ISO 100 (`…0a` = ISO 800, `…00` = AUTO) |
| 30 (ISONR) | `0x001E0000` | high-ISO NR off |
| 31 (LTNR) | `0x001F0000` | long-exposure NR off |
| 64 (ISOAUTOMAX) | `0x00400000` | Auto-ISO max 125 |

Value format is `(setting index << 16) | option index`.

## Upstream review (2026-10-10)

Fresh clones are in `sample-code/` (git-ignored). Layout:

- `sample-code/<repo>`: the seven known repos, current HEAD
- `sample-code/forks/`: forks that add real content
- `sample-code/related/`: repos linked from issues
- `sample-code/issues/`: 39 relevant issue threads saved as markdown (body plus all comments)

### Changes since the 2021 copies in `resources/`

Only two of the seven repos changed.

- **nx500_nx1_modding**: 9 new commits (2022–2025), all by Georg Lukas (ge0rg), who now seems to be the active maintainer. Relevant ones:
  - `stapp` / `stapp.c` (2023): sends `st` commands straight to the camera app's SysV message queue (`msgget(0x8828)`, 208-byte buffer) instead of spawning `st`. Much faster, but it can't read replies. Issue #123 says `st` takes 0.3–0.7 s per call and can crash the camera if called too often. That may explain flaky long brackets.
  - `DFMS Commands.md` (2025): full `dfmstool` help. It can send PTP commands, run DFMS scripts and read/write **adjust (calibration) data**. On the NX500 that includes CIS (sensor) data such as clamp level, pixel counts and shutter-speed offset, plus ISO gain tables. Writing is flagged as dangerous.
  - `prefmandumpread/` (2024): Python parser for prefman dump files.
  - `ssh-server/` (2022): Dropbear SSH/SFTP/SCP for the camera.
  - README now recommends NX-KS2 (mirror: https://nxfiles.nx.tc/files/NX-KS-mod/) and links Georg's blog https://op-co.de/blog/tags/samsung-nx/.
- **Gear-360-File-Access-from-Android-phones**: 4 commits (2023–24) adding a `setdate` CGI for time sync. Nothing relevant to exposure.

### Forks with real additions (cloned to `sample-code/forks/`)

| Fork | Last push | What it adds |
|---|---|---|
| WApaperplane/NXWA-nx500_modding | **2026-10-10** (today) | NX500 reverse engineering, docs in Chinese: 3D LUT table format, the Picture Wizard pipeline, `di-camera-app` internals, an "attribute bus". This is the most active low-level ISP work found so far. Unrelated history to upstream |
| niluss/gear360_gallery_mod | 2023-01 | Gear 360 gallery with a 3D viewer, pinch zoom, unzipped `src/` of the mod |
| hasenbalg/gear360-2017-mods | 2019-04 | AJAX web UI: ISO picker, shutter-mode setter, self-timer, time-lapse |
| bluedskim/gear360-2017-mods | 2021-05 | Photo list, preview and download page |
| robhubi/gear360_modding | 2025-11 | `my-timelapse.sh`, changelog |

### Repos linked from issues (cloned to `sample-code/related/`)

- **ge0rg/samsung-nx-hacks** (+ wiki): the SLP firmware format (used by the Gear 360) and `tools/slp-firmware.py` to unpack it, plus a model/CPU table. The Gear 360 is listed as **DRIMeVs**.
- **lansysart/gear360-telnet.usbshell-mod** (2026-01): Gear 360 **2016** (SM-C200). Telnet in normal boot mode, and joins your own wifi as a client via `wpa_supplicant`. Uses a `dfms.tg` / `nx_ft.adj` launch path that differs from ours.
- **mewlips/nx-remote-controller-mod** (2017): NX live-view streaming. Linked in gear360_modding #18 as a possible way to get a live preview.

### Leads for RAW and low-level control

- **Nobody has public RAW output from a Gear 360.** I found no RAW/SRW/Bayer mention in any Gear 360 repo or issue. The only RAW talk is about the NX500, where RAW is a normal menu feature.
- **The camera's own stitcher** is `libdi-arc-imagestitch.so`, which has `CFisheyePanorama::loadCalibrationDat` (gear360reveng #8). That means factory per-unit lens calibration exists on the camera, which could feed our own stitching.
- **Where `st cap capdtm` is actually handled is unknown.** ge0rg (nx500 #123) couldn't find the "DataManagementService" string in any Linux binary. My guess is that it lives in the RTOS side: the NX cameras run a µITRON/TRON RTOS on partitions `rtos` / `rtos_data` (`rom.bin`) alongside Linux (nx500 #13, #15). If so, RAW capture control is probably in the RTOS too, and the useful way in is through `st` / IPC / `dfmstool` rather than Linux drivers. Unverified.
- **Long exposures**: an open question since 2017 (gear360reveng #5, gear360_modding #12). Nobody has reported exposures longer than 1 s.
- **Firmware update from telnet** (gear360_modding #10): `mount -o bind /sdcard/ /opt/usr/media/`, then `/usr/sbin/fw_upgrade_start <file>.bin`. The same thread mentions SMACK (the security module) blocking some changes.
- **Live preview via OSC** (gear360_modding #18): suggests the Open Spherical Camera `getLivePreview` command; links pyOSCapi and hpd/OpenSphericalCamera.
- **People**: ge0rg (Georg Lukas, op-co.de), ottokiksmaler (no longer active), vasile-gh, usumfabricae (found the stitch library), WApaperplane, lansysart.

## Web research report (2026-10-10)

Full report: `gear360-capture-research.html` in the project root. It is git-ignored by the `*.html` rule, so it lives on disk only. Its new findings, checked where cheap:

- **R210 source bundle exists on a mirror.** https://nxfiles.nx.tc/files/Gear360/R210_2017/Source/ lists `SM-R210_Opensource.zip`, which the report gives as 1.09 GB; I confirmed the listing but not the size. The report's author read the ZIP remotely. It holds an inner `SM-R210_opensource.zip` containing `SM-R210_packages.tar.gz` (GPL/LGPL source RPMs) and `HOW_TO_BUILD.txt`, which refers to a separate `SM-R210_kernel.tar.gz` that is **not** in the listing. Gear360_OSS says Samsung never released R210 source, so this mirror contradicts it. The kernel is what matters for the sensor/MIPI drivers, so the open question is whether it's in there.
- **The mirror also has R210 firmware.** https://nxfiles.nx.tc/files/Gear360/R210_2017/ has `R210GLU0ARB2_180201_1739_REV00_user.bin`, the same firmware the camera runs. It can be unpacked with `sample-code/related/ge0rg_samsung-nx-hacks/tools/slp-firmware.py` to get the rootfs and the RTOS image for offline reverse engineering.
- **NX kernel sources**: https://codeberg.org/dvdkon/samsung-nx-linux has DRIMeIV/DRIMeV kernels with NX1 and NX500 branches, but no R210 branch. NX Files also mirrors the NX1 and NX500 source archives.
- **`/dev/d5_mipi`**: from gear360reveng #7 (C200; saved in `sample-code/issues/`). The Samsung camera binary talks to the sensor through `/dev/d5_mipi` and other `d5_*` nodes. The driver source would be in the kernel tarball.
- **Bulb sequence (NX500 only so far)**: patxitron/NX500_intervalometer does `st key push s1`, `sleep 0.3`, `st key push s2`, `sleep N`, then `st key release s2`, `sleep 0.3`, `st key release s1`, capped at 480 s on the NX500. The NX500 `capdtm` also has `VARIABLE_BULBTIME`. **Untested on the R210**, but it's the cheapest experiment for exposures longer than 1 s: set `SHOOTINGMODE_BULB` (option index 6 in the decoded list), then push/hold/release.
- **Caution**: on a C200, `st app nx capture single` rebooted the camera (gear360reveng #7).
- The report missed the ge0rg/stapp/dfmstool and NXWA leads above; the two sources complement each other.

### Suggested next steps

1. Download `SM-R210_Opensource.zip` (about 1 GB) and check for the kernel and for `d5_*` / sensor drivers.
2. Download the R210 firmware and unpack it with `slp-firmware.py`. Then grep the rootfs for `RAW_SAVE`, `SRW`, `DataManagementService`, `capdtm`, and find which binary or RTOS image owns them.
3. On the camera: dump `st cap capdtm varlist` (the R210 VARIABLE_* list; we only have the NX500 one), then try the Bulb sequence and `setusr 123 0x007B0001` (RAW_SAVE_ON), and watch the SD card and `/tmp`.

## R210 source bundle (examined 2026-10-10)

Downloaded to `firmware/source/` (git-ignored). Contents:

- `SM-R210_Opensource.zip`: 1,090,226,877 bytes, SHA-256 `5e9d2c1eab0f5b3db88eeb0368a749ab83f1862927375bdd1e5936465c725f69`. `unzip -t` passes. No published hash exists to compare against.
- It contains three inner archives, all dated 2017-04-07:
  - `SM-R210_libnl-headers.zip`
  - `tools.zip`: toolchains `arm-2010q1` and `linaro-4.7.3`
  - `SM-R210_opensource.zip`, which holds:
    - `HOW_TO_BUILD.txt`
    - `SM-R210_packages.tar.gz` (669 MB): Tizen build rootstrap with source RPMs. **Not examined yet.**
    - `SM-R210_kernel.tar.gz` (130 MB, 44,829 files): **the kernel is included.** The web research report was wrong about this.

**It really is Gear 360 (2017) code, not a mislabelled C200 bundle.** The kernel defconfig is `drime5_nx360globe_defconfig`, the headers switch on `CONFIG_PROJECT_NX360GLOBE`, and there are `gpio_map_nx360*.h` files. I take NX360GLOBE to be Samsung's internal codename for the Gear 360 (2017). `HOW_TO_BUILD.txt` says "used in the Samsung NX1 Series" and is dated 2016-02-25; it's a reused NX1 template, which explains the odd date. Extracted parts are in `firmware/source/extracted/sm-r210/`. The full file list is `firmware/source/extracted/kernel_filelist.txt`.

**What's in the kernel tarball:**

- `linux-3.5/` with `arch/arm/mach-drime5`, `drivers/media/video/drime5/` (cmdq, ep, hevc, ipcc, lock, mipi_csis / csim / csidsi and their DMA, mptop, sma, srp, tsu) and the matching `include/media/drime5/*/d5_*_ioctl.h` and `_type.h` headers. These are the `/dev/d5_*` drivers. They cover MIPI transport, DMA and inter-core messaging (`ipcc`); I found **no image sensor driver on the Linux side**.
- `multicore-bridge-header/`: the shared interface between the **Linux core (Cortex-A9)** and the **RTOS core (Cortex-A7)**. `ipcc_raw_int_id.h` defines A9↔A7 interrupt IDs, including `RAW_A9_TO_A7_S1` / `_S2`, which look like shutter half and full press; "RAW" here means raw interrupt, not raw image. This backs up the guess that capture and sensor control live on the A7/RTOS side.
- `prefman/include/`: prefman and DFMS adjust-data structures (`dfms_adjdata_struct.h`, `pref_*.h`).
- `emmc_bootloader/`, `device-init/` (the "M4 image": display and MIPI init), `initramfs_images/`, `filesystem/`.

**RAW support is built into the capture interface:**

- `CaptureImgType.h` defines encoders `eCAPTURE_ENC_JPEG`, `eCAPTURE_ENC_RAW_ONLY` and `eCAPTURE_ENC_JPEG_SRW`; image formats RAW and YCC; and buffer types `BAYER`, `RAW_COMPRESS` and `SECC` (split R/Gr/Gb/B planes).
- RAW bit depths run 8 to 16, Bayer orders RGGB / GRBG / BGGR / GBRG, and packing can be nonpack, pack or compress.
- There's an `stCAPTURE_SRWDATA` with SRW maker-note data, `rawStatistic[12]` and `shutterSpeedNum/Den`.
- `mm_camera_data_type.h` has `MM_CAMERA_STILL_ENC_SRW` / `SRW_JPEG`, `MM_CAMERA_CAPTURE_BULB`, `MM_CAMERA_SHOOTINGMODE_BULB`, `MM_CAMERA_IOCTL_REG_APEX_CONVERT_TV`, and, most importantly, these **IMAGEQUALITY** values:
  - `IQ_RAW_ONLAY` (RAW only)
  - `IQ_SFINE`, `IQ_FINE`, `IQ_NORMAL`
  - `IQ_SFINE_RAW`, `IQ_FINE_RAW`, `IQ_NORMAL_RAW`
  - `IQ_SRAW`

  So RAW is probably chosen through **image quality**, not only the `RAW_SAVE` flag we tried in 2021.

**Caveat: the numbering doesn't match the camera's `st` numbering.** In this header IMAGEQUALITY is setting 3 and shooting-mode P is option 0. In the camera's `usrlist`, IMAGEQUALITY is setting 4 (`IMAGEQUALITY_SUPERFINE` = `0x00040000`) and PROGRAM is option 1. The `mm_camera` layer and `st cap capdtm` use different tables, so these values can't be copied across directly. `st` prints the option *name* when you `getusr`, so on the camera we can step through `setusr 4 0x0004000N` and read back which N is a RAW option.

Gear360_OSS's statement that "Samsung did not release R210 source" is wrong; this bundle is it.

## R210 firmware unpacked (2026-10-10)

`firmware/bin/R210GLU0ARB2_180201_1739_REV00_user.bin`: 226,487,079 bytes, SHA-256 `81765495…015d8324`, which **matches** the hash published in Gear360_OSS. Unpacked with `python3 -I sample-code/related/ge0rg_samsung-nx-hacks/tools/slp-firmware.py -x -o unpacked <bin>`. LZO partitions were decompressed with `lzop -dc` (installed 2026-10-10 via `sudo apt install lzop`).

**Firmware version:** the header reads `SMR210 firmware 0.81 (SMR210GLU0ARB2 VER_Rev0.7)`. Version 0.81 matches the `Software: 0.81` in the 2021 photos' EXIF, so **the camera was very likely already on ARB2**. The "0.84" in Gear360_OSS's XML is a different label. This replaces my earlier worry about a version mismatch.

Partitions in `firmware/bin/unpacked/`:

| Chunk | Size | What it is |
|---|---|---|
| 00 | 6.5 MB | Linux 3.5 uImage, built 2017-06-13 (main kernel) |
| 01 | 53 KB | Bootloader stage (ARM code; strings mention `nvd_app`, `/dev/mmcblk0p2/3`) |
| 02 | 4.1 MB | Linux 3.5 uImage, built 2017-10-23 (probably the firmware-update / recovery kernel) |
| 03 | 6.8 MB | Linux 3.5 uImage, built 2016-08-31 |
| 04 | 149 KB | Unknown binary data |
| 05 | 12.9 MB | **RTOS image for the A7 core** (ARM code with a debug monitor: DUMP/MODIFY commands) |
| 06 | 138 MB LZO → 301 MB | **rootfs**, ext4. Tizen 2.2.0 "Magnolia". Extracted to `fs_rootfs/` with 7z (7,122 files, clean) |
| 07 | 6.2 MB LZO → 105 MB | **/opt**, ext4. Extracted to `fs_opt/` with `debugfs rdump` (849 files + 143 symlinks + 192 directories, which matches the used inode count; 7z failed on the symlinks) |
| 08 | 20 KB | `PAGECACHELIST`: list of files to preload |
| 09 | 51 MB LZO → 134 MB | **Hibernation snapshot** (swap image with `SWSUSP1`): a RAM image the camera resumes from for fast boot |

**First look at the RTOS image (chunk-05)** — strings only, a detailed search is the next TODO item:

- It holds `product/DataManagement/Manager/{UserData,Variable/VariableData,DataLock}.cpp` and `m_pcDataManagementService`. **This is where `st cap capdtm` is handled.** It answers ge0rg's question in nx500 #123, and confirms that settings and capture live on the RTOS side, not in Linux.
- It has a full **Bulb** capture path: `SHOOTINGMODE_BULB`, `BulbStop`, `CRecipeBook_NX1_Still_Bulb.cpp`, `eSTILL_RECIPEBOOKID_BULB`, and `CMaterial_PP_Core_Still_Bulb_Image*/Black*` (bulb exposure with **black-frame subtraction**), plus a `CCaptureDebugParser::bulb` debug command.
- It has Gear 360-specific pipeline names: `nx360_lensA_pp`, `nx360_lensB_pp`, `nx360_vfull_ssif`.

## Firmware search results (2026-10-10)

Searched `fs_rootfs/`, `fs_opt/`, `chunk-05.bin` (RTOS), `chunk-09.img` (snapshot) and `chunk-00.bin` (kernel) for `RAW_SAVE`, `IMAGEQUALITY`, `IQ_RAW`, `SRW`, `capdtm`, `SHOOTINGMODE_BULB`, `CCaptureDebugParser`, `DataManagement`, `setusr` and `usrlist`.

- **Every capture and settings term is only in the RTOS image (`chunk-05.bin`).** On the Linux side only `save_crash_info.sh` / `save_log_info.sh` mention `capdtm` (they call `st cap capdtm usrlist`). `SRW` matches in Linux libraries (`libcapture-fw-prod.so`, `libmmf-camcorder.so`, `libdi-alg-imagestitch.so`, `prefman`, …) are mostly substring noise and haven't been checked properly. `IQ_RAW` (from the source headers) doesn't appear anywhere in the firmware.
- Working files are in `firmware/bin/unpacked/`:
  - `chunk-05.strings.txt` — every string with its offset
  - `chunk-05.strings-plain.txt` — the same without offsets
  - `st_cap_help_blocks.txt` — every `usage:` help block, with 45 lines of context each

### Option tables (st numbering) — order checked against known values

The RTOS stores each setting's option names as a list in enum order. I checked this against values known from 2021 (SHOOTINGMODE PROGRAM = 1 and MANUAL = 4, ISO 100 = 1 and 800 = 10, ISOAUTOMAX 125 = 0 and 1600 = 11, ISONR MID = 2); every one matches. Values below are `(setting << 16) | option` for `st cap capdtm setusr`:

| Setting | Options (index) |
|---|---|
| 4 IMAGEQUALITY | 0 SUPERFINE, 1 FINE, 2 NORMAL, **3 RAW, 4 RAW_SUPERFINE, 5 RAW_FINE, 6 RAW_NORMAL, 7 SRAW** |
| 1 SHOOTINGMODE | 0 SMARTAUTO, 1 PROGRAM, 2 APERTURE, 3 SHUTTERSPEED, 4 MANUAL, 5 IMODE, **6 BULB**, 7 CUSTOM, … |
| 0 DIALMODE | 0 MOVIE, 1 SMARTAUTO, 2 PROGRAM, 3 APERTURE, **4 SHUTTERSPEED, 5 MANUAL**, 6 IMODE, … |
| 2 IMAGESIZE | 0–14 the NX sizes (28M … 2M), 15 DUAL (current), 16 DUAL_SMALL, 17 DUAL_WIDE, 18 SINGLE, 19 SINGLE_WIDE |
| 123 RAW_SAVE | OFF, ON |
| RAWQUALITY / RAW_BIT / RAW_PACK / SSIF_RAW | LOSSLESS/LOSSY, 14BIT/12BIT, PACK/UNPACK, OFF/ON |

So **RAW + SuperFine JPEG = `st cap capdtm setusr 4 0x00040004`** and **Bulb = `setusr 1 0x00010006`**. Both are still untested on the camera.

**Correction:** DIALMODE has SMARTAUTO at index 1, so `setusr 0 4` (used in the 2021 scripts and the mod) selects **SHUTTERSPEED**, not MANUAL. ottokiksmaler's comment `4-shutter, 5-manual` was right; "possible bug 5" above was my mistake. The 2021 shots still came out as Manual in EXIF because SHOOTINGMODE was set to 4 (MANUAL). Whether DIALMODE should also be 5 is untested.

### Hidden `st cap` debug commands in the RTOS

The RTOS has help text for many `st cap` subcommands beyond `capdtm`. The full text is in `st_cap_help_blocks.txt`. Most relevant:

- **`st cap capt [command]`** ("Capture Debug Command"):
  - `single start`, `conti`, `burst`, `aeb`, `bulb`, `stop`
  - **`quality [sfine / fine / normal / raw / rawsfine / rawfine / rawnormal / sraw]`**
  - `size [full / n1…n4 / w1…w4 / s1…s4]`
  - `nr [off / ltnr / adnr]`, `hdr [off / on / art]`, `ael` / `afl`, `iqstub [ae/af/awb/iqif/all] [on/off]`
  - `mcb [category] [setting] [len] [data]`, `event`, `status`, `report`
- **`st cap seq [cmd]`** (capture sequencer):
  - **`dump [on/off] [names…]`**, where names include **`ssif`** (sensor interface), `pp`, `aeawb`, `lrc`, `sub`, `ldc`, `rsz_*`, `jpg_*`, `hdr`
  - `stilltype [0/1/2]`: both lenses, lens A only, or lens B only
  - `gpu`, `gpumemcp` and `gpusttyp`, which control on-camera stitching
- **`st cap log`** (dump/clear the A7 core's log, or turn off the A7 console) and **`st cap path dump [ep]`** (dump registers).
- Also present: `st cap back`, `st cap face`, `st cap fenx [lv/still/mv]`, `st cap live [isplog / mipi …]`, plus "Capture Unit Test Command" and "EFS" help blocks.

**Raw-dump code paths that write to the SD card** (`/mnt/mmc` = SD card):
- `/mnt/mmc/ssif_front_%dx%dx%d_%d_10bit(16bit).raw` and `ssif_rear_…`: sensor-interface dumps, which probably come from `st cap seq dump on ssif`
- `/mnt/mmc/RAW_%04d_%s_%dx%d.raw` ("Raw dump - img address is %X"), with mode names still / live / fast_af / fhd_*crop
- `blackraw.raw`, `targetraw.raw`, `resultraw.raw`, `EFS_%03d.raw`, `active_align_check_raw_%02d.raw` (factory calibration)

SRW encoding is present too: `## ALLOC SRW BUFFER`, `BACKEND_ENCODE_SRW_COMPLETION`, `SRW MEMORY FULL`.

**Factory "adjust capture"** (`CAdjustAdapter`, `AdjustCapture4IQ`) prints `sensor mode, pathvalue, imgOpt, iris, ShutterUs= %d(Us), svalue`. In other words, a factory capture path that takes the shutter time directly in **microseconds**. How it's invoked isn't known yet (`st cap … adjust`?).

## How `st` commands reach the RTOS (2026-10-10)

From the rootfs and RTOS strings, plus `readelf` on `/usr/bin/st`:

1. `/usr/bin/st` (4.8 KB) is a stub that calls `shell_sndmsg()` in **`libshell-command.so`**. That library holds the built-in command table (`top_cmd_list`: gpio, hdmi, dump/readl/writel, pmu, log, LCD, clk, util, firmware, devman, stlcd, bat, rtc, misc, …). `st key` and `st app` go to the camera app through a SysV message queue (the one `stapp` uses).
2. **`st cap …` is different.** `shell_capture.cpp` sends the whole command line to the A7 core via `mcb_send()` in **`libmulticore-bridge.so`**, using message type `SHELL_COMMAND`, over `/dev/d5_ipcc` ("Cann't execute capture command over MCB!", "Possiblly, A7 core is not running correctly!").
3. On the RTOS, `CDebugConsoleProxy` receives it ("usage: st cap [command] [param] / Supported capture commands / %s") and hands it to the registered subcommand: `capdtm` → `CDataManagementService`, `capt` → `CCaptureDebugParser`, `seq`, `log`, `path`, `back`, `fenx`, `live`, …

So **any `st cap <anything>` text is passed straight through to the RTOS parser**, and running `st cap help` (or `st cap` plus an unknown word) on the camera should print the RTOS's own list of supported subcommands. That's cheaper than disassembling it.

The bridge also defines other message types: `ADJUST_MODE_START/STOP`, `ADJUST_PC_DATA`, `ADJUST_CVS_DATA`, `LOG_*`, `ATTR_REQUEST/SET`, `COMMAND`, `FIRMWARE_UPDATE_*`.

**Factory "adjust capture" (`CAdjustAdapter`)**, the microsecond-shutter path. Strings in order: `capture`, `ST Command RECV`, `Not Match command..`, then the parameter printout (`sensor mode, pathvalue, imgOpt, iris, ShutterUs, svalue`), then subcommands `debug / adjust / still / burst / live / ud4k / vfaf / stdaf / dzoom`. There's also "capture debug command argc is too few, bigger than 5", plus `type`, `conti`, `burst_dump`, `param`, `finish`.

It also has **`CAdjustAdapter::dumpImage`**, which writes `bayer`, `knee`, `YCbCr`, `YYCC` or `YCbr` images to **`/mnt/mmc/%d_%d_%dx%d_%s.%s`** ("%s File Dump Start!! … Dump Done!!"). That's a factory capture that can **save the Bayer image to the SD card**, with the shutter set directly in µs.

How it's invoked is not clear from strings. It's either a `st cap` subcommand whose name sits in a table we can't see as text, or the DFMS adjust channel (`ADJUST_MODE_START`, `dfmstool`). Next step is on the camera: `st cap help`, then try `st cap capture` / `st cap adj` / `st cap adjust` and read the errors. If that fails, load `chunk-05.bin` into Ghidra (ARM, little-endian; load address still to be found) and follow the cross-references from the `CAdjustAdapter::captureCommandEx` string.

## R210 package archive (examined 2026-10-10)

`SM-R210_packages.tar.gz` (669 MB) is in `firmware/source/extracted/`. Full listing in `packages_filelist.txt` (43,411 entries) and the source RPM names in `srpm_list.txt`.

- **73 source RPMs, all generic GPL/LGPL Tizen packages**: eglibc, gcc 4.6.4, busybox 1.17.1, bluez, glib2, systemd, dbus, connman, pulseaudio, alsa, ffmpeg 1.0, gst-ffmpeg, libexif 0.6.21, EFL (elementary/edje/eina), and so on. **There's no Samsung camera code**: no capture framework, `st`, prefman, multicore bridge or camera app. Those are proprietary and only exist as binaries in the firmware. The only media-related packages are `libexif`, `mmfw-sysconf` (multimedia framework config) and `ffmpeg` / `gst-ffmpeg`.
- **The rest is a complete ARMv7 Tizen build chroot** (`standard-armv7l/`): gcc, headers (4,639 under `usr/include`, including `media/drime5/*/d5_*_ioctl.h`), `libudd5.so` and `libdrm_drime5.so`, with a `.ccache`. **This is useful for compiling our own tools to run on the camera** (in the same way ge0rg/ottokiksmaler build against the camera libraries), for example a fast `st cap` sender that calls `mcb_send()` directly. `tools.zip` adds the `arm-2010q1` and `linaro-4.7.3` cross toolchains.
- The `macros.*imaging_drime5` product-feature files have no capture or RAW flags (product name `drime5`, feature toggles for Wi-Fi, NFC and so on).

Conclusion: nothing in this archive changes the RAW plan. Its value is as a build environment later on.

## SD card setup (2026-10-10)

- Before formatting, the card held unrelated files plus the camera's `DCIM` (2 photos, `360_0330/0331.JPG`) and `SYSTEM`. Those two folders are backed up to `resources/sd backup 3/` (checksums verified). Their EXIF says firmware **0.81**, which confirms the camera is on ARB2, and a date of **2017-01-01**, so the camera's clock has reset.
- Formatted the card in the camera, then copied the mod from `resources/sd backup 2/` (the 2021 HDR version of `top.html`): `info.tg`, `nx_cs.adj`, `mod.sh` and `mods/` (minus vim swap files and `log_1.txt`). All 17 files checksum-match the source.

## Camera session 1 — read-only checks (2026-10-10)

Commands go through the mod's web CGI (`curl -G http://192.168.43.1:8888/cgi-bin/execute --data-urlencode "rawcmd=…"`). Each output is saved in `camera-logs/` (tracked in git, with NUL/CR bytes stripped).

- **System** (`01_identity.txt`): `Linux drime5 3.5.0 #29 PREEMPT Mon Oct 23 20:03:43 KST 2017`, Tizen 2.2.0. The running kernel's build date matches **chunk-02** of the firmware, not chunk-00, so chunk-02 is the main kernel and my earlier "recovery kernel" label was wrong. Camera clock reads 2017-01-01.
- **`st cap help`** (`03`) lists the RTOS subcommands: **`back capdtm capmm capt cis fd fenx iq iqr live lockinfo log obj path ref seq ut`**. There's no `adj` or `capture`, so the factory adjust capture (`CAdjustAdapter`) is probably reached over the DFMS / `ADJUST_MODE` channel rather than `st cap`.
- **`st cap capt help`** (`04`) and **`st cap seq help`** (`05`) match the firmware strings exactly: `quality raw…`, `bulb`, `nr`, `single start`, `seq dump`, `stilltype`, etc.
- **`st cap ref help`** (`15`) is a **T-Kernel** console (`mem/tsk/sem/…`, `ref reboot`, `ref stack`, `ref reg`). So the A7 RTOS is T-Kernel (TRON family), which confirms nx500 #15. ⚠️ `st cap ref reboot` reboots the RTOS; don't run it.
- **`st cap ut help`** (`14`): capture unit tests (`all / movie / still / timelapse`).
- **`st cap iq help`** (`12`): `ae / awb / ipc` debug info. **`st cap lockinfo`** (`19`) prints the AE lock state (Av, Tv, ShSpdNum/Den, Iso, BAGEvNum…), which is useful for reading back what exposure the camera actually chose.
- `cis`, `live`, `fenx`, `obj`, `fd` print nothing for `help`, `capdtm help` says "Unkonwn Operation", and `capmm help` says "command not found in capmm".
- **`varlist`** (`09`): 65 VARIABLE_* entries on the R210, including `VARIABLE_TV`, `AV`, `SV`, **`VARIABLE_BULBTIME` (9)**, `VARIABLE_S2PUSHED`, **`VARIABLE_EXPOSURE_TIME` (46)**, `VARIABLE_TV_MIN` (31), `VARIABLE_SENSORFRAMERATE` = 30, and `VARIABLE_IGNORE_CAPTURE_CMD` (45).
- **`usrlist`** (`22`) matches the 2021 dump except for MOVIESIZE (now DUAL_4096), MOVIEFRAMERATE (now FPS24) and HDR (now OFF). `IMAGEQUALITY` is `SUPERFINE (0x40000)` (`23`). DIALMODE / SHOOTINGMODE are PROGRAM and ISO is AUTO, so **the mod's double-press settings (ISO 100, manual) were not in effect** at the time of the dump.

## Camera session 1 — RAW test 1: IMAGEQUALITY_RAW_SUPERFINE (2026-10-10)

**Setting:** `st cap capdtm setusr 4 0x00040004`, and `getusr 4` reads back `IMAGEQUALITY_RAW_SUPERFINE (0x40004)` (`camera-logs/24`). This confirms the option table decoded from the firmware.

**Shot:** `st key click s2` (`camera-logs/25`). **No file was written, not even the JPEG.** The status screen showed "Capturing" and stayed there. A later "Take photo" from the web UI did nothing.

**RTOS capture log** (`st cap log`, `camera-logs/26`):
- `[CapCounter] Set Max Counter!! Raw:3, Ycc:1, Enc:1`. Three raw passes were planned.
- `[PP_CORE] wdma width=5824, height=2896, bit=eCAP_RAW_BIT_12BIT`. **The sensor readout is a 5824×2896 12-bit Bayer frame** (both lenses side by side). Sensor driver name: **`XO3L6900`**, with "Sensor [A]" and "Sensor [B]".
- Raw Work 3/3 done, then `STL_SHUTTER_CLOSE`, `CAPTURE_STATE_CAPTURE => IDLE`.
- **`(STILL_JPG_FULL) (CCallbackJpegImageSet) Raw Compress Address is NULL!!`**: no buffer for the compressed RAW (SRW), so no SRW was produced.
- `Enc Work is Ended!! 1/1` (JPEG encoded), then back to live view and `capture_ready`. The RTOS finished normally.

**Linux log** (`dlogutil -d -v time`, `camera-logs/28`):
- A **3-second self-timer** ran first (`E_TIMER_SELF_TIMER` 3→0). The camera has a self-timer set.
- The status screen went to `E_SLCD_EXCEPT_EVENT_STBY_CAPTURING_DRAW` ("Capturing"), then `Lock3ACapture`, `CAPTURE START!`, the shutter sound, `SHUTTER CLOSE DONE!`, `NEXTSHOT_READY`, and `CAPTURE_READY` ("[CB]Capture end").
- **No image-data or file-save event ever arrives.** The app (`di-camera-app`, pid 254) sits in `CAPPCaptureMode` with the screen still showing "Capturing". Later key presses (Xorg KeyPress 134 at 490 s and 503 s) reach the app but aren't acted on.

**Interpretation (unverified):** the RTOS can read raw Bayer from the sensor and expects an SRW buffer for RAW modes, but the Linux side didn't supply one ("Raw Compress Address is NULL"). The app then waits for an image set that includes the RAW and never finishes, so the JPEG isn't saved either. The Gear 360 UI probably never sets up SRW buffers because the camera never offered RAW. The likely next routes are the **sensor-level dumps** (`st cap seq dump on ssif`, `CAdjustAdapter::dumpImage`), which write raw files from the RTOS directly, rather than the SRW path.

**Watching the status screen:** the app logs every status-screen change under the tag **`APP_SLCD`** (`CSLCDDrawMan` / `CSLCDDrawStbyMan`, e.g. `E_SLCD_EXCEPT_EVENT_STBY_CAPTURING_DRAW`, `draw_timer_count`), followed by `SYS_MICOM dot_matrix_update`. `dlogutil -d -v time | grep APP_SLCD` shows what the screen is doing.

## Camera session 1 — recovery (2026-10-10)

- `setusr 4 0x00040000` put IMAGEQUALITY back to SUPERFINE (`camera-logs/30`), but the app stayed on "Capturing". The reply also contained a `T2EX >>` prompt, the T-Kernel Extension console leaking through.
- `di-camera-app` runs as **`di-camera-app.service`** (systemd). In the unit file, `Restart=always` is commented out. The hotspot is separate: `mobileap-agent` (pid 483) runs `hostapd` and `dnsmasq`.
- **`systemctl restart di-camera-app.service` took down our telnet, FTP and web servers** (`camera-logs/32/33`). The hotspot stayed up (ping OK), the status screen still said "Capturing", and double-pressing Power did nothing. Likely cause (unverified): the mod is launched by the app (`info.tg` → `nx_cs.adj` → `mod.sh` → `keyscan360` → servers), so it all lives in the app's systemd cgroup and gets killed with it, and the new instance didn't re-run `mod.sh`.
- **⚠️ Don't restart `di-camera-app` from inside the mod.** If we need to recover the app without a reboot in future, first move our servers out of its cgroup (for example start them with `systemd-run`, or move their PIDs into another cgroup), or just accept the power cycle.
- A power cycle recovered everything (`camera-logs/34`): servers back up, status screen normal, IMAGEQUALITY still SUPERFINE (the setting persists). The stuck shot was never saved.

## Camera session 1 — RAW test 2: `st cap seq dump on ssif` ✅ (2026-10-10)

**This is the first raw sensor data out of the Gear 360.**

- `st cap seq dump on ssif` replied `FRAME SSIF Dump on / Set PP Dump Flag 0x10` (`camera-logs/35`). With IMAGEQUALITY back on SUPERFINE, one `st key click s2` (`camera-logs/36`, `37`) produced:
  - **`/sdcard/0_0_11648_5824x2896_bayer_12-16.raw`, 33,732,608 bytes = 5824 × 2896 × 2.** That's a full-sensor 12-bit Bayer frame in 16-bit words (stride 11,648 bytes), with both fisheyes side by side.
  - A normal JPEG `360_0333.JPG`. **The app didn't hang**: the status screen returned to normal after the self-timer and "Capturing".
- RTOS log: `Dump STILL_360_PP_SSIF(0x15000) Material Image, Image Count = 1`, then `[0]/mnt/mmc/0_0_11648_5824x2896_bayer_12-16.raw File Dump Start!! ADDR = 0xa6000000, SIZE = 33732608` … `Dump Done!!`. Writing to the SD card takes about 2.6 s.
- **The dump stays on until `st cap seq dump off ssif`** (not run yet), so every shot writes a 34 MB raw file. Whether the file name increments or gets overwritten is unknown.
- Downloaded to `captures/2026-10-10_ssif_test1/` (git-ignored) through the gallery CGI (`http://192.168.43.1:8888/cgi-bin/gallery?imfile=/sdcard/<file>`, about 10 s for 34 MB). MD5 matches the camera copy (`25193533…`). **FTP listings come back empty and downloads fail with curl error 56**, so use the CGI.
- **Opened in Photoshop** (File → Open As → Photoshop Raw: width 5824, height 2896, 1 channel, 16-bit, header 0, byte order IBM PC / little-endian). It shows a clear Bayer mosaic with both fisheyes. Saved as `captures/2026-10-10_ssif_test1/…bayer_12-16 copy.tif`. (Photoshop's default guess of height 5792 assumes 8-bit.)
- **Decoded (2026-10-10) with `tools/raw2dng.py`** (PiDNG wraps the dump in a DNG; dcraw `-T -a -h` demosaics):
  - **Bit alignment: high-aligned.** The 12-bit value × 16 sits in the top of each uint16. None of the 16.9 M pixels has any of its low 4 bits set.
  - **Black level ≈ 4096** in 16-bit terms (≈ 256 in 12-bit): the 1st percentile is 4032, and the minimum of 3456 is noise below black. **White = 65472** (4092 × 16, saturated).
  - **Bayer pattern = GRBG.** Cells (0,0) and (1,1) have equal, higher means (green). Visually, GRBG gives red keyboard keys, a blue Windows screen and an orange spool; GBRG swaps red and blue. Previews are in `captures/2026-10-10_ssif_test1/previews/`.
  - With GRBG, black 4096 and white 65472, the dcraw render is close to the camera JPEG. There's a slight magenta cast (placeholder identity colour matrix, auto WB) and stronger vignetting, since lens-shading correction isn't applied to the dump (the log says `LSC off` / `FFC`).
  - Usage: `python3 tools/raw2dng.py <dump.raw>` (GRBG / black 4096 / white 65472 are now the defaults), then `dcraw -T -a <file>.dng`, or open the DNG in Adobe Camera Raw / darktable.
- **Black level confirmed = 256 (12-bit) = 4096 (16-bit), the same for both lenses and all four Bayer channels.** I measured it in the unlit corners outside each fisheye circle (four 100×100 patches per channel per lens): the median is exactly 256 everywhere, means are 256.4–256.8, σ ≈ 4 DN at ISO 160. That fits a fixed sensor pedestal of 256. It isn't in the factory calibration (see below). A lens-capped dark frame would confirm it at other ISOs and exposures.
- **The factory calibration data has no black level** (`dfmstool -a`, `camera-logs/39`, 618 lines). `adj_cap CIS_CLAMP_LEVEL` = 0, and almost every `adj_*` field is 0 (unused NX1/NX500 fields). Per-lens module EEPROMs **`EEPA_*` / `EEPB_*`** (180 fields each) hold: `AWB_LOW_GAIN` and `AWB_EEPROM_POINT2..` R/G/B gains (G = 4096 = 1.0; for lens A low-colour-temperature R/B = 2839/1444), `LIVE_ISO_GAIN_X1/X2`, `DECENTER_X/Y`, **`OPTICAL_AXIS_01..40`** (8 bytes each, probably the per-unit stitching calibration; contents not dumped yet), `CREATE_DATE`, `SET_ID`. These AWB gains could seed white balance and the colour matrix for our DNGs.
- Still open: a proper colour matrix (ColorMatrix1) for the sensor, whether the frame has any processing applied before the dump ("PP_SSIF" = sensor-interface output into the pre-processor; it looks unprocessed), and per-lens black levels.

### Full-read log analysis (`camera-logs/29_full_read_analysis.md`)

A second pass read logs 26, 27 and 28 end to end. Corrections and additions:
- **The self-timer is 5 s, not 3 s** (`time:5`). The first column of each log timestamp is a boot/hibernate epoch (0 = before the snapshot, 1 = after resume), not minutes.
- **`XO3L6900` is not the sensor.** It looks like the FPGA that merges the two sensor streams (probably a Lattice MachXO3L-6900; the part number is my inference). The sensor driver is **`CS5K2M8SXDriver`**, which suggests a Samsung S5K2M8-family sensor (inference).
- During RAW test 1 the A9 sized the image as JPEG only (`nMaxSize(JPG): 3053619`). Only the A7 knew about RAW, and **RAW_SAVE / SSIF_RAW were still OFF**. Turning those on is another possible route to SRW (untested).
- At 97.8 s the A9 pushed its whole user-spec list to the A7, which **wiped the mod's boot-time manual settings**. That explains why `usrlist` showed PROGRAM / ISO AUTO.
- The DFMS daemon runs `/mnt/mmc/mod.sh` at every boot and resume. `dfms_check_factory_mode : 1`. Factory, FactoryTest and Development status screens are compiled in.
- During a shot the A7 asks Linux to open and probe files (`RunAdjustFunction FILE_OPEN / FILE_ACCESS result=-1`) without logging the paths. Running `strace` on pid 254 during a shot would show them.
- `camera-logs/` contains the camera's Wi-Fi password and MAC addresses, one reason the logs aren't published.

## Camera colour pipeline from `st cap iq awb` (2026-10-10)

The subcommand names came from the RTOS strings around `usage: st cap iq` (help text `IQ_DebugIF_NX1_Awb.cpp`): `start/resume/suspend`, the mode names `auto, day, cloud, fluW, fluN, fluD, tungsten, acua`, `makernote on/write/off`, `read`, `wbgain`, `adjgain`, `appmode`, `framerate`, `movfr`, `evalmode`, `deltae`, `proc`, `ltnr`, `temp`. AE subcommands (`IQ_DebugIF_NX1_Ae.cpp`): `debugy, patch, srdelay, tvtest, svtest, lensmode, isomax, video, manual, sron, srtest, srevc, srevp, srevd, pllive, plcapt, hitv`. Several of the AE ones probably *set* exposure (`tvtest`, `svtest`, `manual`), so they're candidates for long-exposure experiments. `st cap iq ae` / `ipc` / `awb` with no subcommand answer "no command".

- **`wbgain`** (`camera-logs/41`): live AWB gains, 256 = 1.0. Front R 2.164 / G 1 / B 1.820; rear R 2.176 / B 1.809 (indoors, window daylight). For a DNG, AsShotNeutral = 1/gain ≈ R 0.462, B 0.549.
- **`read`** (`42`, `43`): prints nothing, probably because `adj_iq` AWB data is empty on this camera (inference).
- **`adjgain`** (`44`), 65536 = 1.0. Per-unit calibration: **Adj** front R 1.0162 / B 0.9550, rear R 1.0326 / B 0.9406. **Diff** (rear relative to front): R 1.0161, B 0.9850. **The two lenses differ by about 1.5% in R and B**, which matters for colour matching at the stitch seam. Which raw half is front and which is rear is not confirmed yet.
- **`deltae`** (`45`, `46`), **the camera's colour matrix and tone curve**:
  - `FrontCC` (rows sum to 1.0, so it maps white-balanced camera RGB to output RGB, presumably linear sRGB):
    ```
     1.804688 -0.742188 -0.062500
    -0.210938  1.453125 -0.242188
     0.015625 -0.593750  1.578125
    ```
  - `Front RGB2YCC`: 0.3008 0.5859 0.1133 / -0.1914 -0.3789 0.5703 / 0.5703 -0.4766 -0.0938 (JPEG YCbCr).
  - **Tone curve**, 19 points, 14-bit linear in to 10-bit out: GammaX `0 32 74 140 232 365 550 810 1169 1664 2338 3243 4438 5980 7894 10180 12840 15872 16383`, GammaY `0 8 21 45 80 128 194 269 355 452 556 657 748 828 895 953 998 1022 1023`.
  - `WB Gain 1.442749 2.836563` = 4096/2839 and 4096/1444, exactly the lens-A EEPROM `AWB_LOW_GAIN`. So the CC is printed alongside the LOW calibration point. `Line adjust value OK, delta E 0.468523`, a factory production-line check that passed.
- **Lens EEPROM AWB calibration points** (`EEPA/EEPB_AWB_*`, raw R/G and B/G × 4096; lens A, lens B within about 1–2%):

  | Point | R/G | B/G | WB gains (R, B) | Likely light (inference) |
  |---|---|---|---|---|
  | POINT2 | 0.419 | 0.558 | 2.39, 1.79 | daylight, ~D65 (closest to the live indoor/window reading) |
  | POINT3 | 0.518 | 0.398 | 1.93, 2.51 | ~4000 K |
  | LOW | 0.693 | 0.353 | 1.44, 2.84 | tungsten, ~illuminant A (paired with FrontCC in `deltae`) |
  | POINT4 | 0.841 | 0.280 | 1.19, 3.57 | ~2300 K |

**Plan for DNG colour (not done yet):** with `CC` = FrontCC and `WB` = the gains for the illuminant, `ColorMatrix = diag(1/WB) · CC⁻¹ · M(XYZ→sRGB, D65)`, normalised per the DNG spec. Using POINT2 as D65 gives `ColorMatrix1` (D65); using LOW gives `ColorMatrix2` (illuminant A). This assumes the camera uses one fixed CC for every illuminant (unverified; it could interpolate several). Then `AsShotNeutral` = 1/`wbgain` read straight after each shot. The GammaX/Y curve could optionally go in as a DNG `ProfileToneCurve` to match the camera's JPEG look. Lens diff gains could be applied to the rear half before writing.

## DNG colour v1 — works (2026-10-10)

`tools/raw2dng.py` now writes ColorMatrix1 (illuminant A, from FrontCC + EEPROM `AWB_LOW_GAIN`) and ColorMatrix2 (D65, from FrontCC + EEPROM `POINT2`), plus `AsShotNeutral` from `--wb-gains`. Run on the test dump with `--wb-gains 2.164 1.820` (the `wbgain` reading taken shortly after the shot) → `captures/2026-10-10_ssif_test1/colour_v1/0_0_11648_5824x2896_bayer_12-16_GRBG.dng`.

- exiftool confirms ColorMatrix1 `0.955 -0.342 -0.037 / -0.558 1.483 0.366 / -0.043 0.115 0.802`, ColorMatrix2 `0.671 -0.126 -0.085 / -0.460 1.308 0.119 / -0.086 0.204 0.400`, AsShotNeutral `0.462 1 0.549`.
- **Opened in Photoshop (Adobe Camera Raw), the colour looks "about perfect".**
- Still unverified: the tungsten matrix (no tungsten shot yet) and the illuminant labels of the EEPROM points. Validate with the ColorChecker Passport. The rear-lens diff gains (~1.5%) aren't applied yet.

## RAW test 3: second dump shot + ColorChecker in frame (2026-10-10)

- With the dump still on, a second `st key click s2` (`camera-logs/49`) wrote **a new file, `1_1_11648_5824x2896_bayer_12-16.raw`**, next to `360_0334.JPG`. The first dump `0_0_...raw` was untouched (same MD5). **The dump name increments per shot (`N_N_...`), so raw brackets are possible.** WB straight after the shot: front R 2.160 / B 1.832, rear R 2.172 / B 1.820.
- Downloaded to `captures/2026-10-10_ssif_test2/` (MD5 OK) with `wbgain.txt`, and converted with `--wb-gains 2.160 1.832` -> `1_1_11648_5824x2896_bayer_12-16_GRBG.dng`.
- **A ColorChecker Passport is in the left fisheye.** The room is lit by mixed daylight and monitors, so it's not ideal for profiling, and the chart is small in frame (shoot closer next time). `dcraw -w -h` render vs camera JPEG (`compare.jpg`, `chart_compare.jpg`): **hues match closely patch by patch.** The dcraw render looks flatter and less saturated, because the camera JPEG adds a tone curve and saturation; that's expected. Each patch is about 40 px across in the half-size render, enough for a numeric check later.

## Long exposure tests (2026-10-10)

**Negative TV via `setvar`: doesn't work** (`camera-logs/50`-`52`). Setup: DIALMODE 4, SHOOTINGMODE MANUAL, ISO 100 (the 2021 combination).
- `st cap capdtm setvar TV -16 4` gives `Invalid argument[3]=-16`. TV stays 0, and the shot (`360_0335.JPG`, raw `2_2_...`) is 1 s / ISO 100 / Manual in EXIF.
- `setvar TV 0xFFFFFFF0 4` is accepted, but the value is read with strtol and **clamped to 0x7fffffff**, not -16. I reset it to 0 immediately, without shooting. **`setvar TV` can't go below 0, so 1 s is the floor through this route.** `getvar TV_MIN / BULBTIME / EXPOSURE_TIME` all read 0.
- Internally the RTOS sets exposure in **microseconds**: a normal 1 s shot logs `SetVideoConfig : m_uiExposureTimeStill(1000000)`.

**Bulb mode: starts a 30 s exposure, then hangs** (`camera-logs/53`-`57`).
- `setusr 1 0x00010006` gives `SHOOTINGMODE_BULB`, and the app accepts it. Then `st key push s1`, `push s2`, sleep 3, `release s2`, `release s1`. **The 5 s self-timer delayed the capture**, so the exposure only started (2287.24 s) *after* the keys had already been released.
- RTOS: `CMaterial_PP_Core_Still_Bulb_Image1`, then **`SetStillConfig : m_uiExposureTimeStill(30000000)`** and **`capExposure : Exposure = 30000.0ms`**. **The Bulb path programs a 30-second exposure.** The sensor goes into UD (2880x2880) still mode, `wdma width=2912 height=2896` (a single-lens width?), `SensorCb(2)` at 2287.69 s, and then **the A7 log goes completely silent** (checked up to uptime 2405 s, about 118 s later). No shutter close, no frame counts. The app shows "Capturing". A later `st key push/release s2` produced no A7 log at all; the app is in capture mode and ignores keys.
- Interpretation (unverified): Bulb waits for an end-of-exposure / BulbStop event that never arrives. Either the release was missed because of the self-timer, or Bulb needs hardware this camera lacks. The settings service (`capdtm`) still answers, so only the capture thread is stuck.
- Before rebooting, I reset to DIALMODE_PROGRAM, SHOOTINGMODE_PROGRAM, ISO_AUTO (IMAGEQUALITY still SUPERFINE) (`camera-logs/58`) so the camera doesn't boot into Bulb.

**Leads for long exposures:**
1. **Turn the self-timer off** and retry Bulb, so press -> hold N s -> release happens while the exposure is open.
2. **`st cap capt bulb`** (RTOS capture-debug command), which may drive the bulb sequence directly, including the stop.
3. **The 30 s value comes from somewhere**: possibly `VARIABLE_BULBTIME` (it's 0, which may mean "use the default 30 s") or a bulb timer. Try `setvar BULBTIME <positive>` before a Bulb shot.
4. **`st cap iq ae tvtest` / `manual`** and the microsecond `m_uiExposureTimeStill` path: find the arguments in the RTOS strings or with Ghidra.

## Recovering from the Bulb hang: what the `capt` commands do (2026-10-10)

All tried while the app was stuck on "Capturing" after the Bulb test (`camera-logs/59`-`81`). **None of them un-stuck the app; a reboot was still needed.** But they map out the capture controls:

| Command | Result |
|---|---|
| `st cap capt stop` (no arg) | Prints `please input parameter / 1 : normal stop / 2 : not used / 3, 4 : illegal stop` |
| `stop 1`, `stop 0`, `stop -1` | `CAPTURE_COMMAND_STILL_STOP (0x0)`, then only `SetDriveMode(Single)`. Out-of-range args clamp to 0x0 |
| **`stop 2`** ("not used") | **`STILL_STOP (0x1)`: `Change3AState: STILL_CAPTURING => IDLE (stopEmergently)`**, then AE restarts. Emergency stop of the capture processor's 3A state |
| `stop 3`, `stop 4`, `stop 5` | `STILL_STOP (0x2/0x3/0x4)`: **`[SVC_NX] StopExposure`** (ends an open exposure; nothing followed because the readout thread was stuck) |
| `capt liveview` (no arg) | Nothing |
| **`capt liveview start`** | `LIVEVIEW ERROR, Send dummy callback to avoid system halt`, then fake LIVEVIEW_START callbacks, then **`CAPTURE_STATE_CAPTURE => CAPTURE_STATE_IDLE`**, and live view, AE and AWB run again. The app got `E_CAP_NOTIFY_LV_VIDEOSTART_DONE` but **not** `CAPTURE_READY`, so it stayed on "Capturing" |
| `capt status` | Prints the usage, plus a big **status dump** in the A7 log: clocks and voltages, including the `cis1`/`cis2` (sensor) rails |
| **`capt single start`** | **Fires a capture straight on the capture processor** (shutter sound). The app got `STL_CAPTURE_START` (count 2). The raw dump wrote `3_3_...raw` from buffer `0xab134000` (normal shots use `0xa6000000`) **before** the new readout: the content is garbage (pink streaks, full 0-4095 range), not the Bulb frame. The new capture then stalled at the same point as Bulb (`SensorCb(2)`, then silence) |
| `capt init` | Re-prints the `usrlist` table. No visible recovery |

Strings next to the `capt` help (RTOS lines ~5444-5534) also list: `setLiveview start/movie/high/action`, `s1cancel`, `sts command`, `setTraceLog console/show/save/clear`, `test S1 push/release`, `test AELock/AFLock`, `set Image Quality ...`, **`adjust`, `adjust ycc`, `adjust production`** (probably the factory adjust capture), `testfile`, `testheader`, `efs command`, `calibration`, `shlag (half|full)`.

**Diagnosis (inference):** after Bulb, the capture processor's still-readout path (thread A7 14) ends up waiting at `SensorCb(2)` for a sensor callback that never arrives, and later captures stall at the same place. The app only leaves "Capturing" on `CAPTURE_READY` / `NEXTSHOT_READY`, which never get sent. Nothing found so far re-arms the readout without a reboot.

## Lens calibration ("OPAX") is embedded in every photo (2026-10-10)

**Yes, the camera's JPEGs are unstitched dual-fisheye** (EXIF `SamsungTrailer 0x0a60 = "Jpeg360_2D_NotStitched"`). Stitching is done by Samsung's phone app, or on the camera only in Street View/OSC mode, both with the `GlobeStitcher` in `/usr/lib/libdi-alg-imagestitch.so` (bundles OpenCV 3.2 + Ceres). Strings are in `commands-src/libdi-alg-imagestitch.strings.txt`.

- The stitcher API: `GlobeStitcher::init(__globeOPAI*, globeOPAX*, float*)`, `setDefaultOpax()` / `setDefaultOpai()` (built-in defaults), `ADE_ImageStitch_get/getsize/getversion_OPAX|OPAI|STIP`, `get_rvfOPAI`. **`read_360_OPAX(ExifHandler&, …)` and `read_360_OPAI(ExifHandler&, …)` read the calibration from the photo's EXIF** ("Invalid EXIF _OPAX", "[Use default]opax1 = %f, %f, %f, %f, %f", "opax2 = …"). So **opax1/opax2 = 5 floats per lens**.
- **The Samsung maker note tag `0x0012` (160 bytes = 20 little-endian float64)** holds it. Saved in `calibration/makernote_0x0012_opax.{bin,txt}`:

  ```
  [0]  header (bytes 02 00 00 00 ...: int 2; matches EEPROM OPTICAL_AXIS_FLAG = 2?)
  [1-6]   1444.655518 1446.120728 1444.059937 1447.008301 1444.302979 1440.991699
  [7-12]  1.000304 0.000066 0.000066 1.000595 -0.000140 -0.000140
  [13-15] 4.630198 7.432692 1.256327
  [16-19] 0
  ```

  **Identical in every photo checked**: 360_0003 (2021-10-15), 360_0067 (2021-10-16), 360_0197 (2021-10-17), 360_0333 (today). **It's fixed per-unit factory calibration**, probably copied from the lens EEPROMs (`EEPA/EEPB_OPTICAL_AXIS_*`).
- **Interpretation (unverified):** each lens image is 2896 px square, centre ≈ 1448. Values [1-6] look like fisheye circle centres (cx, cy) per lens plus circle radii (~1444 / ~1441). [7-12] look like per-lens scale/distortion terms near ideal. [13-15] look like the residual rotation between the lenses (yaw/pitch/roll, units unknown) on top of the nominal 180°. The exact field order is not confirmed; the 5+5 split in the log format ("opax1 = 5 values, opax2 = 5 values") doesn't obviously match 15 values, so OPAI may hold part of it.
- Other maker-note tags: `0x0013` (516 bytes) = ints 3, 0x743, 0x7ca and the ID string **`CH80135F5E80174`** (module/set ID?); `0x0014` = `"180 0 0"` (nominal lens-to-lens rotation); `0x0015` = version `"0002-0001"`; `0x00a0` / `0x00a1` = two 13,000-byte blobs (one per lens? maybe the lens-shading table or OPAI); `0x0060` (6000 B), `0x00c0` (2048 B), `0x0080` (10 B) unknown. Yaw/Pitch/RollAngle tags hold the gyro attitude per shot.

**Why it matters:** with the exact per-unit circle centres, radii and lens-to-lens rotation we can build a Hugin/PTGui template from the camera's own calibration instead of hand-tuning control points as in 2021. That should give better stitches of our raw DNGs.

## `st util dump`: pref + lens EEPROM dump (2026-10-10)

`st util dump` (run in a command-testing batch, `camera-logs/91`) silently writes **`/mnt/mmc/dump.tgz`** (5,437,440 bytes; an uncompressed tar despite the name). Pulled via the gallery CGI (MD5 `11c87029...` matches) into `calibration/util_dump/`. Extracted in `calibration/util_dump/extracted/tmp/`: `adj_cap/cs/dpc/iq/sys/vfpn.bin` (the prefman adjust partitions; `adj_dpc` is 5.2 MB of defect-pixel tables), `app.bin`, `app_res.bin`, `line.bin` (2560 B, "line adjust"?), `sysrw.bin`, and **`eeprom_a.bin` / `eeprom_b.bin`** (8192 B each, the raw lens-module EEPROMs).

- EEPROM file offset = dfmstool table offset - 0x200 (e.g. `SET_ID` at 0x2c1 -> file 0xc1 = **`CH80135F5E80174`** in both).
- `OPTICAL_AXIS_FLAG` (file 0x210) = 2. `CREATE_DATE`: **A = 20171101, B = 20171031** (factory calibration dates).
- **`OPTICAL_AXIS_01..16` (file 0xd0, 16 x float64) are byte-identical to photo maker note `0x0012`** in both EEPROMs: 2, then 1444.66 1446.12 1444.06 1447.01 1444.30 1440.99, then 1.0003 6.55e-05 6.55e-05 1.0006 -0.00014 -0.00014, then 4.6302 7.4327 1.2563. `OPTICAL_AXIS_17..40` = 0.
- **So OPAX is the complete factory geometric calibration.** It's stored per lens pair (the same set in both modules) and copied into every photo's EXIF. There's no further hidden lens model in the EEPROM. Generating a PTGui project with no alignment needs these 15 numbers interpreted (disassemble `read_360_OPAX` / `GlobeStitcher::init`), or one PTGui alignment done once and saved as a template.

## Command-testing batch 2: stopped early (2026-10-10)

The resumed runner (commit `4efa5d9`, logs `camera-logs/116`-`161`) ran 46 rows (6 yes / 39 partial / 1 failed), then **the camera stopped responding during `st cap cis vdtime`** (log 161). The runner probed it, saved the CSV and exited. The camera then shut down. Batch 1 had also lost the camera, around `st misc earjack`. **Two camera losses on status/timing reads, so treat `st cap cis vdtime` and `st misc` as supervised-only.**

`tools/runcommands.py` now logs timeouts/errors, marks the row failed, probes with `echo ok`, continues if the camera answers and stops if not. There's also a `--skip REGEX` option.

Findings (from the logs):
- **`st cap cis expinfo`** (log 160; output in the A7 log only): mode eMODE_VIDEO_DUAL_CAM_1920_960_30FPS, exposure 29844 µs = HD count 3103 x HD period ~9.6 µs, frame length 3470 lines, VD 33369 µs (29.97 fps), analog gain 8x, digital gains 1x. This is the sensor timing behind long exposures.
- **`st cap cis info`** (log 159) prints **`IMAGE SENSOR INFORMATION [SONY IMX147]`**, but the driver class is `CS5K2M8SXDriver`. **Sensor identity is unverified**; one label is likely a leftover. Per-mode frame rates: still dual-cam 24.004 fps; video 2880^2 @ 24, 1440^2 @ 30/60, 1920x960 @ 30/15, 1440x720 @ 120, 1280x640 @ 30, single 2304x1296 @ 30/60, 1152x648 @ 120.
- `st cap seq log` (131) shows the full still pipeline: live-view recipe, 360_PP_SSIF, AWB, MAKERNOTE, IPC/3DLUT, stitch, QView, JPEG (main 4.69 MB / screen 576 KB / thumb 11 KB). Bare `st cap seq` (133) prints the sequencer usage.
- `st cap lockinfo help` (148) prints live 3A state: Av 36 (F2.2), Tv 81 (1/30), ISO 800.
- `st cap live mipi help` (135): `info, reg, gpio 1|0, mode 1|0` (**"raw file sensor output test"**), `mode auto`. `mipi info`/`reg` print only usage. `live isplog print`: "isp log is switched off" (`isplog on` exists).
- `st cap path dump` (158): EP register dump; LDC and resize blocks are zero during live view.
- **All 10 `st app` commands return nothing to the CGI**, `show device_opax` included. The app probably prints to dlog, so capture `dlogutil -d` right after each one next time.
- An unexplained still capture shows in the A7 log around 17:11 (log 134); possibly a manual shutter press during the run.
- Not reached: 73 ready `read` rows (`st cap ref ...`, `dfmstool -O OPTICAL_AXIS_*` / `-l`, 39 top-level). The CSV now has **99 `unknown` rows** (found in help output, many duplicates) that need classifying.

## Command-testing batch 3: stopped early at `st thread` (2026-10-11)

**Stopped early: 66 of 68 selected rows attempted, 65 with output (30 yes / 35 partial), 1 hang, 2 not reached.** Logs `camera-logs/176`-`241`, console output in `tmp/runcommands_2026-10-11.log`. The camera had been power-cycled just before. Skip regex: the TODO one plus `^st (firmware|readl|dump)$`. Those 3 bare forms were left out on purpose: `st firmware`'s subcommands flash firmware, and a bare `st readl`/`st dump` might read physical address 0 if the argument parsing defaults to 0. Nobody has checked either, so run them supervised only.

- **Hang: `st thread`** (log 241). No reply within 120 s, then the runner's `echo ok` probe (15 s) also timed out, so the runner saved the CSV and exited. Fact: the camera's CGI stopped answering. Not known whether the camera crashed, powered off or just blocked the web server; nobody has looked at it since. The battery read 91 % (`st bat get_soc`) ten minutes earlier, so a flat battery is unlikely. **Third camera loss on a status read** (after `st misc earjack` and `st cap cis vdtime`), so `st thread` goes on the supervised-only list.
- **Not reached:** `st app` and `st devman`. So the new dlog capture (below) **has not run on a real `st app` row yet**.
- **New in `tools/runcommands.py`:** for `st app ...` rows (or every row with `--dlog`) it dumps `dlogutil -d -v time '*:V'` before and after and saves the new lines in a `=== NEW DLOG LINES ===` section. Checked on the camera first: `-d` dumps without blocking, `-c` would clear (never used), the default filter is `*:I` (3609 lines) and `'*:V'` gives every level (3644 lines, about 507 KB). `dlogutil -g`: ring buffer 1024 KB. Full dumps are diffed and never tailed, so a long output can't be cut off. The cost is about 1 MB of transfer per `st app` row. Background noise in the new lines: `DLNA_STACK` alive messages every second and `DEVICED` battery polling every 10 s.

Notable outputs (facts from the logs):
- **`st rtc get cnt`** (186): `1791748390` = 2026-10-11 19:53:10 UTC, the exact time of the run. So the RTC counter holds correct UTC after this power cycle. Not known whether it kept the time through the power-off or the web UI re-synced it first. `st rtc reset show` (189): "rtc is good". `st rtc dump` (188): 20 registers at 0x10405000, one of them holding 0x2026.
- **`st cap cis chipid`** (207): the reply says "Please select sensor type(a or b)… st cap cis chip a or b", yet the A7 log still prints one sensor's ID: LotID NC4KV, wafer #20, X 153 / Y 100, version 0xa0, feature IDs 0x0/0x4, optional model IDs 0x20/0xd8. `st cap cis chip a` / `chip b` are now read rows.
- **`st cap cis rd_table`** (208): 88 sensor register reads for mode eMODE_VIDEO_DUAL_CAM_1920_960_30FPS (A7 log only). `st cap cis realexp` (232): "Input time 0us / Real time 57us". `st cap cis formula` (233): "Cis convert Voltage to Celsius : 433" (units unclear).
- **`dfmstool -l`** (235): the factory process marks. Pass: SMD_FUNCTION, RF_CAL_1, WLAN, IMEI_WRITE, SIMPLE_TEST, BT_FINAL, SCAM_ISO, SCAM_DEFECT_PIXEL, SCAM_MOT, SCAM_DUST, **SCAM_OPTICAL_AXIS**, SCAM_AWBT2, S_MIC, S_SPK. All others are N (no-test); none are E.
- **`dfmstool -O`** reads: `EEPA_OPTICAL_AXIS_01` = 2, `EEPB_OPTICAL_AXIS_01` = 2, `OPTICAL_AXIS_01` (adj_sys) = 2, `CAM2_DIRECTION_X_CAM1` = 0 (logs 234, 236-238). `-O` prints the 8-byte value as an integer, so the float64 OPAX values (index 1 on) will need `-r` or the `st util dump` copy.
- **`st clk show`** (179): clock-gate table, e.g. DRAM_A 1404 MHz, CA7 600 MHz, SLCD off. **`st dvfs vol show`** (199): VDDI 975 mV, A9 925 mV, ISP 1200 mV. `st dvfs show` (198): A9 and ISP DVFS "off"; cpufreq governor files are missing.
- **`st bat get_soc`** = 91 (ret 0). `get_voltage` returned -1. **`st usb get save`** (205): `/opt/usr/media` + `sm-r210.bin` (the phone firmware-update target). `st oic status`: "OIC data status : INIT". `st micom status`: 0. `st adc dump` (200): register block 0x1003c000-0x1003c0d4.
- **`st cap ref ...`** (209-225): T-Kernel object dumps work and print to both the reply and the A7 log: 48 tasks (`ref tsk`, with names such as AeMain, AwbMain, LvTask, FrmCap, MCB_Receiver), 208 semaphores, the mutex table (I2C mutexes IICc/d/e), message buffers (SLog, DEvt), and per-task stack use (`ref stack`, Assistant0 at 72 %). In `ref int` only SSIF, PP and AWB have non-zero interrupt counts (56540 / 28269 / 28269). `ref reg` with no task ID and `ref dsp` printed nothing useful.
- **`st cap fd` / `st cap obj`** print a usage that says `st cap face [command]` (with `info`, `get3A`), but `st cap face` is not a valid subcommand (logs 230/231 show the generic `st cap` list). So the real form is `st cap fd get3A` (new read row). `fd info` / `obj info` show face detection and object tracking idle.
- Usage only or empty: `st lcd` (power/light/init set 0-6), `st clk`, `st util`/`st leak`/`st pmic`/`st micom dmdump`/`st rtc get alarm` (no output at all), `st tbm`, `st oic`, `st dvfs`, `st adc`, `st thermistor`, `st usb`, `st firmware help`, `st help` (31 built-ins).

**Unknown rows classified (paperwork only, nothing run).** There were 146 `unknown` rows: the 99 from batch 2, plus 47 more found in this run's help output (`st lcd set N`, `st rtc`, `st micom`, `st usb`, `cis chip a/b`, `face get3A`, `firmware up`). Done with `tmp/classify_unknown_2026-10-11.py` (+ `_extra_`), full listing in `tmp/classify_applied_2026-10-11.txt`. commands.csv went from 462 to 400 rows.
- **62 removed as duplicates:** each one is already covered by an existing grouped row with the same risk. `st cap seq stilltype/gpu/gpumemcp/gpusttyp` (set). `st cap back` + `uniteset`/`matr`, `st cap fenx` + `lv/still/mv/gpio *` (11), `st cap ut` + `all/movie/still/timelapse/log on/off` (7) (action). `st cap capt aeb/wbb/pwb/conti/burst/quality/size/hdr/nr/mf/lens init/iris/ois/caf/ael/afl` (set/action) and `capt mcb` (never). `st bat sel`, `st rtc set time`, `st oic test`, `st firmware up` (never). The 19 `st micom dm*`/`watchdog`/`qstart`/`release`/`thread`/`chg`/`sel`/`event`/`stlcd`/`dump` rows were covered by the two grouped micom rows (set/never).
- **84 classified:** 11 read, 39 set, 34 action, 0 never (the never-class ones were all duplicates of existing never rows). Each one's reason is in its `description`, with the original "seen in output of ..." and the log number.
    - **Read** (`run` filled in for a later batch): `st cap capdtm`, `st cap capt`, `st cap iq` (bare forms, expected to print usage; unverified), `st cap path dump ep`, `st cap path info ep`, `st cap ref int all`, `st cap cis chip a`, `st cap cis chip b`, `st cap fd get3A`. Read, no `run`: `st cap seq orderid` (strings next to it are Order-ID tables, so it probably prints one; inferred) and `st cap capt logtest` (inferred from the name only).
    - **Set:** sequencer/capt log levels and trace, capt modes (timer, smart, capprint, shlag, 3dfps, multiexp, motionshot, portrait, hdrart, motionphoto, lls, pgshift, beauty, mfenlarge, moviefade, iqstub), `st cap seq subclock`, `st cap live isplog on`, `st cap live mipi mode auto`, `st lcd set 0/1/3/4`, `st rtc sync`/`set alarm`/`reset set`/`reset clear`, `st micom chg_led`/`dmdebug`, `st usb set tx/rx on/off`, `st usb set save ...`.
    - **Action:** `st cap seq order/demand/check/wbtest`, `st cap live mipi gpio 1/0` and `mipi mode 1/0`, capt drives (movie, panorama, 3dshot, cwb, still3d, bestface, light, conticonti, movieaf, movietouchaf, focusaid, dpreview, fdrun, objecttrk, setois, remotevf, changemode, sas), `st lcd set 2/5/6`, `st micom bat`, `st usb test write/noti/multi start/stop`.
- Parse fixes: the capt help line `3dshot<TAB>bulb` is two entries, so the row became `st cap capt 3dshot` (`bulb` already had a row), and `st cap face get3A` became `st cap fd get3A`. The `st cap back` help lists `uniteset`, but the RTOS strings next to it have `unitest` (`firmware/bin/unpacked/chunk-05.strings-plain.txt` ~9920), so the real keyword is probably `unitest` (unverified).
- Noted, not changed: the existing grouped row `st cap capt event…, counterlog, trace, report, loglevel` is `read`, but `loglevel`/`trace` with an argument change settings, so the new granular rows for those two are `set`.

## Camera web UI v1 (2026-10-10)

New control page at **http://192.168.43.1:8888/**. Source in `camera-www/` (`src/` page/CSS/JS, `vendor/` Bootstrap 5.3.3 stored locally because the hotspot has no internet, `cgi-bin/`). Built by `tools/build_www.py` into a single self-contained `camera-www/dist/index.html`, with Bootstrap, the app and `commands.csv` (as JSON) all inlined. **Confirmed working on the camera.**

- Light theme by default plus a theme toggle. Status badges (mode, quality, ISO, WB, SD free, raw count). One-at-a-time command queue.
- Debug panel: per command it shows time, exit code, duration, the reply, and the new A7 capture-log and dlog lines; search, copy, save.
- RAW tab: dump on/off, timer off, Shoot RAW (waits for the new `N_N_...raw`, saves `..._wb.txt` with `wbgain`, shows the `raw2dng --wb-gains` values). Commands tab: the `commands.csv` menu with risk gating. Files tab: list, download, JPEG preview.
- CGIs: `run` (plain text; headers `X-Exit-Code`, `X-Duration-Ms`; sections `@@REPLY` / `@@A7` / `@@DLOG`; non-printable T2EX filler bytes stripped), `files` (`path|size|mtime`), `put` (POST body -> file under `mods/www`, replies with md5).
- **Deploy over wifi, no SD card:** `python3 tools/build_www.py`, then `cd camera-www/dist && for f in index.html cgi-bin/*; do curl -s --data-binary @"$f" "http://192.168.43.1:8888/cgi-bin/put?path=$f"; done`. The first install of `put` went through `execute` + base64, using busybox via `ln -sf /mnt/mmc/mods/httpd /tmp/busybox` (the camera has no `base64` command; the mod's binaries are BusyBox v1.18.4).
- The old page is kept as `index_classic.html` / `top.html`.

## Camera clock (2026-10-10)

The camera had reset to 2017-01-01 (`camera-logs/162`-`166`). There's no NTP on the hotspot, so the web UI syncs from the browser's clock.
- **System clock:** `date -s @<epoch>` works (GNU date).
- **Hardware RTC = `/dev/rtc0`** (sysfs `/sys/class/rtc/rtc0/{date,time,since_epoch}`, name `drime5`); it holds **UTC**. `hwclock` defaults to `/dev/rtc`, which doesn't exist, hence "select() timed out". **`hwclock -f /dev/rtc0 -w -u` does write it** despite the select()/adjtime (read-only /etc) warnings: the RTC read 2026-10-11 00:49:50 UTC afterwards, matching the PC.
- `st rtc get time` prints the system time. `st rtc set time Y M D h m s` sets the system clock *and* the RTC but treats the arguments as **local** time (giving UTC 05:49 instead of 00:49), so avoid it or give it local time. `st rtc sync` printed nothing and changed nothing visible. `st rtc dump` registers at 0x10405000 did not change (they may be another block).
- **Timezone:** `/etc/localtime -> /opt/etc/localtime` = `GMT+5` (POSIX for UTC-5, EST). Outside that zone (or in summer time), local/EXIF times will be off. Fixed from the web UI, below.
- The web UI auto-syncs on page load if the clock is off by more than 5 s (`date -s` + `hwclock -f /dev/rtc0 -w -u`, then shows the RTC readout). **Still to test: does the RTC keep the time across a power cycle?**

## Raw files live next to their JPEGs (2026-10-10)

- **The raw dump counter (`N_N_...raw`) restarts at 0 after every power cycle and overwrites old dumps.** Confirmed: after a reboot, `0_0`/`1_1` on the card had new content (MD5 differs from the copies in `captures/2026-10-10_ssif_test1` / `test2`, which are the originals for 360_0333 / 360_0334). The camera clock also resets to 2017-01-01 on boot (until the web UI syncs it), so file mtimes repeat across sessions too.
- So raws get moved next to their JPEG immediately: **`cgi-bin/tidyraw`** pairs each `/sdcard/*_bayer_*.raw` with the first `DCIM/*/*.JPG` whose mtime is 0-20 s later (the raw is written 3-5 s before the JPEG), then moves it to `360_NNNN.raw` (plus `360_NNNN_wb.txt`). `?dry=1` previews. With no match, or an existing target, it leaves the file. The web UI's **Shoot RAW** does this automatically after each shot; **Tidy raws** handles shots taken another way. Run it before powering off.
- First run (`camera-logs/168`): `0_0 -> 360_0343.raw`, `1_1 -> 360_0344.raw`, `2_2 -> 360_0335.raw`. `3_3` (the garbage dump from the Bulb hang) has no JPEG and stays in the root.
- `tools/raw2dng.py` now writes `360_NNNN.dng` for camera-named raws.

## Physical shutter + timezone check (2026-10-10)

`camera-logs/169`-`170`. With the raw dump still on, **a physical shutter press also writes a raw dump**, in the SD root as `2_2_...raw` (21:03:29; the counter continues within a session), and the JPEG `360_0345.JPG` 4 s later. These raws are not moved automatically (only the web UI's Shoot RAW does that), so they risk being overwritten after a reboot.

**Timezone via the web UI works live, no reboot needed:** the page relinked `/opt/etc/localtime` to the browser's timezone, and the next photo's EXIF `DateTimeOriginal` and Samsung `TimeStamp` showed the correct local time and UTC offset.

## Raw watcher (2026-10-10)

`camera-www/mods/rawwatch.sh` -> `/sdcard/mods/rawwatch.sh`. A bash-3.2 loop (every 3 s) that moves each finished raw dump (33,732,608 bytes and unchanged for 2 s) from the SD root to `DCIM/.../360_NNNN.raw`, next to the first JPEG saved 0-20 s after it. Single instance (`/tmp/rawwatch.pid`), log `/tmp/rawwatch.log`.
- Started at boot by `/sdcard/mod.sh` (new version in `camera-www/sdroot/mod.sh`; the original is backed up as `/sdcard/mod.sh.bak`), and by the web page on load if not running (`setsid ... &`). The page has a "Watcher log" button.
- Shoot RAW now: wait for the new JPEG, then for `360_NNNN.raw` (moved by the watcher), then `wbgain | tee 360_NNNN_wb.txt`.
- First run (`camera-logs/171`): `2_2 -> 360_0345.raw` (physical shutter shot) and `3_3 -> 360_0346.raw` (a newer shot that had overwritten the old garbage 3_3 dump).
- Deploying files outside `mods/www` (the `put` CGI is restricted to there): `run` + `busybox base64 -d` (busybox via `ln -sf /mnt/mmc/mods/httpd /tmp/busybox`).

## SD card exFAT: phantom duplicate directory entries (2026-10-10)

The SD card is **exFAT** (`/dev/mmcblk1p1 on /opt/storage/sdcard type exfat ... errors=remount-ro`). After repeated deploys with the `put` CGI (write `file.part`, then `mv` over the existing file), `ls` showed **`index.html` 11 times, `run` 3 times, `files` 2 times**, all with the same inode, size and time (`camera-logs/174`). Opening the name gives the latest file (MD5 OK). A cleanup attempt (`camera-logs/175`): `rm` succeeds once and the name is then gone (`[ -e ]` false), yet after restoring the file the listing shows the same duplicates. So they aren't real openable files, but stale entries this exFAT driver keeps listing (in-memory cache or not-fully-deleted entries on disk; unverified which).
- `put` now writes in place (truncate + write), no rename-over-existing. The watcher only renames to new names.
- TODO: after a reboot, check whether the duplicates are still listed; run **chkdsk / fsck.exfat on the card in the PC** (not on the camera while mounted).

- **2026-10-11: they are on the card itself, not a camera-driver cache.** Reading the card in the PC through Windows also lists `index.html` 11 times, `run` 2 and `files` 2. A Windows `chkdsk G: /f` might clean them up (not tried). Deploying by SD card on the PC worked: a plain `cp` over the name, and the MD5 read back matches.

## OPAX decoded from the stitcher library, offline (2026-10-11)

Method: `tools/disasm.py` (Capstone + pyelftools) disassembles named functions from `firmware/bin/unpacked/fs_rootfs/usr/lib/libdi-alg-imagestitch.so` (ARM, PIC). It annotates calls (PLT stubs decoded per stub → imported names), PC-relative literal pools (word, float, double), and PIC string addresses (`ldr rX,[pc,#n]` + `add rX,pc,rX`). Outputs are in `calibration/disasm/*.txt`. Usage: `python3 tools/disasm.py LIB 'GlobeStitcher::init'`, or `--grep opax` to list symbols.

Verified (read directly from the disassembly / bytes):
- **`ADE_ImageStitch_get_OPAX(out, size)`** (`calibration/disasm/ADE_ImageStitch_get_OPAX.txt`): memsets `out`, then calls `dfms_get_adjdata(offset, 0x85c20000)` for offsets **0xd0, 0xd8 … 0x168** and copies each 8-byte value to `out[0..19]`. Its return value is the first 32-bit word at 0xd0 (= 2, the version). So the 20-double OPAX record is read **straight from the lens EEPROM** (adjust-data block `0x85c2` = EEPROM; offsets = `eeprom_a.bin` file offsets). Checked: `eeprom_a.bin[0xd0:0x170]` == maker note `0x0012`, byte for byte.
- Record layout: `[0]` = int32 **2** (format version; reads as 1e-323 as a double), `[1..15]` = calibration, `[16..19]` = 0.
- **`GlobeStitcher::init(__globeOPAI* opai, globeOPAX* opax, float* angle)`** (`calibration/disasm/GlobeStitcher_init.txt`): it does **not** take the 20-double record. `globeOPAX` is **2 lenses × 5 doubles (0x28 bytes each)**, copied to `this+0x120` (lens 1) and `this+0x148` (lens 2). If `opax` is NULL it logs "opax is NULL. Static opax will be used." and calls `setDefaultOpax()`. `__globeOPAI` is 2 × 0x8c bytes, memcpy'd to `this+0x04` and `this+0x90` (NULL → `setDefaultOpai()`). `angle` = 3 floats (NULL → "isAngle is false. {0.0, 0.0, 0.0} will be used"). The angle is **negated** in place when flag `this+1` is set. It then calls `globeDataToSTITCH360()`, and if `this+0` is 0 it fills two 0x118-byte blocks (`this+0x198`, `this+0x2d8`) with identity-like values (1.0 at strides of 0x38 bytes = 7 doubles, i.e. two 5×7 or similar matrices).
- **Default opax** (`setDefaultOpax`, values from the literal pool): lens 1 = [1011.45, 1014.82, 0.996647, 0, 0], lens 2 = [1024.50, 1028.96, 0.997043, 0, 0]. Those are for a different (smaller, ~2048-px) image size than our 2896-px lens images, presumably a phone/GL texture resolution.

So there are **two formats**: the factory EEPROM/EXIF record (v2, 15 values) and the GL stitcher's per-lens 5-double struct. `read_360_OPAX` only memcpy's the raw tag (it has no callers inside the lib; it's exported). **The converter is `main_init(char* opax, char* opai)`** (`calibration/disasm/main_init.txt`), called from `ADE_ImageStitch_Initialize` right after `ADE_ImageStitch_get_OPAX` / `_get_OPAI`.

### `main_init`: EEPROM record → GL opax (verified)

- If `rec[0] != 2`: logs "[Use default]opax…" and overwrites rec[1..4] = 1448.0 (half of 2896), rec[7] = rec[10] = 1.0 and rec[8], rec[9], rec[11], rec[12] = 0.
- If `rec[0] == 2`, with s = 2048 / 2896:
  - **opax1 = [rec[2]·s, rec[1]·s, rec[7], rec[8], rec[9]]**
  - **opax2 = [rec[4]·s, rec[3]·s, rec[10], rec[11], rec[12]]**
  - Then it logs "opax1 = %f…" / "opax2 = …" and calls `GlobeStitcher::init(opai, opax, angle)` with `angle` = a global (+8), not from the record.
- **rec[5], rec[6] (1444.30, 1440.99) and rec[13..15] (4.630, 7.433, 1.256) are not read by `main_init`** or by `GlobeStitcher`.
- The OPAI record goes to `GenerateLscInfoRGB` → **OPAI = lens shading (vignetting) coefficients, not geometry.**

### The lens model is OCamCalib (Scaramuzza), verified

`GlobeStitcher::initialize` calls `get_ocam_model_default(ocam_model*, pol, invpol, centre, affine, size)` once per lens, then `SYSTEM::init(ocam_model&, ocam_model&)`. The struct layout matches OCamCalib's `ocam_model` exactly: `pol[10]` @0x00, `length_pol` @0x50, `invpol[10]` @0x58, `length_invpol` @0xa8, `xc` @0xb0, `yc` @0xb8, `c d e` @0xc0/c8/d0, `width` @0xd8, `height` @0xdc.

- **pol, invpol and size are shared firmware constants** (`.data` 0x57e198, `get_ocam_model_default.txt`). They're the same for both lenses and every unit:
  - `pol` (6) = [-1.5726272232, 1.0398124751, -0.2998335059, 0.3542703799, -0.2635065184, 0.0709548046]
  - `invpol` (6) = [971.9375896974, 526.1058092068, -499.094003808, -645.9034011167, -336.1369527907, -65.8206694527]
  - size = 2048 × 2048
- **Per lens, from OPAX:** centre[0] → `yc`, centre[1] → `xc`. So `xc` = rec[1]·s and `yc` = rec[2]·s (lens 1), and `xc` = rec[3]·s, `yc` = rec[4]·s (lens 2). Affine `c, d, e` = rec[7..9] (lens 1) and rec[10..12] (lens 2).
- **This variant differs from stock OCamCalib.** The polynomials work in **angle θ = atan(z / √(x²+y²))**, with θ = −π/2 on the optical axis and 0 at 90° off-axis:
  - `world2cam`: rho = Σ invpol[i]·θ^i (pixels at 2048 scale). It rejects θ ≥ 0.2 rad, so the usable field of view is ≈ 2·(90° + 11.46°) ≈ **203°**. Then u′ = c·x′ + d·y′, v′ = e·x′ + y′, where x′ = rho·x/‖xy‖ and y′ = rho·y/‖xy‖.
  - `cam2world`: undo the affine, r = ‖·‖, θ = Σ pol[i]·(r / 529.4726)^i, then z = tan(θ)·r.
  - Sanity check: invpol(−π/2) ≈ 0.3 px (axis at centre), invpol(0) = 971.9 px at 2048 scale = **1374.6 px at 2896 scale (90° off-axis)**, invpol(0.2) ≈ 1051 px → 1487 px.
- **`CGL_ACCapture::p_getTexCoord(θ, φ, ocam)`** (`ocam_cam2world_world2cam.txt`) gives the texture lookup:
  - ρ = invpol(θ)
  - **u = (c·ρcosφ + d·ρsinφ + xc) / width**
  - **v = (e·ρcosφ + ρsinφ + yc) / height**
  - So **`xc` is the horizontal (u) centre and `yc` the vertical (v) centre**, which makes **rec[1], rec[2] = lens 1 (cx, cy) and rec[3], rec[4] = lens 2 (cx, cy)**, in pixels of a 2896-px lens image. The lens images are 2896 px tall. Each JPEG half is 2912 px wide; how the 2896 crop sits in the 2912 half is not yet verified.

### Meaning of the 15 EEPROM values: all named (verified)

The camera app has a getter per field: `CHardwareInfoProvider::get_optical_axis_<name>()` → `get_opax_by_param(n)` (`calibration/disasm/di-camera-app_optical_axis_getters.txt`; checked n for left_center_x = 1, left_radius = 5, right_affine_z = 12, diff_x = 13, diff_roll_angle = 15). The label strings (`OpaxVersion, LeftCenterX, … DiffRollAngle`, used by `HardwareInfo::OpticAxisItem::toString` → `st app show device_opax`) appear in the same order (`calibration/disasm/di-camera-app.strings-offsets.txt`, around 0x2eace4).

| rec | name | value | used by camera GlobeStitcher as |
|---|---|---|---|
| 0 | OpaxVersion | 2 (int) | must be 2, else defaults |
| 1 | LeftCenterX | 1444.656 | lens 1 OCam `xc` (×2048/2896), horizontal / u |
| 2 | LeftCenterY | 1446.121 | lens 1 `yc`, vertical / v |
| 3 | RightCenterX | 1444.060 | lens 2 `xc` |
| 4 | RightCenterY | 1447.008 | lens 2 `yc` |
| 5 | LeftRadius | 1444.303 | not used on camera (image circle radius, px) |
| 6 | RightRadius | 1440.992 | not used on camera |
| 7 | LeftAffineX | 1.000304 | lens 1 OCam `c` |
| 8 | LeftAffineY | 6.55e-5 | lens 1 `d` |
| 9 | LeftAffineZ | 6.55e-5 | lens 1 `e` |
| 10 | RightAffineX | 1.000595 | lens 2 `c` |
| 11 | RightAffineY | -1.40e-4 | lens 2 `d` |
| 12 | RightAffineZ | -1.40e-4 | lens 2 `e` |
| 13 | DiffX | 4.630 | not used on camera |
| 14 | DiffY | 7.433 | not used on camera |
| 15 | DiffRollAngle | 1.256 | not used on camera |
| 16 | SpecResult? | 0 | `get_optical_axis_spec_result` exists; index not checked |

- **Left = lens 1, Right = lens 2.** Which JPEG half and which physical lens (front/rear) that is has **not been verified**.
- **Units of DiffX/DiffY/DiffRollAngle are not verified.** My guess: DiffX/DiffY = offset in px (2896 scale) between the two lenses' axes, and DiffRollAngle = relative roll in degrees. The camera's own stitcher ignores them and instead estimates the lens-to-lens alignment from image content per shot (`GlobeStitcher::PreACModuleCalculation` → "AC" auto-calibration, `findPoints`, Ceres). The full 160-byte record is sent to the phone (DLNA `OpaxValue`, `RVFOpaxDataInfo`) and to the PC app (`E_PC_CMD_ID_OPAX`, "GET STATUS OPTICAL METADATA OPAX"), so the phone/PC stitchers probably use the Diff and Radius fields.
- The camera-side angle input to `GlobeStitcher::init` (`float* angle`, 3 floats) comes from a global, not from OPAX. It's probably the gyro attitude (EXIF Yaw/Pitch/RollAngle); unverified.

### What this gives us for stitching

A complete per-unit **lens projection model** for each lens: the shared OCam angle↔radius polynomial, plus the per-lens centre and affine terms. That's enough to remap each fisheye to exact angles (equirectangular) without fitting lens parameters in PTGui. For PTGui/Hugin, the circle centres map to PTGui's lens shift (d/e), and the polynomial can be fitted to PTGui's/Hugin's fisheye distortion. The relative rotation still has to come from DiffX/DiffY/DiffRollAngle (once their units are confirmed) or from one control-point alignment.

## Stitching from the decoded lens model: first tests (2026-10-11)

**Raw vs JPEG geometry** (`tools/raw_jpeg_geometry.py`, output `calibration/raw_jpeg_geometry.txt`): the JPEG (5792x2896) is two 2896-px squares cropped from the raw's two 2912-px halves, with no resampling. ECC registration on 360_0334 (corr 0.90): **raw-half px = JPEG-square px + (7.42, -0.14)** for both halves; scale 1.0002, rotation 0.003 deg. No left/right swap. The other two pairs registered poorly (dark/low texture). So OPAX centres apply to raw files with that fixed shift; no per-shot circle finding is needed.
- Circle fits of the bright image circle (threshold + RANSAC): JPEG centres within ~1-3 px of OPAX; radii 1448-1453 (vs OPAX 1441/1444; depends on threshold). Half 0 is ~3 px larger than half 1, as LeftRadius - RightRadius = 3.3, which is moderate evidence that **JPEG half 0 = OPAX Left** (unverified).

**Exact stitcher** (`tools/opax_stitch.py`): `stitch` remaps each fisheye to equirectangular with the firmware OCam polynomial + OPAX centre/affine (cv2.remap, feathered seam); `solve` estimates the lens-2 rotation correction by reprojecting both lenses into a strip around the seam circle and phase-correlating tiles (SIFT found too few matches).
- The usable image circle ends about 4-5 deg past 90 deg (≈190 deg FOV per lens), so the overlap band is narrow.
- **Indoor scenes can't give the yaw/pitch correction**: 54 old JPEGs (`calibration/opax_solve_batch.txt`) gave clusters at yaw +2.5 / pitch +1.2 and yaw -2.75 / pitch +0.85 for the same room, i.e. dominated by parallax from objects 0.3-1 m away (lens baseline is a few cm). **Roll is consistent at ≈ +0.25 deg** (parallax moves points across the seam, not along it).
- DiffX/DiffY/DiffRollAngle units are still open: 4.63 / 7.43 px would be 0.36 / 0.57 deg at 12.98 px/deg; DiffRollAngle 1.256 doesn't match the measured 0.25 deg roll if it's degrees.
- Next: shoot projector-grid calibration images in RAW. A flat grid at a known distance lets us fit rotation and baseline together.

**What Samsung's stitcher does** (from function names and calls in libdi-alg-imagestitch.so; the internals of each step are not decoded): fixed lens model (OCam + OPAX) → `PreACModuleCalculation` "AC" auto-calibration per shot (`findPoints` feature matching at the seam, Ceres) → `Renderer::ResetSphereWarpData`/`CorrectSphereWarpData` (a mesh warp along the seam, presumably for parallax) → GL render with per-lens gamma/degamma and lens-shading correction (LSC, from OPAI), blended at the seam. So: known lens, only alignment/seam warp estimated per shot, not a PTGui-style full optimisation.

## Seam blending options, researched (2026-10-11)

For our pipeline (fixed lens model, two remapped layers, narrow overlap around 90°), blending only hides misalignment. Near-field parallax is the real problem.

- **enblend**: the old standard. It has seam optimisation (graph-cut / Dijkstra), but it is slow and barely maintained. Hugin 2025.0.1 still uses it.
- **multiblend 2.0** (horman.net, latest 2.0rc5, 2022): a rewrite and drop-in replacement that is much faster than enblend. The author claims better blending. It has **no seam optimisation**, so moving objects can ghost. `gear360pano/multiblend/` holds a vendored copy.
- **PTGui's built-in blender**: the vendor claims optimum seam placement plus zero-overlap blending that beats enblend and smartblend. It is closed source, but we own PTGui.
- **OpenCV `cv2.detail`** (already installed): exposure compensator, then a graph-cut seam finder, then a multi-band blender. The whole chain runs in Python with no external binaries. This is the planned first choice.
- **Optical-flow seam warping**: this is how Insta360's "optical flow stitching" handles near and far objects at once, unlike "template stitching", which is correct at only one distance. Samsung's `CorrectSphereWarpData` is probably a coarser mesh version of the same idea (inferred). Method: compute flow across the overlap band and warp each side halfway, then blend. It can be built from OpenCV DIS flow, or from a learned flow model if needed. This is the upgrade path if parallax shows.
- **Open-source optical-flow stitchers, checked 2026-10-11:**
    - The closest match is **insv-stitch** (github.com/BenjaminHenriksson/insv-stitch, MIT, Python). It is built for Insta360 X5 `.insv` files.
        - Its design is like ours: a factory lens model (MEI) with per-lens extrinsics. A coverage-weighted blend and a seam gain correction follow.
        - It has an optional **OpenCV DIS optical-flow** pass for close-range parallax. The README says objects under 3 m cause about 18 px of ghosting, and that the flow pass "helps but does not match" Insta360's learned model on repetitive patterns.
        - We can't use its input path, but it is a useful reference implementation.
    - **cynricfu/dual-fisheye-video-stitching** (MIT, Python 2.7, OpenCV 3.3) does feature matching, an optimal seamline, graph cut and multiband blending. No optical flow.
    - **Facebook Surround360** (2016, open source) uses optical flow for novel-view synthesis on a 14+ camera ring rig. It is built around that rig, not dual fisheye. Archive status is unverified.
- **Deep stitching (UDIS++, ICCV 2023)**: built for planar image pairs with unknown geometry. It is not a fit for a calibrated 360 seam.

Sources: Hugin site, horman.net multiblend packaging (AUR, Fedora), pixls.us threads on multiblend and Xpano, ptgui.com plugins page, Insta360 Stitcher manual, arXiv 2302.08207.

**Implemented, not yet run (2026-10-11):** `tools/opax_stitch.py stitch` now does the following:
- remaps both lenses with the exact lens model;
- sets coverage from the OPAX image-circle radius;
- applies a per-channel seam gain;
- with `--flow`, warps the seam using DIS optical flow, forward/backward checked, smoothed and clamped;
- blends with a multiband float32 pyramid (or `--blend feather`).

`--save-seam` writes a debug strip. The lens-2 rotation (`--rot`) is still a placeholder until the projector-grid solve.


## Image sensor identified: Samsung ISOCELL S5K2M8 (2026-10-11)

**No public datasheet.** Samsung sensor datasheets are under NDA, and searches found none. The best substitutes are open-source phone kernel drivers, which contain the register tables. Copies are in `sample-code/` (git-ignored):
- `sample-code/s5k2m8-meizu-m685/`: the full S5K2M8 driver from Meizu's MT6797 kernel (github.com/meizuosc/m685, `drivers/misc/mediatek/imgsensor/src/mt6797/s5k2m8_mipi_raw/`).
- `sample-code/s5k-long-exposure-ref/`: S5K2P7 and S5K3M5 drivers from MediaTek kernels. The S5K3M5 one has working long-exposure code (see below).

**Evidence that the S5K2M8 is the sensor:**
- The A7 firmware has the driver class `CS5K2M8SXDriver`, `CIQ_SensorIF_S5K2M8SX` and the string `S5K2M8SX`. The "IMAGE SENSOR INFORMATION [SONY IMX147]" banner is almost certainly a leftover label: the IMX147 is a 20.7 MP 1/2.3" parallel-interface sensor, which doesn't fit.
- Published specs for the ISOCELL 2M8 (Wikipedia): 4208×3120 (13 MP), 1.34 µm pixels, 1/2.6" optical format, also used in the ZUK Z2 / Lenovo Z2 Plus. Each lens's 2912×2896 raw fits inside 4208×3120. The image circle is about 2888 px × 1.34 µm ≈ 3.9 mm.
- **The live register dump fits a 4208×3120 SMIA-style sensor** (`st cap cis rd_table`, `camera-logs/208`, run in a command batch, in video mode). The crop is x 648–3575, y 116–3007 (0x344–0x34a, 2928×2892), and the output is 960×960 (0x34c/0x34e, binned; 0x900 = 0x113).
- The PLL settings are pre-div 6 and multiplier 120 (0x304/0x306), which gives 480 MHz from a 24 MHz clock (the clock is my assumption). `line_length_pck` 0x342 = 4616 and `frame_length_lines` 0x340 = 3470. **4616 / 480 MHz = 9.617 µs per line, and 3470 lines exactly matches `st cap cis expinfo`** (HD period ~9.6 µs, frame length 3470). So the register map is standard SMIA++, the same as the phone drivers.
- `st cap cis chipid` (log 207) wants `a` or `b` (one per sensor). Even without that it printed lot NC4KV, wafer 20, die (153,100), sensor version 0xa0 and model IDs 0x20/0xd8.

**What this means for long exposures** (register names and behaviour come from the phone drivers; untested on this camera):
- Exposure = `coarse_integration_time` (0x0202, in lines) × line time. `frame_length_lines` (0x0340) must be at least the exposure plus a margin of 5 (Meizu driver: `max_frame_length = 0xFFFF`).
- At the current line length, 65535 lines × 9.617 µs ≈ **0.63 s**. 1 s stills must therefore use a longer `line_length_pck` (0x0342) or a lower clock; unverified. With 0x0342 at its maximum of 0xFFFF it would be about 136 µs/line, so ≈ **8.9 s** without any special mode.
- **Samsung long-exposure shifters: 0x0702 (frame-length shift) and 0x0704 (coarse-integration shift).** The S5K3M5 driver enters "long shutter" mode by writing 0x0702 = 0x0704 = 0x0600, which multiplies both by 2^6 = 64. With that it reaches 32 s, and it writes 0 to both to exit. The S5K2P7 init tables write 0x0702 = 0, so that generation has the register. **Whether the S5K2M8 honours 0x0702/0x0704 is unverified.** The firmware's Bulb path programmed 30 s, so it probably uses some mechanism like this. Finding it in the A7 firmware is the next step.

## A7 firmware in Ghidra: how exposure reaches the sensor (2026-10-11)

**Setup:**
- `chunk-05.bin` loads at **0x80000000**. I found that by matching literal words against string offsets: 0x80000000 was the clear peak, and the file starts with an ARM vector table.
- Ghidra 12.1.4 and JDK 21 are installed in `tools/ghidra/` (git-ignored). The project is `tools/ghidra/projects/GearA7`, imported as `ARM:LE:32:v7` raw binary; auto-analysis took about 4 min.
- `tools/ghidra_scripts/DecompileAt.java` decompiles given addresses to `calibration/a7_decomp/<addr>.c`.
- `tools/a7disasm.py` is a quick tool without Ghidra: `refs` (string/address xrefs, including movw/movt pairs), `func`, `imm`, `callers`. The firmware mostly loads string addresses with movw/movt, not literal pools.
- Command (headless, appends to the project): `JAVA_HOME=tools/ghidra/jdk-21.0.12.1+1 tools/ghidra/ghidra_12.1.4_PUBLIC/support/analyzeHeadless tools/ghidra/projects GearA7 -process chunk-05.bin -noanalysis -scriptPath tools/ghidra_scripts -postScript DecompileAt.java OUTDIR ADDR...`

**S5K2M8 driver:**
- I found the vtable at 0x80677538 via the RTTI name `15CS5K2M8SXDriver` (typeinfo 0x80677664). Slot +0x114 is `regw`, and `0x802442b8` reads a register.
- The driver keeps one sensor-mode object per mode (this+0x40 … +0x68). A mode is selected from the capture mode id by `FUN_80240840` / `FUN_802406f0`. Each mode object has virtual getters: **+0xc = line_length (pixel clocks)** and **+0x10 = frame_length (lines)**; these names are inferred from use.

**Exposure setter `FUN_802428dc(this, mode, exp_us)`** (with helper `FUN_802432d8`), read from the decompile:
- `lines = exp_us × 480 000 000 / 1 000 000 / line_length`, so the pixel clock is **480 MHz**, matching the PLL registers.
- Lines are clamped to **[6, frame_length − 6]**. For capture modes 0x16, 0x23 and 0x24 the upper limit is **4 × frame_length − 6**.
- It writes **0x0202 = lines & 0xFFFF** and **0x0340 = frame_length × k & 0xFFFF**. Here k = lines/frame_length + 1, rounded to 1, 2 or 4 for modes 0x16/0x23/0x24.
- **It never touches 0x0702/0x0704** (the Samsung long-exposure shifters), and no code anywhere loads 0x702 as a constant.
- So through this path exposure is capped by the 16-bit line count: **max ≈ 65535 × line_length / 480 MHz**.
  - A 1 s shot needs line_length ≥ 7325, so the still mode's line length is presumably about that.
  - That may be **why 1 s is the floor**: inference, not checked. The still-mode line length can be read with `regr 0x0342` during a still.

**Bulb:**
- `BulbStop` (`FUN_80212a20`) doesn't stop the sensor directly. It sets flags (this+0x249), and when the drive state is 4 and the setting value is 0x1f0000 it logs "force trg SH while readout".
- `BulbTimeCount` (`FUN_80101f60`) measures the elapsed time from a timer minus 7000 µs (250000 if negative).
- So Bulb looks like a separately triggered exposure (shutter-trigger and readout handled by the capture processor or FPGA), not this setter. The 30 s seen in the log may just be a maximum. Not traced yet.

**New sensor debug commands** (found in the `st cap cis` handler strings):
- `regr ADDR` — logs `CIS_READ ADDRESS : 0x%04x, DATA : 0x%04x`
- `regw ADDR DATA` — logs `CIS_WRITE ADDRESS`
- `fpga_regr`, `fpga_regw`, `fpga_sync` — the FPGA that merges the two sensors
- `testpattern` — ALL_LOW … HORIZONTAL_COLORBAR
- `temp`, `temp_log`, `sensor_rst` / `init` / `sleep` / `wakeup`
- `realexp`: log 232 printed `Input time : [0]us / Real time : [57]us`, so it converts a requested exposure into the real one.

**Next long-exposure experiments** (camera; reads first):
1. Read-only, in still mode: `st cap cis regr 0x0342`, `0x0340`, `0x0202`, `0x0702`, `0x0704`; also `st cap cis realexp 1000000`, `2000000` and `30000000` to see the clamp.
2. Supervised: `regw 0x0704 <shift>` and `regw 0x0702 <shift>` (S5K3M5 uses 0x0600, a ×64 shift) before an ordinary short shot. If the S5K2M8 has the shifter, the firmware's normal 0x202/0x340 writes get multiplied. The ISP readout may time out, which is recoverable by reboot.
3. Alternative: `regw 0x0342` (line_length) bigger, for up to about 9 s with no shifter, but the firmware rewrites 0x342 on mode changes.

**Register write test (camera-logs/251, 2026-10-11 17:25):** one `run` request chained these commands:
- `regr a 0x0704`
- `regw a 0x0704 0x0100`
- read back
- `regw a 0x0704 0`
- read back

**No reply came back, and the camera was found powered off.** Whether the write (or something else) crashed it, or it powered itself off at about the same moment, is unknown. Nothing in the chain was logged before the loss. Next time, send `regr` and `regw` as **separate** requests, so the log shows exactly which step it died on.


## Long exposures are capped at ~1/6 s: measured (2026-10-12)

**Raw evidence.** Bracket `captures/2026-10-12-hdr-1` (ISO 100, Manual: 1 s, 1/15, 1/250, 1/4000, 1/8000; raw dump on). Pixel-by-pixel ratios between consecutive raws, on pixels unclipped in both (black 4096 subtracted):

| Step | Expected | Measured (median, IQR) |
|---|---|---|
| 1/250 → 1/4000 | ×16.0 | ×16.2 (14.1–18.3) |
| 1/15 → 1/250 | ×16.7 | ×15.5 (13.6–17.5) |
| **"1 s" → 1/15** | **×15.0** | **×2.59 (2.46–2.73)**, 12.5 M px |

So the "1 s" raw is really exposed ≈ 1/15 × 2.59 ≈ **0.173 s**. The JPEG EXIF still says 1 s: EXIF records the request, not the exposure. The 2021 "1 s" brackets were only ever checked against EXIF.

**Matches the firmware clamp** (Ghidra section above): lines are clamped to frame_length − 6, or 4 × frame_length − 6 in capture modes 0x16/0x23/0x24. Still mode runs at 24.004 fps (41.66 ms/frame), so 4 frames ≈ **0.167 s** (ratio 2.50 vs 1/15, inside the measured IQR). Inference: the still capture uses the 4× mode, so **every request above ~1/6 s gives ~1/6 s**. A raw series at 1/8, 1/4, 1/2, 1 s (predicted: 1/8 honoured, the rest flat at ~0.167 s) would confirm it.

**`st cap cis realexp <us>` works with an argument** (camera-logs/253–257; output in the A7 log). It reports for the *current* sensor mode, here live view (frame_length 3470 × 9.617 µs/line):

| Requested µs | Real µs |
|---|---|
| 30 000 000 | 33 312 |
| 1 000 000 | 33 312 |
| 166 667 | 33 312 |
| 30 000 | 29 994 |
| 10 000 | 9 991 |

Requests are rounded to whole 9.617 µs lines, and anything longer is cut to (3470 − 6) lines = 33 313 µs: live view is a 1× mode. Even 30 s gets no special path. So `realexp` shows the mechanism but not the still-mode cap.

**App shutter path and the climb (2026-10-12, camera-logs/258–284).**
- `st app set tv <v>` is the camera app's own shutter setting (values from its usage text: `30s … 10s … 2.5s, 1.6s, 1.3s, 1s, 0.8s … 0.3s`, plain numbers = 1/x). The app converts to APEX and writes `VARIABLE_TV` as a **16-bit signed** value: 30 s → `0xFFB0` (−80/16 = 32 s), 10 s → `0xFFCB`, 2.5 s → `0xFFEB`, 1.3 s → `0xFFFB`. `setvar TV` only refused `-16` and `0xFFFFFFF0`; the 16-bit form (e.g. `setvar TV 0xFFB0 4`) is **untested** and may work.
- Two capture paths, chosen by **long-exposure NR (USERDATA 31)**, not by the shutter value:

| App shutter | LTNR | Path in the A7 log | Result |
|---|---|---|---|
| 1/8, 1/4, 0.5 s, 1.3 s, 2.5 s, 10 s, 30 s | OFF | `SetVideoConfig`, sensor mode 22 "Video Full for still capture (2912x2896)", 24 fps, `Video STill Exp time = <request>` | JPEG in ~1 s: clamped (≈1/6 s) |
| 30 s | ON (default after reboot) | `CMaterial_PP_Core_Still_LTNR_Image`, `SetStillConfig m_uiExposureTimeStill(32000000)`, `capExposure 32000 ms`, sensor "UD(2880x2880)" still mode | **hangs** after `SensorCb(2)`; reboot needed |

- Odd: app `1s` (TV 0) programmed `Video STill Exp time = 125000` (1/8 s) while 0.5 s got 500000. Not explained; not re-tested.
- The 32 s hang matches the 10-10 Bulb hang (same `SensorCb(2)` then silence), and **the self-timer was off this time**, so the timer was not the cause.
- **App disassembly** (`tools/appdisasm.py`, capstone + `res/di-camera-app.map`; output `calibration/app_disasm/`): `UI_Operate_Start_Capture` = set common params + one `UI_Mm_Camera_Start_Capture()`; no long-exposure special case. `UI_Mm_Camera_Set_Bulb_Shot_Time(t)` = `Set_Variable_Int_Attribute(0x34, t)` and `UI_Mm_Camera_Stop_Long_Press_Capture()` = a second `Start_Capture()` (a bulb is ended by another capture command), but **neither has a direct caller** (likely NX leftovers). So the stock 30 s flow is exactly "set TV, press once", and the long exposure is decided entirely in the A7.
- Open: does a stock 30 s (phone app / camera menu, default settings) also hang? If yes, the LTNR still path is broken in stock firmware, and the fix is A7 work: find what delivers the post-exposure sensor callback in UD still mode (the Bulb code's "force trg SH while readout"; the XO3L6900 FPGA merges the two sensors).

**LTNR still path, more tests (2026-10-12 afternoon, camera-logs/285–294).**
- LTNR on, app 10 s, JPEG only (285–287): same path (`SetStillConfig 9934862`, UD mode cycled 4→5→6→8), **hung**. `CapFrameReadout` starts **35 ms** after `capExposure`, so the long exposure is not actually waited for; the hang comes after readout, at the switch to "post still" mode 8 (`SensorCb(2)`). Only on this path: `set pp size1 w:0, h:0`, AE/AWB window failures with image size 0, `PP Path Still 0` with a 2896×2896 single-lens buffer.
- LTNR on, app 10 s, **raw dump on** (291–292): hung the same way and **no raw was written** to the SD root, so the still frame never reaches the dump.
- **Remote reboot works** (289–290): `setsid sh -c 'sleep 3; sync; systemctl reboot' >/dev/null 2>&1 < /dev/null &` through `cgi-bin/run`. Down after 3 s, web server back after ~28 s with no button press (the boot script restarts the servers and rawwatch). `boot_id` stays the same across reboots (likely the snapshot fast-boot); use uptime to detect a reboot. Settings return to defaults (Program, ISO Auto, ISONR MID, **LTNR ON**). The PC's Wi-Fi had to be reconnected by hand. Not yet tested on a hung camera.
- **Un-sticking the hang without a reboot: nothing works** (camera-logs/295–311, camera hung after the LTNR 10 s test).
  - While hung, sensor registers still read fine (both sensors): 0x0342 = 0x1900 (6400 pck, 13.33 µs/line), 0x0340 = 0x0D47 (3399 lines, ~22 fps), 0x0202 = 0x03FA (1018 lines = 13.6 ms), 0x0702/0x0704 = 0. The 10 s exposure was never programmed into the sensor. With this line length the standard-register ceiling is 65535 × 13.33 µs ≈ 0.87 s.
  - `st cap ref tsk`: no task blocked or spinning; the capture workers (Assistant10 = "A7 24", Still0-7, FrmCap, CaptureControll) are idle waiting for messages (WAI-RMBF), FrontendNx waits on a flag.
  - `st cap ref int` twice 10 s apart: SSIF 4918, PP 2459, AWB 2457 frozen → no frames reach the SoC in "post still" mode 8.
  - `capt bulb stop`: CAPTURE_COMMAND_BULB_STOP accepted, no effect (side effect: SHOOTINGMODE → PROGRAM). `capt stop 6`: LOCK3A_CANCEL → `3A_UNLOCK_FAIL : CapState:3`. `capt sts s1cancel`: actually queued another CAPTURE_COMMAND_STILL_NORMAL (pending) plus `Invalid Parameter (0x1040002)`.
  - `cis md 10`: sensors switch cleanly 8 → 10 (FHD 960x960, EnableStream), console stays responsive, but SSIF still frozen; capture still stuck.
  - Conclusion: the A7 isn't crashed; the still path waits for a frame-done event that never comes and no command supplies it. Only a full reboot (remote `systemctl reboot`) recovers. Restarting only di-camera-app would leave the A7 state stuck.
- **Rolling shutter type doesn't help** (camera-logs/312–313): `setusr 117 0x00750001` is accepted (`ADJUSTSHUTTERTYPE_ROLLING`) and changes the code path (`capExposure : m_eDriveMode(4) eCapOption(1)` instead of `Exposure = 9934.862ms`), but with LTNR on and 10 s it still goes `CapFrameReadout` 48 ms later → `SensorCb(2)` → hung, no JPEG, no raw. So the LTNR still path hangs with mechanical or rolling shutter type, 10 or 32 s, timer on or off, raw on or off. Conclusion: real exposures over ~1/6 s are not available through the firmware's capture paths; remaining options are stacking (practical) or sensor-register work (risky).
- **Bulb with LTNR off and timer off also hangs** (camera-logs/317–318): `setusr 1 0x00010006` (SHOOTINGMODE_BULB), `st key push s1; push s2; sleep 5; release s2; release s1`. `CMaterial_PP_Core_Still_Bulb_Image1`, `SetStillConfig m_uiExposureTimeStill(30000000)` (Bulb always programs 30 s, BULBTIME var = 0), `capExposure 30000.0ms`, `CapFrameReadout` 34 ms later, post still, `SensorCb(2)`, stuck. Key release logs nothing; `capt bulb stop` 60 s later gives `CAPTURE_COMMAND_BULB_STOP` but **no "force trg SH"** (it never reaches the FE's BulbStop), no JPEG, no raw. Conclusion: every long-exposure path (Bulb, LTNR still, `capt single start`) is the same broken still pipeline: no wait for the exposure, then a hang after readout.
- **Fully remote hang recovery works** (2026-10-12 15:0x): send the reboot through `cgi-bin/run`, wait ~30 s, then on the PC `powershell.exe -NoProfile -Command 'netsh wlan connect name="Gear 360(XXXX)"'`. Down at 9 s, connect OK at 39 s, web server answering at 50 s. Needs Windows Location services **and** "Let desktop apps access your location" on (Windows 11 requires location consent for any app using the WLAN API; the Wi-Fi flyout is exempt). The profile is also set to `connectionmode=auto`.
- Shutter type: usrlist [117] `USERDATA_ADJUSTSHUTTERTYPE = ADJUSTSHUTTERTYPE_MECHA` (0x00750000); `ADJUSTSHUTTERTYPE_ROLLING` exists. The Gear 360 has no mechanical shutter; NX500 bulb always uses the mechanical shutter. Untested idea: `setusr 117 0x00750001` before an LTNR shot.
- Research notes (web + offline): `tmp/research/` (gear360_long_exposure_reports.md, sensor_long_exposure.md, hang_recovery.md, hdr_stacking.md).
- SD root clean-up: four per-lens dumps from 10-11 19:29–19:48 (1_1/3_3/5_5/7_7, not the same files as the 16:50 batch despite the names) copied with matching MD5 to `captures/2026-10-11/sd-root-evening/`, then deleted with their empty `.patch` files.

**Consequences:**
- For HDR, treat ~1/6 s as the longest real exposure. For darker frames, raise ISO on the slowest frame (e.g. 1/6 s at ISO 400–800) or average several 1/6 s frames.
- `tools/raw2dng.py` copies ExposureTime from the JPEG, so DNGs of requests above ~1/6 s carry the wrong (requested) value.
- Getting past the cap still needs one of the risky routes in "Next long-exposure experiments": Bulb (programs 30 s, hung), a longer line_length (0x0342), or the 0x0702/0x0704 shifter. The last register write ended with the camera powered off.

## Lens shading (vignetting): Samsung's correction decoded (2026-10-11)

**OPAI is not a per-unit shading table.** I decompiled `libdi-alg-imagestitch.so` in Ghidra (project `tools/ghidra/projects/GearStitchLib`; output in `calibration/stitchlib_decomp/`; the `_1.c` files are the real bodies and `_0` the PLT stubs).
- `ADE_ImageStitch_get_OPAI` builds `{version 3, int from adjust data 0x85c2 offset 800, int from 0x85c4 offset 800, string from vconf}`. When User_Spec 0x1ac == 4 the two ints are −2, −2, and `main_init` then calls `setDoLSC(false)`.
- Maker-note tag **0x0013** holds this record: `[3, 0x743 (1859), 0x7ca (1994), "CH80135F5E80174"]`.
- `GenerateLscInfoRGB(model, value)` fills a 0x8c-byte `_TLSCCoef_model` from **constants built into the library**. Only the first polynomial depends on `value / 100` (<4, <13, ≥13). On our unit both lenses are ≥13.
- **Model:** RGB gain = per-channel 5th-order polynomial in r.
  - `CGL_LSCRender::SetBlendInfo` computes **r = 2 × distance from the lens centre in normalised lens-texture coordinates**, so r = 1 at 1448 px in the 2896-px lens square. The image-circle edge is r ≈ 1, and 90° off-axis is r ≈ 0.95.
  - `p_SetGainFront` / `p_SetGainRear` evaluate the polynomials, and the gain multiplies the image.
- Coefficients (c0…c5). The order R, G, B is assumed: the renderer fills a `vector3df` with them, but the channel order isn't verified.
  - First polynomial, value/100 < 4: 1, 0.357137, −2.68483, 13.6964, −21.9303, 12.4693
  - First polynomial, < 13: 1, 0.35964, −2.70365, 13.7924, −22.0839, 12.5566
  - First polynomial, ≥ 13 (ours): 1, 0.325752, −2.37229, 12.7928, −20.9402, 12.1364
  - Second: 1, 0.314724, −2.18452, 11.8701, −19.2398, 11.0958
  - Third: 1, 0.244838, −1.38679, 8.98952, −15.132, 9.083
  - The struct also holds two more 7-float groups whose use isn't decoded: [0, 0.268828, 0.329584, −1.27891, 4.03011, −5.34816, 2.99855] and [0, 3.57462, −5.3629, 1.56054, 5.9817, −7.35751, 2.60354].
- Gain at r = 0.95 (90°) for R/G/B: **2.47 / 2.42 / 2.39**, so the edge is at about 41% of the centre. At r = 1 it is about 2.9×.
- Whether Samsung applies this in linear or gamma space isn't decoded; the renderer has gamma/degamma steps.

**In the stitcher:** `opax_stitch.py stitch --lsc auto|srgb|linear|off` (default auto: sRGB-decode → gain → re-encode for 8-bit JPEGs, plain multiply for 16-bit). `--lsc-strength` scales it as gain^strength.

**First test, 360_0364** (wall across the left seam, rows 1250–1450 of a 4096-wide pano):
- Without the correction the wall dips from about 101 to 67 at the seam (−34%).
- With the full correction it dips from 130 to 99 (−24%).
- So it helps but doesn't remove the dip. The low point sits about 3.7° past the seam, so part of it may be real light falloff on the wall. Can't tell from this scene.
- `calibration/scratch/lsc_cmp_0364.jpg` compares the two (top off, bottom on).

**Also tried:** `tools/vignette_profile.py` (median brightness vs angle over 24 camera JPEGs) is dominated by scene content: it gives 2.6× at 30°. It's not usable with this photo set.

**A clean check:** tripod, plain evenly lit wall; one shot with a seam pointing at the wall, one rotated 90° so a lens centre points at the same spot.

**Visual verdict (360_0363 / 0364):** brightness with the correction is "really pretty good". `--lsc auto` stays the default.

## Sibling-sensor datasheet: S5K3L6 (2026-10-11)

`sensor-data/` holds `ISOCELL - Wikipedia.pdf`, which only confirms the S5K2M8 specs (4208×3120, 1.34 µm, 1/2.6"), and **`S5K3L6-13MP-MIPI-Auto-Focusing-Camera-Module.pdf`**: Samsung's confidential preliminary datasheet for the S5K3L6XX (1/3" 13 MP, rev 0.01, Sept 2017). It isn't our sensor, but it's the same family and era with the same standard register map. Text extract: `tmp/s5k3l6.txt`.

What it gives us:
- **The registers we already use match:** 0x0100 mode_select, 0x0104 grouped_parameter_hold, 0x0136 EXTCLK (8.8 fixed point), 0x0200 fine / 0x0202 coarse integration time, 0x0204 analogue gain, 0x020E digital gain, PLL 0x0301–0x030F, 0x0340 frame_length_lines, 0x0342 line_length_pck, crop/output size 0x0344–0x034F, 0x0900 binning.
- **Integration time** = (coarse_integration_time × line_length_pck + fine_integration_time) × pixel-clock period. coarse_integration_time and line_length_pck are **both 16-bit**.
- **No long-exposure shifter (0x0702/0x0704) is documented.** The documented 0x0600–0x0FFF list has only test patterns, MIPI link rate and binning. It's a cut-down customer list, so this neither proves nor disproves that the S5K2M8 has them.
- **Test pattern registers:**
  - 0x0601 test_pattern_mode: 0 = off, 1 = solid colour, 2 = colour bars, 3 = fade-to-grey bars;
  - 0x0602–0x0609 solid-colour R / Gr / B / Gb values;
  - 0x060A–0x0611 cursors.

**Ideas this suggests (untested):**
1. **Long exposure via line length instead of a shifter.** The A7 setter (see the Ghidra section) clamps the *line count* to 16 bits but takes line length from the current mode. Raising 0x0342 line_length_pck (with 0x0340 frame_length to match) lengthens each line. In theory the ceiling is 65535 lines × 65535 pck ÷ 480 MHz ≈ **8.9 s**. Risk: the FPGA / capture side may expect fixed line timing, so this could break readout or hang the A7.
2. **A safe first `regw` test: the test pattern, not 0x0704.**
   - `regw a 0x0601 2` should show colour bars on lens a in live view, and `regw a 0x0601 0` undoes it. This is visible, harmless and reversible, and checks the `regw` syntax and whether writes reach the sensor at all.
   - Try the built-in `st cap cis testpattern` first.
   - Send each command as its own request (see the regw camera-loss note above).

## SD card clean-up and new per-lens raw dumps (2026-10-11)

- **New raw format in the SD root:** five `N_N_5824_2896x2896_bayer_12-16.raw` files from today, each 16,866,304 bytes. That size is 5824 × 2896 = a 5824-byte stride (2912 px × 2 bytes) × 2896 rows. **Inferred, not yet decoded:** one lens per file, 16-bit.
  - They come in pairs about 2 s apart: 1+3 → 360_0365 (16:50), 5+7 → 360_0366 (16:54).
  - 9 is a lone file from 17:23, the time the camera went off during the regw test.
  - Yesterday's dumps were a single 33,732,608-byte (5824×2896×2) file per shot. Why the format changed is unknown.
  - `rawwatch.sh` only matches the old size, so it left these in the root.
- Each dump also got a 0-byte `N_N_0_0x0_aeawb.patch` file.
- **Copied with verified copies** to `captures/2026-10-11/sd-root/` (with the two orphan `_wb.txt` files from 2026-10-10), plus 360_0365/0366.JPG to `captures/2026-10-11/`. Then deleted from the card, along with `dump.tgz` (copy in `calibration/util_dump/`) and `mod.sh.bak` (copy in `sd-bak-10-11-2026/`).
- **`DCIM/100PHOTO/360_0367.JPG` is a broken exFAT entry** (0 bytes, 17:23, from the camera dying mid-write). Linux `stat` gives "Invalid argument"; `rm` and PowerShell `Remove-Item` both report success but leave it. It needs `chkdsk G: /f` from an admin prompt.
- **To do:** update `rawwatch.sh` and the raw tools for the two-files-per-shot format once one file is decoded.

## Boot-time servers and Menu double-press RAW shot (2026-10-11)

- **`camera-www/sdroot/mod.sh`** now starts tcpsvd/ftpd, telnetd and httpd 15 s after boot, so no Power double-press is needed. The double-press script (`camera-www/mods/G360POWE_G360POW.sh`, now kept in the repo) still sets ISO 100 / shutter priority / NR off. It now also does `killall httpd` before restarting it.
- **How `keyscan360` names scripts** (from `keyscan360.c`): a double-press (same key, < 1 s) runs `<dir>/<KEY>_<KEY>.sh`, with the name cut to 16 characters. So Power (code 73, "G360POWER") → `G360POWE_G360POW.sh`, and **Menu (code 127, "G360MENU") → `G360MENU_G360MEN.sh`**. It looks for the script at every press, so no reboot is needed after adding one. It calls `system()` and waits for the script to finish.
- **`camera-www/mods/G360MENU_G360MEN.sh`**, run in the background with a mkdir lock:
  - refuses unless in Photo mode (`prefman get 0 0x00004445 b` == 0x01);
  - turns the dump on and starts `rawwatch.sh`;
  - presses `st key click s2` and waits up to 60 s for a new JPEG;
  - turns the dump off unless `/tmp/rawdump_on` exists (the web UI's RAW switch now creates and removes it);
  - LED 5 blinks while busy; log in `/tmp/menuraw.log`.
- Copied to the SD card 2026-10-11 (each file checked against its source). **Not yet tested:** whether the 2017 model's Menu key really sends code 127 (check with `keyscan360 ... debug`), and whether the app's own reaction to the Menu presses gets in the way.
- **Menu was the wrong key (tested 2026-10-11):** the double-press did run the script, but Menu presses also cycle the camera mode (Photo → Video → …), and the shutter press it sent didn't take a photo. A first bug also left `/tmp/menuraw.lock` behind: bash 3.2 doesn't run an `EXIT` trap set inside a backgrounded function, so later presses were all "busy". Fixed with an explicit `rmdir` and a 120 s stale-lock takeover.
- **Moved to the Power double-press**, since the servers now start at boot: the RAW-shot script is now `mods/G360POWE_G360POW.sh`, and `G360MENU_G360MEN.sh` was removed from the card. The old settings (ISO 100, shutter priority, NR off) are in `mods/camera_settings_iso100.sh`, without the server restarts. It isn't wired to anything yet.
- **⚠ `st cap seq dump off ssif` turns photos green until a reboot.** It replies `Set PP Dump Flag 0xFFFFFFEF`.
  - 360_0368, the first photo after the script sent it, averages BGR 5.8 / 68.3 / 29.8 (blue almost gone). The AWB gains read normal (R 1.69, B 2.72) and EXIF shows auto WB.
  - The next photo was still green. After a reboot photos were normal again (2026-10-11).
  - Photos taken with the dump ON (0365/0366) were fine.
  - Guess, not verified: the off path writes the clear-mask itself as the post-processing dump flag, switching on every other PP dump/debug bit. To check: decompile the `Set PP Dump Flag` handler in the A7 image.
  - **Cause confirmed in the A7 image** (`calibration/a7_decomp/0x802802ec.c`, the `st cap seq dump` handler):
    - each dump name sets one bit in a local mask: PP flag `pp`=1, `aeawb`=2, `lrc`=4, `sub`=8, `ssif`=0x10, plus separate BackEnd and Jpg flags;
    - for "off" the mask is inverted (`~mask`);
    - the result is passed to `FUN_805715f8`, a **plain store** to the word at **0x8196a1c8**.
    - So "on ssif" writes 0x10 and "off ssif" writes 0xFFFFFFEF, turning every other PP dump on. No combination of names can write 0.
  - **Clean off: `st writel 0x8196a1c8 0`** (`st readl`/`st writel <addr> [value]` exist in the firmware). Tested 2026-10-11:
    - `st readl` showed 0x10 after a dump on;
    - after the write it read 0;
    - the next shutter press gave 360_0380 as a JPEG only, with normal colour (preview mean BGR 62/71/76, against 0368's 6/68/30).
  - The Power RAW script and the web UI's RAW switch now clear the flag this way, and only if it reads exactly 0x10. The Power script leaves the dump on if the web UI switch had it on (`/tmp/rawdump_on`).
  - The per-lens `N_N_5824_2896x2896_bayer_12-16.raw` files in the SD root were all made while the flag held 0xFFFFFFEF (19:29 = 0368, 19:47/48 just before a reboot). So they likely come from one of the other dump points (lrc/sub?), not from a new ssif format. Inferred from timing. The 16:50/16:54 pair (normal colour) doesn't fit this and is unexplained.
- **Other mods reviewed** (`sample-code/`):
  - lansysart = Wi-Fi client via `wpa_supplicant` (2016 model, static IP);
  - niluss = GPU dual-fisheye viewer (`gallery-3d.js`, generic fisheye model, hard seam) and `st key click wifi`;
  - NX500 notes: `setusr 117` electronic shutter, `poker` for process memory.

## Power RAW retest, web UI sizes and preview, grid shots, PTGui lens numbers (2026-10-11)

- **0382 got a RAW from a plain shutter press** after a Power double-press. Cause (checked in the log): a stale `/tmp/rawdump_on` from an earlier web UI RAW toggle, so the script left the dump on as designed. My manual `writel` test had cleared the flag but not the marker. Both were cleared. The intended behaviour: Power double-press = RAW, shutter = JPEG only. **Retest passed (2026-10-30):** Power double-press gives a RAW, a plain shutter press gives JPEG only.
- **Web UI files table** shows each part's size as a badge (`JPEG 5.3 MB`, `RAW 32.2 MB`, `WB 111 B`); the separate JPEG column is gone.
- **Embedded previews in the camera JPEG:** IFD1 thumbnail 320x160 (it seems to come from a different moment than the photo; unexplained), and an MPF "Large Thumbnail" 1920x960, ~650 KB. Its absolute offset = MP entry offset + the position just after `MPF\0`. The viewer reads the first 128 KB, parses MPF and fetches only the preview through `cgi-bin/get?...&off=&len=` (new byte-range parameters, digits only, clamped to the file size). Checked byte for byte against exiftool's preview.
- **raw2dng** takes several files, reads WB from each `360_NNNN_wb.txt`, shows `[k/N]` progress and skips (and reports) size mismatches.
- **Projector-grid shots: 360_0375–0379** (0372–0374 are not part of the set). Downloaded with md5 checks and converted to DNG in `captures/2026-10-11/`. PTGui opens the DNGs directly.
- **PTGui lens numbers.** 2021 template: circular fisheye, HFOV 189.95, crop circle `C9,2879,17,2887` on 2896 halves, image 2 at yaw 179.01 / roll 0.196 / pitch −0.344. EXIF says 1.2 mm, 35 mm equivalent 6 mm (crop factor 5.0); the physical 1/2.6" sensor has diagonal 6.83 mm (crop ≈ 6.3).
  - From the OPAX lens model, rho/theta (px per radian) runs from 756 at the centre to ~880 near 85° and 862 at the circle edge (95.7°), so it's not purely equidistant. At 1.34 µm/px that's ≈1.0 mm at the centre and ≈1.15–1.2 mm overall (assumes no resampling into the 2912 halves; unverified).
  - PTGui converts mm + crop factor using the loaded image width, so 1.2 mm needs crop factor ≈4.44 for the 5824-wide DNG, ≈8.93 for a 2896 half and ≈4.47 for the 5792 JPEG. The EXIF 5.0 fits none of them. Simplest: enter HFOV ≈190° and let the optimiser refine it.
