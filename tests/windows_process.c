/* SPDX-License-Identifier: Apache-2.0 */

#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#include <windows.h>

int wmain(int argc, wchar_t **argv);

int wmain(int argc, wchar_t **argv)
{
    static const wchar_t *const expected[] = {L"",     L"two words",   L"a\"b",  L"end\\",
                                              L"\\\"", L"line\nbreak", L"\u96ea"};
    wchar_t locale[8];
    size_t index;
    if (argc == 2 && wcscmp(argv[1], L"fail") == 0)
        return 37;
    if (argc != 8)
        return 10;
    for (index = 0; index < sizeof(expected) / sizeof(expected[0]); ++index) {
        if (wcscmp(argv[index + 1], expected[index]) != 0)
            return 11;
    }
    if (GetEnvironmentVariableW(L"CRUST_UNEXPECTED", locale, 8) != 0 ||
        GetEnvironmentVariableW(L"LC_ALL", locale, 8) != 1 || wcscmp(locale, L"C") != 0)
        return 12;
    if (getchar() != EOF)
        return 13;
    return puts("arguments and environment passed") < 0 ? 14 : 0;
}
