# ASTRO BOT — Loop Guard RDNA1: Temuan & Status (15 Okt 2026)

Dokumen ini merangkum analisis + patch "loop guard" di SPIR-V emitter Kyty untuk
mengatasi GPU hang pada **ASTRO's PLAYROOM** di **Radeon RX 5700 (RDNA1/Navi10)**,
box `192.168.18.225` (user `tyo`).

---

## 0. ⭐ BUILD YANG BISA MASUK GAME — DISIMPAN (15 Okt 17:24)

> **Run 17:18 dengan `KYTY_LOOP_GUARD_LIMIT=50000` berhasil melewati titik hang
> dan masuk layar loading level** (gambar Astro + controller), tanpa GPU hang
> (frame terus naik 4397 → 5200+; run sebelumnya hang di ~4397).

> **Update 17:28 ✓ MASUK GAMEPLAY**: run yang sama lanjut masuk **gameplay** —
> Astro Bot berjalan di level (bukan hanya menu/loading), frame ~6.000,
> fps 2-4 (kompilasi shader masih berjalan, CPU ~165%), **tanpa GPU hang**.
> Bukti screenshot: `screenshots/astro-gameplay.png` di repo GitHub (§8).

Artefak yang disimpan:

| Artefak | Lokasi |
|---|---|
| **Binary** (yang masuk game) | `/mnt/share/tyo/patches/kyty_emulator_loopguard_works_2026-10-15` |
| SHA-256 binary | `2e7a4d4ae55a5a4ae0a78d21933192a78e5e3dd47696c327bdb685ec5e3aac6a` |
| Sumber yang dipatch (3 file) | `/mnt/share/tyo/patches/2026-10-15_loopguard/` |
| Diff loop guard | `.../loopguard_internal.diff`, `.../loopguard_program.diff` |
| Script patch + analyzer + monitor | `.../loopguard_v2.py`, `.../analyze_guard.py`, `.../lg_mon3.sh` |
| **Launcher siap pakai** | `/mnt/share/tyo/run_astro_loopguard.sh` |

**Cara pakai ulang (penting!):**

```bash
/mnt/share/tyo/run_astro_loopguard.sh            # sudah set env + args yang benar
# atau manual:
KYTY_LOOP_GUARD_LIMIT=50000 /mnt/share/tyo/patches/kyty_emulator_loopguard_works_2026-10-15 ...
```

> ⚠️ Binary ini **wajib** dijalankan dengan `KYTY_LOOP_GUARD_LIMIT=50000`
> (atau nilai kecil lain). Tanpa env tsb, default build = **1.000.000** dan
> pada run 17:14 limit 1jt **masih hang** (total iterasi × ribuan wave melewati
> timeout hang RADV ~10 s). Lihat §6.

---

## 1. Ringkasan (TL;DR)

- **Akar masalah**: shader compute guest (BVH traversal) memiliki loop yang **tidak
  pernah selesai** di RX 5700 — wave berputar terus. Kyty **tidak punya** mekanisme
  fault-retry/redispatch, jadi dispatch yang nyangkut tidak pernah bisa "di-unstick"
  → ring gfx timeout → `vkQueueSubmit failed: ErrorDeviceLost (-4)`.
- **Perbaikan**: *loop guard* di SPIR-V emitter — setiap loop header guest diberi
  counter iterasi; bila melewati batas (`KYTY_LOOP_GUARD_LIMIT`, default 1.000.000;
  `0` = mati), **semua cabang keluar loop yang sudah ada (menuju blok merge)
  "diracuni"** agar selalu keluar.
- **Bukti guard bekerja**: pada dump hang RADV sebelum patch, `GRBM_STATUS=0xa0407028`
  (`TA_BUSY=1, SPI_BUSY=1, CP_BUSY=1`) = wave berputar. Setelah patch:
  `GRBM_STATUS=0x3028` (**semua idle**) = tidak ada wave yang spin lagi.
