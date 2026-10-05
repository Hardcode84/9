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
C_LIBRARY = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources c/package.crs),$(error Stage package query failed))
RESOURCE_EXPORTS = $(or $(shell python3 tests/prepare.py --build $(BUILD) --exports resources/package.crs),$(error Stage package query failed))
OVERLOAD_EXPORTS = $(or $(shell python3 tests/prepare.py --build $(BUILD) --exports overload/package.crs),$(error Stage package query failed))
C_STAGE = $(C_LIBRARY) stages/c/main.crs
ASM_LIBRARY = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources asm/package.crs),$(error Stage package query failed))
READER = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources reader/package.crs),$(error Stage package query failed))
HIGHLIGHT = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources highlight/package.crs),$(error Stage package query failed))
CCN = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources ccn/package.crs),$(error Stage package query failed))
SOURCE = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources source/package.crs),$(error Stage package query failed))
RESOURCE_LIBRARY = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources resources/package.crs),$(error Stage package query failed))
OWNERSHIP_LIBRARY = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources ownership/package.crs),$(error Stage package query failed))
OVERLOAD = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources overload/local-sources.crs),$(error Stage package query failed))
OVERLOAD_LIBRARY = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources overload/package.crs),$(error Stage package query failed))
OVERLOAD_RESOURCE_LIBRARY = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources overload/resources-package.crs),$(error Stage package query failed))

.PHONY: all clean check witness api test-tools check-highlight check-ccn check-vscode check-overload check-overload-alloc check-c check-stage check-examples check-resources check-resource-alloc check-reader check-modules check-native check-asm check-cache
.PHONY: amalgamate check-amalgamation FORCE
all: $(BUILD)/crust

.PHONY: test-tools
test-tools: $(BUILD)/crust $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a $(BUILD)/libcrust0_run.a
	python3 tests/prepare.py --build $(BUILD) --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

$(BUILD)/crust-c $(BUILD)/crust-c-seed $(BUILD)/crust-highlight $(BUILD)/crust-ccn $(BUILD)/crust-resource $(BUILD)/crust-overload $(BUILD)/crust-overload-resource $(BUILD)/crust-asm-library.o: test-tools

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

$(BUILD)/libcrust_asm.a: $(BUILD)/crust-asm-library.o
	$(AR) rcs $@ $^

GENERIC_OWNERSHIP = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources generics/ownership/package.crs),$(error Stage package query failed))

$(BUILD)/crust-ownership-generics-test: $(BUILD)/crust-c tests/ownership_input.crs tests/ownership_generics_driver.crs Makefile
	$< -o $@ $(GENERIC_OWNERSHIP) tests/ownership_input.crs tests/ownership_generics_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

.PHONY: test-tools check-ownership-generics

$(BUILD)/crust-ownership-generics-clone: $(BUILD)/crust-c tests/ownership_generics_clone.crs Makefile
	$< -o $@ $(GENERIC_OWNERSHIP) tests/ownership_generics_clone.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

check-ownership-generics: all test-tools $(BUILD)/crust-ownership-generics-test $(BUILD)/crust-ownership-generics-clone
	$(BUILD)/crust-ownership-generics-clone
	python3 tests/ownership_generics.py --build $(BUILD) --sanitize
	python3 tests/generics_ownership_imports.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/ownership_generics_alloc.py --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION) --sources $(GENERIC_OWNERSHIP)

.PHONY: test-tools check-generics

check-generics: all test-tools
	python3 tests/generics.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/generics_source.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

UNION_LIBRARY = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources union/package.crs),$(error Stage package query failed))

.PHONY: test-tools check-union check-union-alloc

$(BUILD)/crust-union-test: $(BUILD)/crust-c api/crust0_x64.crs api/crust0_eval.crs tests/union_alloc.crs tests/union_driver.crs $(BUILD)/libcrust0_run.a $(BUILD)/libcrust_asm.a
	$< -o $@ $(UNION_LIBRARY) api/crust0_x64.crs api/crust0_eval.crs tests/union_alloc.crs tests/union_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0_run.a --ldflag=-ldl --ldflag=-lffi --ldflag $(BUILD)/libcrust_asm.a --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

check-union: all test-tools $(BUILD)/crust-union-test
	python3 tests/union.py --build $(BUILD)

check-union-alloc: all test-tools $(BUILD)/crust-union-test
	python3 tests/union.py --build $(BUILD) --sanitize-stage

check-highlight: all test-tools
	python3 stages/highlight/test.py --build $(BUILD)

check-ccn: all test-tools
	python3 tests/ccn.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-vscode: test-tools $(BUILD)/crust
	CRUST_HIGHLIGHT=$(abspath $(BUILD))/crust-highlight CRUST_LAUNCHER=$(abspath $(BUILD))/crust bun test ./editors/vscode

