#!/bin/bash
# Gear 360 raw-dump watcher (runs on the camera; bash 3.2).
# With `st cap seq dump on ssif`, every shot (web UI or physical shutter) writes
#   /sdcard/N_N_11648_5824x2896_bayer_12-16.raw
# a few seconds BEFORE its JPEG. The N_N counter restarts at 0 after every reboot, so dumps left in the
# SD root get overwritten. This loop moves each finished dump next to its JPEG as 360_NNNN.raw
# (the first JPEG saved 0-20 s after the raw), and writes 360_NNNN_wb.txt with the live AWB gains
# (st cap iq awb wbgain) right after. Unmatched dumps are left where they are.
# Single instance (pidfile); log in /tmp/rawwatch.log. Start: /sdcard/mods/rawwatch.sh &

PIDFILE=/tmp/rawwatch.pid
LOG=/tmp/rawwatch.log
RAWSIZE=33732608   # 5824 x 2896 x 2 bytes

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "rawwatch already running (pid $(cat "$PIDFILE"))"
    exit 0
fi
echo $$ > "$PIDFILE"
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
log "started (pid $$)"
shopt -s nullglob
declare -a warned

while true; do
    now=$(date +%s)
    for raw in /sdcard/*_bayer_*.raw; do
        size=$(stat -c %s "$raw" 2>/dev/null) || continue
        rt=$(stat -c %Y "$raw" 2>/dev/null) || continue
        # still being written: wrong size or modified in the last 2 s
        if [ "$size" != "$RAWSIZE" ] || [ $((now - rt)) -lt 2 ]; then continue; fi
        best=""
        bestd=999
        for j in /sdcard/DCIM/*/*.JPG; do
            d=$(( $(stat -c %Y "$j") - rt ))
            if [ "$d" -ge 0 ] && [ "$d" -le 20 ] && [ "$d" -lt "$bestd" ]; then best="$j"; bestd=$d; fi
        done
        if [ -z "$best" ]; then
            # JPEG not saved yet: keep waiting up to 60 s, then note it once and leave the file
            if [ $((now - rt)) -gt 60 ]; then
                case " ${warned[*]} " in *" $raw "*) ;; *) log "no JPEG for $raw; leaving it"; warned+=("$raw") ;; esac
            fi
            continue
        fi
        target="${best%.*}.raw"
        if [ -e "$target" ]; then
            case " ${warned[*]} " in *" $raw "*) ;; *) log "$target exists; leaving $raw"; warned+=("$raw") ;; esac
            continue
        fi
        if mv "$raw" "$target"; then
            log "moved $raw -> $target (JPEG +${bestd}s)"
            # white balance sidecar: the live AWB gains just after the shot (same light in practice)
            wb="${best%.*}_wb.txt"
            if [ ! -e "$wb" ]; then
                st cap iq awb wbgain 2>&1 | sed 's/T2EX >> //g' | LC_ALL=C tr -cd '\11\12\40-\176' > "$wb"
                log "wrote $wb: $(head -1 "$wb")"
            fi
        else
            log "mv failed: $raw"
        fi
    done
    sleep 3
done
