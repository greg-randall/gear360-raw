#!/bin/bash
# Recover the Gear 360 remotely after a capture hang ("Capturing" forever): clean Linux reboot through the web CGI,
# then rejoin the camera's hotspot from Windows and wait until the web server answers again (~50 s in practice).
# Needs Windows Location services + "Let desktop apps access your location" for netsh (see docs/safety.md).
# Usage: tools/camrecover.sh "<Wi-Fi profile name>"
#   the camera's hotspot, e.g. "Gear 360(1A2B)"; list them with `netsh wlan show profiles`
CAM=http://192.168.43.1:8888/cgi-bin/run
if [ -z "$1" ]; then
    echo "usage: $0 \"<Wi-Fi profile name of the camera's hotspot>\"" >&2
    exit 1
fi
PROFILE="$1"

wait5() { timeout 5 tail -f /dev/null; }     # 5 s pause without `sleep` (blocked in some shells here)
uptime_cam() { curl -s -G --max-time 4 "$CAM" --data-urlencode "cmd=cat /proc/uptime" 2>/dev/null | grep -a -o -E "^[0-9.]+" | head -1; }
log() { echo "$(date +%T) camrecover: $*" >&2; }

before=$(uptime_cam)
if [ -z "$before" ]; then
    log "camera not reachable before reboot; trying to reconnect Wi-Fi first"
else
    log "uptime before: ${before}s; sending reboot"
    curl -s -G --max-time 20 "$CAM" \
        --data-urlencode "cmd=setsid sh -c 'sleep 3; sync; systemctl reboot' >/dev/null 2>&1 < /dev/null & echo scheduled" \
        | grep -a -q scheduled || { log "reboot request failed"; exit 1; }
    t0=$(date +%s)
    for i in $(seq 1 6); do wait5; [ -z "$(uptime_cam)" ] && { log "down after $(( $(date +%s) - t0 ))s"; break; }; done
    for i in 1 2 3 4 5; do wait5; done          # hotspot needs ~30 s to come back
fi
t0=$(date +%s)
for i in $(seq 1 12); do
    u=$(uptime_cam)
    if [ -n "$u" ]; then
        log "camera back (uptime ${u}s) after $(( $(date +%s) - t0 ))s of reconnecting"
        echo "$u"
        exit 0
    fi
    r=$(powershell.exe -NoProfile -Command "netsh wlan connect name=\"$PROFILE\"" 2>&1 | tr -d '\r' | head -1)
    log "connect: $r"
    wait5; wait5
done
log "camera did not come back within ~2 min"
exit 1
