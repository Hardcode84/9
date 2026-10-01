CC ?= cc
AR ?= ar
AS ?= as
ASFLAGS ?= --64
CFLAGS ?= -O2 -g
CPPFLAGS += -Iinclude
STRICT = -std=c99 -pedantic-errors -Wall -Wextra -Werror -Wstrict-prototypes -Wmissing-prototypes -Wshadow -Wvla
BUILD ?= build
CORE = $(BUILD)/core.o $(BUILD)/read.o $(BUILD)/check.o
BACKEND = $(BUILD)/x64.o
RUNNER = $(BUILD)/eval.o $(BUILD)/run.o
PRELUDE = api/rmd0.rmd api/rmd0_host.rmd api/rmd0_eval.rmd api/rmd0_run.rmd stages/host.rmd
C_LIBRARY = api/rmd0.rmd api/rmd0_host.rmd api/rmd0_stage.rmd stages/c/model.rmd stages/c/base.rmd stages/c/types.rmd stages/c/emit.rmd stages/c/driver.rmd stages/c/program.rmd
C_STAGE = $(C_LIBRARY) stages/c/main.rmd
C_EXPORTS = c_backend_build c_program c_backend_build_with_body c_stage_init c_stage_destroy c_emit c_emit_with_body c_error c_alloc c_map_get c_map_set c_text c_number c_quote c_expression c_place c_statement c_value c_symbol c_global c_type_name c_binding c_temp c_address_temp
READER = stages/reader/model.rmd stages/reader/lex.rmd stages/reader/parse.rmd
RESOURCE = stages/resources/model.rmd stages/resources/base.rmd stages/resources/read.rmd stages/resources/types.rmd stages/resources/constants.rmd stages/resources/state.rmd stages/resources/cleanup.rmd stages/resources/places.rmd stages/resources/expr.rmd stages/resources/control.rmd stages/resources/emit.rmd stages/resources/program.rmd stages/resources/build.rmd
RESOURCE_LIBRARY = $(C_LIBRARY) $(READER) $(RESOURCE)
RESOURCE_EXPORTS = resource_build resource_program rs_init rs_read rs_prepare rs_c_body rs_source_import
OVERLOAD = stages/overload/model.rmd stages/overload/base.rmd stages/overload/types.rmd stages/overload/collect.rmd stages/overload/resolve.rmd stages/overload/read.rmd stages/overload/program.rmd
OVERLOAD_LIBRARY = $(C_LIBRARY) $(READER) $(OVERLOAD)
OVERLOAD_EXPORTS = overload_build overload_program ov_init ov_read ov_prepare ov_collect ov_resolve ov_mangle ov_alloc ov_error ov_put ov_type ov_intern ov_global ov_function_syntax ov_select ov_same ov_encode_type ov_text ov_bytes ov_number ov_part ov_expression ov_statement ov_standard_expression ov_standard_statement ov_scope ov_leave_scope ov_lookup ov_bind ov_block ov_field_type ov_driver_build ov_check
OVERLOAD_RESOURCE_LIBRARY = $(RESOURCE_LIBRARY) $(OVERLOAD) stages/overload/resources.rmd stages/overload/resource_program.rmd
OVERLOAD_RESOURCE_EXPORTS = $(RESOURCE_EXPORTS) $(OVERLOAD_EXPORTS) overload_resource_build overload_resource_program ov_resources_init ov_resources_read ov_resources_prepare ov_resources_check

.PHONY: all clean check witness api c-stage resource-stage overload-stage check-overload check-overload-alloc check-c check-stage check-examples check-resources check-resource-alloc check-reader
all: $(BUILD)/rmd $(BUILD)/rmd0 $(BUILD)/librmd0.a $(BUILD)/librmd0_host.a $(BUILD)/librmd0_run.a

$(BUILD):
	mkdir -p $@

$(BUILD)/%.o: src/%.c include/rmd0.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -MMD -MP -c $< -o $@

$(BUILD)/host.o: runtime/host.c include/rmd0_host.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -MMD -MP -c $< -o $@

