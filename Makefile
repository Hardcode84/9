# SPDX-License-Identifier: Apache-2.0

CC ?= cc
AR ?= ar
AS ?= as
ASFLAGS ?= --64
CFLAGS ?= -O2 -g
CPPFLAGS += -Iinclude
STRICT = -std=c99 -pedantic-errors -Wall -Wextra -Werror -Wstrict-prototypes -Wmissing-prototypes -Wshadow -Wvla
BUILD ?= build
PROFILE ?= linux_x64
AMALGAMATION ?= 1
ifneq ($(PROFILE),linux_x64)
$(error Unsupported PROFILE '$(PROFILE)'; expected linux_x64)
endif
ifeq ($(AMALGAMATION),1)
CORE = $(BUILD)/crust0_amalg.o $(BUILD)/profile_$(PROFILE).o
else ifeq ($(AMALGAMATION),0)
CORE = $(BUILD)/core.o $(BUILD)/read.o $(BUILD)/check.o $(BUILD)/profile_$(PROFILE).o
else
$(error Unsupported AMALGAMATION '$(AMALGAMATION)'; expected 0 or 1)
endif
RUNNER = $(BUILD)/eval.o $(BUILD)/eval_ffi_$(PROFILE).o $(BUILD)/run.o $(BUILD)/run_posix.o
HOST = $(BUILD)/host.o $(BUILD)/host_posix.o
PRELUDE = api/crust0.crs api/crust0_host.crs api/crust0_eval.crs api/crust0_run.crs stages/host.crs
C_LIBRARY = api/crust0.crs api/crust0_host.crs api/crust0_stage.crs stages/c/model.crs stages/c/base.crs stages/c/types.crs stages/c/emit.crs stages/c/driver.crs stages/c/program.crs
C_STAGE = $(C_LIBRARY) stages/c/main.crs
ASM_LIBRARY = api/crust0.crs stages/asm/model.crs stages/asm/output.crs stages/asm/plan.crs stages/asm/emit.crs stages/asm/program.crs
READER = stages/reader/model.crs stages/reader/lex.crs stages/reader/parse.crs
HIGHLIGHT = api/crust0.crs api/crust0_host.crs stages/reader/model.crs stages/reader/lex.crs stages/highlight/model.crs stages/highlight/scan.crs stages/highlight/output.crs stages/highlight/program.crs
CCN = api/crust0.crs api/crust0_host.crs api/crust0_eval.crs api/crust0_run.crs stages/ccn/count.crs stages/ccn/read.crs stages/ccn/report.crs stages/ccn/program.crs
RESOURCE = stages/resources/model.crs stages/resources/base.crs stages/resources/read.crs stages/resources/types.crs stages/resources/constants.crs stages/resources/state.crs stages/resources/cleanup.crs stages/resources/places.crs stages/resources/expr.crs stages/resources/control.crs stages/resources/emit.crs stages/resources/program.crs stages/resources/build.crs
RESOURCE_LIBRARY = $(C_LIBRARY) $(READER) $(RESOURCE)
RESOURCE_EXPORTS = resource_build resource_program rs_init rs_read rs_prepare rs_prepare_delegated rs_c_body rs_source_import rs_return_from
PROOF = stages/proof/model.crs stages/proof/base.crs stages/proof/terms.crs stages/proof/state.crs stages/proof/query.crs stages/proof/expression.crs stages/proof/execute.crs stages/proof/verify.crs stages/proof/z3.crs
MEMORY = stages/memory/options.crs stages/memory/model.crs stages/memory/base.crs stages/memory/plan.crs stages/memory/storage.crs stages/memory/expr.crs stages/memory/foreign.crs stages/memory/statement.crs stages/memory/assign.crs stages/memory/copy.crs stages/memory/summary_plan.crs stages/memory/summary_terms.crs stages/memory/summary.crs stages/memory/program.crs
MEMORY_LIBRARY = $(C_LIBRARY) $(PROOF) $(MEMORY)
RESOURCE_MEMORY = stages/resource_memory/model.crs stages/resource_memory/view.crs stages/resource_memory/effects.crs stages/resource_memory/program.crs
RESOURCE_MEMORY_LIBRARY = $(RESOURCE_LIBRARY) $(PROOF) $(MEMORY) $(RESOURCE_MEMORY)
MEMORY_CONTRACT = stages/memory/contract.crs
INTRUSIVE_CONTRACT = examples/intrusive/contract-options.crs examples/intrusive/contract.crs
MEMORY_LOOP = stages/memory/loop.crs
INTRUSIVE_WALK = examples/intrusive/walk-options.crs examples/intrusive/walk-stage.crs
Z3_LIBDIR ?=
Z3_FLAGS = -lz3
ifneq ($(strip $(Z3_LIBDIR)),)
Z3_FLAGS += -L$(Z3_LIBDIR) -Wl,-rpath,$(abspath $(Z3_LIBDIR))
endif
Z3_LINK = $(foreach flag,$(Z3_FLAGS),--ldflag=$(flag))
OVERLOAD = stages/overload/model.crs stages/overload/base.crs stages/overload/types.crs stages/overload/collect.crs stages/overload/resolve.crs stages/overload/read.crs stages/overload/program.crs
OVERLOAD_LIBRARY = $(C_LIBRARY) $(READER) $(OVERLOAD)
OVERLOAD_EXPORTS = overload_build overload_program ov_init ov_read ov_prepare ov_collect ov_resolve ov_mangle ov_alloc ov_error ov_put ov_type ov_intern ov_global ov_function_syntax ov_select ov_same ov_encode_type ov_text ov_bytes ov_number ov_part ov_expression ov_statement ov_standard_expression ov_standard_statement ov_scope ov_leave_scope ov_lookup ov_bind ov_block ov_field_type ov_driver_build ov_check
OVERLOAD_RESOURCE_LIBRARY = $(RESOURCE_LIBRARY) $(OVERLOAD) stages/overload/resources.crs stages/overload/resource_program.crs
OVERLOAD_RESOURCE_EXPORTS = $(RESOURCE_EXPORTS) $(OVERLOAD_EXPORTS) overload_resource_build overload_resource_program ov_resources_init ov_resources_read ov_resources_prepare ov_resources_check

