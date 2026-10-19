/* SPDX-License-Identifier: Apache-2.0 */

#include "ownership_race_config.h"
#include <process.h>
#include <stdint.h>
#include <stdlib.h>
#include <wchar.h>
#include <windows.h>

int wmain(int argc, wchar_t **argv);

int wmain(int argc, wchar_t **argv)
{
    const wchar_t *compiler = CRUST_RACE_COMPILER;
    const wchar_t *replacement = CRUST_RACE_REPLACEMENT;
    const wchar_t *artifact = CRUST_RACE_ARTIFACT;
    const wchar_t *marker = CRUST_RACE_MARKER;
    intptr_t status;
    HANDLE file;
    if (argc < 1 || compiler == NULL || replacement == NULL || artifact == NULL || marker == NULL)
        return 1;
    if (GetFileAttributesW(marker) == INVALID_FILE_ATTRIBUTES) {
        if (!MoveFileExW(replacement, artifact, MOVEFILE_REPLACE_EXISTING))
            return 2;
        file = CreateFileW(marker, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
        if (file == INVALID_HANDLE_VALUE || !CloseHandle(file))
            return 3;
    }
    argv[0] = (wchar_t *)compiler;
    status = _wspawnv(_P_WAIT, compiler, (const wchar_t *const *)argv);
    return status < 0 ? 4 : (int)status;
}
