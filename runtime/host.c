#define _POSIX_C_SOURCE 200809L
#include "crust0_host.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

void crust0_host_free(void *data)
{
    free(data);
}

void crust0_host_move_bytes(void *dst, const void *src, size_t size)
{
    if (size != 0) {
        memmove(dst, src, size);
    }
}

int32_t crust0_host_read_file(const char *path, unsigned char **data, size_t *size)
{
    FILE *file;
    unsigned char *buffer = NULL;
    size_t used = 0;
    size_t capacity = 0;
    int status = 0;
    *data = NULL;
    *size = 0;
    file = fopen(path, "rb");
    if (file == NULL) {
        return 1;
    }
    for (;;) {
        size_t count;
        if (used == capacity) {
            size_t next = capacity == 0 ? 4096 : capacity * 2;
            unsigned char *allocation;
            if (next < capacity || next > (size_t)INTPTR_MAX) {
                status = 1;
                break;
            }
            allocation = realloc(buffer, next);
            if (allocation == NULL) {
                status = 1;
                break;
            }
            buffer = allocation;
            capacity = next;
        }
        count = fread(buffer + used, 1, capacity - used, file);
        used += count;
        if (ferror(file)) {
            status = 1;
            break;
        }
        if (feof(file)) {
            break;
        }
        if (count == 0) {
            status = 1;
            break;
        }
    }
    if (fclose(file) != 0) {
        status = 1;
    }
    if (status != 0 || used == 0) {
        free(buffer);
    } else {
        *data = buffer;
        *size = used;
    }
    return status;
}

static int write_bytes(FILE *file, const unsigned char *data, size_t size)
{
    while (size != 0) {
        size_t count = fwrite(data, 1, size, file);
        if (count == 0 || ferror(file)) {
            return 1;
        }
        data += count;
        size -= count;
    }
    return 0;
}

int32_t crust0_host_write_file(const char *path, const unsigned char *data, size_t size)
{
    FILE *file = fopen(path, "wb");
    int status;
    if (file == NULL) {
        return 1;
    }
    status = write_bytes(file, data, size);
    if (fclose(file) != 0) {
        status = 1;
    }
    return status;
}

int32_t crust0_host_write_stream(uint32_t stream, const unsigned char *data, size_t size)
{
    FILE *file;
    int status;
    if (stream != 1 && stream != 2) {
        return 1;
    }
    file = stream == 1 ? stdout : stderr;
    status = write_bytes(file, data, size);
    if (fflush(file) != 0) {
        status = 1;
    }
    return status;
}
