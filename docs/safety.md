# Safety and recovery

What hung the Gear 360 or lost it during this project, how to recover remotely, which commands to stay away from (and how sure we are about that), and the security cost of the mod.

## Things that hang the camera app

Each of these leaves the camera app on "Capturing" for good. The camera stays on Wi-Fi and the RTOS still answers commands, but no more photos get taken until a reboot.

- RAW image quality. `st cap capdtm setusr 4 0x00040004` (or any other RAW option of setting 4) and then a shot: the A7 finishes but has no buffer for the compressed RAW (`Raw Compress Address is NULL!!`), and nothing is saved, not even the JPEG. Use the sensor dump instead ([raw-capture.md](raw-capture.md)). The setting persists across a reboot, so put it back with `setusr 4 0x00040000`.
- Bulb. `setusr 1 0x00010006` (SHOOTINGMODE_BULB) and a press: Bulb always programs a 30 s exposure, then hangs after readout at `SensorCb(2)`. It hung with the self-timer on and off, and with long-exposure NR off.
- Long exposures with long-exposure NR on. With LTNR on (the default after a reboot), an app shutter of 10 s or 30 s takes the LTNR still path and hangs the same way, with or without the raw dump, and with either shutter type (`setusr 117`). With LTNR off the same requests take a different path and finish, but are clamped to about 1/6 s (see [exposure.md](exposure.md)).
- `st cap capt single start`. It fires a capture on the capture processor and then stalls at the same point.

After the first Bulb hang we reset the camera to Program (`setusr 0 0x00000002`, `setusr 1 0x00010001`, ISO Auto) before rebooting, so it wouldn't boot back into Bulb. The web UI's Auto button sends those first two commands.

### Nothing un-sticks it without a reboot

We tried these while hung, and none brought the app back:

- `st cap capt stop` 0 to 6, `capt liveview start`, `capt init`, `capt bulb stop` (which also switched SHOOTINGMODE to PROGRAM), `capt sts s1cancel` (which queued another capture instead).
- `st cap cis md 10`: the sensors switch mode cleanly, but no frames reach the SoC.
- Restarting `di-camera-app` (see below).

While hung, the sensor registers still read normally, the T-Kernel task list shows the capture workers idle waiting for messages, and the SSIF, PP and AWB interrupt counts stay frozen. Our reading is that the still path waits for a frame-done event that never comes, and no command supplies it. Only a full reboot recovers.

## Commands that lost the camera

These stopped the camera answering during command-testing runs. The first three were classed as reads when they ran, which is why the risk classes below are a guide and not a guarantee. Treat them as supervised-only:

- `st misc earjack` (batch 1 lost the camera around this command; not confirmed that this command caused it)
- `st cap cis vdtime` (the camera stopped responding, then shut down)
- `st thread` (no reply in 120 s and the `echo ok` probe also timed out; nobody checked whether the camera crashed, powered off or only blocked the web server; the battery read 91 % ten minutes earlier)
- the sensor register write test: one `run` request chained `regr a 0x0704`, `regw a 0x0704 0x0100`, a read back, `regw a 0x0704 0` and another read back. No reply came back and the camera was found powered off. We don't know whether the write crashed it. Send `regr` and `regw` as separate requests, so the log shows which step it died on.

`st log afinfo` didn't lose the camera, but it hung for more than 120 s with no reply: the camera stayed up and other `st` built-ins still answered, while the `st log afinfo` process stayed blocked. Supervised only as well.

Bare `st firmware`, `st readl` and `st dump` (no arguments) were also left out of the bulk runs on purpose: `st firmware`'s subcommands flash firmware, and a bare `st readl`/`st dump` might read physical address 0 if the argument parsing defaults to 0. Nobody has checked either.

## Don't restart the camera app from the mod

`systemctl restart di-camera-app.service` took down our telnet, FTP and web servers. The hotspot stayed up, the status screen still said "Capturing", and the Power double-press did nothing, so a power cycle was needed anyway. The likely cause (unverified) is that the mod is launched by the app (`info.tg` → `nx_cs.adj` → `mod.sh` → `keyscan360` → servers), so it lives in the app's systemd cgroup and gets killed with it, and the new app instance didn't re-run `mod.sh`. A hung A7 capture would stay stuck after an app restart in any case.

## Remote recovery

A clean Linux reboot through the `run` CGI works, including on a hung camera:

```
setsid sh -c 'sleep 3; sync; systemctl reboot' >/dev/null 2>&1 < /dev/null &
```

`tools/camrecover.sh` sends it this way:

