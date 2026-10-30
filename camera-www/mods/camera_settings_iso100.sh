#!/bin/sh
# Adapted from ottokiksmaler's gear360_modding SD mod (https://github.com/ottokiksmaler/gear360_modding).
# The old Power double-press settings (ottokiksmaler mod): ISO 100, shutter priority, NR off.
# Servers are no longer started here (mod.sh does that at boot). Run by hand or from the web UI.
st led 3 on; st led 5 blink
export DISPLAY=":0"
export HIB="a"
export HISTSIZE="1000"
export HOME="/root"
export HUSHLOGIN="FALSE"
export LD_LIBRARY_PATH=":/usr/lib:/usr/lib/driver"
export LOGNAME="root"
export OLDPWD
export PATH="/usr/share/scripts:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/usr/devel/usr/sbin:/opt/usr/devel/usr/bin:/opt/usr/devel/sbin:/opt/usr/devel/bin"
export PS1="[\\u@\\h \\W]\\\$ "
export PWD="/root"
export SHELL="/bin/sh"
export SHLVL="1"
export TERM="vt102"
export USER="root"
export XDG_CACHE_HOME="/tmp/.cache"

st led 5 off;
# SET PARAMS
# set ISO to 100
st cap capdtm setusr 5 0x050001
# set AUTO ISO MAX to 125
st cap capdtm setusr 64 0x400000
# set mode 0-movie, 1-smartauto, 2-program, 3-aperture, 4-shutter, 5-manual, 6-imode, 7-magic, 8-wifi, 9-scene, A-smartpro, B-SAS, 
st cap capdtm setusr 0 4
# set mode 0-movie, 1-smartauto, 2-program, 3-aperture, 4-shutter, 5-manual, 6-imode, 7-magic, 8-wifi, 9-scene, A-smartpro, B-SAS, 
st cap capdtm setusr 1 0x10004
# ISO NR off
st cap capdtm setusr 30 0x1e0000
# LTNR OFF
st cap capdtm setusr 31 0x1f0000

st led 3 off