$(BUILD)/rmd0: $(CORE) $(BACKEND) $(BUILD)/driver.o $(BUILD)/host.o
	$(CC) $(CFLAGS) $^ $(LDFLAGS) -o $@

$(BUILD)/prelude.inc: tools/prelude.py $(PRELUDE) | $(BUILD)
	python3 tools/prelude.py $@

$(BUILD)/run_main.o: CPPFLAGS += -I$(BUILD)
$(BUILD)/run_main.o: $(BUILD)/prelude.inc

$(BUILD)/rmd: $(CORE) $(BACKEND) $(RUNNER) $(BUILD)/run_main.o $(BUILD)/host.o
	$(CC) $(CFLAGS) $^ -rdynamic $(LDFLAGS) -ldl -lffi -o $@

$(BUILD)/librmd0_run.a: $(RUNNER)
	$(AR) rcs $@ $^

$(BUILD)/librmd0.a: $(CORE) $(BACKEND)
	$(AR) rcs $@ $^

$(BUILD)/librmd0_host.a: $(BUILD)/host.o
	$(AR) rcs $@ $^

$(BUILD)/rmd-c-seed.s: $(BUILD)/rmd0 $(C_STAGE)
	$(BUILD)/rmd0 -S -o $@ $(C_STAGE)

$(BUILD)/rmd-c-seed.o: $(BUILD)/rmd-c-seed.s
	$(AS) $(ASFLAGS) $< -o $@

$(BUILD)/rmd-c-seed: $(BUILD)/rmd-c-seed.o $(BUILD)/librmd0.a $(BUILD)/librmd0_host.a
	$(CC) -no-pie $^ $(LDFLAGS) -o $@

$(BUILD)/rmd-c: $(BUILD)/rmd-c-seed
	$< -o $@ $(C_STAGE) $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/librmd0.a --ldflag $(BUILD)/librmd0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/rmd-c-library.o: $(BUILD)/rmd-c $(C_LIBRARY) Makefile
	$< --library --object $(foreach name,$(C_EXPORTS),--export $(name)) --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(C_LIBRARY)

$(BUILD)/rmd-c-library.so: $(BUILD)/rmd-c-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(LDFLAGS) -o $@

c-stage: $(BUILD)/rmd-c $(BUILD)/rmd-c-library.so

$(BUILD)/rmd-resource: $(BUILD)/rmd-c $(RESOURCE_LIBRARY) stages/resources/main.rmd
	$< -o $@ $(RESOURCE_LIBRARY) stages/resources/main.rmd $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/librmd0.a --ldflag $(BUILD)/librmd0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/rmd-resource-library.o: $(BUILD)/rmd-c $(RESOURCE_LIBRARY) Makefile
	$< --library --object $(foreach name,$(RESOURCE_EXPORTS),--export $(name)) --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(RESOURCE_LIBRARY)

$(BUILD)/rmd-resource-library.so: $(BUILD)/rmd-resource-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(LDFLAGS) -o $@

resource-stage: $(BUILD)/rmd-resource $(BUILD)/rmd-resource-library.so

$(BUILD)/rmd-overload: $(BUILD)/rmd-c $(OVERLOAD_LIBRARY) stages/overload/main.rmd
	$< -o $@ $(OVERLOAD_LIBRARY) stages/overload/main.rmd $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/librmd0.a --ldflag $(BUILD)/librmd0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/rmd-overload-library.o: $(BUILD)/rmd-c $(OVERLOAD_LIBRARY) Makefile
	$< --library --object $(foreach name,$(OVERLOAD_EXPORTS),--export $(name)) --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(OVERLOAD_LIBRARY)

$(BUILD)/rmd-overload-library.so: $(BUILD)/rmd-overload-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(LDFLAGS) -o $@

$(BUILD)/rmd-overload-resource: $(BUILD)/rmd-c $(OVERLOAD_RESOURCE_LIBRARY) stages/overload/resource_main.rmd
	$< -o $@ $(OVERLOAD_RESOURCE_LIBRARY) stages/overload/resource_main.rmd $(foreach flag,$(CFLAGS),--cflag $(flag)) --ldflag $(BUILD)/librmd0.a --ldflag $(BUILD)/librmd0_host.a $(foreach flag,$(LDFLAGS),--ldflag $(flag))