```
curl -s -G --max-time 20 "$CAM" \
    --data-urlencode "cmd=setsid sh -c 'sleep 3; sync; systemctl reboot' >/dev/null 2>&1 < /dev/null & echo scheduled"
```

The camera goes down a few seconds later and the web server is back about 28 s after that, with no button press: `mod.sh` restarts the servers and `rawwatch.sh`. Settings return to their defaults (Program, ISO Auto, high-ISO NR MID, long-exposure NR ON). `/proc/sys/kernel/random/boot_id` stays the same across these reboots (likely because of the snapshot fast boot), so check `/proc/uptime` to tell whether it rebooted.

The PC drops the camera's Wi-Fi during the reboot and has to rejoin it. From Windows (we ran it from WSL):

```
powershell.exe -NoProfile -Command 'netsh wlan connect name="Gear 360(XXXX)"'
```

On Windows 11 this needs Location services and "Let desktop apps access your location" both on, because Windows requires location consent for any app using the WLAN API (the Wi-Fi flyout is exempt). We also set the profile to `connectionmode=auto`. In our fully remote test the camera was down at 9 s, the connect succeeded at 39 s, and the web server answered at 50 s.

`tools/camrecover.sh` does the whole sequence from WSL:

```
tools/camrecover.sh "<Wi-Fi profile name>"
```

The profile is the camera's hotspot, e.g. `"Gear 360(1A2B)"`; list them with `netsh wlan show profiles`. The script reads the camera's uptime through `cgi-bin/run`. If the camera answers, it sends the reboot, waits up to 30 s for it to go down and another 25 s for the hotspot. Then, up to 12 times, it checks the uptime and, if there is no answer, runs `netsh wlan connect` through `powershell.exe` and waits 10 s. It prints the new uptime and exits 0 once the camera answers, or exits 1 after about 2 minutes. If the camera doesn't answer at the start, it skips the reboot and goes straight to reconnecting.

If none of that works, power-cycle the camera by hand.

## Turns photos green until a reboot

`st cap seq dump off ssif` looks like the obvious way to turn the raw dump off, but don't use it. Its handler inverts the mask and stores 0xFFFFFFEF in the dump flag, which switches every other post-processing dump on, and photos come out green until a reboot. Clear the flag with `st writel 0x8196a1c8 0` instead, after `st readl 0x8196a1c8` shows 0x10 ([raw-capture.md](raw-capture.md#turning-it-off-dont-use-dump-off)). The same applies to `dump off` with any other dump name.

## How the risk classes were set

The `risk` column in [`commands.csv`](../commands.csv) (read / set / action / never) is our judgement from each command's name, its help text and what the NX500/NX1 community reported. It is not a record of what happened. None of the commands below has been run on this camera, apart from the two noted as tested.

