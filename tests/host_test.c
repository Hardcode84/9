/* SPDX-License-Identifier: Apache-2.0 */

#define _POSIX_C_SOURCE 200809L
#include "crust0_host.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static unsigned checks;
static unsigned failures;

static void check(bool condition, const char *message)
{
    ++checks;
    if (!condition) {
        ++failures;
        fprintf(stderr, "host check failed: %s\n", message);
    }
}

int main(void)
{
    char path[] = "/tmp/crust0-host-XXXXXX";
    unsigned char contents[10000];
    unsigned char overlap[] = "abcdef";
    unsigned char *data;
    size_t size;
    size_t index;
    int descriptor = mkstemp(path);
    if (descriptor == -1) {
        perror("host test temporary");
        return 1;
    }
    check(close(descriptor) == 0, "close temporary file descriptor");
    for (index = 0; index < sizeof(contents); ++index)
        contents[index] = (unsigned char)index;
    check(crust0_host_read_file(path, &data, &size) == 0 && data == NULL && size == 0,
          "empty read returns no allocation");
    check(crust0_host_write_file(path, contents, sizeof(contents)) == 0, "write binary bytes");
    check(crust0_host_read_file(path, &data, &size) == 0 && size == sizeof(contents) &&
              memcmp(data, contents, size) == 0,
          "read grows the buffer and preserves bytes");
    crust0_host_free(data);
    check(crust0_host_write_file(path, NULL, 0) == 0, "empty write truncates");
    check(crust0_host_read_file(path, &data, &size) == 0 && size == 0 && data == NULL,
          "truncated read is empty");
    check(unlink(path) == 0, "remove test file");
    data = contents;
    size = sizeof(contents);
    check(crust0_host_read_file(path, &data, &size) != 0 && data == NULL && size == 0,
          "failed read clears both outputs");
    check(crust0_host_write_file("/dev/full", contents, sizeof(contents)) != 0,
          "write reports output failure");
    check(crust0_host_write_stream(3, NULL, 0) != 0, "invalid stream fails");
    check(crust0_host_write_stream(1, NULL, 0) == 0, "zero byte stream write permits null");
    crust0_host_move_bytes(overlap + 1, overlap, 5);
    check(memcmp(overlap, "aabcde", 6) == 0, "byte move preserves overlapping input");
    crust0_host_move_bytes(NULL, NULL, 0);
    check(crust0_host_alloc(0, 1) == NULL, "zero allocation returns null");
    check(crust0_host_alloc(8, 3) == NULL, "invalid alignment fails");
    check(crust0_host_alloc(SIZE_MAX, 1) == NULL, "oversized allocation fails");
    for (index = 1; index <= 4096; index *= 2) {
        data = crust0_host_alloc(31, index);
        check(data != NULL && (uintptr_t)data % index == 0, "host allocation alignment");
        memset(data, 0, 31);
        crust0_host_free(data);
    }
    crust0_host_free(NULL);
    printf("host: %u/%u checks passed\n", checks - failures, checks);
    return failures == 0 ? 0 : 1;
}