.PHONY: all clean check witness api c-stage resource-stage overload-stage highlight-stage check-highlight ccn-stage check-ccn vscode check-vscode check-overload check-overload-alloc check-c check-stage check-examples check-resources check-resource-alloc check-reader check-modules check-native check-asm check-cache
.PHONY: amalgamate check-amalgamation FORCE
.PHONY: memory-stage check-memory check-memory-alloc
.PHONY: resource-memory-stage check-resource-memory check-resource-memory-alloc
.PHONY: check-memory-summaries
.PHONY: memory-contract-stage check-memory-contracts
.PHONY: memory-loop-stage check-memory-loops
all: $(BUILD)/crust $(BUILD)/crust0 $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a $(BUILD)/libcrust0_run.a $(BUILD)/libcrust_asm.a $(BUILD)/crust-asm-library.so

$(BUILD):
	mkdir -p $@

$(BUILD)/%.o: src/%.c include/crust0.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -MMD -MP -c $< -o $@

crust0_amalg.c: tools/amalgamate.py src/core.c src/read.c src/check.c
	python3 tools/amalgamate.py

amalgamate:
	python3 tools/amalgamate.py

$(BUILD)/crust0_amalg.o: crust0_amalg.c | $(BUILD)
	$(CC) $(CPPFLAGS) -Isrc $(CFLAGS) $(STRICT) -MMD -MP -c $< -o $@

# A mode change must relink even when the other mode's objects already exist.
$(BUILD)/core-mode: FORCE | $(BUILD)
	@printf '%s\n' '$(AMALGAMATION)' > $@.tmp
	@if cmp -s $@.tmp $@; then rm $@.tmp; else mv $@.tmp $@; fi

$(BUILD)/crust $(BUILD)/crust0 $(BUILD)/libcrust0.a: $(BUILD)/core-mode

$(HOST): $(BUILD)/%.o: runtime/%.c include/crust0_host.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -MMD -MP -c $< -o $@

$(BUILD)/crust0: $(BUILD)/crust-asm-library.o $(CORE) $(BUILD)/driver.o $(BUILD)/driver_posix.o $(HOST)
	$(CC) $(CFLAGS) $(filter-out $(BUILD)/core-mode,$^) $(LDFLAGS) -o $@

$(BUILD)/prelude.inc: tools/prelude.py $(PRELUDE) | $(BUILD)
	python3 tools/prelude.py $@

