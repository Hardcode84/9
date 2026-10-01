/* SPDX-License-Identifier: Apache-2.0 */

#define _POSIX_C_SOURCE 200809L
#include "crust0_host.h"

#include <stdlib.h>

void *crust0_host_alloc(size_t size, size_t alignment)
{
    void *result = NULL;
    if (size == 0 || size > (size_t)INTPTR_MAX || alignment == 0 ||
        (alignment & (alignment - 1)) != 0) {
        return NULL;
    }
    if (alignment < sizeof(void *)) {
        alignment = sizeof(void *);
    }
    if (posix_memalign(&result, alignment, size) != 0) {
        return NULL;
    }
    return result;
}
