# gear360-raw

Tools, camera mod files and findings for shooting RAW on the Samsung Gear 360 (2017, model SM-R210), converting it to DNG with the camera's own colour calibration, and stitching it with the camera's own lens model. In our review of every public Gear 360 repo and issue thread (October 2026), nobody had published RAW from this camera, so this is the first public RAW from it that we know of. The 2016 Gear 360 (SM-C200) is a different camera and none of this has been tested on it.

## What works and what doesn't

| Feature | Works? | Notes | Doc |
|---|---|---|---|
| RAW capture | Yes | The sensor-interface dump (`st cap seq dump on ssif`): a 12-bit Bayer frame, 5824 × 2896, both lenses side by side, written next to the normal JPEG | [raw-capture.md](docs/raw-capture.md) |
| DNG with camera colour | Yes | Colour matrices from the camera's colour-correction matrix and lens-EEPROM AWB points, plus the white balance recorded for each shot | [dng-colour.md](docs/dng-colour.md) |
| Exact lens model | Yes | The per-unit factory calibration stored in every photo (maker note `0x0012`), used with the firmware's OCamCalib-style model | [lens-model.md](docs/lens-model.md) |
| Stitching | Yes | `tools/opax_stitch.py`, or PTGui with a ChArUco-calibrated template | [stitching.md](docs/stitching.md) |
| Web UI and one-button RAW shot | Yes | Control page on the camera's hotspot; a double-press of Power takes one photo with a RAW | [raw-capture.md](docs/raw-capture.md#ways-to-shoot-raw) |
| Exposures longer than about 1/6 s | No | Measured cap: a "1 s" request gave about 0.173 s. Every long-exposure path we tried (Bulb, long-exposure NR) hangs the camera until a reboot | [exposure.md](docs/exposure.md) |

## Quick start

1. Put ottokiksmaler's SD card mod on the card: `gear360_mods_SD.zip` from https://github.com/ottokiksmaler/gear360_modding.
2. Copy our files on top of it, with the card in the PC. A prebuilt web UI is in `camera-www/dist/` (rebuild it with `python3 tools/build_www.py` if you change anything):

   | From this repo | To the SD card |
   |---|---|
   | `camera-www/sdroot/mod.sh` | `mod.sh` in the card root (replaces the mod's own) |
   | `camera-www/mods/*` (`rawwatch.sh`, `G360POWE_G360POW.sh`, `camera_settings_iso100.sh`) | `mods/` |
   | everything in `camera-www/dist/` (`index.html`, `cgi-bin/`) | `mods/www/` |

3. Put the card in the camera and power it on. The servers start by themselves about 15 s after boot. Turn on the camera's hotspot: hold Menu until the screen offers a "Connect to …" option, press Menu again until it shows "Connect to iOS" (or "Connect to Android"), and confirm with the shutter button. These are the steps from ottokiksmaler's and vitorio's guides; vitorio suggests picking the phone type you're not using. Don't pick "Connect to Street View", which is a different (OSC) mode. Then join the Wi-Fi network the camera creates (named like `Gear 360(1A2B)`; the password is shown on the camera's screen) and open http://192.168.43.1:8888/.
4. Shoot RAW: turn on "Save RAW + WB with every shot" in the web UI and take a photo, or double-press Power in Photo mode. The watcher on the camera moves each dump next to its JPEG as `DCIM/100PHOTO/360_NNNN.raw` and saves the white balance as `360_NNNN_wb.txt`. Download all three from the web UI's Files tab.
5. Convert to DNG on the PC. `exiftool` must be on the PATH to copy the shot's EXIF into the DNG.

   ```
   pip install -r requirements.txt
   python3 tools/raw2dng.py 360_NNNN.raw
   ```

