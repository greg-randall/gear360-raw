# Shooting RAW

How to get the raw Bayer sensor frame out of the Gear 360 (2017, SM-R210): installing the SD card mod, turning the sensor dump on and off safely, where the files go, and what is in them.

## What you get

With the A7 capture sequencer's sensor-interface dump switched on (`st cap seq dump on ssif`), every photo also writes the full sensor frame to the SD card as a headerless file. The camera still saves its normal JPEG and the app does not hang. The dump is a 12-bit Bayer frame with both fisheyes side by side, before lens-shading correction (the A7 log says `LSC off`).

The camera's own RAW quality settings do not work on this model (see [Why the RAW quality modes don't work](#why-the-raw-quality-modes-dont-work)), so the dump is the only route we have found.

## Install

1. Put ottokiksmaler's SD card mod on the card first: `gear360_mods_SD.zip` from https://github.com/ottokiksmaler/gear360_modding. Its boot chain is `info.tg` → `nx_cs.adj` → `mod.sh` → `keyscan360`. It brings the BusyBox servers (telnet, FTP, httpd on port 8888) and the `cgi-bin/execute` CGI that runs a shell command from a URL.
2. Build our web UI on the PC:

   ```
   python3 tools/build_www.py
   ```

   This writes `camera-www/dist/index.html` (Bootstrap, the app and `commands.csv` all inlined into one file) and copies `camera-www/cgi-bin/*` to `camera-www/dist/cgi-bin/`.
3. Copy our files on top of the mod, with the card in the PC:

   | From this repo | To the SD card |
   |---|---|
   | `camera-www/sdroot/mod.sh` | `mod.sh` in the card root (replaces the mod's own) |
   | `camera-www/mods/*` (`rawwatch.sh`, `G360POWE_G360POW.sh`, `camera_settings_iso100.sh`) | `mods/` |
   | everything in `camera-www/dist/` (`index.html`, `cgi-bin/`) | `mods/www/` |

   On the camera the card root is `/sdcard` (the same card is also mounted as `/mnt/mmc`), so these land in `/sdcard/mod.sh`, `/sdcard/mods/` and `/sdcard/mods/www/`. If the card shows as read-only on the PC, check the SD adapter's lock switch.
4. Put the card in the camera and power it on. The camera's DFMS daemon runs `/mnt/mmc/mod.sh` at every boot and resume. Our `mod.sh` starts `keyscan360` and `rawwatch.sh` straight away, then FTP, telnet and httpd 15 s later, so no Power double-press is needed to get the servers.
5. Turn on the camera's hotspot: hold Menu until the screen offers a "Connect to …" option, press Menu again until it shows "Connect to iOS" (or "Connect to Android"), and confirm with the shutter button. These are the steps from ottokiksmaler's and vitorio's guides; vitorio suggests picking the phone type you're not using. Don't pick "Connect to Street View", which is a different (OSC) mode. Then join the Wi-Fi network the camera creates (named like `Gear 360(1A2B)`; the password is shown on the camera's screen) and open http://192.168.43.1:8888/.

### Updating over Wi-Fi

Once the `put` CGI is on the card, the web UI can be redeployed without taking the card out:

```
python3 tools/build_www.py
cd camera-www/dist && for f in index.html cgi-bin/*; do curl -s --data-binary @"$f" "http://192.168.43.1:8888/cgi-bin/put?path=$f"; done
```

`put` writes the POST body to a file under `/sdcard/mods/www/` and replies with its md5. It refuses absolute paths and paths containing `..`. It writes in place, because rename-over-existing left phantom directory entries on the card's exFAT file system (see [safety.md](safety.md#exfat-phantom-entries)). For files outside `mods/www`, we sent them through the `run` CGI and decoded them with `busybox base64 -d`; the camera has no `base64` command of its own, so busybox comes from `ln -sf /mnt/mmc/mods/httpd /tmp/busybox` (the mod's binaries are BusyBox v1.18.4).

## Turning the dump on

```
st cap seq dump on ssif
```

The reply is `FRAME SSIF Dump on / Set PP Dump Flag 0x10`. From then on, each shot writes

```
/sdcard/N_N_11648_5824x2896_bayer_12-16.raw
```

where `N_N` counts up per shot (`0_0`, `1_1`, …). Each file is 33,732,608 bytes (5824 × 2896 × 2). The A7 log shows `Dump STILL_360_PP_SSIF(0x15000) Material Image` and `File Dump Start!! ADDR = 0xa6000000, SIZE = 33732608`; writing it to the card takes about 2.6 s, and it appears 3-5 s before the JPEG. The dump stays on for every shot until you clear it.

We first did this with image quality on the normal SUPERFINE JPEG setting. Leave image quality on a JPEG setting.

## Turning it off: don't use `dump off`

`st cap seq dump off ssif` replies `Set PP Dump Flag 0xFFFFFFEF`, and every photo after that is green (the first one averaged BGR 5.8 / 68.3 / 29.8) until the camera is rebooted. Photos taken with the dump on are fine.

