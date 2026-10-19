/* SPDX-License-Identifier: Apache-2.0 */

#define WINVER 0x0602
#define _WIN32_WINNT 0x0602
#include "windows_io.h"

#include <stdint.h>
#include <stdlib.h>
#include <windows.h>

wchar_t *crust_windows_wide(const char *text)
{
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
    wchar_t *result;
    if (count == 0 || (size_t)count > SIZE_MAX / sizeof(*result))
        return NULL;
    result = malloc((size_t)count * sizeof(*result));
    if (result != NULL &&
        MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, result, count) == 0) {
        free(result);
        return NULL;
    }
    return result;
}

char *crust_windows_utf8(const wchar_t *text)
{
    int count = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, -1, NULL, 0, NULL, NULL);
    char *result;
    if (count == 0)
        return NULL;
    result = malloc((size_t)count);
    if (result != NULL && WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, -1, result,
                                              count, NULL, NULL) == 0) {
        free(result);
        return NULL;
    }
    return result;
}

FILE *crust_windows_open(const char *path, const char *mode)
{
    wchar_t *wide = crust_windows_wide(path);
    FILE *file;
    if (wide == NULL)
        return NULL;
    file = _wfopen(wide, mode[0] == 'r' ? L"rb" : L"wb");
    free(wide);
    return file;
}
