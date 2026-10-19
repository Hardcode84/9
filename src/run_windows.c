/* SPDX-License-Identifier: Apache-2.0 */

#define WINVER 0x0602
#define _WIN32_WINNT 0x0602
#include "../runtime/windows_io.h"
#include "crust0_abi.h"
#include "crust0_host.h"
#include "run_platform.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#include <bcrypt.h>

struct CrustLibrary {
    HMODULE handle;
    CrustRun *owner;
    CrustLibrary *next;
};

typedef struct {
    const char *name;
    void (*function)(void);
} CrustHostSymbol;

const char *crust_run_profile_name(void) { return "Windows x86-64"; }

static bool run_error(CrustRun *run, const char *message)
{
    crust_set_error(run->context, run->source,
                    run->cursor <= run->source->size ? run->cursor : run->source->size, message);
    return false;
}

static bool windows_error(CrustRun *run, const char *operation)
{
    char message[512];
    (void)snprintf(message, sizeof(message), "%s (Windows error %lu)", operation,
                   (unsigned long)GetLastError());
    return run_error(run, message);
}

static char *absolute_path(const char *path)
{
    wchar_t *input = crust_windows_wide(path);
    wchar_t *output;
    char *result = NULL;
    DWORD capacity;
    DWORD count;
    if (input == NULL)
        return NULL;
    capacity = GetFullPathNameW(input, 0, NULL, NULL);
    if (capacity == 0) {
        free(input);
        return NULL;
    }
    output = malloc((size_t)capacity * sizeof(*output));
    if (output != NULL) {
        count = GetFullPathNameW(input, capacity, output, NULL);
        if (count != 0 && count < capacity)
            result = crust_windows_utf8(output);
    }
    free(output);
    free(input);
    return result;
}

char *crust_run_root_path(CrustContext *context, const char *path)
{
    char *absolute;
    char *result;
    size_t index;
    if (path[0] == '\0' || (path[1] == ':' && path[2] != '/' && path[2] != '\\')) {
        crust_set_error(context, NULL, 0, "root path is empty or drive-relative");
        return NULL;
    }
    absolute = absolute_path(path);
    if (absolute == NULL) {
        crust_set_error(context, NULL, 0, "cannot resolve UTF-8 root path");
        return NULL;
    }
    for (index = 0; absolute[index] != '\0'; ++index) {
        if (absolute[index] == '\\')
            absolute[index] = '/';
    }
    result = crust_try_copy_string(context, (const unsigned char *)absolute, index);
    free(absolute);
    return result;
}

bool crust_run_native_host(CrustRun *run, CrustDecl *declaration, void **result)
{
    static const CrustHostSymbol symbols[] = {
#define RUN_SYMBOL(name) {#name, (void (*)(void))name}
#define CRUST_HOST_SYMBOL(name) RUN_SYMBOL(name),
#include "host_symbols.inc"
#undef CRUST_HOST_SYMBOL
        RUN_SYMBOL(puts),
        RUN_SYMBOL(strlen),
        RUN_SYMBOL(strcmp),
        RUN_SYMBOL(strncmp),
        RUN_SYMBOL(memcpy),
        RUN_SYMBOL(memmove),
        RUN_SYMBOL(memset),
        RUN_SYMBOL(memcmp),
        RUN_SYMBOL(malloc),
        RUN_SYMBOL(calloc),
        RUN_SYMBOL(realloc),
        RUN_SYMBOL(free),
        RUN_SYMBOL(abort),
        RUN_SYMBOL(exit),
        RUN_SYMBOL(GetLastError),
        RUN_SYMBOL(MultiByteToWideChar),
        RUN_SYMBOL(WideCharToMultiByte),
        RUN_SYMBOL(GetFullPathNameW),
        RUN_SYMBOL(GetFinalPathNameByHandleW),
        RUN_SYMBOL(GetModuleFileNameW),
        RUN_SYMBOL(GetFileAttributesW),
        RUN_SYMBOL(CreateDirectoryW),
        RUN_SYMBOL(RemoveDirectoryW),
        RUN_SYMBOL(CreateFileW),
        RUN_SYMBOL(DeleteFileW),
        RUN_SYMBOL(MoveFileExW),
        RUN_SYMBOL(ReplaceFileW),
        RUN_SYMBOL(GetFileInformationByHandleEx),
        RUN_SYMBOL(BCryptGenRandom),
        RUN_SYMBOL(GetEnvironmentVariableW),
        RUN_SYMBOL(SearchPathW),
        RUN_SYMBOL(GetCurrentProcess),
        RUN_SYMBOL(GetStdHandle),
        RUN_SYMBOL(DuplicateHandle),
        RUN_SYMBOL(CreateProcessW),
        RUN_SYMBOL(WaitForSingleObject),
        RUN_SYMBOL(GetExitCodeProcess),
        RUN_SYMBOL(TerminateProcess),
        RUN_SYMBOL(CloseHandle),
        RUN_SYMBOL(CompareStringOrdinal),
#undef RUN_SYMBOL
    };
    size_t index;
    char message[512];
    for (index = 0; index < sizeof(symbols) / sizeof(symbols[0]); ++index) {
        if (strcmp(declaration->link_name, symbols[index].name) == 0) {
            memcpy(result, &symbols[index].function, sizeof(*result));
            return true;
        }
    }
    (void)snprintf(message, sizeof(message),
                   "unresolved host symbol '%s'; bind a library export explicitly",
                   declaration->link_name);
    crust_set_error(run->context, declaration->loc.source, declaration->loc.offset, message);
    return false;
}

