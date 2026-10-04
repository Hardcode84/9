/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0.h"
#include "crust0_host.h"
#include "driver_platform.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void usage(FILE *stream)
{
    fputs("usage: crust0 [--check | --prepare | -S] [--library | --entry NAME]\n"
          "            [--export NAME] [-o OUTPUT] SOURCE...\n",
          stream);
}

static void crust_driver_diagnostic(const CrustContext *ctx)
{
    const CrustSource *source = ctx->error_loc.source;
    size_t line = 1;
    size_t column = 1;
    size_t index;
    if (source == NULL) {
        fprintf(stderr, "crust0: error: %s\n", ctx->error);
        return;
    }
    for (index = 0; index < ctx->error_loc.offset && index < source->size; ++index) {
        if (source->bytes[index] == '\n') {
            ++line;
            column = 1;
        } else {
            ++column;
        }
    }
    fprintf(stderr, "%s:%zu:%zu: error: %s\n", source->path, line, column, ctx->error);
}

static bool crust_driver_names(CrustContext *ctx)
{
    CrustFailureFrame failure;
    CrustUnit *unit;
    const char *private_name;
    failure.previous = ctx->failure;
    ctx->failure = &failure;
    if (setjmp(failure.jump) != 0) {
        ctx->failure = failure.previous;
        return false;
    }
    private_name = crust_copy_string(ctx, NULL, 0);
    for (unit = ctx->units; unit != NULL; unit = unit->next) {
        CrustDecl *decl;
        for (decl = unit->declarations; decl != NULL; decl = decl->next) {
            if (decl->kind != CRUST_D_RECORD && decl->link_name == NULL) {
                decl->link_name = private_name;
            }
        }
    }
    ctx->failure = failure.previous;
    return true;
}

static CrustDecl *crust_driver_find(const CrustContext *ctx, const char *name)
{
    CrustUnit *unit;
    for (unit = ctx->units; unit != NULL; unit = unit->next) {
        CrustDecl *decl;
        for (decl = unit->declarations; decl != NULL; decl = decl->next) {
            if (strcmp(decl->name->text, name) == 0) {
                return decl;
            }
        }
    }
    return NULL;
}

static bool hosted_entry(const CrustDecl *decl)
{
    const CrustType *type;
    const CrustType *argv;
    if (decl == NULL || decl->kind != CRUST_D_FUNCTION) {
        return false;
    }
    type = decl->type;
    if (type->kind != CRUST_T_FUNCTION || type->param_count != 2 ||
        type->base->kind != CRUST_T_I32 || type->params[0]->kind != CRUST_T_I32) {
        return false;
    }
    argv = type->params[1];
    return argv->kind == CRUST_T_POINTER && argv->base->kind == CRUST_T_POINTER &&
           argv->base->base->kind == CRUST_T_U8;
}

typedef struct {
    CrustSource *sources;
    size_t source_count;
    const char *entry_name;
    const char *output;
    enum { EMIT, CHECK, PREPARE } mode;
    bool library;
    bool exports;
} DriverOptions;

typedef enum { ARGUMENTS_ERROR, ARGUMENTS_DONE, ARGUMENTS_COMPILE } ArgumentResult;

static bool parse_argument(DriverOptions *options, int argc, char **argv, int *argument)
{
    const char *arg = argv[*argument];
    if (strcmp(arg, "--check") == 0) {
        options->mode = CHECK;
    } else if (strcmp(arg, "--prepare") == 0) {
        options->mode = PREPARE;
    } else if (strcmp(arg, "-S") == 0) {
        options->mode = EMIT;
    } else if (strcmp(arg, "--library") == 0) {
        options->library = true;
    } else if (strcmp(arg, "-o") == 0 || strcmp(arg, "--entry") == 0 ||
               strcmp(arg, "--export") == 0) {
        if (++*argument == argc) {
            fprintf(stderr, "crust0: missing argument for %s\n", arg);
            return false;
        }
        if (strcmp(arg, "-o") == 0)
            options->output = argv[*argument];
        else if (strcmp(arg, "--entry") == 0)
            options->entry_name = argv[*argument];
        else
            options->exports = true;
    } else if (arg[0] == '-') {
        fprintf(stderr, "crust0: unknown option %s\n", arg);
        return false;
    } else {
        options->sources[options->source_count++].path = arg;
    }
    return true;
}