$(BUILD)/run_main.o: CPPFLAGS += -I$(BUILD)
$(BUILD)/run_main.o: $(BUILD)/prelude.inc
$(BUILD)/eval.o: CPPFLAGS += -Isrc/$(PROFILE)

$(BUILD)/crust: $(CORE) $(RUNNER) $(BUILD)/run_main.o $(HOST)
	$(CC) $(CFLAGS) $(filter-out $(BUILD)/core-mode,$^) -rdynamic $(LDFLAGS) -ldl -lffi -o $@

$(BUILD)/libcrust0_run.a: $(RUNNER)
	$(AR) rcs $@ $^

$(BUILD)/libcrust0.a: $(CORE) Makefile
	rm -f $@
	$(AR) rcs $@ $(CORE)

$(BUILD)/libcrust0_host.a: $(HOST)
	$(AR) rcs $@ $^

$(BUILD)/crust-c-seed: $(BUILD)/crust $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a $(C_STAGE) stages/c/bootstrap.crs stages/c/build.crs
	$(BUILD)/crust stages/c/bootstrap.crs -o $@ $(filter-out api/crust0.crs,$(C_STAGE)) $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-c: $(BUILD)/crust-c-seed
	$< -o $@ $(C_STAGE) $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/c-exports: $(BUILD)/crust stages/modules/library.crs stages/modules/exports.crs stages/c/api.crs stages/c/extension.crs Makefile
	$< stages/modules/exports.crs stages/c/api.crs stages/c/extension.crs > $@.tmp
	mv $@.tmp $@

$(BUILD)/crust-c-library.o: $(BUILD)/crust-c $(C_LIBRARY) $(BUILD)/c-exports Makefile
	crust_exports=$$(cat $(BUILD)/c-exports) && $< --library --object $$crust_exports --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(C_LIBRARY)

$(BUILD)/crust-c-library.so: $(BUILD)/crust-c-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(LDFLAGS) -o $@

$(BUILD)/asm-exports: $(BUILD)/crust stages/modules/library.crs stages/modules/exports.crs api/crust0_x64.crs Makefile
	$< stages/modules/exports.crs api/crust0_x64.crs > $@.tmp
	mv $@.tmp $@

$(BUILD)/crust-asm-library.o: $(BUILD)/crust-c $(ASM_LIBRARY) $(BUILD)/asm-exports Makefile
	crust_exports=$$(cat $(BUILD)/asm-exports) && $< --library --object $$crust_exports --export crust_x64_default_ops --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(ASM_LIBRARY)

$(BUILD)/libcrust_asm.a: $(BUILD)/crust-asm-library.o
	$(AR) rcs $@ $^

$(BUILD)/crust-asm-library.so: $(BUILD)/crust-asm-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(LDFLAGS) -o $@

c-stage: $(BUILD)/crust-c $(BUILD)/crust-c-library.so

$(BUILD)/crust-highlight: $(BUILD)/crust-c $(HIGHLIGHT) stages/highlight/main.crs
	$< -o $@ $(HIGHLIGHT) stages/highlight/main.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

highlight-stage: $(BUILD)/crust-highlight

check-highlight: all highlight-stage
	python3 stages/highlight/test.py --build $(BUILD)

$(BUILD)/crust-ccn: $(BUILD)/crust-c $(CCN) stages/ccn/main.crs $(BUILD)/libcrust0_run.a $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a Makefile
	$< -o $@ $(CCN) stages/ccn/main.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0_run.a --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a --ldflag=-ldl --ldflag=-lffi $(foreach flag,$(LDFLAGS),--ldflag $(flag))

ccn-stage: $(BUILD)/crust-ccn

check-ccn: all c-stage ccn-stage
	python3 tests/ccn.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

vscode: highlight-stage
	python3 editors/vscode/package.py --binary $(BUILD)/crust-highlight --output $(BUILD)/crust-vscode.vsix

check-vscode: highlight-stage $(BUILD)/crust
	CRUST_HIGHLIGHT=$(abspath $(BUILD))/crust-highlight CRUST_LAUNCHER=$(abspath $(BUILD))/crust bun test ./editors/vscode

