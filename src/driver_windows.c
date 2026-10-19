/* SPDX-License-Identifier: Apache-2.0 */

#define WINVER 0x0602
#define _WIN32_WINNT 0x0602
#include "../runtime/windows_io.h"
#include "driver_platform.h"

#include <fcntl.h>
#include <io.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#include <bcrypt.h>

static bool output_error(const char *operation)
{
    fprintf(stderr, "crust0: %s (Windows error %lu)\n", operation, (unsigned long)GetLastError());
    return false;
}

static HANDLE create_temporary(wchar_t *temporary, const wchar_t *path)
{
    static const wchar_t digits[] = L"0123456789abcdef";
    size_t length = wcslen(path);
    unsigned attempt;
    memcpy(temporary, path, length * sizeof(*path));
    memcpy(temporary + length, L".crust-", 7 * sizeof(*path));
    for (attempt = 0; attempt < 128; ++attempt) {
        unsigned char random[16];
        size_t index;
        HANDLE file;
        if (BCryptGenRandom(NULL, random, sizeof(random), BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0)
            return INVALID_HANDLE_VALUE;
        for (index = 0; index < sizeof(random); ++index) {
            temporary[length + 7 + index * 2] = digits[random[index] >> 4];
            temporary[length + 8 + index * 2] = digits[random[index] & 15];
        }
        temporary[length + 39] = L'\0';
        file =
            CreateFileW(temporary, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
        if (file != INVALID_HANDLE_VALUE || GetLastError() != ERROR_FILE_EXISTS)
            return file;
    }
    return INVALID_HANDLE_VALUE;
}

static bool emit_handle(CrustX64Program *program, HANDLE handle)
{
    int descriptor = _open_osfhandle((intptr_t)handle, _O_BINARY | _O_WRONLY);
    FILE *file;
    bool success;
    if (descriptor < 0) {
        if (!CloseHandle(handle))
            (void)output_error("cannot close output handle");
        return output_error("cannot open output descriptor");
    }
    file = _fdopen(descriptor, "wb");
    if (file == NULL) {
        if (_close(descriptor) != 0)
            (void)output_error("cannot close output descriptor");
        return output_error("cannot open output stream");
    }
    success = crust_x64_emit_program(program, file);
    if (fclose(file) != 0)
        success = output_error("cannot close output stream");
    return success;
}

static bool emit_atomic(CrustX64Program *program, const wchar_t *path, bool replace)
{
    size_t length = wcslen(path);
    wchar_t *temporary;
    HANDLE handle;
    bool success;
    if (length > SIZE_MAX / sizeof(*temporary) - 40)
        return output_error("output path is too long");
    temporary = malloc((length + 40) * sizeof(*temporary));
    if (temporary == NULL)
        return output_error("cannot allocate output path");
    handle = create_temporary(temporary, path);
    if (handle == INVALID_HANDLE_VALUE) {
        free(temporary);
        return output_error("cannot create output temporary");
    }
    success = emit_handle(program, handle);
    if (success) {
        BOOL published = replace ? ReplaceFileW(path, temporary, NULL, 0, NULL, NULL)
                                 : MoveFileExW(temporary, path, 0);
        if (!published)
            success = output_error("cannot publish output");
    }
    if (!success && !DeleteFileW(temporary))
        (void)output_error("cannot remove output temporary");
    free(temporary);
    return success;
}

static bool emit_stream(CrustX64Program *program, const char *path)
{
    FILE *file = crust_windows_open(path, "wb");
    bool success;
    if (file == NULL)
        return output_error("cannot open output");
    success = crust_x64_emit_program(program, file);
    if (fclose(file) != 0)
        success = output_error("cannot close output");
    return success;
}

static bool emit_path(CrustX64Program *program, const char *path, const wchar_t *wide)
{
    HANDLE handle = CreateFileW(
        wide, FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
        OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    DWORD type;
    DWORD attributes;
    if (handle == INVALID_HANDLE_VALUE) {
        if (GetLastError() == ERROR_FILE_NOT_FOUND)
            return emit_atomic(program, wide, false);
        return output_error("cannot inspect output");
    }
    type = GetFileType(handle);
    if (!CloseHandle(handle))
        return output_error("cannot close inspected output");
    if (type == FILE_TYPE_UNKNOWN)
        return output_error("unsupported output file type");
    if (type != FILE_TYPE_DISK)
        return emit_stream(program, path);
    attributes = GetFileAttributesW(wide);
    if (attributes == INVALID_FILE_ATTRIBUTES)
        return output_error("cannot inspect output attributes");
    if ((attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != 0)
        return emit_stream(program, path);
    return emit_atomic(program, wide, true);
}

bool crust_driver_emit_file(CrustX64Program *program, const char *path)
{
    wchar_t *wide;
    bool success;
    if (path == NULL || strcmp(path, "-") == 0) {
        success = crust_x64_emit_program(program, stdout);
        if (fflush(stdout) != 0)
            success = output_error("cannot flush output");
        return success;
    }
    wide = crust_windows_wide(path);
    if (wide == NULL)
        return output_error("invalid UTF-8 output path or allocation failure");
    success = emit_path(program, path, wide);
    free(wide);
    return success;
}
