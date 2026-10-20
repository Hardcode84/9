/* SPDX-License-Identifier: Apache-2.0 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <windows.h>

int wmain(int argc, wchar_t **argv);

static wchar_t *quote_argument(wchar_t *output, const wchar_t *input)
{
    *output++ = L'"';
    while (*input != L'\0') {
        size_t slashes = 0;
        while (*input == L'\\') {
            ++slashes;
            ++input;
        }
        if (*input == L'"' || *input == L'\0')
            slashes *= 2;
        while (slashes-- != 0)
            *output++ = L'\\';
        if (*input == L'\0')
            break;
        if (*input == L'"')
            *output++ = L'\\';
        *output++ = *input++;
    }
    *output++ = L'"';
    *output++ = L' ';
    return output;
}

static wchar_t *command_line(int argc, wchar_t **argv)
{
    size_t count = 1;
    int index;
    wchar_t *result;
    wchar_t *cursor;
    for (index = 1; index < argc; ++index) {
        size_t length = wcslen(argv[index]);
        if (length > (SIZE_MAX / sizeof(*result) - count - 3) / 2)
            return NULL;
        count += length * 2 + 3;
    }
    result = malloc(count * sizeof(*result));
    if (result == NULL)
        return NULL;
    cursor = result;
    for (index = 1; index < argc; ++index)
        cursor = quote_argument(cursor, argv[index]);
    *cursor = L'\0';
    return result;
}

static DWORD execute(HANDLE job, wchar_t *command)
{
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    DWORD status = 1;
    memset(&startup, 0, sizeof(startup));
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    if (!CreateProcessW(NULL, command, NULL, NULL, TRUE, CREATE_SUSPENDED, NULL, NULL, &startup,
                        &process))
        return 1;
    if (!AssignProcessToJobObject(job, process.hProcess) ||
        ResumeThread(process.hThread) == (DWORD)-1) {
        if (!TerminateProcess(process.hProcess, 1))
            fputs("test limit: cannot terminate suspended child\n", stderr);
    } else if (WaitForSingleObject(process.hProcess, INFINITE) == WAIT_OBJECT_0) {
        if (!GetExitCodeProcess(process.hProcess, &status))
            status = 1;
    }
    if (!CloseHandle(process.hThread))
        status = 1;
    if (!CloseHandle(process.hProcess))
        status = 1;
    return status;
}

int wmain(int argc, wchar_t **argv)
{
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits;
    HANDLE job;
    wchar_t *command;
    DWORD status;
    const char *unlimited = getenv("CRUST_TEST_UNLIMITED_MEMORY");
    if (argc < 2)
        return 1;
    command = command_line(argc, argv);
    if (command == NULL)
        return 1;
    job = CreateJobObjectW(NULL, NULL);
    memset(&limits, 0, sizeof(limits));
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (unlimited == NULL || strcmp(unlimited, "1") != 0) {
        limits.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_JOB_MEMORY;
        limits.JobMemoryLimit = (SIZE_T)512 * 1024 * 1024;
    }
    if (job == NULL ||
        !SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) {
        if (job != NULL && !CloseHandle(job))
            fputs("test limit: cannot close job\n", stderr);
        free(command);
        return 1;
    }
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    status = execute(job, command);
    free(command);
    if (!CloseHandle(job))
        status = 1;
    return (int)status;
}
