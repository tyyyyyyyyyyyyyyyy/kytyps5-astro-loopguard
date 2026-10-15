#!/usr/bin/env python3
"""Analisa loop guard pada disassembly SPIR-V.

Untuk setiap OpLoopMerge: hitung blok di dalam loop (BFS dari header tanpa
melewati merge), deteksi increment counter di header, deteksi cabang keluar
(OpBranchConditional yang menuju merge) dan apakah cabang itu sudah
di-"racuni" oleh guard (kondisinya lewat OpLogicalOr/OpLogicalAnd dengan
OpUGreaterThan vs >=1000000).
"""
import re
import sys
from collections import defaultdict

path = sys.argv[1]
lines = open(path).read().splitlines()

# Parse blocks: id -> list of instruction lines; telusuri semua lini
blocks = {}
order = []
label_re = re.compile(r"^\s*%(\d+) = OpLabel")
cur = None
for ln in lines:
    s = ln.strip()
    if not s or s.startswith(';'):
        continue
    m = label_re.match(ln)
    if m:
        cur = m.group(1)
        blocks[cur] = []
        order.append(cur)
        continue
    if cur is not None:
        blocks[cur].append(s)

def term_of(bid):
    for s in reversed(blocks.get(bid, [])):
        if s.startswith('OpBranchConditional') or s.startswith('OpBranch ') or \
           s.startswith('OpReturn') or s.startswith('OpSwitch') or s.startswith('OpKill'):
            return s
    return None

def targets(bid):
    t = term_of(bid)
    if not t:
        return []
    if t.startswith('OpBranch '):
        return [t.split()[1].lstrip('%')]
    if t.startswith('OpBranchConditional'):
        p = t.split()
        return [p[2].lstrip('%'), p[3].lstrip('%')]
    if t.startswith('OpSwitch'):
        p = t.split()
        out = [p[1].lstrip('%')]
        for x in p[3:]:
            if x.startswith('%'):
                out.append(x.lstrip('%'))
        return out
    return []

def defsite(bid, vid):
    """Cari definisi %vid di blok mana (vid tanpa %)."""
    for b, ins in blocks.items():
        for s in ins:
            if re.match(r"^%%%s = " % re.escape(vid), s):
                return b, s
    return None, None

# cari semua loop header
loops = []
for bid in order:
    for s in blocks[bid]:
        if s.startswith('OpLoopMerge'):
            p = s.split()
            loops.append((bid, p[1].lstrip('%'), p[2].lstrip('%')))

print("file: %s" % path)
print("loops found: %d" % len(loops))
for (h, m, c) in loops:
    # BFS inside
    inside = set()
    stack = [h]
    while stack:
        b = stack.pop()
        if b in inside or b == m:
            continue
        inside.add(b)
        for t in targets(b):
            stack.append(t)
    # increment in header?
    inc = any(s.startswith('OpStore') for s in blocks.get(h, []))
    # exit branches
    exits = []
    for b in sorted(inside):
        t = term_of(b)
        if t and t.startswith('OpBranchConditional'):
            p = t.split()
            if p[2].lstrip('%') == m or p[3].lstrip('%') == m:
                exits.append((b, p[1].lstrip('%')))
    poisoned = []
    unpoisoned = []
    for (b, cond) in exits:
        db, ds = defsite(b, cond)
        ok = False
        if ds and ('OpLogicalOr' in ds or 'OpLogicalAnd' in ds):
            # cek operand-nya ada guard compare?
            for op in ds.split():
                if op.startswith('%'):
                    ob, os_ = defsite(b, op.lstrip('%'))
                    if os_ and 'OpUGreaterThan' in os_ and '1000000' in os_:
                        ok = True
                    if os_ and 'OpLogicalNot' in os_:
                        for op2 in os_.split():
                            if op2.startswith('%'):
                                ob2, os2 = defsite(b, op2.lstrip('%'))
                                if os2 and 'OpUGreaterThan' in os2 and '1000000' in os2:
                                    ok = True
        (poisoned if ok else unpoisoned).append((b, cond, ds))
    tag = "OK" if (inc and poisoned and not unpoisoned) else ("PARTIAL" if (inc or poisoned) else "NO-GUARD")
    if not exits:
        tag = "NO-EXIT-BRANCH"
    print("loop hdr=%%%s merge=%%%s cont=%%%s blocks=%d inc=%s exits=%d poisoned=%d unpoisoned=%d -> %s"
          % (h, m, c, len(inside), inc, len(exits), len(poisoned), len(unpoisoned), tag))
    for (b, cond, ds) in unpoisoned:
        print("    UNPOISONED exit: block %%%s cond %%%s  def: %s" % (b, cond, ds))
    if not exits:
        # tampilkan terminator di dalam loop agar tahu bentuknya
        for b in sorted(inside):
            print("    in-loop block %%%s term: %s" % (b, term_of(b)))
