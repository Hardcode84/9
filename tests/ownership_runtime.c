/* SPDX-License-Identifier: Apache-2.0 */

#include <stddef.h>
#include <stdlib.h>

enum { SLOT_COUNT = 64 };

static void *slots[SLOT_COUNT];
static size_t extents[SLOT_COUNT];
static unsigned int calls;
static unsigned int failure;
static unsigned int busy[SLOT_COUNT];
static unsigned int reused;

void *ownership_test_allocate(size_t size);
void ownership_test_release(void *pointer);

static void finish(void)
{
    unsigned int index;
    for (index = 0; index < SLOT_COUNT; ++index) {
        if (busy[index]) {
            abort();
        }
        free(slots[index]);
    }
    if (failure == 0 && !reused) {
        abort();
    }
}

void *ownership_test_allocate(size_t size)
{
    unsigned int index;
    if (calls == 0) {
        const char *choice = getenv("CRUST_TEST_ALLOCATION_FAILURE");
        failure = choice == NULL ? 0 : (unsigned int)strtoul(choice, NULL, 10);
        if (atexit(finish) != 0) {
            abort();
        }
    }
    ++calls;
    if (calls == failure) {
        return NULL;
    }
    for (index = 0; index < SLOT_COUNT; ++index) {
        if (busy[index] || (slots[index] != NULL && extents[index] != size)) {
            continue;
        }
        if (slots[index] == NULL) {
            extents[index] = size;
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
    for (index = 0; index < SLOT_COUNT; ++index) {
        if (pointer == slots[index] && busy[index]) {
            busy[index] = 0;
            return;
        }
    }
    abort();
}
