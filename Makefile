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
API_HEADERS = $(addprefix include/,$(addsuffix .h,crust0 crust0_host crust0_x64 crust0_stage crust0_eval crust0_run))
API_GENERATED = $(patsubst include/%.h,api/%.crs,$(API_HEADERS)) include/crust0_abi.h stages/asm/model.crs
C_LIBRARY = api/crust0.crs api/crust0_host.crs api/crust0_stage.crs stages/c/model.crs stages/c/base.crs stages/c/types.crs stages/c/emit.crs stages/c/driver.crs stages/c/program.crs
C_STAGE = $(C_LIBRARY) stages/c/main.crs
ASM_LIBRARY = api/crust0.crs stages/asm/model.crs stages/asm/output.crs stages/asm/plan.crs stages/asm/emit.crs stages/asm/program.crs
READER = stages/reader/model.crs stages/reader/lex.crs stages/reader/parse.crs
HIGHLIGHT = api/crust0.crs api/crust0_host.crs stages/reader/model.crs stages/reader/lex.crs stages/highlight/model.crs stages/highlight/scan.crs stages/highlight/output.crs stages/highlight/program.crs
CCN = api/crust0.crs api/crust0_host.crs api/crust0_eval.crs api/crust0_run.crs stages/ccn/count.crs stages/ccn/read.crs stages/ccn/report.crs stages/ccn/program.crs
RESOURCE = stages/resources/model.crs stages/resources/base.crs stages/resources/read.crs stages/resources/types.crs stages/resources/constants.crs stages/resources/state.crs stages/resources/cleanup.crs stages/resources/drop.crs stages/resources/places.crs stages/resources/outputs.crs stages/resources/expr.crs stages/resources/control.crs stages/resources/emit.crs stages/resources/program.crs stages/resources/build.crs
RESOURCE_LIBRARY = $(C_LIBRARY) $(READER) $(RESOURCE)
RESOURCE_EXPORTS = resource_build resource_program rs_init rs_kind rs_read rs_prepare rs_prepare_delegated rs_c_body rs_source_import rs_return_from
OWNERSHIP = stages/ownership/abstract.crs stages/ownership/abstract_expr.crs stages/ownership/model.crs stages/ownership/trust.crs stages/ownership/base.crs stages/ownership/native_read.crs stages/ownership/native.crs stages/ownership/read.crs stages/ownership/objects.crs stages/ownership/fields.crs stages/ownership/loans.crs stages/ownership/views.crs stages/ownership/view_results.crs stages/ownership/results.crs stages/ownership/places.crs stages/ownership/expressions.crs stages/ownership/conditions.crs stages/ownership/calls.crs stages/ownership/entry.crs stages/ownership/flow.crs stages/ownership/contracts.crs stages/ownership/effects.crs stages/ownership/scopes.crs stages/ownership/defer.crs stages/ownership/loop.crs stages/ownership/control.crs stages/ownership/check.crs stages/ownership/program.crs
OWNERSHIP_IMPORTS = api/crust0_eval.crs api/crust0_run.crs stages/native/model.crs stages/native/linux.crs stages/cache/model.crs stages/cache/linux.crs stages/cache/artifact.crs stages/cache/inputs.crs stages/ownership/library_model.crs stages/ownership/interface.crs stages/ownership/artifact.crs stages/ownership/publish.crs stages/ownership/imports.crs
OWNERSHIP_LIBRARY = $(RESOURCE_LIBRARY) $(OWNERSHIP) $(OWNERSHIP_IMPORTS)
OVERLOAD = stages/overload/model.crs stages/overload/base.crs stages/overload/types.crs stages/overload/collect.crs stages/overload/resolve.crs stages/overload/read.crs stages/overload/program.crs
OVERLOAD_LIBRARY = $(C_LIBRARY) $(READER) $(OVERLOAD)
OVERLOAD_EXPORTS = overload_build overload_program ov_init ov_read ov_prepare ov_collect ov_resolve ov_mangle ov_alloc ov_error ov_put ov_type ov_intern ov_global ov_function_syntax ov_select ov_same ov_encode_type ov_text ov_bytes ov_number ov_part ov_expression ov_statement ov_standard_expression ov_standard_statement ov_scope ov_leave_scope ov_lookup ov_bind ov_block ov_field_type ov_driver_build ov_check
OVERLOAD_RESOURCE_LIBRARY = $(RESOURCE_LIBRARY) $(OVERLOAD) stages/overload/resources.crs stages/overload/resource_program.crs
OVERLOAD_RESOURCE_EXPORTS = $(RESOURCE_EXPORTS) $(OVERLOAD_EXPORTS) overload_resource_build overload_resource_program ov_resources_init ov_resources_read ov_resources_prepare ov_resources_check

