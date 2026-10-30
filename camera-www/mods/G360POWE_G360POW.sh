#!/bin/bash
# Uses the keyscan360 double-press hook from ottokiksmaler's gear360_modding SD mod (https://github.com/ottokiksmaler/gear360_modding).
# Double-press Power: take one photo with a RAW dump (runs on the camera; bash 3.2).
# keyscan360 runs <dir>/<KEY>_<KEY>.sh on a double-press, with the name cut to 16 characters, so the Power key
# (code 73, "G360POWER") gives G360POWE_G360POW.sh. (Menu was tried first: its presses also cycle the camera mode.)
# keyscan360 waits for this script to finish, so the work runs in the background and the script returns at once.
# The servers now start from mod.sh at boot; the old ISO-100 settings are in camera_settings_iso100.sh.
#
# Steps: refuse unless the camera is in Photo mode (in Video mode the shutter would start a recording), turn the
# raw dump on, make sure rawwatch.sh is running (it moves the dump next to its JPEG as 360_NNNN.raw), press the
# shutter and wait for the JPEG. LED 5 blinks while busy. Log: /tmp/menuraw.log
# RAW off: `st cap seq dump off ssif` must NOT be used (it stores 0xFFFFFFEF into the post-processing dump flag and
# every later photo is green until a reboot). The flag is the A7 word at 0x8196a1c8 (setter FUN_805715f8 in the
# A7 image is a plain store); `st writel 0x8196a1c8 0` clears it cleanly (tested 2026-10-11). It's only written if
# it reads exactly 0x10 (ssif dump only). If the web UI's RAW switch had the dump on (/tmp/rawdump_on), it's left on.

export PATH="/usr/share/scripts:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
LOG=/tmp/menuraw.log
LOCK=/tmp/menuraw.lock
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

shoot() {
    # mkdir is atomic: a second double-press while a shot is running is ignored. A lock older than 120 s is
    # stale (a shot takes at most ~65 s) and is taken over.
    if ! mkdir "$LOCK" 2>/dev/null; then
        age=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || date +%s) ))
        if [ "$age" -lt 120 ]; then
            log "busy, ignored"
            return
        fi
        log "stale lock (${age}s old), taking it over"
        touch "$LOCK"
    fi
    mode=$(prefman get 0 0x00004445 b | grep -o "0x..")
    if [ "$mode" != "0x01" ]; then
        log "not in Photo mode (mode code '$mode'), no shot"
        st led 5 on; sleep 2; st led 5 off
        rmdir "$LOCK"
        return
    fi
    st led 5 blink
    keep_on=""
    [ -f /tmp/rawdump_on ] && keep_on=1   # the web UI's RAW switch is on: leave the dump on afterwards
    st cap seq dump on ssif >> "$LOG" 2>&1
    /sdcard/mods/rawwatch.sh </dev/null >/dev/null 2>&1 &
    sleep 1
    before=$(ls -t /sdcard/DCIM/*/*.JPG 2>/dev/null | head -1)
    log "shutter (newest JPEG before: ${before:-none})"
    st key click s2 >> "$LOG" 2>&1
    after=""
    for i in $(seq 1 60); do
        sleep 1
        newest=$(ls -t /sdcard/DCIM/*/*.JPG 2>/dev/null | head -1)
        if [ -n "$newest" ] && [ "$newest" != "$before" ]; then after="$newest"; break; fi
    done
    if [ -n "$after" ]; then log "saved $after after ${i}s"; else log "no new JPEG after 60 s"; fi
    if [ -n "$keep_on" ]; then
        log "web UI RAW switch is on, leaving the dump on"
    elif st readl 0x8196a1c8 | grep -q "h:00000010,"; then
        st writel 0x8196a1c8 0 >> "$LOG" 2>&1
        log "raw dump off (flag cleared)"
    else
        log "dump flag isn't 0x10 ($(st readl 0x8196a1c8)), not touching it"
    fi
    st led 5 off
    rmdir "$LOCK"   # explicit: bash 3.2 doesn't run an EXIT trap set inside a backgrounded function
}

shoot </dev/null >/dev/null 2>&1 &
exit 0