The cause is in the A7 firmware's `st cap seq dump` handler. Each dump name sets one bit in a mask (`pp` = 1, `aeawb` = 2, `lrc` = 4, `sub` = 8, `ssif` = 0x10). For "off" the handler inverts the mask and stores the result as a plain write to the word at 0x8196a1c8. So "on ssif" writes 0x10, "off ssif" writes 0xFFFFFFEF (every other post-processing dump bit on), and no combination of names can write 0.

The clean way off is to write 0 to that word, and only after checking that it holds 0x10:

```
st readl 0x8196a1c8
st writel 0x8196a1c8 0
```

We tested this on 2026-10-11: `st readl` showed 0x10 after a dump on and 0 after the write, and the next shutter press gave a JPEG only, with normal colour. The web UI's RAW switch and the Power double-press script both turn the dump off this way, and both leave the flag alone if it reads anything other than exactly 0x10. `st writel` is otherwise on our never-run list; this one address is the exception.

## File format

| Property | Value |
|---|---|
| Size | 5824 × 2896 pixels, 33,732,608 bytes, no header |
| Sample | uint16, little-endian (stride 11,648 bytes) |
| Bit depth | 12-bit, high-aligned (the 12-bit value × 16; no pixel has any of its low 4 bits set) |
| Bayer pattern | GRBG |
| Black level | 4096 in 16-bit terms (256 in 12-bit) |
| White level | 65472 (4092 × 16, saturated) |
| Layout | both fisheye images side by side, 2912 pixels wide each |

The black level was measured in the unlit corners outside each fisheye circle, four 100 × 100 patches per Bayer channel per lens: the median is exactly 256 (12-bit) for both lenses and all four channels, means 256.4-256.8, σ ≈ 4 DN at ISO 160. It is not in the factory calibration data. A lens-capped dark frame would confirm it at other ISOs and exposures; we haven't shot one.

GRBG was chosen because cells (0,0) and (1,1) have equal, higher means (the greens), and it renders red keyboard keys red and a blue screen blue; GBRG swaps red and blue. The frame looks unprocessed ("PP_SSIF" is the sensor-interface output going into the pre-processor), but we have not proved that no processing happens before the dump.

To view one without converting, Photoshop's File → Open As → Photoshop Raw works with width 5824, height 2896, 1 channel, 16-bit, header 0, byte order IBM PC.

## Where the files end up

The `N_N` counter restarts at 0 after every power cycle, and new dumps overwrite old ones with the same name. The camera clock also resets to 2017-01-01 at boot until the web UI syncs it, so file times repeat across sessions too. Dumps need moving off the SD root before the next boot.

`mods/rawwatch.sh` does this. It is started by `mod.sh` at boot, and by the web page on load if it isn't running. Every 3 s it looks for dumps in the SD root that are 33,732,608 bytes and unchanged for 2 s, pairs each with the first JPEG saved 0-20 s after it, and moves it next to that JPEG:

```
/sdcard/N_N_11648_5824x2896_bayer_12-16.raw  ->  /sdcard/DCIM/100PHOTO/360_NNNN.raw
```