$(BUILD)/crust-resource: $(BUILD)/crust-c $(RESOURCE_LIBRARY) stages/resources/main.crs
	$< -o $@ $(RESOURCE_LIBRARY) stages/resources/main.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-resource-library.o: $(BUILD)/crust-c $(RESOURCE_LIBRARY) Makefile
	$< --library --object $(foreach name,$(RESOURCE_EXPORTS),--export $(name)) --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(RESOURCE_LIBRARY)

$(BUILD)/crust-resource-library.so: $(BUILD)/crust-resource-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(LDFLAGS) -o $@

resource-stage: $(BUILD)/crust-resource $(BUILD)/crust-resource-library.so

$(BUILD)/crust-memory-test: $(BUILD)/crust-c $(MEMORY_LIBRARY) examples/ownership/ring_contracts.crs examples/ownership/compiler.crs tests/memory_driver.crs Makefile
	$< -o $@ $(MEMORY_LIBRARY) examples/ownership/ring_contracts.crs examples/ownership/compiler.crs tests/memory_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(Z3_LINK) $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-resource-memory-test: $(BUILD)/crust-c $(RESOURCE_MEMORY_LIBRARY) tests/resource_memory_driver.crs Makefile
	$< -o $@ $(RESOURCE_MEMORY_LIBRARY) tests/resource_memory_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(Z3_LINK) $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-resource-memory-library.o: $(BUILD)/crust-c $(RESOURCE_MEMORY_LIBRARY) Makefile
	$< --library --object --export resource_memory_program --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(RESOURCE_MEMORY_LIBRARY)

$(BUILD)/crust-resource-memory-library.so: $(BUILD)/crust-resource-memory-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $< $(Z3_FLAGS) $(LDFLAGS) -o $@

resource-memory-stage: $(BUILD)/crust-resource-memory-test $(BUILD)/crust-resource-memory-library.so

$(BUILD)/crust-memory-contract-test: $(BUILD)/crust-c $(RESOURCE_MEMORY_LIBRARY) $(MEMORY_CONTRACT) $(INTRUSIVE_CONTRACT) tests/memory_contract_models.crs tests/memory_contract_driver.crs Makefile
	$< -o $@ $(RESOURCE_MEMORY_LIBRARY) $(MEMORY_CONTRACT) $(INTRUSIVE_CONTRACT) tests/memory_contract_models.crs tests/memory_contract_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(Z3_LINK) $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-intrusive-contract-library.o: $(BUILD)/crust-c $(RESOURCE_MEMORY_LIBRARY) $(MEMORY_CONTRACT) $(INTRUSIVE_CONTRACT) Makefile
	$< --library --object --export intrusive_contract_program --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(RESOURCE_MEMORY_LIBRARY) $(MEMORY_CONTRACT) $(INTRUSIVE_CONTRACT)

$(BUILD)/crust-intrusive-contract-library.so: $(BUILD)/crust-intrusive-contract-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $< $(Z3_FLAGS) $(LDFLAGS) -o $@

memory-contract-stage: $(BUILD)/crust-memory-contract-test $(BUILD)/crust-intrusive-contract-library.so

check-memory-contracts: all resource-memory-stage memory-contract-stage
	python3 tests/memory_contract.py --build $(BUILD)
	python3 tests/memory_alloc.py --contracts --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION) --z3-flags='$(Z3_FLAGS)'

$(BUILD)/crust-memory-loop-test: $(BUILD)/crust-c $(RESOURCE_MEMORY_LIBRARY) $(MEMORY_LOOP) $(INTRUSIVE_WALK) tests/memory_loop_models.crs tests/memory_loop_driver.crs Makefile
	$< -o $@ $(RESOURCE_MEMORY_LIBRARY) $(MEMORY_LOOP) $(INTRUSIVE_WALK) tests/memory_loop_models.crs tests/memory_loop_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(Z3_LINK) $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-intrusive-walk-library.o: $(BUILD)/crust-c $(RESOURCE_MEMORY_LIBRARY) $(MEMORY_LOOP) $(INTRUSIVE_WALK) Makefile
	$< --library --object --export intrusive_walk_program --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(RESOURCE_MEMORY_LIBRARY) $(MEMORY_LOOP) $(INTRUSIVE_WALK)

$(BUILD)/crust-intrusive-walk-library.so: $(BUILD)/crust-intrusive-walk-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $< $(Z3_FLAGS) $(LDFLAGS) -o $@

