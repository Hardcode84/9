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

.PHONY: all clean check witness api c-stage check-c check-stage
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

$(BUILD)/rmd-c-library.o: $(BUILD)/rmd-c $(C_LIBRARY)
	$< --library --object --export c_backend_build --export c_program --cflag=-fPIC --cflag=-fno-semantic-interposition $(foreach flag,$(CFLAGS),--cflag $(flag)) -o $@ $(C_LIBRARY)

$(BUILD)/rmd-c-library.so: $(BUILD)/rmd-c-library.o
	$(CC) -shared -Wl,-Bsymbolic,-z,text,-z,relro,-z,now $^ $(LDFLAGS) -o $@

c-stage: $(BUILD)/rmd-c $(BUILD)/rmd-c-library.so

$(BUILD)/intrusive.s: $(BUILD)/rmd0 examples/intrusive.rmd
	$(BUILD)/rmd0 -S -o $@ examples/intrusive.rmd

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

check-stage: all c-stage
	python3 tests/source_order.py --build $(BUILD) --cc '$(CC)' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'

clean:
	rm -rf $(BUILD)

-include $(wildcard $(BUILD)/*.d)
