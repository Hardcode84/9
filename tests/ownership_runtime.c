/* SPDX-License-Identifier: Apache-2.0 */

#include <stddef.h>
#include <stdlib.h>

static void *slots[2];
static size_t extent;
static unsigned int calls;
static unsigned int failure;
static unsigned int busy[2];
static unsigned int reused;

void *ownership_test_allocate(size_t size);
void ownership_test_release(void *pointer);

static void finish(void)
{
    if (busy[0] || busy[1] || (failure == 0 && !reused)) {
        abort();
    }
    free(slots[0]);
    free(slots[1]);
}

void *ownership_test_allocate(size_t size)
{
    unsigned int index;
    if (calls == 0) {
        const char *choice = getenv("CRUST_TEST_ALLOCATION_FAILURE");
        failure = choice == NULL ? 0 : (unsigned int)strtoul(choice, NULL, 10);
        extent = size;
        if (atexit(finish) != 0) {
            abort();
        }
    }
    ++calls;
    if (calls == failure) {
        return NULL;
    }
    if (size != extent) {
        abort();
    }
    for (index = 0; index < 2; ++index) {
        if (busy[index]) {
            continue;
        }
        if (slots[index] == NULL) {
            slots[index] = malloc(size);
            if (slots[index] == NULL) {
                abort();
            }
        } else {
            reused = 1;
        }
        busy[index] = 1;
        return slots[index];
    }
    abort();
}

void ownership_test_release(void *pointer)
{
    unsigned int index;
    if (pointer == NULL) {
        return;
    }
    for (index = 0; index < 2; ++index) {
        if (pointer == slots[index] && busy[index]) {
            busy[index] = 0;
            return;
        }
    }
    abort();
}
