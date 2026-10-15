#!/bin/bash
# Demo "GPU 99%": clpeak (bakar compute OpenCL) + vkmark desktop (Vulkan) + MangoHud.
# Durasi ~70 detik. Screenshot dari luar: import -window root /tmp/shot.png
T=/mnt/share/tyo/vkmark_tools
export DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority
export LD_LIBRARY_PATH=$T/usr/lib/x86_64-linux-gnu LD_PRELOAD=$T/redir.so
export MANGOHUD=1 MANGOHUD_CONFIG="fps,gpu_stats,gpu_temp,cpu_stats,position=top-right,font_size=20"
timeout 90 $T/usr/bin/clpeak > /tmp/clpeak.log 2>&1 &
P=$!
cd $T
timeout 80 $T/usr/bin/vkmark --winsys-dir $T/usr/lib/x86_64-linux-gnu/vkmark --winsys xcb -b desktop:duration=70 > /tmp/vkmark_burn.log 2>&1
wait $P 2>/dev/null
echo "Selesai. clpeak: /tmp/clpeak.log | vkmark: /tmp/vkmark_burn.log"
