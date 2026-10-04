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

struct CrustNativeModule {
    void *handle;
    CrustNativeModule *next;
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

bool crust_run_native_resolve(CrustRun *run, CrustNativeModule *modules, CrustDecl *declaration,
                              void **result)
{
    CrustNativeModule *module;
    void *address;
    char message[512];
    const char *name = declaration->link_name;
    dlerror();
    address = dlsym(RTLD_DEFAULT, name);
    if (dlerror() != NULL)
        address = NULL;
    for (module = modules; module != NULL; module = module->next) {
        void *candidate;
        dlerror();
        candidate = dlsym(module->handle, name);
        if (dlerror() != NULL)
            continue;
        if (candidate != NULL && address != NULL && candidate != address) {
            (void)snprintf(message, sizeof(message), "ambiguous native symbol '%s'", name);
            crust_set_error(run->context, declaration->loc.source, declaration->loc.offset,
                            message);
            return false;
        }
        if (candidate != NULL)
            address = candidate;
    }
    if (address == NULL) {
        (void)snprintf(message, sizeof(message), "unresolved native symbol '%s'", name);
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

bool crust_run_native_link(CrustRun *run, CrustNativeModule **modules, const char *path)
{
    CrustNativeModule *module;
    void *handle;
    const char *error;
    char message[512];
    if (path == NULL || path[0] == '\0')
        return run_error(run, "native path is empty");
    if (strchr(path, '/') == NULL)
        return run_error(run,
                         "native path must contain '/' (use './' for a current-directory file)");
    module = crust_try_alloc(run->context, sizeof(*module), CRUST_ALIGNOF(CrustNativeModule));
    if (module == NULL)
        return false;
    handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (handle == NULL) {
        error = dlerror();
        (void)snprintf(message, sizeof(message), "cannot load native input '%s': %s", path,
                       error == NULL ? "loader failure" : error);
        return run_error(run, message);
    }
    error = native_abi_error(handle);
    if (error != NULL) {
        (void)snprintf(message, sizeof(message), "cannot load native input '%s': %s", path, error);
        (void)run_error(run, message);
        if (!native_close(run, handle))
            crust_run_diagnostic(run->context);
        return false;
    }
    module->handle = handle;
    module->next = *modules;
    *modules = module;
    return true;
}

bool crust_run_native_destroy(CrustRun *run, CrustNativeModule *modules)
{
    CrustNativeModule *module;
    bool success = true;
    for (module = modules; module != NULL; module = module->next) {
        if (!native_close(run, module->handle)) {
            crust_run_diagnostic(run->context);
            success = false;
        }
    }
    return success;
}
