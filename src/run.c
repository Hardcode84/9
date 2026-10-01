#define _XOPEN_SOURCE 700
#include "crust0_run.h"

#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

typedef struct NativeModule NativeModule;
struct NativeModule {
    void *handle;
    NativeModule *next;
};

struct CrustRunState {
    NativeModule *modules;
    CrustEval *initial_eval;
};

void crust_run_diagnostic(const CrustContext *context)
{
    const CrustSource *source = context->error_loc.source;
    size_t line = 1;
    size_t column = 1;
    size_t index;
    if (source == NULL) {
        fprintf(stderr, "crust: error: %s\n", context->error);
        return;
    }
    for (index = 0; index < context->error_loc.offset && index < source->size; ++index) {
        if (source->bytes[index] == '\n') { ++line; column = 1; }
        else ++column;
    }
    fprintf(stderr, "%s:%zu:%zu: error: %s\n", source->path, line, column,
            context->error);
}

static bool run_error(CrustRun *run, const char *message)
{
    crust_set_error(run->context, run->source,
                  run->cursor <= run->source->size ? run->cursor : run->source->size,
                  message);
    return false;
}

static bool resolve_native(void *user, CrustDecl *declaration, void **result)
{
    CrustRun *run = user;
    NativeModule *module;
    void *address;
    char message[512];
    const char *name = declaration->link_name;
    dlerror();
    address = dlsym(RTLD_DEFAULT, name);
    if (dlerror() != NULL) address = NULL;
    for (module = run->state->modules; module != NULL; module = module->next) {
        void *candidate;
        dlerror();
        candidate = dlsym(module->handle, name);
        if (dlerror() != NULL) continue;
        if (candidate != NULL && address != NULL && candidate != address) {
            (void)snprintf(message, sizeof(message), "ambiguous native symbol '%s'", name);
            crust_set_error(run->context, declaration->loc.source, declaration->loc.offset,
                          message);
            return false;
        }
        if (candidate != NULL) address = candidate;
    }
    if (address == NULL) {
        (void)snprintf(message, sizeof(message), "unresolved native symbol '%s'", name);
        crust_set_error(run->context, declaration->loc.source, declaration->loc.offset,
                      message);
        return false;
    }
    *result = address;
    return true;
}

bool crust_run_link(CrustRun *run, const char *path)
{
    NativeModule *module;
    void *handle;
    char message[512];
    if (path == NULL || path[0] == '\0') return run_error(run, "native path is empty");
    if (strchr(path, '/') == NULL)
        return run_error(run, "native path must contain '/' (use './' for a current-directory file)");
    module = crust_try_alloc(run->context, sizeof(*module), CRUST_ALIGNOF(NativeModule));
    if (module == NULL) return false;
    handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (handle == NULL) {
        const char *error = dlerror();
        (void)snprintf(message, sizeof(message), "cannot load native input '%s': %s",
                       path, error == NULL ? "loader failure" : error);
        return run_error(run, message);
    }
    module->handle = handle;
    module->next = run->state->modules;
    run->state->modules = module;
    return true;
}

bool crust_run_init(CrustRun *run, CrustContext *context, CrustSource *source,
                  int32_t argc, char **argv)
{
    CrustEvalOptions options;
    memset(run, 0, sizeof(*run));
    run->context = context;
    run->source = source;
    run->argc = argc;
    run->argv = argv;
    run->read = crust_run_read;
    run->execute = crust_run_execute;
    if (source->identity == UINT64_MAX)
        return run_error(run, "no identity remains for host inputs");
    run->next_identity = source->identity + 1;
    run->state = crust_try_alloc(context, sizeof(*run->state), CRUST_ALIGNOF(CrustRunState));
    if (run->state == NULL) return false;
    options.resolve = resolve_native;
    options.user = run;
    run->eval = crust_eval_create(context, &options);
    run->state->initial_eval = run->eval;
    return run->eval != NULL;
}

