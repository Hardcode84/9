/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0_run.h"
#include "run_platform.h"

#include <stdio.h>
#include <string.h>

struct CrustRunState {
    CrustNativeModule *modules;
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
        if (source->bytes[index] == '\n') {
            ++line;
            column = 1;
        } else
            ++column;
    }
    fprintf(stderr, "%s:%zu:%zu: error: %s\n", source->path, line, column, context->error);
}

static bool run_error(CrustRun *run, const char *message)
{
    crust_set_error(run->context, run->source,
                    run->cursor <= run->source->size ? run->cursor : run->source->size, message);
    return false;
}

static bool resolve_native(void *user, CrustDecl *declaration, void **result)
{
    CrustRun *run = user;
    return crust_run_native_resolve(run, run->state->modules, declaration, result);
}

bool crust_run_link(CrustRun *run, const char *path)
{
    return crust_run_native_link(run, &run->state->modules, path);
}

bool crust_run_init(CrustRun *run, CrustContext *context, CrustSource *source, int32_t argc,
                    char **argv)
{
    CrustEvalOptions options = {NULL, NULL, 0};
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
    if (run->state == NULL)
        return false;
    options.resolve = resolve_native;
    options.user = run;
    run->eval = crust_eval_create(context, &options);
    run->state->initial_eval = run->eval;
    return run->eval != NULL;
}

bool crust_run_destroy(CrustRun *run)
{
    bool success;
    if (run->state == NULL)
        return true;
    if (run->state->initial_eval != NULL)
        crust_eval_destroy(run->state->initial_eval);
    success = crust_run_native_destroy(run, run->state->modules);
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
        !crust_check_unit(run->context, unit))
        return false;
    for (declaration = unit->declarations; declaration != NULL; declaration = declaration->next) {
        if (!crust_eval_prepare(run->eval, declaration))
            return false;
    }
    return true;
}

bool crust_run_read(CrustRun *run, void *user, void **result)
{
    CrustAction action;
    CrustAction *stored;
    (void)user;
    *result = NULL;
    if (!crust_read_one(run->context, run->source, run->cursor, run->source->size, &action))
        return false;
    run->cursor = action.end;
    if (action.declaration == NULL && action.statement == NULL)
        return true;
    stored = crust_try_alloc(run->context, sizeof(*stored), CRUST_ALIGNOF(CrustAction));
    if (stored == NULL)
        return false;
    *stored = action;
    *result = stored;
    return true;
}

bool crust_run_execute(CrustRun *run, void *user, void *data)
{
    CrustAction *action = data;
    bool returned;
    int32_t status;
    (void)user;
    if ((action->declaration == NULL) == (action->statement == NULL))
        return run_error(run, "CRUST action must contain one declaration or statement");
    if (action->declaration != NULL) {
        CrustUnit *unit = crust_try_alloc(run->context, sizeof(*unit), CRUST_ALIGNOF(CrustUnit));
        if (unit == NULL)
            return false;
        unit->source = action->declaration->loc.source;
        unit->declarations = action->declaration;
        if (run->context->last_unit == NULL)
            run->context->units = unit;
        else
            run->context->last_unit->next = unit;
        run->context->last_unit = unit;
        return crust_run_check_unit(run, unit);
    }
    if (!crust_check_root(run->context, &run->scope, action->statement))
        return false;
    if (!crust_eval_statement(run->eval, action->statement, &returned, &status))
        return false;
    if (returned) {
        run->returned = true;
        run->status = status;
    }
    return true;
}

static bool read_action(CrustRun *run, bool (*reader)(CrustRun *, void *, void **), void *user,
                        void **action)
{
    CrustSource *source = run->source;
    size_t begin = run->cursor;
    if (!reader(run, user, action)) {
        if (run->context->error_count == 0)
            run_error(run, "root reader failed without a diagnostic");
        return false;
    }
    if (run->context->error_count != 0)
        return false;
    if (run->source != source) {
        run->source = source;
        return run_error(run, "reader changed the source");
    }
    if (run->cursor < begin || run->cursor > source->size)
        return run_error(run, "reader changed the source or returned an invalid cursor");
    return true;
}

static bool execute_action(CrustRun *run, bool (*execute)(CrustRun *, void *, void *), void *user,
                           void *action)
{
    CrustSource *source = run->source;
    size_t consumed = run->cursor;
    if (!execute(run, user, action)) {
        if (run->context->error_count == 0)
            run_error(run, "root executor failed without a diagnostic");
        return false;
    }
    if (run->context->error_count != 0)
        return false;
    if (run->source != source) {
        run->source = source;
        return run_error(run, "executor changed the source");
    }
    if (run->cursor < consumed || run->cursor > source->size)
        return run_error(run, "executor changed the source or returned an invalid cursor");
    return true;
}

bool crust_run_loop(CrustRun *run)
{
    while (!run->returned) {
        CrustSource *source = run->source;
        size_t begin = run->cursor;
        bool (*reader)(CrustRun *, void *, void **) = run->read;
        bool (*execute)(CrustRun *, void *, void *) = run->execute;
        void *user = run->user;
        void *action = NULL;
        if (reader == NULL || execute == NULL)
            return run_error(run, "root reader and executor must be callable");
        if (!read_action(run, reader, user, &action))
            return false;
        if (run->returned)
            break;
        if (action == NULL) {
            if (run->cursor != source->size)
                return run_error(run, "reader returned EOF with unread bytes");
            break;
        }
        if (run->cursor == begin)
            return run_error(run, "reader returned an action without input progress");
        if (!execute_action(run, execute, user, action))
            return false;
    }
    if (run->status < 0 || run->status > 255)
        return run_error(run, "root status must be between zero and 255");
    return true;
}
