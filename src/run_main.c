#define _XOPEN_SOURCE 700
#include "crust0_host.h"
#include "crust0_run.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "prelude.inc"

static char *root_path(CrustContext *context, const char *path)
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

static bool installed_program(CrustContext *context)
{
    size_t index;
    for (index = 0; index < sizeof(installed_sources) / sizeof(installed_sources[0]); ++index) {
        CrustUnit *unit;
        if (!crust_read(context, &installed_sources[index], &unit))
            return false;
    }
    return crust_collect(context) && crust_resolve(context) && crust_check(context);
}

static bool bind_run(CrustRun *run, CrustRun **storage)
{
    CrustContext *context = run->context;
    CrustName *type_name =
        crust_try_intern(context, (const unsigned char *)"CrustRun", sizeof("CrustRun") - 1);
    CrustSymbol *type;
    CrustSymbol *parameter;
    if (type_name == NULL)
        return false;
    type = crust_map_get(&context->globals, (uintptr_t)type_name);
    assert(type != NULL && type->kind == CRUST_SYM_RECORD && type->type->size == sizeof(CrustRun));
    parameter = crust_try_alloc(context, sizeof(*parameter), CRUST_ALIGNOF(CrustSymbol));
    if (parameter == NULL)
        return false;
    parameter->kind = CRUST_SYM_PARAM;
    parameter->name = crust_try_intern(context, (const unsigned char *)"run", 3);
    parameter->loc.source = run->source;
    parameter->type = crust_try_pointer_type(context, type->type);
    if (parameter->name == NULL || parameter->type == NULL ||
        !crust_try_map_set(context, &run->scope.locals, (uintptr_t)parameter->name, parameter))
        return false;
    run->scope.scope = parameter;
    return crust_eval_bind(run->eval, parameter, storage);
}

static int flush_output(int status)
{
    if (fflush(stdout) != 0 || ferror(stdout)) {
        fputs("crust: cannot write standard output\n", stderr);
        if (status == 0)
            status = 1;
    }
    return status;
}

static bool prepare_installed_program(CrustRun *run)
{
    CrustContext *context = run->context;
    CrustUnit *unit;
    for (unit = context->units; unit != NULL; unit = unit->next) {
        CrustDecl *declaration;
        for (declaration = unit->declarations; declaration != NULL;
             declaration = declaration->next) {
            if (!crust_eval_prepare(run->eval, declaration))
                return false;
        }
    }
    return true;
}

static bool read_root(CrustContext *context, CrustSource *source, const char *path,
                      unsigned char **bytes)
{
    source->path = root_path(context, path);
    if (source->path == NULL)
        return false;
    if (crust0_host_read_file(source->path, bytes, &source->size) != 0) {
        char message[512];
        (void)snprintf(message, sizeof(message),
                       "cannot read root '%s' (input or allocation failure)", path);
        crust_set_error(context, NULL, 0, message);
        return false;
    }
    source->bytes = *bytes;
    return true;
}

int main(int argc, char **argv)
{
    CrustContext context;
    CrustSource source_input;
    CrustRun run;
    CrustRun *run_pointer = &run;
    unsigned char *bytes = NULL;
    bool initialized = false;
    int status = 1;
    if (argc < 2) {
        fputs("usage: crust ROOT [ARGUMENT...]\n", stderr);
        return 1;
    }
    if (strcmp(argv[1], "--help") == 0) {
        puts("usage: crust ROOT [ARGUMENT...]\nExecute the root compilation program in source "
             "order.");
        return flush_output(0);
    }
    if (strcmp(argv[1], "--version") == 0) {
        puts("crust " CRUST_VERSION " (source runner, x86-64 System V)");
        return flush_output(0);
    }
    crust_context_init(&context, NULL);
    memset(&source_input, 0, sizeof(source_input));
    source_input.identity = sizeof(installed_sources) / sizeof(installed_sources[0]) + 1;
    if (!read_root(&context, &source_input, argv[1], &bytes))
        goto done;
    if (!installed_program(&context))
        goto done;
    initialized = true;
    if (!crust_run_init(&run, &context, &source_input, argc - 2, argv + 2))
        goto done;
    if (!prepare_installed_program(&run))
        goto done;
    if (!bind_run(&run, &run_pointer) || !crust_run_loop(&run))
        goto done;
    status = run.status;
done:
    if (context.error_count != 0) {
        crust_run_diagnostic(&context);
        if (status == 0)
            status = 1;
    }
    if (initialized && !crust_run_destroy(&run) && status == 0)
        status = 1;
    status = flush_output(status);
    crust_context_destroy(&context);
    free(bytes);
    return status;
}
