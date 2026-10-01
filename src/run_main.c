#define _XOPEN_SOURCE 700
#include "rmd0_run.h"
#include "rmd0_host.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "prelude.inc"

static char *root_path(RmdContext *context, const char *path)
{
    char *directory;
    char *result;
    size_t prefix;
    size_t suffix = strlen(path);
    if (path[0] == '/')
        return rmd_try_copy_string(context, (const unsigned char *)path, suffix);
    directory = getcwd(NULL, 0);
    if (directory == NULL) {
        rmd_set_error(context, NULL, 0, "cannot read working directory");
        return NULL;
    }
    prefix = strlen(directory);
    if (suffix > SIZE_MAX - prefix - 2) {
        free(directory);
        rmd_set_error(context, NULL, 0, "root path is too long");
        return NULL;
    }
    result = rmd_try_alloc(context, prefix + suffix + 2, 1);
    if (result != NULL) {
        memcpy(result, directory, prefix);
        result[prefix] = '/';
        memcpy(result + prefix + 1, path, suffix + 1);
    }
    free(directory);
    return result;
}

static bool installed_program(RmdContext *context)
{
    size_t index;
    for (index = 0; index < sizeof(installed_sources) / sizeof(installed_sources[0]); ++index) {
        RmdUnit *unit;
        if (!rmd_read(context, &installed_sources[index], &unit)) return false;
    }
    return rmd_collect(context) && rmd_resolve(context) && rmd_check(context);
}

static bool bind_run(RmdRun *run, RmdRun **storage)
{
    RmdContext *context = run->context;
    RmdName *type_name = rmd_try_intern(context, (const unsigned char *)"RmdRun", 6);
    RmdSymbol *type;
    RmdSymbol *parameter;
    if (type_name == NULL) return false;
    type = rmd_map_get(&context->globals, (uintptr_t)type_name);
    assert(type != NULL && type->kind == RMD_SYM_RECORD && type->type->size == sizeof(RmdRun));
    parameter = rmd_try_alloc(context, sizeof(*parameter), RMD_ALIGNOF(RmdSymbol));
    if (parameter == NULL) return false;
    parameter->kind = RMD_SYM_PARAM;
    parameter->name = rmd_try_intern(context, (const unsigned char *)"run", 3);
    parameter->loc.source = run->source;
    parameter->type = rmd_try_pointer_type(context, type->type);
    if (parameter->name == NULL || parameter->type == NULL ||
        !rmd_try_map_set(context, &run->scope.locals, (uintptr_t)parameter->name, parameter))
        return false;
    run->scope.scope = parameter;
    return rmd_eval_bind(run->eval, parameter, storage);
}

static int flush_output(int status)
{
    if (fflush(stdout) != 0 || ferror(stdout)) {
        fputs("rmd: cannot write standard output\n", stderr);
        if (status == 0) status = 1;
    }
    return status;
}

int main(int argc, char **argv)
{
    RmdContext context;
    RmdSource source_input;
    RmdRun run;
    RmdRun *run_pointer = &run;
    RmdUnit *unit;
    unsigned char *bytes = NULL;
    bool initialized = false;
    int status = 1;
    if (argc < 2) {
        fputs("usage: rmd ROOT [ARGUMENT...]\n", stderr);
        return 1;
    }
    if (strcmp(argv[1], "--help") == 0) {
        puts("usage: rmd ROOT [ARGUMENT...]\nExecute the root compilation program in source order.");
        return flush_output(0);
    }
    if (strcmp(argv[1], "--version") == 0) {
        puts("rmd " RMD_VERSION " (source runner, x86-64 System V)");
        return flush_output(0);
    }
    rmd_context_init(&context, NULL);
    memset(&source_input, 0, sizeof(source_input));
    source_input.identity = sizeof(installed_sources) / sizeof(installed_sources[0]) + 1;
    source_input.path = root_path(&context, argv[1]);
    if (source_input.path == NULL) goto done;
    if (rmd0_host_read_file(source_input.path, &bytes, &source_input.size) != 0) {
        char message[512];
        (void)snprintf(message, sizeof(message),
                       "cannot read root '%s' (input or allocation failure)", argv[1]);
        rmd_set_error(&context, NULL, 0, message);
        goto done;
    }
    source_input.bytes = bytes;
    if (!installed_program(&context)) goto done;
    initialized = true;
    if (!rmd_run_init(&run, &context, &source_input, argc - 2, argv + 2)) goto done;
    for (unit = context.units; unit != NULL; unit = unit->next) {
        RmdDecl *declaration;
        for (declaration = unit->declarations; declaration != NULL; declaration = declaration->next) {
            if (!rmd_eval_prepare(run.eval, declaration)) goto done;
        }
    }
    if (!bind_run(&run, &run_pointer) || !rmd_run_loop(&run)) goto done;
    status = run.status;
done:
    if (context.error_count != 0) {
        rmd_run_diagnostic(&context);
        if (status == 0) status = 1;
    }
    if (initialized && !rmd_run_destroy(&run) && status == 0) status = 1;
    status = flush_output(status);
    rmd_context_destroy(&context);
    free(bytes);
    return status;
}
