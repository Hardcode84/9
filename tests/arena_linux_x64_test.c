/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0.h"

#include <errno.h>
#include <stdio.h>

int __real_madvise(void *address, size_t size, int advice);
int __wrap_madvise(void *address, size_t size, int advice);

static int advice_error;
static unsigned calls;

int __wrap_madvise(void *address, size_t size, int advice)
{
    ++calls;
    if (advice_error != 0) {
        errno = advice_error;
        return -1;
    }
    return __real_madvise(address, size, advice);
}

int main(void)
{
    const int errors[] = {0, EINVAL, ENOMEM};
    size_t index;
    for (index = 0; index < sizeof(errors) / sizeof(errors[0]); ++index) {
        CrustArena arena;
        CrustArenaBlock *previous;
        size_t reserved;
        unsigned char *retained;
        unsigned char *data;
        bool accepted;
        advice_error = errors[index];
        calls = 0;
        crust_arena_init(&arena, NULL);
        retained = crust_arena_alloc(&arena, 1, 1);
        if (retained == NULL)
            return 1;
        *retained = 99;
        previous = arena.blocks;
        reserved = arena.bytes_reserved;
        data = crust_arena_alloc(&arena, 3145728, 8);
        accepted = data != NULL;
        if (calls != 1 || *retained != 99 || accepted != (advice_error != ENOMEM) ||
            (!accepted && (arena.blocks != previous || arena.bytes_reserved != reserved))) {
            fprintf(stderr, "arena advice case %zu failed\n", index);
            crust_arena_destroy(&arena);
            return 1;
        }
        if (accepted) {
            data[0] = 17;
            data[3145727] = 43;
        }
        crust_arena_destroy(&arena);
    }
    puts("arena platform: supported, unsupported and failed advice paths passed");
    return 0;
}
