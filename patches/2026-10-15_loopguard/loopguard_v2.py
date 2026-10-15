import re, sys

ROOT = "/mnt/share/tyo/kyty_latest/src/graphics/shader/recompiler/backend/spirv/"
HDR  = ROOT + "spirvEmitterInternal.h"
CPP  = ROOT + "spirvEmitterProgram.cpp"

def insert_before(text, pattern, insert, tag, expect=1):
    pat = re.compile(pattern)
    ms = list(pat.finditer(text))
    if len(ms) != expect:
        print("FAIL %s: %d matches" % (tag, len(ms))); sys.exit(1)
    out, last = [], 0
    for m in ms:
        out.append(text[last:m.start()]); out.append(insert); last = m.start()
    out.append(text[last:])
    return "".join(out)

def replace_match(text, pattern, build, tag, expect=1):
    pat = re.compile(pattern)
    ms = list(pat.finditer(text))
    if len(ms) != expect:
        print("FAIL %s: %d matches" % (tag, len(ms))); sys.exit(1)
    out, last = [], 0
    for m in ms:
        out.append(text[last:m.start()]); out.append(build(m)); last = m.end()
    out.append(text[last:])
    return "".join(out)

# ---------------------------------------------------------------- header
h = open(HDR).read()
fields = ("\n"
          "\n"
          "\t// [LOCAL PATCH RDNA1] Loop guard: counter iterasi per loop header guest.\n"
          "\t// Counter dinaikkan sekali per iterasi; begitu melewati LoopGuardLimit()\n"
          "\t// semua cabang keluar loop (yang menuju blok merge) dipaksa keluar. Ini\n"
          "\t// mencegah guest loop tanpa batas iterasi menggantungkan GPU\n"
          "\t// (ring gfx timeout -> device lost). Cabang yang sudah ada di-\"racuni\"\n"
          "\t// kondisinya supaya struktur SPIR-V tetap valid (tanpa predecessor OpPhi\n"
          "\t// baru dan tanpa blok keluar tambahan di dalam loop).\n"
          "\tstruct LoopGuardHeader {\n"
          "\t\tconst IR::Block* header   = nullptr;\n"
          "\t\tuint32_t         variable = 0;\n"
          "\t};\n"
          "\tstruct LoopGuardExit {\n"
          "\t\tconst IR::Block* site     = nullptr;\n"
          "\t\tconst IR::Block* merge    = nullptr;\n"
          "\t\tsize_t           variable = 0;\n"
          "\t};\n"
          "\tstd::vector<LoopGuardHeader> loop_guard_headers;\n"
          "\tstd::vector<LoopGuardExit>   loop_guard_exits;")
h = replace_match(h, r"std::vector<uint32_t>\s+interface_variables;",
                  lambda m: m.group(0) + fields, "hdr/fields")
open(HDR, "w").write(h)

# ---------------------------------------------------------------- cpp
c = open(CPP).read()

c = replace_match(c, r"#include <bit>", lambda m: m.group(0) + "\n#include <cstdlib>",
                  "cpp/include")

helpers = r"""// [LOCAL PATCH RDNA1] Batas iterasi loop guest (0 = guard dimatikan).
// Env: KYTY_LOOP_GUARD_LIMIT, default 1000000 iterasi per loop per invokasi.
// Guest loop tanpa batas iterasi membuat wave berputar selamanya; ring gfx lalu
// timeout dan seluruh device hilang (vkQueueSubmit ErrorDeviceLost).
uint32_t LoopGuardLimit() {
	static const uint32_t limit = [] {
		if (const char* env = std::getenv("KYTY_LOOP_GUARD_LIMIT")) {
			return static_cast<uint32_t>(std::strtoul(env, nullptr, 10));
		}
		return 1000000u;
	}();
	return limit;
}

void EmitLoopGuardIncrement(EmitterState& state, uint32_t guard_variable) {
	auto&      builder = state.builder;
	const auto loaded  = builder.AllocateId();
	builder.AddFunction(spv::OpLoad, TypeU32(state), loaded, guard_variable);
	const auto incremented = builder.AllocateId();
	builder.AddFunction(spv::OpIAdd, TypeU32(state), incremented, loaded, ConstantU32(state, 1));
	builder.AddFunction(spv::OpStore, guard_variable, incremented);
}

uint32_t EmitLoopGuardOver(EmitterState& state, uint32_t guard_variable) {
	auto&      builder = state.builder;
	const auto loaded  = builder.AllocateId();
	builder.AddFunction(spv::OpLoad, TypeU32(state), loaded, guard_variable);
	const auto over = builder.AllocateId();
	builder.AddFunction(spv::OpUGreaterThan, TypeBool(state), over, loaded,
	                    ConstantU32(state, LoopGuardLimit()));
	return over;
}

// Susun guard: satu counter per loop header guest + daftar cabang keluar loop
// (blok di dalam loop yang bercabang berkondisi menuju blok merge).
void CollectLoopGuardSites(EmitterState& state) {
	state.loop_guard_headers.clear();
	state.loop_guard_exits.clear();
	if (LoopGuardLimit() == 0) {
		return;
	}
	for (const auto* header: state.program.blocks) {
		const auto& term = header->terminator;
		if (!term.loop_header || term.merge_block == nullptr || term.continue_block == nullptr) {
			continue;
		}
		const auto* merge = term.merge_block;
		// Blok di dalam loop = reachable dari header tanpa melewati merge.
		std::unordered_set<const IR::Block*> inside;
		std::vector<const IR::Block*>       pending {header};
		while (!pending.empty()) {
			const auto* current = pending.back();
			pending.pop_back();
			if (current == nullptr || current == merge || inside.count(current) != 0) {
				continue;
			}
			inside.insert(current);
			for (const auto* next: current->ImmSuccessors()) {
				pending.push_back(next);
			}
		}
		std::vector<EmitterState::LoopGuardExit> found;
		for (const auto* block: state.program.blocks) {
			if (inside.count(block) == 0) {
				continue;
			}
			const auto& block_term = block->terminator;
			if (block_term.kind != CFG::TerminatorKind::ConditionalBranch ||
			    block_term.true_block == nullptr || block_term.false_block == nullptr) {
				continue;
			}
			if (block_term.true_block == merge || block_term.false_block == merge) {
				found.push_back(EmitterState::LoopGuardExit {block, merge, 0});
			}
		}
		if (found.empty()) {
			// Loop tanpa cabang keluar berkondisi: tidak bisa dijaga dengan aman.
			continue;
		}
		const auto index = state.loop_guard_headers.size();
		state.loop_guard_headers.push_back(EmitterState::LoopGuardHeader {header, state.builder.AllocateId()});
		for (auto& exit: found) {
			exit.variable = index;
			state.loop_guard_exits.push_back(exit);
		}
	}
}

"""
c = insert_before(c, r"void EmitReturn\(ValueEmitContext& ctx\) \{", helpers, "cpp/helpers")

