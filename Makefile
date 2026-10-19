# SPDX-License-Identifier: Apache-2.0

CC ?= cc
AR ?= ar
AS ?= as
ASFLAGS ?= --64
CFLAGS ?= -O2 -g
STRICT = -std=c99 -pedantic-errors -Wall -Wextra -Werror -Wstrict-prototypes -Wmissing-prototypes -Wshadow -Wvla
PROFILE ?= linux_x64
AMALGAMATION ?= 1
ifeq ($(PROFILE),linux_x64)
BUILD ?= build
PLATFORM = posix
EXE =
HOST_EXTRA =
RUN_LDFLAGS = -rdynamic
RUN_LIBS = -ldl -lffi
API_ROOT = .
SEED_IMPORT =
else ifeq ($(PROFILE),windows_x64)
BUILD ?= build/windows
PLATFORM = windows
EXE = .exe
HOST_EXTRA = $(BUILD)/windows_io.o
# The seed owns the thread stack required by the default evaluator depth limit.
RUN_LDFLAGS = -municode -Wl,--stack,8388608 -Wl,--export-all-symbols -Wl,--out-implib,$(BUILD)/crust.exe.a
RUN_LIBS = -lffi -lbcrypt
API_ROOT = $(BUILD)/profile
SEED_IMPORT = $(BUILD)/crust.exe.a
CPPFLAGS += -I$(API_ROOT)/include
WINDOWS_GOALS = all clean api amalgamate fetch-llvm-release fetch-llvm-main check-llvm-fetch check-windows check-windows-build check-windows-bootstrap check-windows-cache check-windows-tools check-windows-llvm check-windows-asm check-windows-ownership check-windows-shader check-windows-shared-core check-windows-shared-split-core check-windows-shared-ownership check-windows-shared-tooling check-windows-shared-llvm
ifneq ($(filter-out $(WINDOWS_GOALS) $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a $(BUILD)/libcrust0_run.a,$(MAKECMDGOALS)),)
$(error This target is not available for Windows; use the check-windows targets)
endif
else
$(error Unsupported PROFILE '$(PROFILE)'; expected linux_x64 or windows_x64)
endif
CPPFLAGS += -Iinclude $(FFI_CFLAGS)
ifneq ($(PROFILE),windows_x64)
ifneq ($(filter check-windows check-windows-build check-windows-bootstrap check-windows-cache check-windows-tools check-windows-llvm check-windows-asm check-windows-ownership check-windows-shader check-windows-shared-core check-windows-shared-split-core check-windows-shared-ownership check-windows-shared-tooling check-windows-shared-llvm,$(MAKECMDGOALS)),)
$(error check-windows requires PROFILE=windows_x64)
endif
endif
ifeq ($(AMALGAMATION),1)
CORE = $(BUILD)/crust0_amalg.o $(BUILD)/profile_$(PROFILE).o
else ifeq ($(AMALGAMATION),0)
CORE = $(BUILD)/core.o $(BUILD)/read.o $(BUILD)/check.o $(BUILD)/profile_$(PROFILE).o
else
$(error Unsupported AMALGAMATION '$(AMALGAMATION)'; expected 0 or 1)
endif
RUNNER = $(BUILD)/eval.o $(BUILD)/eval_ffi.o $(BUILD)/run.o $(BUILD)/run_$(PLATFORM).o
HOST = $(BUILD)/host.o $(BUILD)/host_$(PLATFORM).o $(HOST_EXTRA)
PRELUDE = $(addprefix $(API_ROOT)/,api/crust0.crs api/crust0_host.crs api/crust0_eval.crs api/crust0_run.crs) stages/host_$(PLATFORM).crs stages/host.crs
API_HEADERS = $(addprefix include/,$(addsuffix .h,crust0 crust0_host crust0_x64 crust0_stage crust0_eval crust0_run))
API_GENERATED = $(addprefix $(API_ROOT)/,$(patsubst include/%.h,api/%.crs,$(API_HEADERS)) include/crust0_abi.h include/host_symbols.inc stages/asm/model.crs)
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
all: $(BUILD)/crust$(EXE) $(SEED_IMPORT)

