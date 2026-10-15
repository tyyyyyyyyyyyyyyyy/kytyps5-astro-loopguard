#!/bin/bash
# Launcher "FAST" - recipe harian yang lebih cepat.
# Perbedaan vs run_astro_loopguard.sh:
#   - KYTY_FORCE_PIPELINE_CACHE=1  : pipeline cache Kyty ON (build non-Release pun jalan).
#       Run pertama tetap kompilasi penuh (~8-10 menit) lalu cache DISIMPAN saat exit bersih
#       (tutup jendela game / keluar normal - JANGAN kill -9).
#       Run berikutnya memuat cache -> tanpa warmup 8 menit & tanpa hitch kompilasi.
#   - --graphics-debug-dump dihapus (hemat I/O & CPU saat kompilasi; dump tidak diperlukan harian).
#   - --shader-validation tetap ON (murah, cuma saat kompilasi).
cd /mnt/share/tyo/run || exit 1
export DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority XDG_RUNTIME_DIR=/run/user/1000 SDL_VIDEODRIVER=x11
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json
export RADV_DEBUG=hang                 # dump jika hang
export KYTY_LOOP_GUARD_LIMIT="${KYTY_LOOP_GUARD_LIMIT:-50000}"
export KYTY_FORCE_PIPELINE_CACHE=1     # <- baru: aktifkan pipeline cache
LOG="${1:-/mnt/share/tyo/astro_fast.log}"
exec /mnt/share/tyo/kyty_latest/build/kyty_emulator_loopguard \
  --game /mnt/ulfa/astrobot/PPSA01325 --screen-width 1280 --screen-height 720 \
  --shader-validation true \
  --printf-direction File --printf-output-file /dev/null \
  > "$LOG" 2>&1
