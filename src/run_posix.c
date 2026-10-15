/* SPDX-License-Identifier: Apache-2.0 */

#define _GNU_SOURCE
#include "crust0_abi.h"
#include "run_platform.h"

#include <dlfcn.h>
#include <link.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct CrustLibrary {
    void *handle;
    CrustRun *owner;
    CrustLibrary *next;
};

static bool run_error(CrustRun *run, const char *message)
{
    crust_set_error(run->context, run->source,
                    run->cursor <= run->source->size ? run->cursor : run->source->size, message);
    return false;
}

char *crust_run_root_path(CrustContext *context, const char *path)
{
    char *directory;
    char *result;
    size_t prefix;
    size_t suffix = strlen(path);
    if (path[0] == '/')
        return crust_try_copy_string(context, (const unsigned char *)path, suffix);
    directory = getcwd(NULL, 0);
    if (directory == NULL) {
        crust_set_error(context, NULL, 0, "cannot read working directory");
        return NULL;
    }
    prefix = strlen(directory);
    if (suffix > SIZE_MAX - prefix - 2) {
        free(directory);
        crust_set_error(context, NULL, 0, "root path is too long");
        return NULL;
    }
    result = crust_try_alloc(context, prefix + suffix + 2, 1);
    if (result != NULL) {
        memcpy(result, directory, prefix);
        result[prefix] = '/';
        memcpy(result + prefix + 1, path, suffix + 1);
    }
    free(directory);
    return result;
}

bool crust_run_native_host(CrustRun *run, CrustDecl *declaration, void **result)
{
    void *address;
    char message[512];
    dlerror();
    address = dlsym(RTLD_DEFAULT, declaration->link_name);
    if (dlerror() != NULL || address == NULL) {
        (void)snprintf(message, sizeof(message),
                       "unresolved host symbol '%s'; bind a library export explicitly",
                       declaration->link_name);
        crust_set_error(run->context, declaration->loc.source, declaration->loc.offset, message);
        return false;
    }
    *result = address;
    return true;
}

bool crust_run_native_symbol(CrustRun *run, CrustLibrary *library, CrustDecl *declaration,
                             void **result)
{
    void *address;
    struct link_map *map;
    Dl_info info;
    char message[512];
    if (library == NULL || library->owner != run)
        return run_error(run, "native library belongs to a different runner or is null");
    dlerror();
    address = dlsym(library->handle, declaration->link_name);
    if (dlerror() != NULL || address == NULL ||
        dlinfo(library->handle, RTLD_DI_LINKMAP, &map) != 0 || dladdr(address, &info) == 0 ||
        info.dli_fbase != (void *)map->l_addr) {
        (void)snprintf(message, sizeof(message), "library does not export '%s'",
                       declaration->link_name);
        crust_set_error(run->context, declaration->loc.source, declaration->loc.offset, message);
        return false;
    }
    *result = address;
    return true;
}

static const char *native_abi_error(void *handle)
{
    static const char *const names[] = CRUST_ABI_NAMES;
    struct link_map *map;
    size_t index;
    if (dlinfo(handle, RTLD_DI_LINKMAP, &map) != 0)
        return "cannot inspect native API digest";
    for (index = 0; index < sizeof(names) / sizeof(names[0]); ++index) {
        const char *const *digest;
        Dl_info info;
        void *symbol = dlsym(handle, names[index]);
        /* dlsym also searches dependencies. Each image must carry its own base
           marker; a dependency must not attest to the image that imports it. */
        if (symbol == NULL || dladdr(symbol, &info) == 0 || info.dli_fbase != (void *)map->l_addr) {
            if (index == 0)
                return "missing native API digest; rebuild the library with the current API";
            continue;
        }
        digest = symbol;
        if (*digest == NULL || strcmp(*digest, CRUST_ABI_DIGEST) != 0)
            return "native API digest mismatch; rebuild the library with the current API";
    }
    return NULL;
}

static bool native_close(CrustRun *run, void *handle)
{
    if (dlclose(handle) != 0) {
        const char *error = dlerror();
        char message[512];
        (void)snprintf(message, sizeof(message), "cannot unload native input: %s",
                       error == NULL ? "loader failure" : error);
        return run_error(run, message);
    }
    return true;
}

CrustLibrary *crust_run_native_open(CrustRun *run, CrustLibrary **modules, const char *path)
{
    CrustLibrary *module;
    void *handle;
    const char *error;
    char message[512];
    if (path == NULL || path[0] == '\0') {
        (void)run_error(run, "native path is empty");
        return NULL;
    }
    if (strchr(path, '/') == NULL) {
        (void)run_error(run,
                        "native path must contain '/' (use './' for a current-directory file)");
        return NULL;
    }
    module = crust_try_alloc(run->context, sizeof(*module), CRUST_ALIGNOF(CrustLibrary));
    if (module == NULL)
        return NULL;
    handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (handle == NULL) {
        error = dlerror();
        (void)snprintf(message, sizeof(message), "cannot load native input '%s': %s", path,
                       error == NULL ? "loader failure" : error);
        (void)run_error(run, message);
        return NULL;
    }
    error = native_abi_error(handle);
    if (error != NULL) {
        (void)snprintf(message, sizeof(message), "cannot load native input '%s': %s", path, error);
        (void)run_error(run, message);
        if (!native_close(run, handle))
            crust_run_diagnostic(run->context);
        return NULL;
    }
    module->handle = handle;
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
        if (!native_close(run, module->handle)) {
            crust_run_diagnostic(run->context);
            success = false;
        }
    }
    return success;
}