$(BUILD)/rmd-overload-resource-library.o: $(BUILD)/rmd-c $(OVERLOAD_RESOURCE_LIBRARY) Makefile
	$< --library --object $(foreach name,$(OVERLOAD_RESOURCE_EXPORTS),--export $(name)) --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(OVERLOAD_RESOURCE_LIBRARY)

$(BUILD)/rmd-overload-resource-library.so: $(BUILD)/rmd-overload-resource-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(LDFLAGS) -o $@

overload-stage: $(BUILD)/rmd-overload $(BUILD)/rmd-overload-library.so $(BUILD)/rmd-overload-resource $(BUILD)/rmd-overload-resource-library.so

$(BUILD)/intrusive.s: $(BUILD)/rmd0 examples/intrusive/program.rmd
	$(BUILD)/rmd0 -S -o $@ examples/intrusive/program.rmd

$(BUILD)/intrusive.o: $(BUILD)/intrusive.s
	$(AS) $(ASFLAGS) $< -o $@

$(BUILD)/intrusive: $(BUILD)/intrusive.o $(BUILD)/librmd0_host.a
	$(CC) -no-pie $^ $(LDFLAGS) -o $@

$(BUILD)/intrusive-c: benchmarks/bootstrap/intrusive.c $(BUILD)/librmd0_host.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $^ $(LDFLAGS) -o $@

witness: $(BUILD)/intrusive $(BUILD)/intrusive-c
	$(BUILD)/intrusive
	$(BUILD)/intrusive-c

$(BUILD)/%_test: tests/%_test.c $(BUILD)/librmd0.a $(BUILD)/librmd0_host.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $^ $(LDFLAGS) -pthread -o $@

$(BUILD)/eval_test: tests/eval_test.c tests/native.c $(BUILD)/eval.o $(BUILD)/librmd0.a $(BUILD)/librmd0_host.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $^ -rdynamic $(LDFLAGS) -ldl -lffi -o $@

api:
	python3 tools/api.py

check: all $(BUILD)/core_test $(BUILD)/read_test $(BUILD)/check_test $(BUILD)/host_test $(BUILD)/parallel_test $(BUILD)/x64_test $(BUILD)/eval_test
	$(BUILD)/core_test
	$(BUILD)/read_test
	$(BUILD)/check_test
	$(BUILD)/host_test
	$(BUILD)/parallel_test
	$(BUILD)/x64_test
	$(BUILD)/eval_test
	python3 tools/api.py --check
	python3 tests/run.py --compiler $(BUILD)/rmd0 --cc '$(CC)' --assembler '$(AS) $(ASFLAGS)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-c: c-stage
	python3 tests/run.py --backend c --compiler $(BUILD)/rmd-c --cc '$(CC)' --assembler '$(AS) $(ASFLAGS)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
	python3 tests/c_body.py --build $(BUILD) --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-reader: all c-stage
	python3 stages/reader/test.py --build $(BUILD) --cc '$(CC)' --ldflags='$(LDFLAGS)'

check-resources: all resource-stage
	python3 tests/resources.py --build $(BUILD)

check-overload: all overload-stage
	python3 tests/overload.py --build $(BUILD)
	python3 tests/overload_resources.py --build $(BUILD)
	python3 tests/overload_hooks.py --build $(BUILD) --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-overload-alloc: all c-stage
	python3 tests/overload_alloc.py --build $(BUILD) --cc '$(CC)'

check-resource-alloc: all c-stage
	python3 tests/resources_alloc.py --build $(BUILD) --cc '$(CC)'

check-stage: all c-stage
	python3 tests/source_order.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

check-examples: all c-stage
	python3 tests/source_order.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)' --group examples

clean:
	rm -rf $(BUILD)

-include $(wildcard $(BUILD)/*.d)