.PHONY: all clean check witness api c-stage resource-stage overload-stage highlight-stage check-highlight ccn-stage check-ccn vscode check-vscode check-overload check-overload-alloc check-c check-stage check-examples check-resources check-resource-alloc check-reader check-modules check-native check-asm check-cache
.PHONY: amalgamate check-amalgamation FORCE
all: $(BUILD)/crust $(BUILD)/crust0 $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a $(BUILD)/libcrust0_run.a $(BUILD)/libcrust_asm.a $(BUILD)/crust-asm-library.so

$(API_GENERATED) &: tools/api.py $(API_HEADERS)
	python3 tools/api.py

$(BUILD)/run_posix.o: include/crust0_abi.h

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
	@set -e; crust_mode_tmp='$@.tmp.'$$$$; \
	trap 'rm -f "$$crust_mode_tmp"' 0; \
	printf '%s\n' '$(AMALGAMATION)' > "$$crust_mode_tmp"; \
	if ! cmp -s "$$crust_mode_tmp" '$@'; then mv "$$crust_mode_tmp" '$@'; fi

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

GENERICS = stages/generics/model.crs stages/generics/base.crs stages/generics/definition.crs stages/generics/key.crs stages/generics/types.crs stages/generics/clone.crs stages/generics/instances.crs
GENERICS_SOURCE = $(READER) stages/generics/source_model.crs stages/generics/read.crs stages/generics/source_key.crs stages/generics/normalize.crs stages/generics/source.crs

$(BUILD)/generics-exports: $(BUILD)/crust stages/modules/library.crs stages/modules/exports.crs stages/generics/api.crs stages/generics/source_api.crs stages/generics/source_extension.crs Makefile
	$< stages/modules/exports.crs stages/generics/api.crs stages/generics/source_api.crs stages/generics/source_extension.crs > $@.tmp
	mv $@.tmp $@

$(BUILD)/crust-generics-library.o: $(BUILD)/crust-c $(GENERICS) $(GENERICS_SOURCE) $(BUILD)/generics-exports Makefile
	crust_exports=$$(cat $(BUILD)/generics-exports) && $< --library --object $$crust_exports --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ api/crust0.crs $(GENERICS) $(GENERICS_SOURCE)

$(BUILD)/crust-generics-library.so: $(BUILD)/crust-generics-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $< $(LDFLAGS) -o $@

GENERIC_OWNERSHIP = $(OWNERSHIP_LIBRARY) $(GENERICS) $(filter-out $(READER),$(GENERICS_SOURCE)) stages/generics/ownership/model.crs stages/generics/ownership/read.crs stages/generics/ownership/clone.crs stages/generics/ownership/domains.crs stages/generics/ownership/domains_seal.crs stages/generics/ownership/arguments.crs stages/generics/ownership/proof.crs stages/generics/ownership/check.crs stages/generics/ownership/program.crs stages/generics/ownership/library_model.crs stages/generics/ownership/library_bindings.crs stages/generics/ownership/library_bytes.crs stages/generics/ownership/library.crs

$(BUILD)/crust-ownership-generics-test: $(BUILD)/crust-c $(GENERIC_OWNERSHIP) tests/ownership_input.crs tests/ownership_generics_driver.crs Makefile
	$< -o $@ $(GENERIC_OWNERSHIP) tests/ownership_input.crs tests/ownership_generics_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-ownership-generics-library.o: $(BUILD)/crust-c $(GENERIC_OWNERSHIP) Makefile
	$< --library --object --export ownership_generics_program --export og_init --export og_read --export og_read_range --export og_prove --export og_check --export og_destroy --export og_library_publish --export og_library_import --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(GENERIC_OWNERSHIP)

