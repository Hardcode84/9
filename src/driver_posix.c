/* SPDX-License-Identifier: Apache-2.0 */

#define _POSIX_C_SOURCE 200809L
#include "driver_platform.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static bool emit_stream_file(CrustX64Program *program, const char *path)
{
    FILE *file;
    bool success;
    file = fopen(path, "wb");
    if (file == NULL) {
        fprintf(stderr, "crust0: cannot open output %s: %s\n", path, strerror(errno));
        return false;
    }
    success = crust_x64_emit_program(program, file);
    if (fclose(file) != 0) {
        fprintf(stderr, "crust0: cannot close output: %s\n", strerror(errno));
        success = false;
    }
    return success;
}

static bool emit_atomic_file(CrustX64Program *program, const char *path)
{
    FILE *file;
    char *temporary;
    size_t length;
    int descriptor;
    bool success;
    length = strlen(path);
    if (length > SIZE_MAX - 16) {
        fputs("crust0: output path is too long\n", stderr);
        return false;
    }
    temporary = malloc(length + 16);
    if (temporary == NULL) {
        fputs("crust0: cannot allocate output path\n", stderr);
        return false;
    }
    memcpy(temporary, path, length);
    memcpy(temporary + length, ".tmp.XXXXXX", 12);
    descriptor = mkstemp(temporary);
    if (descriptor < 0) {
        fprintf(stderr, "crust0: cannot create output %s: %s\n", path, strerror(errno));
        free(temporary);
        return false;
    }
    file = fdopen(descriptor, "w");
    if (file == NULL) {
        fprintf(stderr, "crust0: cannot open output stream: %s\n", strerror(errno));
        if (close(descriptor) != 0) {
            fprintf(stderr, "crust0: cannot close output: %s\n", strerror(errno));
        }
        if (unlink(temporary) != 0) {
            fprintf(stderr, "crust0: cannot remove output temporary: %s\n", strerror(errno));
        }
        free(temporary);
        return false;
    }
    success = crust_x64_emit_program(program, file);
    if (fclose(file) != 0) {
        fprintf(stderr, "crust0: cannot close output: %s\n", strerror(errno));
        success = false;
    }
    if (success && rename(temporary, path) != 0) {
        fprintf(stderr, "crust0: cannot publish output %s: %s\n", path, strerror(errno));
        success = false;
    }
    if (!success && unlink(temporary) != 0) {
        fprintf(stderr, "crust0: cannot remove output temporary: %s\n", strerror(errno));
    }
    free(temporary);
    return success;
}

bool crust_driver_emit_file(CrustX64Program *program, const char *path)
{
    bool success;
    struct stat info;
    if (path == NULL || strcmp(path, "-") == 0) {
        success = crust_x64_emit_program(program, stdout);
        if (fflush(stdout) != 0) {
            fprintf(stderr, "crust0: cannot flush output: %s\n", strerror(errno));
            success = false;
        }
        return success;
    }
    if (lstat(path, &info) == 0) {
        if (!S_ISREG(info.st_mode)) {
            return emit_stream_file(program, path);
        }
    } else if (errno != ENOENT) {
        fprintf(stderr, "crust0: cannot inspect output %s: %s\n", path, strerror(errno));
        return false;
    }
    return emit_atomic_file(program, path);
}