.PHONY: fetch-llvm-release fetch-llvm-main check-llvm-fetch
fetch-llvm-release:
	python3 tools/fetch_llvm.py release --directory '$(BUILD)/toolchains/llvm'

fetch-llvm-main:
	python3 tools/fetch_llvm.py main --directory '$(BUILD)/toolchains/llvm'

check-llvm-fetch:
	python3 tests/llvm_fetch.py

.PHONY: test-tools
test-tools: $(BUILD)/crust $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a $(BUILD)/libcrust0_run.a
	python3 tests/prepare.py --build $(BUILD) --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

$(BUILD)/crust-c $(BUILD)/crust-c-seed $(BUILD)/crust-highlight $(BUILD)/crust-ccn $(BUILD)/crust-resource $(BUILD)/crust-overload $(BUILD)/crust-overload-resource $(BUILD)/crust-asm-library.o: test-tools

$(API_GENERATED) &: tools/api.py $(API_HEADERS)
	python3 tools/api.py --profile $(PROFILE) --output-root $(API_ROOT)

$(BUILD)/run_$(PLATFORM).o: $(API_ROOT)/include/crust0_abi.h $(API_ROOT)/include/host_symbols.inc

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
	printf '%s\n' '$(PROFILE) $(AMALGAMATION)' > "$$crust_mode_tmp"; \
	if ! cmp -s "$$crust_mode_tmp" '$@'; then mv "$$crust_mode_tmp" '$@'; fi

$(BUILD)/crust$(EXE) $(BUILD)/crust0 $(BUILD)/libcrust0.a: $(BUILD)/core-mode

$(HOST): $(BUILD)/%.o: runtime/%.c include/crust0_host.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -MMD -MP -c $< -o $@

$(BUILD)/crust0: $(BUILD)/crust-asm-library.o $(CORE) $(BUILD)/driver.o $(BUILD)/driver_posix.o $(HOST)
	$(CC) $(CFLAGS) $(filter-out $(BUILD)/core-mode,$^) $(LDFLAGS) -o $@

$(BUILD)/prelude.inc: tools/prelude.py $(PRELUDE) | $(BUILD)
	python3 tools/prelude.py $@ --profile $(PROFILE) --api-root $(API_ROOT)

$(BUILD)/run_main.o: CPPFLAGS += -I$(BUILD)
$(BUILD)/run_main.o: $(BUILD)/prelude.inc

$(BUILD)/crust$(EXE) $(SEED_IMPORT) &: $(CORE) $(RUNNER) $(BUILD)/run_main.o $(BUILD)/run_entry_$(PLATFORM).o $(HOST) Makefile
	$(CC) $(CFLAGS) $(filter-out $(BUILD)/core-mode Makefile,$^) $(RUN_LDFLAGS) $(LDFLAGS) $(FFI_LDFLAGS) $(RUN_LIBS) -o $(BUILD)/crust$(EXE)

$(BUILD)/libcrust0_run.a: $(RUNNER)
	rm -f $@
	$(AR) rcs $@ $^

$(BUILD)/libcrust0.a: $(CORE) Makefile
	rm -f $@
	$(AR) rcs $@ $(CORE)

$(BUILD)/libcrust0_host.a: $(HOST)
	$(AR) rcs $@ $^

.PHONY: check-windows check-windows-build check-windows-bootstrap
check-windows-build: all $(BUILD)/windows_seed.exe $(BUILD)/windows_library.dll $(BUILD)/windows_limit.exe

$(BUILD)/windows_limit.exe: tests/windows_limit.c | $(BUILD)
	$(CC) $(CFLAGS) $(STRICT) -municode $< $(LDFLAGS) -o $@

$(BUILD)/windows_library.dll: tests/windows_library.c tests/native.c $(API_ROOT)/include/crust0_abi.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -shared -Wl,--export-all-symbols tests/windows_library.c tests/native.c $(LDFLAGS) -o $@