$(BUILD)/crust-ownership-generics-library.so: $(BUILD)/crust-ownership-generics-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $< $(LDFLAGS) -o $@

.PHONY: ownership-generics-stage check-ownership-generics
ownership-generics-stage: $(BUILD)/crust-ownership-generics-library.so

$(BUILD)/crust-ownership-generics-clone: $(BUILD)/crust-c $(GENERIC_OWNERSHIP) tests/ownership_generics_clone.crs Makefile
	$< -o $@ $(GENERIC_OWNERSHIP) tests/ownership_generics_clone.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

check-ownership-generics: all c-stage ownership-generics-stage $(BUILD)/crust-ownership-generics-test $(BUILD)/crust-ownership-generics-clone
	$(BUILD)/crust-ownership-generics-clone
	python3 tests/ownership_generics.py --build $(BUILD) --sanitize
	python3 tests/generics_ownership_imports.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/ownership_generics_alloc.py --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION) --sources $(GENERIC_OWNERSHIP)

.PHONY: generics-stage check-generics
generics-stage: $(BUILD)/crust-generics-library.so

check-generics: all c-stage generics-stage
	python3 tests/generics.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/generics_source.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

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

$(BUILD)/crust-ownership-test: $(BUILD)/crust-c $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_driver.crs Makefile
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-ownership-library.o: $(BUILD)/crust-c $(OWNERSHIP_LIBRARY) Makefile
	$< --library --object --export ownership_program --export ownership_publish --export ownership_import_program --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(OWNERSHIP_LIBRARY)

$(BUILD)/crust-ownership-library.so: $(BUILD)/crust-ownership-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $< $(LDFLAGS) -o $@

$(BUILD)/crust-ownership-erasure: $(BUILD)/crust-c $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_erasure.crs Makefile
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_erasure.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-ownership-import-test: $(BUILD)/crust-c $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_import_driver.crs Makefile
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_import_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

.PHONY: check-ownership-imports
check-ownership-imports: $(BUILD)/crust-ownership-import-test
	python3 tests/ownership_imports.py --build $(BUILD)

.PHONY: ownership-stage check-ownership check-ownership-alloc
ownership-stage: $(BUILD)/crust-ownership-test $(BUILD)/crust-ownership-library.so

check-ownership: all ownership-stage $(BUILD)/crust-ownership-erasure $(BUILD)/crust-ownership-import-test
	python3 tests/ownership.py --build $(BUILD)
	python3 tests/ownership_index.py --build $(BUILD)
	python3 tests/ownership_views.py --build $(BUILD)
	python3 tests/ownership_native.py --build $(BUILD)

check-ownership-alloc: all c-stage
	python3 tests/ownership_alloc.py --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION) --sources $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_alloc.crs

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

$(BUILD)/kind_composition: $(BUILD)/crust-c $(RESOURCE_LIBRARY) tests/kind_wrapper.crs tests/kind_composition.crs Makefile
	$< -o $@ $(RESOURCE_LIBRARY) tests/kind_wrapper.crs tests/kind_composition.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

check-resources: all resource-stage $(BUILD)/kind_composition
	python3 tests/resources.py --build $(BUILD)
	python3 tests/resource_returns.py --build $(BUILD)
	python3 tests/extension_kinds.py --build $(BUILD)

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
	python3 tests/abi.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)' --amalgamation $(AMALGAMATION)

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

$(BUILD)/ownership-clock.o: benchmarks/ownership/clock_linux_x64.c | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -c $< -o $@

$(BUILD)/ownership-cost: $(BUILD)/crust-c $(OWNERSHIP_LIBRARY) tests/ownership_input.crs benchmarks/ownership/driver.crs $(BUILD)/ownership-clock.o
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs benchmarks/ownership/driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/ownership-clock.o --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

.PHONY: ownership-benchmark-config
ownership-benchmark-config:
	@printf '%s\n' 'CC=$(CC) CFLAGS=$(CFLAGS) LDFLAGS=$(LDFLAGS) AMALGAMATION=$(AMALGAMATION)'
