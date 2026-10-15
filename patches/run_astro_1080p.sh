#!/bin/bash
# Launcher "1080p MAX GPU" - borderless fullscreen 1920x1080 + HUD MangoHud (font besar).
# Sama seperti run_astro_fast.sh, tapi resolusi naik (beban GPU ~x2.25) untuk lihat GPU maksimal.
cd /mnt/share/tyo/run || exit 1
export DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority XDG_RUNTIME_DIR=/run/user/1000 SDL_VIDEODRIVER=x11
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json
export RADV_DEBUG=hang
export KYTY_LOOP_GUARD_LIMIT="${KYTY_LOOP_GUARD_LIMIT:-50000}"
export KYTY_FORCE_PIPELINE_CACHE=1
export MANGOHUD="${MANGOHUD:-1}"
export MANGOHUD_CONFIG="${MANGOHUD_CONFIG:-fps,gpu_stats,gpu_temp,cpu_stats,cpu_temp,ram,vram,position=top-right,font_size=24}"
LOG="${1:-/mnt/share/tyo/astro_1080p.log}"
exec /mnt/share/tyo/kyty_latest/build/kyty_emulator_loopguard \
  --game /mnt/ulfa/astrobot/PPSA01325 --screen-width 1920 --screen-height 1080 --fullscreen \
  --shader-validation true \
  --printf-direction File --printf-output-file /dev/null \
  > "$LOG" 2>&1
