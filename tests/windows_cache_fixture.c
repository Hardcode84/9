/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0_abi.h"
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include <windows.h>

CRUST_ABI_EXPORT;
int cache_barrier(const char *directory, int index);
int wmain(int argc, wchar_t **argv);

int cache_barrier(const char *directory, int index)
{
    wchar_t base[32768];
    wchar_t path[32768];
    HANDLE file;
    unsigned int attempt;
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, directory, -1, base, 32768) ||
        swprintf(path, 32768, L"%ls/%d", base, index) < 0)
        return 1;
    file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, CREATE_NEW,
                       FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE || !CloseHandle(file))
        return 2;
    if (swprintf(path, 32768, L"%ls/%d", base, 3 - index) < 0)
        return 3;
    for (attempt = 0; attempt < 1000; ++attempt) {
        if (GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES)
            return 0;
        Sleep(10);
    }
    return 4;
}

static int start(wchar_t *command, PROCESS_INFORMATION *process)
{
    STARTUPINFOW startup;
    memset(&startup, 0, sizeof(startup));
    startup.cb = sizeof(startup);
    return CreateProcessW(NULL, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, process) != 0;
}

static int finish(PROCESS_INFORMATION *process, int terminate)
{
    DWORD status = 1;
    int success = 1;
    if (terminate && !TerminateProcess(process->hProcess, 0))
        success = 0;
    if (WaitForSingleObject(process->hProcess, 30000) != WAIT_OBJECT_0 ||
        !GetExitCodeProcess(process->hProcess, &status) || status != 0)
        success = 0;
    if (!CloseHandle(process->hThread))
        success = 0;
    if (!CloseHandle(process->hProcess))
        success = 0;
    return success;
}

static int interrupt_child(PROCESS_INFORMATION *process, const wchar_t *marker)
{
    unsigned int attempt;
    for (attempt = 0; attempt < 1000; ++attempt) {
        if (GetFileAttributesW(marker) != INVALID_FILE_ATTRIBUTES)
            return finish(process, 1);
        Sleep(10);
    }
    (void)finish(process, 1);
    return 0;
}

int wmain(int argc, wchar_t **argv)
{
    PROCESS_INFORMATION first;
    PROCESS_INFORMATION second;
    int success;
    if (argc != 4 || !start(argv[2], &first))
        return 1;
    if (wcscmp(argv[1], L"interrupt") == 0)
        return interrupt_child(&first, argv[3]) ? 0 : 1;
    if (!start(argv[3], &second)) {
        (void)finish(&first, 1);
        return 1;
    }
    success = finish(&first, 0);
    if (!finish(&second, 0))
        success = 0;
    return success ? 0 : 1;
}