Straight after the move it writes `360_NNNN_wb.txt` with the output of `st cap iq awb wbgain` (the live AWB gains, which `raw2dng.py` reads for the DNG's white balance). It leaves a dump alone if no JPEG turns up, or if the target name already exists. It runs as a single instance (`/tmp/rawwatch.pid`) and logs to `/tmp/rawwatch.log`; the web UI's "Watcher log" button shows the log.

For dumps the watcher left behind, the `tidyraw` CGI pairs them with JPEGs by time once and also moves any matching `_wb.txt`. Unlike the watcher, it doesn't check the file size or wait for the file to stop growing, so it would also rename a per-lens dump or a dump that is still being written. Run it only when no shot is in progress, and check with `?dry=1` first, which reports what it would do without moving anything:

```
http://192.168.43.1:8888/cgi-bin/tidyraw?dry=1
```

To download, use the web UI's Files tab, or the `get` CGI directly (`GET /cgi-bin/get?path=<urlencoded absolute path under /sdcard>[&dl=1]`). The mod's FTP server was no use for this: listings came back empty and downloads failed with curl error 56.

## Ways to shoot RAW

- Web UI: turn on "Save RAW + WB with every shot", then use Take photo, Shoot burst or Shoot bracket. The switch runs `st cap seq dump on ssif; touch /tmp/rawdump_on` and starts the watcher; turning it off does the clean `writel` above. The marker in `/tmp` clears on reboot.
- Power double-press: `mods/G360POWE_G360POW.sh` takes one photo with a RAW. It refuses unless the camera is in Photo mode (`prefman get 0 0x00004445 b` must be 0x01, because in Video mode the shutter would start a recording), turns the dump on, makes sure `rawwatch.sh` is running, sends `st key click s2`, waits up to 60 s for the new JPEG, then clears the dump flag. If the web UI switch had the dump on (`/tmp/rawdump_on`), it leaves it on. LED 5 blinks while it works, and it logs to `/tmp/menuraw.log`. A plain shutter press stays JPEG only. A retest of both (double-press gives a RAW, plain shutter gives a JPEG only) passed, reported 2026-10-30.
- Physical shutter with the dump left on: this writes a dump too, and the watcher moves it next to its JPEG like any other.

`keyscan360` runs `<dir>/<KEY>_<KEY>.sh` on a double-press of the same key within 1 s, with the name cut to 16 characters, which is where `G360POWE_G360POW.sh` comes from. We tried the Menu key first, but Menu presses also cycle the camera mode, so we moved the script to Power. The old Power double-press settings from ottokiksmaler's mod (ISO 100, shutter priority, NR off) are kept in `mods/camera_settings_iso100.sh`, which nothing calls.

## Why the RAW quality modes don't work

The firmware's IMAGEQUALITY setting has RAW options, and `st cap capdtm setusr 4 0x00040004` selects `IMAGEQUALITY_RAW_SUPERFINE` (`getusr 4` confirms it). With that set, a shot writes nothing, not even the JPEG, and the status screen stays on "Capturing" until a power cycle.

The A7 side does its part: it plans three raw passes, reads a 5824 × 2896 12-bit frame, and finishes normally. Then it logs `Raw Compress Address is NULL!!`, meaning it had no buffer for the compressed RAW (SRW). The Linux side had sized the image as JPEG only, and the app waits for an image set that never completes. Our reading of this, unverified: the Gear 360 app never sets up SRW buffers because the camera never offered RAW. RAW_SAVE and SSIF_RAW were still OFF during that test; turning them on is another possible route to SRW that we haven't tried.

Put IMAGEQUALITY back with `st cap capdtm setusr 4 0x00040000` (SUPERFINE). The setting persists across a power cycle. See [safety.md](safety.md) for the hang.

## Open questions

On 2026-10-11 the SD root also held files named `N_N_5824_2896x2896_bayer_12-16.raw`, each 16,866,304 bytes, which is 2912 × 2896 × 2. We think each is one lens at 16 bits, but none has been decoded. Five appeared that day, each with a 0-byte `N_N_0_0x0_aeawb.patch` file: two pairs about 2 s apart that belong to the normal-colour photos 360_0365 and 360_0366, and a lone file at 17:23, when the camera went off during the register-write test. Four more appeared that evening, all made while the dump flag held 0xFFFFFFEF, so those likely come from one of the other dump points (`lrc` or `sub`?) rather than a new ssif format. That is inferred from timing only, and the afternoon pairs don't fit it. `rawwatch.sh` only matches the full-frame size, so it leaves these where they are (`tidyraw` doesn't check size and would rename them). `tools/inspect_dump.py` reports statistics and a quick-look image for files like these.

## Next step

Convert the raws to DNG on the PC:

```
python3 tools/raw2dng.py 360_NNNN.raw
```

See [dng-colour.md](dng-colour.md) for the options and how the colour is worked out.

Source: [Camera session 1 — RAW test 2: `st cap seq dump on ssif` ✅ (2026-10-10)](lab-notebook.md#camera-session-1--raw-test-2-st-cap-seq-dump-on-ssif--2026-10-10), [RAW test 3: second dump shot + ColorChecker in frame (2026-10-10)](lab-notebook.md#raw-test-3-second-dump-shot--colorchecker-in-frame-2026-10-10), [Raw files live next to their JPEGs (2026-10-10)](lab-notebook.md#raw-files-live-next-to-their-jpegs-2026-10-10), [Physical shutter + timezone check (2026-10-10)](lab-notebook.md#physical-shutter--timezone-check-2026-10-10), [Raw watcher (2026-10-10)](lab-notebook.md#raw-watcher-2026-10-10), [SD card setup (2026-10-10)](lab-notebook.md#sd-card-setup-2026-10-10), [Camera web UI v1 (2026-10-10)](lab-notebook.md#camera-web-ui-v1-2026-10-10), [Boot-time servers and Menu double-press RAW shot (2026-10-11)](lab-notebook.md#boot-time-servers-and-menu-double-press-raw-shot-2026-10-11), [Power RAW retest, web UI sizes and preview, grid shots, PTGui lens numbers (2026-10-11)](lab-notebook.md#power-raw-retest-web-ui-sizes-and-preview-grid-shots-ptgui-lens-numbers-2026-10-11), [Camera session 1 — RAW test 1: IMAGEQUALITY_RAW_SUPERFINE (2026-10-10)](lab-notebook.md#camera-session-1--raw-test-1-imagequality_raw_superfine-2026-10-10), [SD card clean-up and new per-lens raw dumps (2026-10-11)](lab-notebook.md#sd-card-clean-up-and-new-per-lens-raw-dumps-2026-10-11)
