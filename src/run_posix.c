/* SPDX-License-Identifier: Apache-2.0 */

#define _XOPEN_SOURCE 700
#include "run_platform.h"

#include <dlfcn.h>
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

bool crust_run_native_link(CrustRun *run, CrustNativeModule **modules, const char *path)
{
    CrustNativeModule *module;
    void *handle;
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
        const char *error = dlerror();
        (void)snprintf(message, sizeof(message), "cannot load native input '%s': %s", path,
                       error == NULL ? "loader failure" : error);
        return run_error(run, message);
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
        if (dlclose(module->handle) != 0) {
            const char *error = dlerror();
            char message[512];
            (void)snprintf(message, sizeof(message), "cannot unload native input: %s",
                           error == NULL ? "loader failure" : error);
            (void)run_error(run, message);
            crust_run_diagnostic(run->context);
            success = false;
        }
    }
    return success;
}
