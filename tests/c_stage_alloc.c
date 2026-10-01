#include "crust0_host.h"

#include <stddef.h>

void *__real_crust0_host_alloc(size_t size, size_t alignment);
void __real_crust0_host_free(void *allocation);
void *__wrap_crust0_host_alloc(size_t size, size_t alignment);
void __wrap_crust0_host_free(void *allocation);
void crust_test_allocation_reset(size_t fail_at);
size_t crust_test_allocation_calls(void);
size_t crust_test_allocation_live(void);

static size_t allocation_calls;
static size_t allocation_failure;
static size_t live_allocations;

void crust_test_allocation_reset(size_t fail_at)
{
    allocation_calls = 0;
    allocation_failure = fail_at;
}

size_t crust_test_allocation_calls(void) { return allocation_calls; }

size_t crust_test_allocation_live(void) { return live_allocations; }

void *__wrap_crust0_host_alloc(size_t size, size_t alignment)
{
    void *result;
    ++allocation_calls;
    if (allocation_calls == allocation_failure)
        return NULL;
    result = __real_crust0_host_alloc(size, alignment);
    if (result != NULL)
        ++live_allocations;
    return result;
}

void __wrap_crust0_host_free(void *allocation)
{
    if (allocation != NULL)
        --live_allocations;
    __real_crust0_host_free(allocation);
}
