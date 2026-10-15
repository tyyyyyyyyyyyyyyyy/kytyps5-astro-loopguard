#!/bin/bash
export DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority
XID=$(xdotool search --class kyty_emulator_loopguard 2>/dev/null | tail -1)
[ -z "$XID" ] && exit 1
xdotool windowactivate --sync $XID 2>/dev/null
for i in $(seq 1 48); do
  xdotool key --clearmodifiers j 2>/dev/null
  sleep 15
done