$(BUILD)/windows_seed.exe: tests/windows_seed.c $(CORE) $(RUNNER) $(HOST) $(BUILD)/driver_windows.o $(BUILD)/core-mode
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $(filter-out $(BUILD)/core-mode,$^) $(LDFLAGS) $(FFI_LDFLAGS) -lffi -lbcrypt -o $@

check-windows: check-windows-build
	python3 tests/windows.py --build $(BUILD) --cc '$(CC)'

$(BUILD)/windows_process.exe: tests/windows_process.c Makefile | $(BUILD)
	$(CC) $(CFLAGS) $(STRICT) -municode $< $(LDFLAGS) -o $@

check-windows-bootstrap: all $(BUILD)/windows_limit.exe $(BUILD)/windows_process.exe
	python3 tests/windows_bootstrap.py --build $(BUILD)

.PHONY: check-windows-cache
$(BUILD)/windows_cache_fixture.exe: tests/windows_cache_fixture.c $(API_ROOT)/include/crust0_abi.h Makefile | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $< -municode $(LDFLAGS) -o $@

$(BUILD)/windows_cache_fixture.dll: tests/windows_cache_fixture.c $(API_ROOT)/include/crust0_abi.h Makefile | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $< -shared -Wl,--export-all-symbols $(LDFLAGS) -o $@

check-windows-cache: all $(BUILD)/windows_limit.exe $(BUILD)/windows_process.exe $(BUILD)/windows_cache_fixture.exe $(BUILD)/windows_cache_fixture.dll
	python3 tests/windows_cache.py --build $(BUILD)

.PHONY: check-windows-tools check-windows-llvm check-windows-asm check-windows-ownership
check-windows-tools: all $(BUILD)/windows_limit.exe $(BUILD)/windows_library.dll
	python3 tests/windows_tools.py --build $(BUILD)

check-windows-llvm: all $(BUILD)/windows_limit.exe $(BUILD)/windows_library.dll
	python3 tests/windows_backends.py --build $(BUILD) --backend llvm --llvm "$(CRUST_LLVM_DIRECTORY)"

check-windows-asm: all $(BUILD)/windows_limit.exe $(BUILD)/windows_library.dll
	python3 tests/windows_backends.py --build $(BUILD) --backend asm

check-windows-ownership: all $(BUILD)/windows_limit.exe
	python3 tests/windows_ownership.py --build $(BUILD)

.PHONY: check-windows-shader
check-windows-shader: all $(BUILD)/windows_limit.exe $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a
	python3 tests/shader.py --profile windows_x64 --build $(BUILD) --cc '$(CC)' --llvm '$(LLVM_DIRECTORY)' --spirv-tools '$(SPIRV_TOOLS)' --vulkan-include '$(VULKAN_INCLUDE)' --vulkan-library '$(VULKAN_LIBRARY)' $(if $(WGSL_VALIDATOR),--wgsl-validator '$(WGSL_VALIDATOR)')

$(BUILD)/libcrust_asm.a: $(BUILD)/crust-asm-library.o
	$(AR) rcs $@ $^

GENERIC_OWNERSHIP = $(or $(shell python3 tests/prepare.py --build $(BUILD) --sources generics/ownership/package.crs),$(error Stage package query failed))

# Native test drivers embed stage sources. Rebuild after source package preparation.
$(BUILD)/crust-ownership-generics-test: $(BUILD)/crust-c tests/ownership_input.crs tests/ownership_generics_driver.crs Makefile test-tools
	$< -o $@ $(GENERIC_OWNERSHIP) tests/ownership_input.crs tests/ownership_generics_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

.PHONY: test-tools check-ownership-generics

$(BUILD)/crust-ownership-generics-clone: $(BUILD)/crust-c tests/ownership_generics_clone.crs Makefile test-tools
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

.PHONY: test-tools check-union check-union-alloc

