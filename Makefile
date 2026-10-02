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
RESOURCE_EXPORTS = resource_build resource_program rs_init rs_read rs_prepare rs_c_body rs_source_import
OVERLOAD = stages/overload/model.crs stages/overload/base.crs stages/overload/types.crs stages/overload/collect.crs stages/overload/resolve.crs stages/overload/read.crs stages/overload/program.crs
OVERLOAD_LIBRARY = $(C_LIBRARY) $(READER) $(OVERLOAD)
OVERLOAD_EXPORTS = overload_build overload_program ov_init ov_read ov_prepare ov_collect ov_resolve ov_mangle ov_alloc ov_error ov_put ov_type ov_intern ov_global ov_function_syntax ov_select ov_same ov_encode_type ov_text ov_bytes ov_number ov_part ov_expression ov_statement ov_standard_expression ov_standard_statement ov_scope ov_leave_scope ov_lookup ov_bind ov_block ov_field_type ov_driver_build ov_check
OVERLOAD_RESOURCE_LIBRARY = $(RESOURCE_LIBRARY) $(OVERLOAD) stages/overload/resources.crs stages/overload/resource_program.crs
OVERLOAD_RESOURCE_EXPORTS = $(RESOURCE_EXPORTS) $(OVERLOAD_EXPORTS) overload_resource_build overload_resource_program ov_resources_init ov_resources_read ov_resources_prepare ov_resources_check

.PHONY: all clean check witness api c-stage resource-stage overload-stage highlight-stage check-highlight ccn-stage check-ccn vscode check-vscode check-overload check-overload-alloc check-c check-stage check-examples check-resources check-resource-alloc check-reader check-modules check-native check-asm check-cache
.PHONY: amalgamate check-amalgamation FORCE
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

$(BUILD)/intrusive.s: $(BUILD)/crust0 examples/intrusive/program.crs
	$(BUILD)/crust0 -S -o $@ examples/intrusive/program.crs

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

clean:
	rm -rf $(BUILD)

-include $(wildcard $(BUILD)/*.d)