- **Belum selesai**: masih ada hang lanjutan (lihat §6). Hipotesis utama: batas
  1.000.000 iterasi terlalu besar sehingga *total* waktu GPU (ribuan wave × 1 juta
  iterasi) melewati timeout hang RADV (~10 s). Sedang diuji dengan
  `KYTY_LOOP_GUARD_LIMIT=50000`.

---

## 2. Rantai akar masalah

1. Game mengirim dispatch BVH: `groups=1x2048x1, local=128x1x1`, shader
   `hash=0x7d6ab87e6c984bb7`, 5 buffer + 1 storage (BDA).
2. Shader traversal memiliki 10 loop; keluar dari loop bergantung pada tes
   ballot wave-wide (mis. `OpAll(OpGroupNonUniformBallot(...))`) dan sentinel node
   `0xffffffff`. Kondisi ini bisa **tidak pernah** terpenuhi (data/stack tidak
   konsisten pada RDNA1) → loop tak berujung.
3. Wave berputar selamanya → command processor tidak pernah "retire" → RADV/kernel
   mendeteksi hang (~10 s) → dengan `RADV_DEBUG=hang` proses di-abort setelah dump.
4. Di Kyty **tidak ada** jalur retry/redispatch untuk recovery — satu-satunya cara
   adalah membatasi loop di level emitter.

---

## 3. Desain loop guard (final)

### 3.1 Cara kerja

- Untuk **setiap loop header** guest (`term.loop_header`, merge & continue != null):
  - Alokasi 1 variabel `Function` storage `uint` (per invokasi/lane) — initializer 0.
  - **Increment** di loop header setiap iterasi: `OpLoad/OpIAdd/OpStore` (3 instruksi).
  - Pre-scan `CollectLoopGuardSites()`:
    - Hitung blok "di dalam loop" = reachable dari header tanpa melewati merge (BFS).
    - Cari semua blok di dalam loop yang terminatornya `OpBranchConditional` dengan
      **salah satu target = blok merge** (titik keluar loop).
    - Simpan daftar (site, merge, index counter). Loop tanpa titik keluar berkondisi
      → **di-skip** (tidak bisa dijaga dengan aman).
  - Saat emit terminasi titik keluar: kondisi diracuni:
    - `OpBranchConditional %cond %body %merge` → `%cond' = %cond || %over`
    - `OpBranchConditional %cond %merge %body` → `%cond' = %cond && !%over`
    - `%over = OpUGreaterThan (OpLoad counter), 1000000`
- Efek: begitu counter > limit, semua jalur keluar loop langsung diambil → keluar
  secara graceful (nilai loop terakhir, data mungkin sampah, tapi **tidak hang**).
- Env `KYTY_LOOP_GUARD_LIMIT`: `0` = guard dimatikan; default 1.000.000.

### 3.2 Pelajaran penting: aturan validator SPIR-V (jangan diulang!)

Versi pertama guard (v1) menambahkan blok `OpReturn` baru **di dalam** loop lalu
mengubah `OpBranch` header menjadi `OpBranchConditional %over %exit %target`.
Ini **INVALID** menurut `ValidateStructuredSelections` (SPIRV-Tools):

> Di blok yang punya `OpLoopMerge` (atau tanpa merge instruction), `OpBranchConditional`
> **harus** memiliki minimal satu target yang sudah "seen" oleh reverse-postorder walk
> — praktis hanya **merge/continue loop itu sendiri** (atau merge/continue enclosing
> construct yang sudah dilewati). Dua target baru → error *"Selection must be
> structured"*.

Gejala: `spirv-val`: `error: line 2400: Selection must be structured —
OpBranchConditional %1131 %1133 %39`, dan Kyty fatal di
`pipelineCache.cpp:344` (`--shader-validation true`).

**Konsekuensi desain**: jangan menambah cabang/blok baru untuk keluar loop —
**racuni cabang keluar yang sudah ada**. Ini otomatis menghindari masalah
predecessor `OpPhi` pada blok merge (tidak ada edge baru).