$(BUILD)/crust-ownership-test: $(BUILD)/crust-c tests/ownership_input.crs tests/ownership_driver.crs Makefile
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-ownership-erasure: $(BUILD)/crust-c tests/ownership_input.crs tests/ownership_erasure.crs Makefile
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_erasure.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-ownership-import-test: $(BUILD)/crust-c tests/ownership_input.crs tests/ownership_import_driver.crs Makefile
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_import_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

.PHONY: check-ownership-imports
check-ownership-imports: $(BUILD)/crust-ownership-import-test
	python3 tests/ownership_imports.py --build $(BUILD)

.PHONY: test-tools check-ownership check-ownership-alloc check-ownership-ergonomics

check-ownership: all test-tools $(BUILD)/crust-ownership-test $(BUILD)/crust-ownership-erasure $(BUILD)/crust-ownership-import-test
	python3 tests/ownership.py --build $(BUILD)
	python3 tests/ownership_index.py --build $(BUILD)
	python3 tests/ownership_views.py --build $(BUILD)
	python3 tests/ownership_native.py --build $(BUILD)

check-ownership-ergonomics: all test-tools $(BUILD)/crust-ownership-test
	python3 tests/ownership_ergonomics.py --build $(BUILD)

check-ownership-alloc: all test-tools
	python3 tests/ownership_alloc.py --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION) --sources $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_alloc.crs

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

check: all $(BUILD)/crust0 $(BUILD)/core_test $(BUILD)/arena_test $(BUILD)/read_test $(BUILD)/check_test $(BUILD)/host_test $(BUILD)/parallel_test $(BUILD)/x64_test $(BUILD)/eval_test
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

check-c: test-tools
	python3 tests/run.py --backend c --compiler $(BUILD)/crust-c --cc '$(CC)' --assembler '$(AS) $(ASFLAGS)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/c_body.py --build $(BUILD) --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-reader: all test-tools
	python3 stages/reader/test.py --build $(BUILD) --cc '$(CC)' --ldflags='$(LDFLAGS)'

$(BUILD)/kind_composition: $(BUILD)/crust-c tests/kind_wrapper.crs tests/kind_composition.crs Makefile
	$< -o $@ $(RESOURCE_LIBRARY) tests/kind_wrapper.crs tests/kind_composition.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

check-resources: all test-tools $(BUILD)/kind_composition
	python3 tests/resources.py --build $(BUILD)
	python3 tests/resource_returns.py --build $(BUILD)
	python3 tests/extension_kinds.py --build $(BUILD)

$(BUILD)/composition-test: $(BUILD)/crust-c   examples/composition/build.crs tests/composition_driver.crs Makefile
	$< -o $@ $(OWNERSHIP_LIBRARY) $(OVERLOAD) examples/composition/build.crs tests/composition_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

check-overload: all test-tools $(BUILD)/composition-test
	python3 tests/overload.py --build $(BUILD)
	python3 tests/overload_resources.py --build $(BUILD)
	python3 tests/overload_hooks.py --build $(BUILD) --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/nesting.py --build $(BUILD)
	python3 tests/composition.py --build $(BUILD)

check-overload-alloc: all test-tools
	python3 tests/overload_alloc.py --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION)

check-resource-alloc: all test-tools
	python3 tests/resources_alloc.py --build $(BUILD) --cc '$(CC)' --amalgamation $(AMALGAMATION)

check-examples: all test-tools
	python3 tests/source_order.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)' --group examples

check-modules: all test-tools
	python3 tests/modules.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-asm: all test-tools
	python3 tests/asm.py --build $(BUILD) --cc '$(CC)' --ldflags='$(LDFLAGS)'

check-cache: $(BUILD)/crust
	python3 tests/stage_packages.py --build $(BUILD)
	python3 tests/cache.py --build $(BUILD)

check-native: all test-tools
	python3 tests/native.py --build $(BUILD)

PARALLEL = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources parallel/package.crs),$(error Stage package query failed))

.PHONY: test-tools check-parallel

check-parallel: all test-tools
	python3 tests/parallel.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

clean:
	rm -rf $(BUILD)

-include $(wildcard $(BUILD)/*.d)

$(BUILD)/ownership-clock.o: benchmarks/ownership/clock_linux_x64.c | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -c $< -o $@

$(BUILD)/ownership-cost: $(BUILD)/crust-c tests/ownership_input.crs benchmarks/ownership/driver.crs $(BUILD)/ownership-clock.o
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs benchmarks/ownership/driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/ownership-clock.o --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

.PHONY: ownership-benchmark-config
ownership-benchmark-config:
	@printf '%s\n' 'CC=$(CC) CFLAGS=$(CFLAGS) LDFLAGS=$(LDFLAGS) AMALGAMATION=$(AMALGAMATION)'

check-stage: all test-tools
	python3 tests/source_order.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/abi.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)' --amalgamation $(AMALGAMATION)