$(BUILD)/crust-union-test: $(BUILD)/crust-c api/crust0_x64.crs api/crust0_eval.crs tests/union_alloc.crs tests/union_driver.crs $(BUILD)/libcrust0_run.a $(BUILD)/libcrust_asm.a test-tools
	python3 tests/prepare.py --build $(BUILD) --compile-package tests/union-package.crs --output $@ --cflags='$(CFLAGS)' --ldflags='$(BUILD)/libcrust0_run.a -ldl -lffi $(BUILD)/libcrust_asm.a $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a $(LDFLAGS)'

check-union: all test-tools $(BUILD)/crust-union-test
	python3 tests/union.py --build $(BUILD)

check-union-alloc: all test-tools $(BUILD)/crust-union-test
	python3 tests/union.py --build $(BUILD) --sanitize-stage

.PHONY: check-format
check-format: all test-tools
	python3 tests/format.py --build $(BUILD)

check-highlight: all test-tools
	python3 stages/highlight/test.py --build $(BUILD)

check-ccn: all test-tools
	python3 tests/ccn.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-vscode: test-tools $(BUILD)/crust
	CRUST_HIGHLIGHT=$(abspath $(BUILD))/crust-highlight CRUST_LAUNCHER=$(abspath $(BUILD))/crust bun test ./editors/vscode

$(BUILD)/crust-ownership-test: $(BUILD)/crust-c tests/ownership_input.crs tests/ownership_driver.crs Makefile test-tools
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-ownership-erasure: $(BUILD)/crust-c tests/ownership_input.crs tests/ownership_erasure.crs Makefile test-tools
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs tests/ownership_erasure.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/crust-ownership-import-test: $(BUILD)/crust-c tests/ownership_input.crs tests/ownership_import_driver.crs Makefile test-tools
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
	python3 tests/ownership_arrays.py --build $(BUILD)

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

$(BUILD)/eval_test: tests/eval_test.c tests/eval_lookup_posix.c tests/native.c $(BUILD)/eval.o $(BUILD)/eval_ffi.o $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $^ -rdynamic $(LDFLAGS) -ldl -lffi -o $@

api:
	python3 tools/api.py --profile $(PROFILE) --output-root $(API_ROOT)

check-amalgamation:
	python3 tools/check_amalgamation.py --cc '$(CC)' --cflags='$(CFLAGS) $(STRICT)'

check: all $(BUILD)/crust0 $(BUILD)/core_test $(BUILD)/arena_test $(BUILD)/read_test $(BUILD)/check_test $(BUILD)/host_test $(BUILD)/parallel_test $(BUILD)/x64_test $(BUILD)/eval_test
	$(BUILD)/core_test
	$(BUILD)/arena_test
	$(BUILD)/read_test
	$(BUILD)/check_test
	$(BUILD)/host_test $(BUILD)/host-test.tmp /dev/full
	$(BUILD)/parallel_test
	$(BUILD)/x64_test
	python3 tests/eval.py --build $(BUILD)
	python3 tools/api.py --check
	python3 tests/run.py --compiler $(BUILD)/crust0 --cc '$(CC)' --assembler '$(AS) $(ASFLAGS)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-c: test-tools
	python3 tests/run.py --backend c --compiler $(BUILD)/crust-c --cc '$(CC)' --assembler '$(AS) $(ASFLAGS)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/c_body.py --build $(BUILD) --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-reader: all test-tools
	python3 stages/reader/test.py --build $(BUILD) --cc '$(CC)' --ldflags='$(LDFLAGS)'

$(BUILD)/kind_composition: $(BUILD)/crust-c tests/kind_wrapper.crs tests/kind_composition.crs Makefile test-tools
	$< -o $@ $(RESOURCE_LIBRARY) tests/kind_wrapper.crs tests/kind_composition.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/resource-backends: $(BUILD)/crust-c tests/resource_backends.crs tests/resource_backends_package.crs tests/ownership_input.crs api/crust0_eval.crs test-tools
	python3 tests/prepare.py --build $(BUILD) --compile-package tests/resource_backends_package.crs --output $@ --cflags='$(CFLAGS)' --ldflags='$(BUILD)/libcrust0_run.a $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a -ldl -lffi $(LDFLAGS)'