bool crust_run_destroy(CrustRun *run)
{
    NativeModule *module;
    bool success = true;
    if (run->state == NULL) return true;
    if (run->state->initial_eval != NULL) crust_eval_destroy(run->state->initial_eval);
    for (module = run->state->modules; module != NULL; module = module->next) {
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
    run->state = NULL;
    return success;
}

bool crust_run_check_unit(CrustRun *run, CrustUnit *unit)
{
    CrustDecl *declaration;
    for (declaration = unit->declarations; declaration != NULL; declaration = declaration->next) {
        if (crust_map_get(&run->scope.locals, (uintptr_t)declaration->name) != NULL) {
            crust_set_error(run->context, declaration->loc.source, declaration->loc.offset,
                          "declaration conflicts with a root local");
            return false;
        }
    }
    if (!crust_collect_unit(run->context, unit) || !crust_resolve_unit(run->context, unit) ||
        !crust_check_unit(run->context, unit)) return false;
    for (declaration = unit->declarations; declaration != NULL; declaration = declaration->next) {
        if (!crust_eval_prepare(run->eval, declaration)) return false;
    }
    return true;
}

bool crust_run_read(CrustRun *run, void **result)
{
    CrustAction action;
    CrustAction *stored;
    *result = NULL;
    if (!crust_read_one(run->context, run->source, run->cursor, run->source->size,
                      &action)) return false;
    run->cursor = action.end;
    if (action.declaration == NULL && action.statement == NULL) return true;
    stored = crust_try_alloc(run->context, sizeof(*stored), CRUST_ALIGNOF(CrustAction));
    if (stored == NULL) return false;
    *stored = action;
    *result = stored;
    return true;
}

bool crust_run_execute(CrustRun *run, void *data)
{
    CrustAction *action = data;
    bool returned;
    int32_t status;
    if ((action->declaration == NULL) == (action->statement == NULL))
        return run_error(run, "CRUST action must contain one declaration or statement");
    if (action->declaration != NULL) {
        CrustUnit *unit = crust_try_alloc(run->context, sizeof(*unit), CRUST_ALIGNOF(CrustUnit));
        if (unit == NULL) return false;
        unit->source = action->declaration->loc.source;
        unit->declarations = action->declaration;
        if (run->context->last_unit == NULL) run->context->units = unit;
        else run->context->last_unit->next = unit;
        run->context->last_unit = unit;
        return crust_run_check_unit(run, unit);
    }
    if (!crust_check_root(run->context, &run->scope, action->statement)) return false;
    if (!crust_eval_statement(run->eval, action->statement, &returned, &status)) return false;
    if (returned) {
        run->returned = true;
        run->status = status;
    }
    return true;
}

bool crust_run_loop(CrustRun *run)
{
    while (!run->returned) {
        CrustSource *source = run->source;
        size_t begin = run->cursor;
        size_t consumed;
        bool (*reader)(CrustRun *, void **) = run->read;
        bool (*execute)(CrustRun *, void *) = run->execute;
        void *action = NULL;
        if (reader == NULL || execute == NULL)
            return run_error(run, "root reader and executor must be callable");
        if (!reader(run, &action)) {
            if (run->context->error_count == 0) run_error(run, "root reader failed without a diagnostic");
            return false;
        }
        if (run->context->error_count != 0) return false;
        if (run->source != source) {
            run->source = source;
            return run_error(run, "reader changed the source");
        }
        if (run->cursor < begin || run->cursor > source->size)
            return run_error(run, "reader changed the source or returned an invalid cursor");
        if (run->returned) break;
        if (action == NULL) {
            if (run->cursor != source->size)
                return run_error(run, "reader returned EOF with unread bytes");
            break;
        }
        if (run->cursor == begin)
            return run_error(run, "reader returned an action without input progress");
        consumed = run->cursor;
        if (!execute(run, action)) {
            if (run->context->error_count == 0) run_error(run, "root executor failed without a diagnostic");
            return false;
        }
        if (run->context->error_count != 0) return false;
        if (run->source != source) {
            run->source = source;
            return run_error(run, "executor changed the source");
        }
        if (run->cursor < consumed || run->cursor > source->size)
            return run_error(run, "executor changed the source or returned an invalid cursor");
    }
    if (run->status < 0 || run->status > 255)
        return run_error(run, "root status must be between zero and 255");
    return true;
}
