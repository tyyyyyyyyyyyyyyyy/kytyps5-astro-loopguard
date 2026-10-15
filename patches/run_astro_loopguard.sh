#!/bin/bash
# Jalankan ASTRO's PLAYROOM dengan loop guard (RDNA1) - resep yang TERBUKTI masuk game.
# KYTY_LOOP_GUARD_LIMIT: batas iterasi per loop guest (0=off, default build=1000000;
# 50000 dipakai di run yang berhasil masuk game).
cd /mnt/share/tyo/run || exit 1
export DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority XDG_RUNTIME_DIR=/run/user/1000 SDL_VIDEODRIVER=x11
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json
export RADV_DEBUG=hang                 # wajib: dump saat hang
export KYTY_LOOP_GUARD_LIMIT="${KYTY_LOOP_GUARD_LIMIT:-50000}"
LOG="${1:-/mnt/share/tyo/astro_loopguard.log}"
exec /mnt/share/tyo/patches/kyty_emulator_loopguard_works_2026-10-15 \
  --game /mnt/ulfa/astrobot/PPSA01325 --screen-width 1280 --screen-height 720 \
  --shader-validation true --graphics-debug-dump true \
  --printf-direction File --printf-output-file /dev/null \
  > "$LOG" 2>&1