memory-loop-stage: $(BUILD)/crust-memory-loop-test $(BUILD)/crust-intrusive-walk-library.so

check-memory-loops: all resource-memory-stage memory-loop-stage
	python3 tests/memory_loop.py --build $(BUILD)
	python3 tests/memory_alloc.py --loops --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION) --z3-flags='$(Z3_FLAGS)'

check-resource-memory: all resource-stage resource-memory-stage
	python3 tests/resource_memory.py --build $(BUILD)
	python3 tests/resource_initialization.py --build $(BUILD)

check-resource-memory-alloc: all c-stage
	python3 tests/memory_alloc.py --resources --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION) --z3-flags='$(Z3_FLAGS)'

check-memory-summaries: all memory-stage resource-memory-stage
	python3 tests/memory_summary.py --build $(BUILD)
	python3 tests/memory_alloc.py --summaries --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION) --z3-flags='$(Z3_FLAGS)'
	python3 tests/memory_alloc.py --summaries --resources --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION) --z3-flags='$(Z3_FLAGS)'

$(BUILD)/crust-memory-library.o: $(BUILD)/crust-c $(MEMORY_LIBRARY) Makefile
	$< --library --object --export memory_program --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(MEMORY_LIBRARY)

$(BUILD)/crust-memory-library.so: $(BUILD)/crust-memory-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(Z3_FLAGS) $(LDFLAGS) -o $@

memory-stage: $(BUILD)/crust-memory-test $(BUILD)/crust-memory-library.so

$(BUILD)/proof-solver-test: $(BUILD)/crust-c api/crust0.crs api/crust0_host.crs stages/c/model.crs stages/c/base.crs stages/proof/z3.crs tests/proof_solver.crs Makefile
	$< -o $@ api/crust0.crs api/crust0_host.crs stages/c/model.crs stages/c/base.crs stages/proof/z3.crs tests/proof_solver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(Z3_LINK) $(foreach flag,$(LDFLAGS),--ldflag $(flag))

check-memory: all memory-stage $(BUILD)/proof-solver-test
	$(BUILD)/proof-solver-test
	python3 tests/memory.py --build $(BUILD)

check-memory-alloc: all c-stage
	python3 tests/memory_alloc.py --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION) --z3-flags='$(Z3_FLAGS)'

$(BUILD)/crust-overload: $(BUILD)/crust-c $(OVERLOAD_LIBRARY) stages/overload/main.crs
	$< -o $@ $(OVERLOAD_LIBRARY) stages/overload/main.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-overload-library.o: $(BUILD)/crust-c $(OVERLOAD_LIBRARY) Makefile
	$< --library --object $(foreach name,$(OVERLOAD_EXPORTS),--export $(name)) --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(OVERLOAD_LIBRARY)

$(BUILD)/crust-overload-library.so: $(BUILD)/crust-overload-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(LDFLAGS) -o $@

$(BUILD)/crust-overload-resource: $(BUILD)/crust-c $(OVERLOAD_RESOURCE_LIBRARY) stages/overload/resource_main.crs
	$< -o $@ $(OVERLOAD_RESOURCE_LIBRARY) stages/overload/resource_main.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-overload-resource-library.o: $(BUILD)/crust-c $(OVERLOAD_RESOURCE_LIBRARY) Makefile
	$< --library --object $(foreach name,$(OVERLOAD_RESOURCE_EXPORTS),--export $(name)) --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(OVERLOAD_RESOURCE_LIBRARY)

$(BUILD)/crust-overload-resource-library.so: $(BUILD)/crust-overload-resource-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(LDFLAGS) -o $@

overload-stage: $(BUILD)/crust-overload $(BUILD)/crust-overload-library.so $(BUILD)/crust-overload-resource $(BUILD)/crust-overload-resource-library.so

$(BUILD)/intrusive.s: $(BUILD)/crust0 examples/intrusive/raw.crs
	$(BUILD)/crust0 -S -o $@ examples/intrusive/raw.crs

$(BUILD)/intrusive.o: $(BUILD)/intrusive.s
	$(AS) $(ASFLAGS) $< -o $@

$(BUILD)/intrusive: $(BUILD)/intrusive.o $(BUILD)/libcrust0_host.a
	$(CC) -no-pie $^ $(LDFLAGS) -o $@