static ArgumentResult parse_arguments(DriverOptions *options, int argc, char **argv)
{
    int argument;
    for (argument = 1; argument < argc; ++argument) {
        const char *arg = argv[argument];
        if (strcmp(arg, "--help") == 0) {
            usage(stdout);
            return ARGUMENTS_DONE;
        } else if (strcmp(arg, "--version") == 0) {
            puts("crust0 " CRUST_VERSION " (x86-64 System V)");
            return ARGUMENTS_DONE;
        } else if (!parse_argument(options, argc, argv, &argument))
            return ARGUMENTS_ERROR;
    }
    if (options->source_count == 0) {
        usage(stderr);
        return ARGUMENTS_ERROR;
    }
    if (options->output != NULL && options->mode != EMIT) {
        fputs("crust0: -o requires assembly emission\n", stderr);
        return ARGUMENTS_ERROR;
    }
    return ARGUMENTS_COMPILE;
}

static bool read_sources(CrustContext *ctx, const DriverOptions *options)
{
    size_t index;
    for (index = 0; index < options->source_count; ++index) {
        unsigned char *bytes;
        CrustUnit *unit;
        options->sources[index].identity = index + 1;
        if (crust0_host_read_file(options->sources[index].path, &bytes,
                                  &options->sources[index].size) != 0) {
            fprintf(stderr, "crust0: cannot read %s (input or allocation failure)\n",
                    options->sources[index].path);
            return false;
        } else {
            options->sources[index].bytes = bytes;
        }
        if (!crust_read(ctx, &options->sources[index], &unit))
            return false;
    }
    if (!crust_collect(ctx) || !crust_resolve(ctx) || !crust_check(ctx))
        return false;
    return true;
}

static bool export_symbols(CrustContext *ctx, int argc, char **argv)
{
    int argument;
    for (argument = 1; argument < argc; ++argument) {
        if (strcmp(argv[argument], "-o") == 0 || strcmp(argv[argument], "--entry") == 0) {
            ++argument;
        } else if (strcmp(argv[argument], "--export") == 0) {
            CrustDecl *decl = crust_driver_find(ctx, argv[++argument]);
            if (decl == NULL || (decl->kind != CRUST_D_FUNCTION && decl->kind != CRUST_D_CONST)) {
                fprintf(stderr, "crust0: export '%s' must name a defined function or constant\n",
                        argv[argument]);
                return false;
            }
            decl->link_name = argv[argument];
        }
    }
    return true;
}

static bool compile_program(CrustContext *ctx, const DriverOptions *options, int argc, char **argv)
{
    CrustDecl *entry = NULL;
    CrustX64Program *program = NULL;
    if (!read_sources(ctx, options))
        goto compile_error;
    if (options->exports && !export_symbols(ctx, argc, argv))
        return false;
    if (options->mode == CHECK) {
        return true;
    }
    if (!crust_driver_names(ctx))
        goto compile_error;
    if (!options->library) {
        entry = crust_driver_find(ctx, options->entry_name);
        if (!hosted_entry(entry)) {
            fprintf(stderr, "crust0: entry '%s' must be a defined fn(i32, **u8) -> i32\n",
                    options->entry_name);
            return false;
        }
    }
    if (!crust_x64_prepare(ctx, &program, entry))
        goto compile_error;
    if (options->mode == PREPARE || crust_driver_emit_file(program, options->output)) {
        return true;
    }
    if (ctx->error_count == 0)
        return false;
compile_error:
    if (ctx->error_count != 0)
        crust_driver_diagnostic(ctx);
    return false;
}

int main(int argc, char **argv)
{
    DriverOptions options = {.entry_name = "main", .mode = EMIT};
    CrustContext ctx;
    ArgumentResult parsed;
    size_t index;
    int status = 1;
    options.sources = calloc((size_t)argc, sizeof(*options.sources));
    if (options.sources == NULL) {
        fputs("crust0: cannot allocate input list\n", stderr);
        return 1;
    }
    crust_context_init(&ctx, NULL);
    parsed = parse_arguments(&options, argc, argv);
    if (parsed == ARGUMENTS_DONE)
        status = 0;
    else if (parsed == ARGUMENTS_COMPILE && compile_program(&ctx, &options, argc, argv))
        status = 0;
    if (status == 0 && fflush(stdout) != 0) {
        fprintf(stderr, "crust0: cannot flush standard output: %s\n", strerror(errno));
        status = 1;
    }
    crust_context_destroy(&ctx);
    for (index = 0; index < options.source_count; ++index) {
        free((void *)options.sources[index].bytes);
    }
    free(options.sources);
    return status;
}
