/* SPDX-License-Identifier: Apache-2.0 */

#define _POSIX_C_SOURCE 200809L
#include "driver_platform.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>
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

static int create_temporary(char *temporary, const char *path, mode_t mode)
{
    static const char digits[] = "0123456789abcdef";
    const char *slash = strrchr(path, '/');
    size_t directory = slash == NULL ? 0 : (size_t)(slash - path) + 1;
    unsigned attempt;
    memcpy(temporary, path, directory);
    memcpy(temporary + directory, ".crust-", 7);
    for (attempt = 0; attempt < 128; ++attempt) {
        unsigned char random[16];
        size_t index;
        int descriptor;
        if (getentropy(random, sizeof(random)) != 0)
            return -1;
        for (index = 0; index < sizeof(random); ++index) {
            temporary[directory + 7 + index * 2] = digits[random[index] >> 4];
            temporary[directory + 8 + index * 2] = digits[random[index] & 15];
        }
        temporary[directory + 39] = '\0';
        descriptor = open(temporary, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, mode);
        if (descriptor >= 0 || errno != EEXIST)
            return descriptor;
    }
    return -1;
}

static bool finish_output(FILE *file, const struct stat *previous, bool success)
{
    if (success && previous != NULL && fchmod(fileno(file), previous->st_mode & 0777) != 0) {
        fprintf(stderr, "crust0: cannot set output permissions: %s\n", strerror(errno));
        success = false;
    }
    if (fclose(file) != 0) {
        fprintf(stderr, "crust0: cannot close output: %s\n", strerror(errno));
        success = false;
    }
    return success;
}

static bool emit_atomic_file(CrustX64Program *program, const char *path,
                             const struct stat *previous)
{
    FILE *file;
    char *temporary;
    size_t length;
    int descriptor;
    bool success;
    length = strlen(path);
    if (length > SIZE_MAX - 40) {
        fputs("crust0: output path is too long\n", stderr);
        return false;
    }
    temporary = malloc(length + 40);
    if (temporary == NULL) {
        fputs("crust0: cannot allocate output path\n", stderr);
        return false;
    }
    descriptor =
        create_temporary(temporary, path, previous != NULL ? previous->st_mode & 0666 : 0666);
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
    success = finish_output(file, previous, success);
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
        return emit_atomic_file(program, path, &info);
    } else if (errno != ENOENT) {
        fprintf(stderr, "crust0: cannot inspect output %s: %s\n", path, strerror(errno));
        return false;
    }
    return emit_atomic_file(program, path, NULL);
}