---

## 4. Bukti empiris

### 4.1 Dump RADV sebelum patch (klakson spin) — `radv_dumps_244955_2026.10.15_12.59.25`

- `registers.log`: `GRBM_STATUS <- 0xa0407028` → `TA_BUSY=1, SPI_BUSY=1, CP_BUSY=1,
  TCP_BUSY=1, GL1CC_BUSY=1` = **wave berputar**.
- `pipeline.log`: pipeline hash `7e945238b73afba0`, **190× `@ballot`** = shader BVH
  (jalur traversal dengan ballot) sedang dieksekusi → hung.
- `vm_fault.log` 0 byte, `dmesg.log` kosong = **tidak ada page fault** (bukan masalah
  alamat).

### 4.2 Dump RADV setelah patch — `radv_dumps_562602_2026.10.15_17.04.59`

- Shader yang di-dump = **BVH dengan guard**: 10 loop, 16× konstanta `1000000`,
  `LocalSize 128 1 1`, `spirv-val` → **VALID**.
- `registers.log`: `GRBM_STATUS <- 0x3028` → **semua idle**
  (`TA_BUSY=0, SPI_BUSY=0, CP_BUSY=0`), `CP_CPC_STATUS=0` = **tidak ada wave spin**.
- Extract dari `_Shaders/0139_new_shader_cs_7d6ab87e6c984bb7.spv` (run 17:56):
  ```
  file: /tmp/bvh_new.spvasm
  loops found: 10
  loop hdr=%66  merge=%209 ... inc=True exits=1 poisoned=1 unpoisoned=0 -> OK
  loop hdr=%68  merge=%207 ... inc=True exits=2 poisoned=2 unpoisoned=0 -> OK
  ... (semua 10 loop: OK, 0 exit tak-ter-poison)
  ```
  (baseline tanpa guard: `inc=False ... unpoisoned=1` untuk semua loop)

### 4.3 Scan semua dump shader run 17:04

- 112 shader divalidasi `spirv-val --target-env vulkan1.2`: hanya 4 **invalid**, dan
  semuanya **mesh shader** (`ms_`) dengan VUID `CullPrimitiveEXT` — masalah emulasi
  mesh **pre-existing**, bukan dari loop guard.
- Semua shader ber-loop: **increment ada + semua cabang keluar ter-poison**.

### 4.4 Temuan sampingan: printf "firehose" 14 GB (!)

`--printf-direction File` mengaktifkan log `LOGF` per CP-packet + per dispatch
(`CP packet: ...` di `graphicsRun.cpp:703`, `GraphicsRenderDispatchDirect: ...`).
Satu run ~8 menit menghasilkan **14 GB** file:

```
-rw-rw-r-- 1 tyo tyo 14911137511 Oct 15 17:04 /mnt/share/tyo/astro_lg2_printf.txt
/dev/sdb2 147G 130G 9.5G 94% /mnt/share   (disk hampir penuh!)
```

Gejala menyesatkan: frame freeze + GPU idle + thread `D` state di
`folio_wait_bit_common` (nunggu IO disk) → seolah "hang GPU" padahal proses
kehabisan bandwidth disk. **Selalu pakai `--printf-output-file /dev/null`** kalau
tidak sedang butuh log dispatch.

---

## 5. Perubahan kode (uncommitted, minimal & reversible)

Semua di `kyty_latest` (HEAD `99358054`), backup `*.loopguard.bak` di sebelah file:

| File | Perubahan |
|---|---|
| `src/graphics/shader/recompiler/backend/spirv/spirvEmitterInternal.h` | struct `LoopGuardHeader`/`LoopGuardExit` + field `loop_guard_headers`, `loop_guard_exits` di `EmitterState` |
| `src/graphics/shader/recompiler/backend/spirv/spirvEmitterProgram.cpp` | `#include <cstdlib>`; helper `LoopGuardLimit()`, `EmitLoopGuardIncrement()`, `EmitLoopGuardOver()`, `CollectLoopGuardSites()`; increment di `EmitStructuredTerminator`; poisoning di kasus `ConditionalBranch`; pre-scan + deklarasi `OpVariable` di `EmitProgram` |
| `src/graphics/presentation/window/vulkanWindow.cpp:275` | `check_feature(fragment_barycentric)` fatal → warning (*regression* di `kyty_latest`; tree `kyty_build` tidak punya baris ini) |

