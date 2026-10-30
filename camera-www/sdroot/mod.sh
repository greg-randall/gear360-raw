#sleep 30
#/mnt/mmc/mods/telnetd &
/sdcard/mods/keyscan360 /dev/event0 /dev/event1 /sdcard/mods/ &
/sdcard/mods/rawwatch.sh </dev/null >/dev/null 2>&1 &
# Start telnet, FTP and the web UI at boot (no Power double-press needed). Camera settings (ISO 100 etc.) stay on
# the double-press. The delay lets the camera app and hotspot come up first; double-press Power restarts them.
(sleep 15
 /mnt/mmc/mods/tcpsvd -vE 0.0.0.0 21 ftpd -w / &
 /mnt/mmc/mods/telnetd &
 /mnt/mmc/mods/httpd -p 8888 -f -h /sdcard/mods/www/ &
) </dev/null >/dev/null 2>&1 &
st led 2 on; st led 2 off