The evidence also cuts the other way: three of the four times we lost the camera, the command was classed as a harmless read when it ran (`st misc earjack`, since moved to `action`; `st cap cis vdtime`; `st thread`; see [Commands that lost the camera](#commands-that-lost-the-camera)). Treat every untested command as unknown, whatever its class says, and run it alone, supervised, with a way to reboot.

## Don't run: could do lasting damage

These could change something that a reboot doesn't undo. We haven't run any of them and don't plan to.

- `dfmstool -w/-o/-d`: write adjust data or defaults. The adjust data includes the factory calibration, among it the lens EEPROM record ([lens-model.md](lens-model.md)) that every photo's maker note and our stitcher depend on. There's no known way to restore it. ge0rg's DFMS notes for the NX500 flag these writes as dangerous.
- `prefman set …`: writes the preference/adjust partitions, which also hold calibration.
- `st firmware up`, `st firmware merge`, `st app fwupgrade`: firmware writes. A bad flash could brick the camera.
- `st pmic write`, `st dvfs set …`, `st dvfs vol set`: change voltages. Could in principle damage hardware; nobody has shown that on this camera.
- `st gpio set`: drives a GPIO pin. Without a pin map, driving the wrong pin could in principle damage something.
- `st app event reset [all, camera, wifi, factory]`: factory reset. We don't know what it wipes.
- `st app foramt` (sic): formats the SD card. Only the card's contents are at risk, but that includes your photos and the mod.
- the `st micom` control subcommands (`watchdog`, `qstart`, `release`, `thread`, `chg`, `sel`, `event`, `stlcd`, `dump`): the micom is the power and battery controller. These are different from the dot-matrix drawing commands (`st micom dmdraw`, `dmupdate` …), which are classed `set`.

## Avoid unless you know why: likely needs a reboot

These are expected to crash, hang or confuse the camera, but not to leave anything behind after a reboot. That expectation comes from what they do (they act on running state, not on stored data) and is only confirmed for the two tested ones.

- `st writel <addr> <value>`: 32-bit register or RAM write. Tested: clearing the raw-dump flag with `st writel 0x8196a1c8 0`, after `st readl 0x8196a1c8` shows 0x10, works and is how we turn the dump off ([raw-capture.md](raw-capture.md#turning-it-off-dont-use-dump-off)). Other addresses could hang the camera.
- `systemctl restart di-camera-app.service`: tested. It kills the mod's servers until a reboot (see [Don't restart the camera app from the mod](#dont-restart-the-camera-app-from-the-mod)).
- `st cap ref reboot`: reboots the T-Kernel on the A7 under a running Linux side. A full Linux reboot ([Remote recovery](#remote-recovery)) is the known-good way to restart everything.
- `st util fault`: makes a deliberate fault (a crash).
- `st usb test appkill`: kills the camera app, with the same result as restarting it.
- `st pmu set`, `st clk set`: power an IP block on or off, gate a clock. Likely a hang.
- `st cap capt mcb …`: a raw multicore-bridge message in a format we don't know. Likely a hang.
- `st usb mode dnl`: download (Odin) mode. We expect a power cycle to get out of it, as on other Samsung devices (unverified here). The danger is flashing firmware while in it, not the mode itself.

All of the commands in both lists are still `never` in `commands.csv`, so `runcommands.py` refuses them whatever its options say. Run anything from the second list by hand.

## exFAT phantom entries

The SD card is exFAT. After repeated deploys with an older `put` CGI that wrote `file.part` and then renamed it over the old file, `ls` listed `index.html` 11 times, `run` 3 times and `files` 2 times, all with the same inode, size and time. Opening the name gave the latest file, and `rm` succeeded once, but after the file was restored the duplicates were listed again. Windows on the PC lists them too, so they are on the card itself and not a camera-driver cache.

- Deploy by writing in place. The current `put` CGI truncates and writes the target directly, and `rawwatch.sh` only renames to new names. Copying files onto the card from the PC with a plain `cp` also worked (md5 matched).
- A photo the camera was writing when it died (`360_0367.JPG`, 0 bytes) became a broken entry: Linux `stat` gives "Invalid argument", and `rm` and PowerShell `Remove-Item` report success but leave it. Fixing that needs `chkdsk G: /f` from an admin prompt on the PC. Run it on the PC, not on the camera while the card is mounted. It might clear the phantom duplicates too; we haven't tried it.

## Security

The mod's `cgi-bin/execute` and our `cgi-bin/run` both run any shell command as root from a URL, and telnet is root with no password. That's fine on the camera's own hotspot. Don't let the camera join a shared network with the mod active.

## Battery

On 2026-10-10 the camera died mid-session with a low battery, and `st` calls had slowed to 2-3 s each beforehand. If commands start getting slow, check the battery (`st bat get_soc`) before blaming the command.

Source: [Camera session 1 — RAW test 1: IMAGEQUALITY_RAW_SUPERFINE (2026-10-10)](lab-notebook.md#camera-session-1--raw-test-1-imagequality_raw_superfine-2026-10-10), [Camera session 1 — recovery (2026-10-10)](lab-notebook.md#camera-session-1--recovery-2026-10-10), [Long exposure tests (2026-10-10)](lab-notebook.md#long-exposure-tests-2026-10-10), [Recovering from the Bulb hang: what the `capt` commands do (2026-10-10)](lab-notebook.md#recovering-from-the-bulb-hang-what-the-capt-commands-do-2026-10-10), [Command-testing batch 2: stopped early (2026-10-10)](lab-notebook.md#command-testing-batch-2-stopped-early-2026-10-10), [Command-testing batch 3: stopped early at `st thread` (2026-10-11)](lab-notebook.md#command-testing-batch-3-stopped-early-at-st-thread-2026-10-11), [A7 firmware in Ghidra: how exposure reaches the sensor (2026-10-11)](lab-notebook.md#a7-firmware-in-ghidra-how-exposure-reaches-the-sensor-2026-10-11), [Long exposures are capped at ~1/6 s: measured (2026-10-12)](lab-notebook.md#long-exposures-are-capped-at-16-s-measured-2026-10-12), [SD card exFAT: phantom duplicate directory entries (2026-10-10)](lab-notebook.md#sd-card-exfat-phantom-duplicate-directory-entries-2026-10-10), [SD card clean-up and new per-lens raw dumps (2026-10-11)](lab-notebook.md#sd-card-clean-up-and-new-per-lens-raw-dumps-2026-10-11)