- Script patch (idempotec, restore dari `.bak` lalu apply): `/tmp/loopguard_v2.py`
  (salinan lokal: `.../opencode/loopguard_v2.py`).
- Script analisis guard per-loop: `/tmp/analyze_guard.py`
  (lokal: `.../opencode/analyze_guard.py`).

Rebuild: `ninja -C /mnt/share/tyo/kyty_latest/build kyty_emulator -j$(nproc)` →
binary `build/kyty_emulator` (+ salinan `build/kyty_emulator_loopguard`).

---

## 6. Status terkini & langkah berikut

### Status

| Waktu | Konfigurasi | Hasil |
|---|---|---|
| 12:59 | tanpa guard (`kyty_build`) | hang GPU **busy** (`0xa0407028`), wave spin BVH |
| 17:04 | guard, limit 1jt, printf **FILE (14 GB!)** | guard lolos (`GRBM 0x3028` idle), tapi proses stall karena **IO disk** |
| 17:14 | guard, limit 1jt, printf /dev/null | hang GPU **busy** lagi; tapi shader BVH **belum dikompilasi** saat itu (dump terakhir 0135) → spin di shader CS lain / limit 1jt terlalu lama |
| **17:18** | **guard, limit 50.000**, printf /dev/null | ✅ **LEWAT titik hang & masuk layar loading level** (frame 4397 → 5200+, tanpa GPU hang; fps 2-5 saat kompilasi shader, CPU ~150%) — *build ini disimpan* |
| **17:28** | run 17:18 lanjut (akhirnya selesai loading) | ✅ **MASUK GAMEPLAY** — Astro Bot berjalan di level (frame ~6.000; fps 2-4; CPU ~165%; 0 GPU hang) — bukti: `screenshots/astro-gameplay.png` |

### Hipotesis utama kenapa masih hang (run 17:14) — ✅ TERKONFIRMASI

1. **Limit 1.000.000 terlalu besar** (TERBUKTI: dengan `KYTY_LOOP_GUARD_LIMIT=50000`
   run 17:18 lolos ke loading level): total kerja GPU = jumlah wave × iterasi.
   BVH = 2048 workgroup × 4 wave = 8192 wave; bila occupancy rendah, ratusan wave
   bergiliran × 1jt iterasi ≈ puluhan detik > timeout hang RADV (~10 s) → tetap
   dianggap hang walau secara logika berhenti.
   → **Solusi terpakai**: limit 50.000 ✓ (build tersimpan + launcher sudah set env).
2. Loop tanpa cabang keluar (`NO-EXIT-BRANCH`) di-skip guard — scan semua dump
   **tidak menemukan** kasus ini untuk shader yang sudah dikompilasi, jadi bukan ini.
3. Spin di shader lain yang belum teridentifikasi — tidak terbukti setelah limit
   diturunkan ✓.

### Cara menguji ulang (resep run)

```bash
cd /mnt/share/tyo/run
export DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority XDG_RUNTIME_DIR=/run/user/1000 SDL_VIDEODRIVER=x11
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json
export RADV_DEBUG=hang                 # wajib: dump hang
export KYTY_LOOP_GUARD_LIMIT=50000     # 0 = guard off; default 1000000
/mnt/share/tyo/kyty_latest/build/kyty_emulator_loopguard \
  --game /mnt/ulfa/astrobot/PPSA01325 --screen-width 1280 --screen-height 720 \
  --shader-validation true --graphics-debug-dump true \
  --printf-direction File --printf-output-file /dev/null \
  > /mnt/share/tyo/astro_lgX.log 2>&1
```

