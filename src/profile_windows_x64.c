/* SPDX-License-Identifier: Apache-2.0 */

#define WINVER 0x0602
#define _WIN32_WINNT 0x0602
#include "core_internal.h"

#include <float.h>
#include <limits.h>
#include <locale.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#if !defined(_WIN64) || !defined(__x86_64__)
#error The windows_x64 profile requires a Windows x86-64 host
#endif

typedef char
    CrustHostProfile[(CHAR_BIT == 8 && sizeof(float) == 4 && FLT_RADIX == 2 && FLT_MANT_DIG == 24 &&
                      FLT_MAX_EXP == 128 && sizeof(void *) == 8 && sizeof(size_t) == 8 &&
                      sizeof(CrustTypeKind) == 4 && sizeof(short) == 2 && sizeof(int) == 4 &&
                      sizeof(long) == 4 && sizeof(long long) == 8 && sizeof(bool) == 1 &&
                      sizeof(void (*)(void)) == 8)
                         ? 1
                         : -1];

void *crust_profile_allocate(size_t size) { return malloc(size); }

bool crust_profile_f32(const char *text, uint32_t *bits)
{
    HMODULE library = LoadLibraryExW(L"ucrtbase.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    void *(*create_locale)(int, const char *);
    void (*free_locale)(void *);
    float (*parse)(const char *, char **, void *);
    FARPROC create;
    FARPROC release;
    FARPROC convert;
    void *locale;
    float value;
    if (library == NULL)
        return false;
    create = GetProcAddress(library, "_create_locale");
    release = GetProcAddress(library, "_free_locale");
    convert = GetProcAddress(library, "_strtof_l");
    if (create == NULL || release == NULL || convert == NULL) {
        (void)FreeLibrary(library);
        return false;
    }
    memcpy(&create_locale, &create, sizeof(create_locale));
    memcpy(&free_locale, &release, sizeof(free_locale));
    memcpy(&parse, &convert, sizeof(parse));
    /* Keep locale creation, parsing, and release in the same CRT instance.
       The legacy MSVCRT scanf path can round through binary64. */
    locale = create_locale(LC_NUMERIC, "C");
    if (locale == NULL) {
        (void)FreeLibrary(library);
        return false;
    }
    value = parse(text, NULL, locale);
    free_locale(locale);
    if (!FreeLibrary(library))
        return false;
    memcpy(bits, &value, sizeof(value));
    return true;
}