check-resources: all test-tools $(BUILD)/kind_composition $(BUILD)/resource-backends
	python3 tests/resources.py --build $(BUILD)
	python3 tests/resource_returns.py --build $(BUILD)
	python3 tests/resource_backends.py --build $(BUILD)
	python3 tests/extension_kinds.py --build $(BUILD)

$(BUILD)/composition-test: $(BUILD)/crust-c   examples/composition/build.crs tests/composition_driver.crs Makefile test-tools
	$< -o $@ $(OWNERSHIP_LIBRARY) $(OVERLOAD) examples/composition/build.crs tests/composition_driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

check-overload: all test-tools $(BUILD)/crust0 $(BUILD)/composition-test
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

check-asm: all test-tools $(BUILD)/crust0
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

$(BUILD)/ownership-cost: $(BUILD)/crust-c tests/ownership_input.crs benchmarks/ownership/driver.crs $(BUILD)/ownership-clock.o test-tools
	$< -o $@ $(OWNERSHIP_LIBRARY) tests/ownership_input.crs benchmarks/ownership/driver.crs $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/ownership-clock.o --ldflag $(BUILD)/libcrust0.a --ldflag $(BUILD)/libcrust0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

.PHONY: ownership-benchmark-config
ownership-benchmark-config:
	@printf '%s\n' 'CC=$(CC) CFLAGS=$(CFLAGS) LDFLAGS=$(LDFLAGS) AMALGAMATION=$(AMALGAMATION)'

check-stage: all test-tools
	python3 tests/source_order.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/abi.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)' --amalgamation $(AMALGAMATION)

.PHONY: check-llvm

$(BUILD)/llvm-alloc-wrap.o: tests/c_stage_alloc.c | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -c $< -o $@

$(BUILD)/llvm-test-driver: $(BUILD)/crust-c tests/llvm_driver.crs tests/llvm_alloc.crs tests/llvm_driver_package.crs $(BUILD)/llvm-alloc-wrap.o test-tools
	python3 tests/prepare.py --build $(BUILD) --compile-package tests/llvm_driver_package.crs --output $@ --cflags='$(CFLAGS)' --ldflags='$(BUILD)/llvm-alloc-wrap.o -Wl,--wrap=crust0_host_alloc -Wl,--wrap=crust0_host_free $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a $(LDFLAGS)'

check-llvm: all test-tools $(BUILD)/llvm-test-driver $(BUILD)/resource-backends
	python3 tests/llvm.py --build $(BUILD)
	python3 tests/llvm_packages.py --build $(BUILD)

.PHONY: check-tutorials
check-tutorials: all test-tools
	python3 tests/tutorials.py --build $(BUILD)

.PHONY: check-shader
check-shader: all test-tools
	python3 tests/prepare.py --build $(BUILD) --compile-package tests/shader_alloc_package.crs --output $(BUILD)/shader-alloc --cflags='$(CFLAGS)' --ldflags='$(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a $(LDFLAGS)'
	python3 tests/shader.py --build $(BUILD) --cc '$(CC)' --llvm '$(LLVM_DIRECTORY)' --spirv-tools '$(SPIRV_TOOLS)' $(if $(VULKAN_INCLUDE),--vulkan-include '$(VULKAN_INCLUDE)') $(if $(WGSL_VALIDATOR),--wgsl-validator '$(WGSL_VALIDATOR)')

.PHONY: check-windows-shared-core check-windows-shared-split-core check-windows-shared-ownership check-windows-shared-tooling check-windows-shared-llvm
check-windows-shared-core check-windows-shared-split-core check-windows-shared-ownership check-windows-shared-tooling check-windows-shared-llvm: all $(BUILD)/windows_limit.exe $(BUILD)/libcrust0.a $(BUILD)/libcrust0_host.a $(BUILD)/libcrust0_run.a
	$(BUILD)/windows_limit.exe python3 tests/windows_shared.py --build $(BUILD) --suite $(patsubst check-windows-shared-%,%,$@) --amalgamation $(AMALGAMATION) --ldflags='$(LDFLAGS) $(FFI_LDFLAGS)'
