# Ringkasan Bukti — Loop Guard RDNA1 (15 Okt 2026)

Semua angka diambil dari dump `RADV_DEBUG=hang` di box asli
(Xeon E3-1230 v3 + Radeon RX 5700, Xubuntu). Detail penuh: `FINDINGS.md`.

## 1. Register GPU: sebelum vs sesudah patch

| Dump | Shader yang di-dump | `GRBM_STATUS` | Interpretasi |
|---|---|---|---|
| `radv_dumps_244955_2026.10.15_12.59.25` (sebelum patch) | BVH, `pipeline.log` hash `7e945238b73afba0`, 190× `@ballot` | `0xa0407028` | `TA/SPI/CP/TCP/GL1CC_BUSY=1` → **wave spin** (hang nyata) |
| `radv_dumps_562602_2026.10.15_17.04.59` (sesudah patch) | BVH **dengan guard** (10 loop, `spirv-val` VALID) | `0x00003028` | **semua idle** → guard menghentikan spin |

`vm_fault.log` 0 byte & `dmesg.log` kosong di dump pra-patch → **bukan page fault**.

## 2. Shader yang pernah spin

- Dispatch: `groups=1x2048x1`, `local=128x1x1`, hash **`0x7d6ab87e6c984bb7`**
  (BVH traversal, 5 buffer + 1 storage BDA).
- 10 loop; keluar loop tergantung sentinel node `0xffffffff` + ballot wave-wide.

## 3. Verifikasi guard per-loop (`analyze_guard.py`)

Sesudah patch, semua shader ber-loop di dump: `inc=True`, `unpoisoned=0`
(semua cabang keluar ter-poison), contoh:

```
loop hdr=%66  merge=%209 ... inc=True exits=1 poisoned=1 unpoisoned=0 -> OK
loop hdr=%68  merge=%207 ... inc=True exits=2 poisoned=2 unpoisoned=0 -> OK
... (10/10 loop OK)
```

`spirv-val --target-env vulkan1.2` pada 112 shader dump: hanya 4 invalid, semuanya
mesh shader (`ms_`) dengan VUID `CullPrimitiveEXT` — masalah pre-existing emulasi
mesh, **bukan** dari loop guard.

## 4. Jebakan validator (kenapa desain v1 ditolak)

`ValidateStructuredSelections` (SPIRV-Tools): di blok ber-`OpLoopMerge`,
`OpBranchConditional` **harus** punya minimal satu target yang sudah "seen" oleh
reverse-postorder walk (praktis: merge/continue loop itu sendiri). Desain v1 yang
menambah blok `OpReturn` baru di dalam loop → error *"Selection must be structured"*
→ Kyty fatal di `pipelineCache.cpp:344`. Desain final (v2) **tidak menambah edge/blok**
— hanya meracuni kondisi cabang keluar yang sudah ada.

## 5. Hasil akhir

- Run `KYTY_LOOP_GUARD_LIMIT=50000`, `RADV_DEBUG=hang`, `--shader-validation true`,
  `--printf-output-file /dev/null`:
  - lewat titik hang (~frame 4.397) → loading level (~frame 5.200) →
    **gameplay (~frame 6.000+, screenshot `screenshots/astro-gameplay.png`)**;
  - **0 hit "GPU hang"** di sepanjang log.
- Limit 1.000.000 (default) **masih hang**: total wave × iterasi melewati timeout
  hang RADV (~10 s).
