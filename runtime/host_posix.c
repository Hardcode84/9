/* SPDX-License-Identifier: Apache-2.0 */

#define _POSIX_C_SOURCE 200809L
#include "crust0_host.h"
#include "host_platform.h"

#include <stdlib.h>

void crust0_host_free(void *data) { free(data); }
void *crust_host_resize(void *data, size_t size) { return realloc(data, size); }
FILE *crust_host_open(const char *path, const char *mode) { return fopen(path, mode); }

int32_t crust0_host_write_stream(uint32_t stream, const unsigned char *data, size_t size)
{
    FILE *file;
    int status;
    if (stream != 1 && stream != 2)
        return 1;
    file = stream == 1 ? stdout : stderr;
    status = crust_host_write_bytes(file, data, size);
    if (fflush(file) != 0)
        status = 1;
    return status;
}

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