- Tekan `j` (= tombol X) di "PRESS ANY BUTTON" lalu di menu "CONTINUE".
- Monitor: `/mnt/share/tyo/lg_mon3.sh` (frame/fps/gpu/cpu + dump thread state saat
  frame freeze).
- Analisa dump hang RADV:
  ```bash
  sed 's/\x1b\[[0-9;]*m//g' radv_dumps_*/registers.log | grep -E "GRBM_STATUS|BUSY"
  # TA/SPI/CP_BUSY=1 → wave spin; semua 0 → tidak ada wave (stall host/IO)
  ```
- Validasi shader yang di-dump:
  ```bash
  for f in _Shaders/*.spv; do spirv-val --target-env vulkan1.2 "$f" || echo "FAIL $f"; done
  python3 /tmp/analyze_guard.py <(spirv-dis "$f" -o -)   # ringkasan guard per loop
  ```

### Sisa pekerjaan

- [x] ~~Konfirmasi run limit 50k~~ → ✅ **TERKONFIRMASI 17:28: masuk gameplay, tanpa hang.**
- [ ] Bila ya: tuning limit final (default tetap 1jt untuk build "aman", tapi
      dokumentasikan bahwa di RDNA1 perlu limit kecil / timeout lebih besar).
- [ ] Bila tidak: identifikasi shader/pipeline yang spin dari `pipeline.log`
      (`0xf4240`, `@ballot`) dan cek apakah ada loop yang tidak terjaga.
- [ ] Opsional: tambah opsi CLI/env untuk limit + log jumlah loop yang di-guard
      (saat ini guard hanya bisa diaktifkan via env `KYTY_LOOP_GUARD_LIMIT`).
- [ ] Opsional: naikkan toleransi hang RADV (drag `RADV_DEBUG=hang` timeout) atau
      kurangi beban: limit kecil terbukti lebih aman.

---

## 7. Catatan penting lain

- **Jangan sentuh** `/mnt/share/tyo/kyty_build` (tree `spike/mesh-compute` dengan
  stash) — binary known-good `kyty_emulator_astro_3560` ada di
  `kyty_build/build/`.
- `kyty_latest` **butuh** patch barycentric (§5) — tanpa itu error
  `Could not find suitable device: fragmentShaderBarycentric is not supported`
  (fatal di `vulkanWindow.cpp:1001`).
- Pipeline cache Kyty **disabled** untuk dirty build → tiap run mengompilasi ulang
  semua shader (~8 menit untuk ~160 shader). Jangan aktifkan paksa: cache dari
  emitter lama akan **tanpa guard**.
- RADV dump + abort: dengan `RADV_DEBUG=hang`, proses di-abort ~4 s setelah dump →
  monitor akan melihat `PROCESS-DOWN`.
- File besar di `/mnt/share/tyo` (printf run lama) sudah dibersihkan
  (`astro_lg2_printf.txt` 14 GB dihapus).

---

## 8. Publikasi: repo GitHub

- Repo: **https://github.com/tyyyyyyyyyyyyyyyy/kyty-astro-loopguard**
- Isi: README (ringkasan + quickstart), `docs/FINDINGS.md` (dokumen ini),
  `patches/` (diff + script patch + sumber 3 file yang diubah),
  `screenshots/` (bukti masuk gameplay), release **v1.0**
  (`https://github.com/tyyyyyyyyyyyyyyyy/kyty-astro-loopguard/releases/tag/v1.0`)
  = binary siap pakai + SHA-256.
- 🤖 **Semua edit (loop guard, launcher, dokumen) dilakukan oleh AI —
  DeepSeek V4.1 Flash** (model `deepseek-v4.1-flash-free`, via OpenCode).

---

## 9. Analisis FPS & tuning (15 Okt 17:30–17:45)

### 9.1 Fakta pengukuran (run gameplay, 1280×720, limit 50k)