6. Stitch. For `tools/opax_stitch.py`, demosaic the DNG to a full-size TIFF first (for example with `dcraw -w -T 360_NNNN.dng`, which keeps the shot's white balance from the DNG), then:

   ```
   python3 tools/opax_stitch.py --layout raw stitch 360_NNNN.tiff 360_NNNN_pano.tif --rot -0.14 -0.12 0.16
   ```

   `--layout` goes before `stitch`, and `--rot -0.14 -0.12 0.16` is the lens-2 correction for our unit. Camera JPEGs work too, with the layout guessed from the size. For PTGui, open the DNGs with `templates/charuco_pooled.pts` as the template, and build HDR projects for brackets with `tools/make_hdr_pts.py`:

   ```
   python3 tools/make_hdr_pts.py brackets/360_039[1-5].dng --template templates/charuco_pooled.pts --out "brackets/360_0391 HDR.pts"
   ```

Read [docs/safety.md](docs/safety.md) before experimenting: some commands hang or crash the camera, and the mod gives root shell access over HTTP to anyone on the network, so use it only on the camera's own hotspot.

## Sample shots

Raw dumps, with their DNGs and camera JPEGs, are attached to the GitHub Release ([Releases](../../releases)).

## Docs

- [raw-capture.md](docs/raw-capture.md): installing the mod, turning the sensor dump on and safely off, the file format, the raw watcher, and why the camera's own RAW quality settings don't work.
- [dng-colour.md](docs/dng-colour.md): what `raw2dng.py` does, its options, and where the colour matrices and per-shot white balance come from.
- [lens-model.md](docs/lens-model.md): the factory lens calibration in every photo, its 15 named fields, the OCamCalib variant the camera's stitcher uses, and how raw pixels map onto JPEG pixels.
- [stitching.md](docs/stitching.md): `opax_stitch.py` and its options, Samsung's lens-shading correction, the PTGui template, and calibrating your own unit with ChArUco boards.
- [exposure.md](docs/exposure.md): setting shutter speed and ISO with `st` commands, the measured ~1/6 s cap and the firmware code behind it, the long-exposure paths that hang, and the S5K2M8 sensor.
- [commands.md](docs/commands.md): how `st` commands reach the capture RTOS, how to send them over Wi-Fi, the `commands.csv` catalogue and its risk classes, and the commands we found most useful.
- [safety.md](docs/safety.md): what hangs or loses the camera, remote recovery with `tools/camrecover.sh`, the never-run list, exFAT card problems, and the mod's security cost.
- [lab-notebook.md](docs/lab-notebook.md): the working notebook in date order, with dead ends, corrections and guesses.

## Repo layout

```
tools/         PC-side scripts: raw2dng, opax_stitch, PTGui helpers, ChArUco solve, command runner, disassembly helpers, camrecover.sh
camera-www/    files for the camera's SD card: web UI source and prebuilt dist/, CGIs, mod.sh, raw watcher, Power double-press script
utils/         ChArUco board and projector grid generators, with ready-made boards
templates/     PTGui template calibrated for our unit (charuco_pooled.pts)
sensor-data/   reference PDFs on the sensor family (S5K3L6 sibling datasheet, ISOCELL)
docs/          the documentation listed above
commands.csv   catalogue of known camera commands with risk class and test results
```

## Credits

This builds on years of work by others:

| Who | Links | What it gave this project |
|---|---|---|
| ottokiksmaler | https://github.com/ottokiksmaler/gear360_modding · https://github.com/ottokiksmaler/nx500_nx1_modding | the SD-card mod and keyscan360, and the `st` command docs everything else builds on |
| ge0rg (Georg Lukas) | https://github.com/ge0rg/samsung-nx-hacks · https://op-co.de/blog/tags/samsung-nx/ | `slp-firmware.py` (unpacked the R210 firmware), stapp, the DFMS docs, and the question of where `capdtm` lives |
| ultramango | https://github.com/ultramango/gear360pano · https://github.com/ultramango/gear360reveng | Hugin stitching scripts and early Gear 360 reverse engineering |
| vitorio | https://github.com/vitorio/gear360-2017-mods | mods for the 2017 model |
| hasenbalg · bluedskim · robhubi | https://github.com/hasenbalg/gear360-2017-mods · https://github.com/bluedskim/gear360-2017-mods · https://github.com/robhubi/gear360_modding | web UI and time-lapse ideas |
| niluss | https://github.com/niluss/gear360_gallery_mod | gallery and dual-fisheye viewer |
| KieronQuinn | https://github.com/KieronQuinn/Gear360_OSS | firmware hashes, used to verify our firmware download |
| ilker-aktuna | https://github.com/ilker-aktuna/Gear-360-File-Access-from-Android-phones | alternative mod and time sync |
| lansysart | https://github.com/lansysart/gear360-telnet.usbshell-mod | telnet and Wi-Fi client mode on the 2016 model |
| mewlips | https://github.com/mewlips/nx-remote-controller-mod | NX live-view streaming |
| WApaperplane | https://github.com/WApaperplane/NXWA-nx500_modding | NX500 ISP internals |
| patxitron | https://github.com/patxitron | the NX500 bulb key sequence (NX500_intervalometer) |
| usumfabricae | https://github.com/usumfabricae | found the camera's stitching library (gear360reveng #8) |
| nxfiles.nx.tc | https://nxfiles.nx.tc/ | mirrors the R210 firmware and source bundle |
| Everyone in the issue threads | [vasile-gh](https://github.com/vasile-gh) · [utack](https://github.com/utack) · [ivent](https://github.com/ivent) · [Tommixoft](https://github.com/Tommixoft) · [Nick-0814](https://github.com/Nick-0814) · [nhhollander](https://github.com/nhhollander) · [woroko](https://github.com/woroko) · [tdechangy](https://github.com/tdechangy) · [sithgundam](https://github.com/sithgundam) · [sebastian1111](https://github.com/sebastian1111) · [royeiror](https://github.com/royeiror) · [oukene](https://github.com/oukene) · [ilowen](https://github.com/ilowen) · [ftoledo](https://github.com/ftoledo) · [andrew-bydlon](https://github.com/andrew-bydlon) · [amvzo](https://github.com/amvzo) · [amougel](https://github.com/amougel) · [Zlikster](https://github.com/Zlikster) · [Skygaze](https://github.com/Skygaze) · [PeterNX](https://github.com/PeterNX) · [PABourdin](https://github.com/PABourdin) · [MarkVillacampa](https://github.com/MarkVillacampa) · [LogicBypass](https://github.com/LogicBypass) · [GrzegorzKarczewski](https://github.com/GrzegorzKarczewski) · [Etua](https://github.com/Etua) | questions and findings in the gear360_modding, nx500_nx1_modding, gear360reveng, gear360pano, gear360-2017-mods and Gear360_OSS issues |

Built with and referenced:

- [PiDNG](https://github.com/schoolpost/PiDNG), which writes the DNGs.
- OCamCalib by Davide Scaramuzza, the lens model family Samsung's stitcher uses.
- OpenCV, for ChArUco detection, registration and the optical-flow seam.
- Ghidra, Capstone and pyelftools, for reading the firmware.
- [insv-stitch](https://github.com/BenjaminHenriksson/insv-stitch), the reference for the optical-flow seam.
- The [Meizu m685 kernel](https://github.com/meizuosc/m685), for the S5K2M8 sensor registers.

## Licence

The code is GPL-3.0 ([LICENSE](LICENSE)). The docs are CC BY 4.0 ([LICENSE-docs](LICENSE-docs)).

`camera-www/mods/camera_settings_iso100.sh` is adapted from ottokiksmaler's gear360_modding SD mod, and `camera-www/mods/G360POWE_G360POW.sh` uses that mod's keyscan360 double-press hook. `camera-www/vendor/` is Bootstrap 5.3.3 (MIT). `sensor-data/` holds third-party PDFs, included for reference.

This project is not affiliated with Samsung.