$(BUILD)/intrusive-c: benchmarks/bootstrap/intrusive.c $(BUILD)/libcrust0_host.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $^ $(LDFLAGS) -o $@

witness: $(BUILD)/intrusive $(BUILD)/intrusive-c
	$(BUILD)/intrusive
	$(BUILD)/intrusive-c

$(BUILD)/%_test: tests/%_test.c $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $^ $(LDFLAGS) -pthread -o $@

$(BUILD)/core_test $(BUILD)/check_test $(BUILD)/x64_test $(BUILD)/parallel_test: $(BUILD)/%_test: tests/%_test.c $(BUILD)/libcrust_asm.a $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $^ $(LDFLAGS) -pthread -o $@

$(BUILD)/arena_test: tests/arena_$(PROFILE)_test.c $(BUILD)/libcrust0.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $^ $(LDFLAGS) -Wl,--wrap=madvise -o $@

$(BUILD)/eval_test: tests/eval_test.c tests/native.c $(BUILD)/eval.o $(BUILD)/eval_ffi_$(PROFILE).o $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $^ -rdynamic $(LDFLAGS) -ldl -lffi -o $@

api:
	python3 tools/api.py

check-amalgamation:
	python3 tools/check_amalgamation.py --cc '$(CC)' --cflags='$(CFLAGS) $(STRICT)'

check: all $(BUILD)/core_test $(BUILD)/arena_test $(BUILD)/read_test $(BUILD)/check_test $(BUILD)/host_test $(BUILD)/parallel_test $(BUILD)/x64_test $(BUILD)/eval_test
	$(BUILD)/core_test
	$(BUILD)/arena_test
	$(BUILD)/read_test
	$(BUILD)/check_test
	$(BUILD)/host_test
	$(BUILD)/parallel_test
	$(BUILD)/x64_test
	$(BUILD)/eval_test
	python3 tools/api.py --check
	python3 tests/run.py --compiler $(BUILD)/crust0 --cc '$(CC)' --assembler '$(AS) $(ASFLAGS)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-c: c-stage
	python3 tests/run.py --backend c --compiler $(BUILD)/crust-c --cc '$(CC)' --assembler '$(AS) $(ASFLAGS)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/c_body.py --build $(BUILD) --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-reader: all c-stage
	python3 stages/reader/test.py --build $(BUILD) --cc '$(CC)' --ldflags='$(LDFLAGS)'

check-resources: all resource-stage
	python3 tests/resources.py --build $(BUILD)
	python3 tests/resource_returns.py --build $(BUILD)

check-overload: all overload-stage resource-stage
	python3 tests/overload.py --build $(BUILD)
	python3 tests/overload_resources.py --build $(BUILD)
	python3 tests/overload_hooks.py --build $(BUILD) --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/nesting.py --build $(BUILD)

check-overload-alloc: all c-stage
	python3 tests/overload_alloc.py --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION)

check-resource-alloc: all c-stage
	python3 tests/resources_alloc.py --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION)

check-stage: all c-stage
	python3 tests/source_order.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-examples: all c-stage
	python3 tests/source_order.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)' --group examples

check-modules: all c-stage
	python3 tests/modules.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-asm: all
	python3 tests/asm.py --build $(BUILD) --cc '$(CC)' --ldflags='$(LDFLAGS)'

check-cache: $(BUILD)/crust
	python3 tests/cache.py --build $(BUILD)

check-native: all
	python3 tests/native.py --build $(BUILD)

PARALLEL = api/crust0.crs stages/parallel/model.crs stages/parallel/linux_x64.crs

$(BUILD)/crust-parallel-library.so: $(BUILD)/crust-c $(PARALLEL)
	$< --library --export parallel_run --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag=-shared --ldflag=-pthread --ldflag=-Wl,-Bsymbolic,-z,text,-z,relro,-z,now $(foreach flag,$(LDFLAGS),--ldflag $(flag)) -o $@ $(PARALLEL)

.PHONY: parallel-stage check-parallel
parallel-stage: $(BUILD)/crust-parallel-library.so

check-parallel: all c-stage parallel-stage
	python3 tests/parallel.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

clean:
	rm -rf $(BUILD)

-include $(wildcard $(BUILD)/*.d)