| Metrik | Nilai | Arti |
|---|---|---|
| fps gameplay (stabil) | **~2.5 fps** | batas nyata di box ini |
| GPU `gpu_busy_percent` | avg **22%**, max 84% | **GPU bukan bottleneck** (menganggur) |
| CPU proses | 169–177% (dari 800%) | beban di CPU |
| Thread terpanas (sample 3 dtk) | main `kyty_emulator_l` **65%**, `SceSndzAudioOut` **39%**, ~11× `tbb_thead` @5% (~50%) | audio (SDL3) + job-system guest + main thread |
| RAM | 8.9 GiB RSS, swap 5 MiB | tidak ada thrash |
| CPU freq / suhu | 3.4–3.6 GHz / **51 °C** | bukan thermal throttle |

**Uji renice** (thread audio/TBB/DrawThread → nice 15, live di PID berjalan):
fps **tidak berubah** (2.50) → bukan masalah rebutan CPU; rantai utama (main
thread + sinkronisasi) memang yang menentukan waktu per frame.

### 9.2 Kesimpulan

- **2–3 fps itu batas CPU** (Xeon E3-1230v3, 4c/8t 2013) untuk judul PS5 60 fps +
  overhead HLE Kyty. GPU menganggur → **turunkan resolusi/matikan efek tidak
  menaikkan fps**. Naik signifikan = CPU lebih cepat (Zen3+) atau optimisasi Kyty.
- Yang **bisa** dihemat: kompilasi shader (warmup ~8–10 menit tiap run + hitch
  saat shader baru muncul) → **pipeline cache**.

### 9.3 Pipeline cache ON (patch `KYTY_FORCE_PIPELINE_CACHE`)

- Kyty mematikan pipeline cache untuk build non-Release ATAU build "dirty";
  log run 17:18: `Vulkan pipeline cache: disabled (dirty build)`.
- Patch (`pipelineCache.cacheforce.diff`, backup `.cacheforce.bak`): gate tsb
  **dilewati bila env `KYTY_FORCE_PIPELINE_CACHE=1`** (tanpa env, perilaku default).
- Binary baru: `/mnt/share/tyo/patches/kyty_emulator_loopguard_cacheforce_2026-10-15`
  (sha256 `370393ad0c21cc74b681f92b984401729417203aae16234c3cec45557d857c55`),
  juga di `kyty_latest/build/kyty_emulator_loopguard`.
- **Cara pakai**: `run_astro_fast.sh` (cache ON, tanpa `--graphics-debug-dump`).
  Run pertama tetap kompilasi penuh, lalu **exit bersih** (tutup jendela game —
  jangan `kill -9`) agar `_PipelineCache/PPSA01325.bin` disimpan; run berikutnya
  memuat cache → mulai cepat, tanpa hitch.
- `_PipelineCache/PPSA01325.bin` lama (10:59, pra-guard) sudah dipindah ke
  `.pre-guard.bak` supaya tidak termuat. Signature cache memuat git revision +
  GPU + driver (auto-invalid kalau berubah); jika mengganti emitter/guard limit,
  hapus `_PipelineCache/PPSA01325.bin` untuk bersih-bersih.
- ⚠️ Cache hanya valid untuk kombinasi `KYTY_LOOP_GUARD_LIMIT` yang sama (konstanta
  guard ikut ke SPIR-V); ganti limit = kompilasi ulang shader terdampak.

### 9.4 Verifikasi cache (17:47) ✅

Run pertama dengan `run_astro_fast.sh` menulis di `/mnt/share/tyo/astro_fast1.log`:

```
Vulkan pipeline cache: initializing _PipelineCache/PPSA01325.bin
Vulkan pipeline cache: initialized empty
```

(bukan lagi `disabled (dirty build)` → patch force bekerja). Run ini sedang
mengisi cache; **tutup jendela game dengan cara normal** saat selesai supaya
`_PipelineCache/PPSA01325.bin` tersimpan untuk run-run berikutnya.