guard_increment = r"""	auto& state = ctx.state;

	// [LOCAL PATCH RDNA1] Loop guard: naikkan counter iterasi loop ini.
	if (term.loop_header) {
		for (const auto& entry: state.loop_guard_headers) {
			if (entry.header == block) {
				EmitLoopGuardIncrement(state, entry.variable);
				break;
			}
		}
	}

	switch (term.kind) {"""
c = replace_match(c,
    r"spv::SelectionControlMaskNone\);\s*\n\s*\}\s*\n\s*\};\s*\n\s*switch \(term\.kind\) \{",
    lambda m: "spv::SelectionControlMaskNone);\n\t\t}\n\t};\n\n" + guard_increment,
    "cpp/increment")

poison = r"""const auto condition = ctx.Def(block->condition);
			emit_merge();
			auto branch_condition = condition;
			// [LOCAL PATCH RDNA1] Paksa keluar loop bila counter iterasi sudah
			// melewati batas: cabang menuju blok merge dibuat selalu diambil.
			for (const auto& exit: state.loop_guard_exits) {
				if (exit.site != block) {
					continue;
				}
				const auto over = EmitLoopGuardOver(state, state.loop_guard_headers[exit.variable].variable);
				const auto next = state.builder.AllocateId();
				if (term.true_block == exit.merge) {
					state.builder.AddFunction(spv::OpLogicalOr, TypeBool(state), next,
					                          branch_condition, over);
				} else {
					const auto in_range = state.builder.AllocateId();
					state.builder.AddFunction(spv::OpLogicalNot, TypeBool(state), in_range, over);
					state.builder.AddFunction(spv::OpLogicalAnd, TypeBool(state), next,
					                          branch_condition, in_range);
				}
				branch_condition = next;
			}
			ctx.state.builder.AddFunction(spv::OpBranchConditional, branch_condition,
			                              true_block->Definition(), false_block->Definition());
			return;"""
c = replace_match(c,
    r"const auto condition = ctx\.Def\(block->condition\);\s*\n\s*emit_merge\(\);\s*\n\s*ctx\.state\.builder\.AddFunction\(spv::OpBranchConditional, condition,\s*\n\s*true_block->Definition\(\), false_block->Definition\(\)\);\s*\n\s*return;",
    lambda m: poison, "cpp/poison")

prescan = r"""// [LOCAL PATCH RDNA1] Siapkan counter loop guard + titik keluarnya.
	if (!state.program.dispatcher_fallback) {
		CollectLoopGuardSites(state);
	}
	"""
c = insert_before(c, r"state\.builder\.AddFunction\(spv::OpFunction, TypeVoid\(state\),", prescan, "cpp/prescan")

decl_extra = r"""
	for (const auto& entry: state.loop_guard_headers) {
		// Initializer 0: counter di-reset setiap pemanggilan fungsi.
		state.builder.AddFunction(spv::OpVariable,
		                          TypePointer(state, spv::StorageClassFunction, TypeU32(state)),
		                          entry.variable, spv::StorageClassFunction, ConstantU32(state, 0));
	}"""
c = replace_match(c,
    r"state\.pixel_valid_mask_variable, spv::StorageClassFunction\);\s*\n\s*\}",
    lambda m: m.group(0) + decl_extra, "cpp/prologue-decl")

open(CPP, "w").write(c)
print("PATCH OK")
