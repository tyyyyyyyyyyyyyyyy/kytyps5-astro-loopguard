#!/bin/bash
LOG=/mnt/share/tyo/lg_mon3.log
: > $LOG
prev_frame=-1; stall=0; missing=0
for i in $(seq 1 900); do
  W=$(DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority xwininfo -root -tree 2>/dev/null | grep -m1 -oE "frame: [0-9]+, fps: [0-9]+")
  F=$(echo "$W" | grep -oE "frame: [0-9]+" | grep -oE "[0-9]+")
  FPS=$(echo "$W" | grep -oE "fps: [0-9]+" | grep -oE "[0-9]+")
  GPU=$(cat /sys/class/drm/card*/device/gpu_busy_percent 2>/dev/null | head -1)
  PID=$(pgrep -f "kyty_emulator_loopguard --game" | head -1)
  if [ -z "$PID" ]; then
     missing=$((missing+1))
     if [ $missing -ge 3 ]; then echo "$(date +%H:%M:%S) i=$i PROCESS-DOWN (3x missing)" >> $LOG; break; fi
     sleep 4; continue
  fi
  missing=0
  CPU=$(ps -p $PID -o %cpu= | tr -d ' ')
  echo "$(date +%H:%M:%S) i=$i frame=${F:-?} fps=${FPS:-?} gpu=${GPU:-?} cpu=$CPU pid=$PID" >> $LOG
  if [ "$F" = "$prev_frame" ]; then
     stall=$((stall+1))
     if [ $stall -eq 3 ]; then
        { echo "--- STALL at i=$i (frame frozen) ---";
          ps -L -p $PID -o tid,stat,pcpu,wchan:44,comm | head -28;
          echo "--- per-task wchan ---";
          for t in /proc/$PID/task/*; do echo -n "tid $(basename $t): "; cat $t/wchan 2>/dev/null; echo; done;
          echo "--- end stall dump ---"; } >> $LOG 2>&1
        stall=0
     fi
  else
     stall=0
  fi
  prev_frame=$F
  sleep 4
done
