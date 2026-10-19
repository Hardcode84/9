/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0_host.h"
#include "host_platform.h"
#include "windows_io.h"

#include <io.h>
#include <malloc.h>
#include <windows.h>

void *crust0_host_alloc(size_t size, size_t alignment)
{
    if (size == 0 || size > (size_t)INTPTR_MAX || alignment == 0 ||
        (alignment & (alignment - 1)) != 0)
        return NULL;
    if (alignment < sizeof(void *))
        alignment = sizeof(void *);
    return _aligned_malloc(size, alignment);
}

void crust0_host_free(void *data) { _aligned_free(data); }

void *crust_host_resize(void *data, size_t size)
{
    return _aligned_realloc(data, size, sizeof(void *));
}

FILE *crust_host_open(const char *path, const char *mode) { return crust_windows_open(path, mode); }

int32_t crust0_host_write_stream(uint32_t stream, const unsigned char *data, size_t size)
{
    FILE *file;
    HANDLE handle;
    if (stream != 1 && stream != 2)
        return 1;
    file = stream == 1 ? stdout : stderr;
    if (fflush(file) != 0)
        return 1;
    handle = (HANDLE)_get_osfhandle(_fileno(file));
    while (size != 0) {
        DWORD written;
        DWORD count = size > MAXDWORD ? MAXDWORD : (DWORD)size;
        if (!WriteFile(handle, data, count, &written, NULL) || written == 0)
            return 1;
        data += written;
        size -= written;
    }
    return 0;
}