/* Forwarded exports resolve into another image and do not belong to this provider. */
static void *owned_symbol(HMODULE library, const char *name)
{
    FARPROC function = GetProcAddress(library, name);
    void *address;
    HMODULE owner;
    if (function == NULL)
        return NULL;
    memcpy(&address, &function, sizeof(address));
    if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            address, &owner) ||
        owner != library)
        return NULL;
    return address;
}

bool crust_run_native_symbol(CrustRun *run, CrustLibrary *library, CrustDecl *declaration,
                             void **result)
{
    void *address;
    char message[512];
    if (library == NULL || library->owner != run)
        return run_error(run, "native library belongs to a different runner or is null");
    address = owned_symbol(library->handle, declaration->link_name);
    if (address == NULL) {
        (void)snprintf(message, sizeof(message), "library does not export '%s'",
                       declaration->link_name);
        crust_set_error(run->context, declaration->loc.source, declaration->loc.offset, message);
        return false;
    }
    *result = address;
    return true;
}

static const char *native_abi_error(HMODULE library)
{
    static const char *const names[] = CRUST_ABI_NAMES;
    size_t index;
    for (index = 0; index < sizeof(names) / sizeof(names[0]); ++index) {
        const char *const *digest = owned_symbol(library, names[index]);
        if (digest == NULL) {
            if (index == 0)
                return "missing native API digest; rebuild the library with the current API";
            continue;
        }
        if (*digest == NULL || strcmp(*digest, CRUST_ABI_DIGEST) != 0)
            return "native API digest mismatch; rebuild the library with the current API";
    }
    return NULL;
}

static HMODULE open_library(CrustRun *run, const char *path)
{
    char *absolute = crust_run_root_path(run->context, path);
    wchar_t *wide;
    HMODULE library;
    if (absolute == NULL)
        return NULL;
    wide = crust_windows_wide(absolute);
    if (wide == NULL) {
        (void)run_error(run, "cannot allocate native library path");
        return NULL;
    }
    library =
        LoadLibraryExW(wide, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (library == NULL)
        (void)windows_error(run, "cannot load native input");
    free(wide);
    return library;
}

CrustLibrary *crust_run_native_open(CrustRun *run, CrustLibrary **modules, const char *path)
{
    CrustLibrary *module;
    HMODULE library;
    const char *error;
    if (path == NULL || (strchr(path, '/') == NULL && strchr(path, '\\') == NULL)) {
        (void)run_error(run, "native path must contain a directory separator");
        return NULL;
    }
    module = crust_try_alloc(run->context, sizeof(*module), CRUST_ALIGNOF(CrustLibrary));
    if (module == NULL)
        return NULL;
    library = open_library(run, path);
    if (library == NULL)
        return NULL;
    error = native_abi_error(library);
    if (error != NULL) {
        (void)run_error(run, error);
        if (!FreeLibrary(library)) {
            crust_run_diagnostic(run->context);
            (void)windows_error(run, "cannot unload rejected native input");
        }
        return NULL;
    }
    module->handle = library;
    module->owner = run;
    module->next = *modules;
    *modules = module;
    return module;
}

bool crust_run_native_destroy(CrustRun *run, CrustLibrary *modules)
{
    CrustLibrary *module;
    bool success = true;
    for (module = modules; module != NULL; module = module->next) {
        if (!FreeLibrary(module->handle)) {
            (void)windows_error(run, "cannot unload native input");
            success = false;
        }
    }
    return success;
}
