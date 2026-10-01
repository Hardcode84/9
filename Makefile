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

.PHONY: all clean check witness api
all: $(BUILD)/rmd0 $(BUILD)/librmd0.a $(BUILD)/librmd0_host.a

$(BUILD):
	mkdir -p $@

$(BUILD)/%.o: src/%.c include/rmd0.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -MMD -MP -c $< -o $@

$(BUILD)/host.o: runtime/host.c include/rmd0_host.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) -MMD -MP -c $< -o $@

$(BUILD)/rmd0: $(CORE) $(BACKEND) $(BUILD)/driver.o $(BUILD)/host.o
	$(CC) $(CFLAGS) $^ $(LDFLAGS) -o $@

$(BUILD)/librmd0.a: $(CORE) $(BACKEND)
	$(AR) rcs $@ $^

$(BUILD)/librmd0_host.a: $(BUILD)/host.o
	$(AR) rcs $@ $^

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

api:
	python3 tools/api.py

check: all $(BUILD)/core_test $(BUILD)/read_test $(BUILD)/check_test $(BUILD)/host_test $(BUILD)/parallel_test $(BUILD)/x64_test
	$(BUILD)/core_test
	$(BUILD)/read_test
	$(BUILD)/check_test
	$(BUILD)/host_test
	$(BUILD)/parallel_test
	$(BUILD)/x64_test
	python3 tools/api.py --check
	python3 tests/run.py --compiler $(BUILD)/rmd0 --cc '$(CC)' --assembler '$(AS) $(ASFLAGS)' --ldflags='$(LDFLAGS)'

clean:
	rm -rf $(BUILD)

-include $(wildcard $(BUILD)/*.d)
