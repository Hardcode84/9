#define _POSIX_C_SOURCE 200809L
#include "rmd0.h"
#include "rmd0_host.h"
#include "rmd0_x64.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void usage(FILE *stream)
{
    fputs("usage: rmd0 [--check | --prepare | -S] [--library | --entry NAME]\n"
          "            [--export NAME] [-o OUTPUT] SOURCE...\n", stream);
}

static void rmd_driver_diagnostic(const RmdContext *ctx)
{
    const RmdSource *source = ctx->error_loc.source;
    size_t line = 1;
    size_t column = 1;
    size_t index;
    if (source == NULL) {
        fprintf(stderr, "rmd0: error: %s\n", ctx->error);
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

static bool rmd_driver_names(RmdContext *ctx)
{
    RmdFailureFrame failure;
    RmdUnit *unit;
    failure.previous = ctx->failure;
    ctx->failure = &failure;
    if (setjmp(failure.jump) != 0) {
        ctx->failure = failure.previous;
        return false;
    }
    for (unit = ctx->units; unit != NULL; unit = unit->next) {
        RmdDecl *decl;
        for (decl = unit->declarations; decl != NULL; decl = decl->next) {
            if (decl->kind != RMD_D_RECORD && decl->link_name == NULL) {
                char buffer[96];
                int length = snprintf(buffer, sizeof(buffer), "_rmd0_u%" PRIu64 "_d%" PRIu64,
                                      decl->unit_identity, decl->identity);
                if (length < 0 || (size_t)length >= sizeof(buffer)) {
                    rmd_fail(ctx, decl->loc, "cannot format native link identity");
                }
                decl->link_name = rmd_copy_string(ctx, (const unsigned char *)buffer,
                                                 (size_t)length);
            }
        }
    }
    ctx->failure = failure.previous;
    return true;
}

static RmdDecl *rmd_driver_find(const RmdContext *ctx, const char *name)
{
    RmdUnit *unit;
    for (unit = ctx->units; unit != NULL; unit = unit->next) {
        RmdDecl *decl;
        for (decl = unit->declarations; decl != NULL; decl = decl->next) {
            if (strcmp(decl->name->text, name) == 0) {
                return decl;
            }
        }
    }
    return NULL;
}

static bool hosted_entry(const RmdDecl *decl)
{
    const RmdType *type;
    const RmdType *argv;
    if (decl == NULL || decl->kind != RMD_D_FUNCTION) {
        return false;
    }
    type = decl->type;
    if (type->kind != RMD_T_FUNCTION || type->param_count != 2 ||
        type->base->kind != RMD_T_I32 || type->params[0]->kind != RMD_T_I32) {
        return false;
    }
    argv = type->params[1];
    return argv->kind == RMD_T_POINTER && argv->base->kind == RMD_T_POINTER &&
           argv->base->base->kind == RMD_T_U8;
}

static bool emit_file(RmdX64Program *program, const char *path)
{
    FILE *file;
    char *temporary;
    size_t length;
    int descriptor;
    bool success;
    struct stat info;
    if (path == NULL || strcmp(path, "-") == 0) {
        success = rmd_x64_emit_program(program, stdout);
        if (fflush(stdout) != 0) {
            fprintf(stderr, "rmd0: cannot flush output: %s\n", strerror(errno));
            success = false;
        }
        return success;
    }
    if (lstat(path, &info) == 0) {
        if (!S_ISREG(info.st_mode)) {
            file = fopen(path, "wb");
            if (file == NULL) {
                fprintf(stderr, "rmd0: cannot open output %s: %s\n", path, strerror(errno));
                return false;
            }
            success = rmd_x64_emit_program(program, file);
            if (fclose(file) != 0) {
                fprintf(stderr, "rmd0: cannot close output: %s\n", strerror(errno));
                success = false;
            }
            return success;
        }
    } else if (errno != ENOENT) {
        fprintf(stderr, "rmd0: cannot inspect output %s: %s\n", path, strerror(errno));
        return false;
    }
    length = strlen(path);
    if (length > SIZE_MAX - 16) {
        fputs("rmd0: output path is too long\n", stderr);
        return false;
    }
    temporary = malloc(length + 16);
    if (temporary == NULL) {
        fputs("rmd0: cannot allocate output path\n", stderr);
        return false;
    }
    memcpy(temporary, path, length);
    memcpy(temporary + length, ".tmp.XXXXXX", 12);
    descriptor = mkstemp(temporary);
    if (descriptor < 0) {
        fprintf(stderr, "rmd0: cannot create output %s: %s\n", path, strerror(errno));
        free(temporary);
        return false;
    }
    file = fdopen(descriptor, "w");
    if (file == NULL) {
        fprintf(stderr, "rmd0: cannot open output stream: %s\n", strerror(errno));
        if (close(descriptor) != 0) {
            fprintf(stderr, "rmd0: cannot close output: %s\n", strerror(errno));
        }
        if (unlink(temporary) != 0) {
            fprintf(stderr, "rmd0: cannot remove output temporary: %s\n", strerror(errno));
        }
        free(temporary);
        return false;
    }
    success = rmd_x64_emit_program(program, file);
    if (fclose(file) != 0) {
        fprintf(stderr, "rmd0: cannot close output: %s\n", strerror(errno));
        success = false;
    }
    if (success && rename(temporary, path) != 0) {
        fprintf(stderr, "rmd0: cannot publish output %s: %s\n", path, strerror(errno));
        success = false;
    }
    if (!success && unlink(temporary) != 0) {
        fprintf(stderr, "rmd0: cannot remove output temporary: %s\n", strerror(errno));
    }
    free(temporary);
    return success;
}

int main(int argc, char **argv)
{
    enum { EMIT, CHECK, PREPARE } mode = EMIT;
    RmdContext ctx;
    RmdSource *sources;
    RmdDecl *entry = NULL;
    RmdX64Program *program = NULL;
    const char *entry_name = "main";
    const char *output = NULL;
    bool library = false;
    bool exports = false;
    size_t source_count = 0;
    size_t index;
    int argument;
    int status = 1;
    sources = calloc((size_t)argc, sizeof(*sources));
    if (sources == NULL) {
        fputs("rmd0: cannot allocate input list\n", stderr);
        return 1;
    }
    rmd_context_init(&ctx, NULL);
    for (argument = 1; argument < argc; ++argument) {
        const char *arg = argv[argument];
        if (strcmp(arg, "--help") == 0) {
            usage(stdout);
            status = 0;
            goto done;
        } else if (strcmp(arg, "--version") == 0) {
            puts("rmd0 " RMD_VERSION " (x86-64 System V)");
            status = 0;
            goto done;
        } else if (strcmp(arg, "--check") == 0) {
            mode = CHECK;
        } else if (strcmp(arg, "--prepare") == 0) {
            mode = PREPARE;
        } else if (strcmp(arg, "-S") == 0) {
            mode = EMIT;
        } else if (strcmp(arg, "--library") == 0) {
            library = true;
        } else if (strcmp(arg, "-o") == 0 || strcmp(arg, "--entry") == 0 ||
                   strcmp(arg, "--export") == 0) {
            if (++argument == argc) {
                fprintf(stderr, "rmd0: missing argument for %s\n", arg);
                goto done;
            }
            if (strcmp(arg, "-o") == 0) output = argv[argument];
            else if (strcmp(arg, "--entry") == 0) entry_name = argv[argument];
            else exports = true;
        } else if (arg[0] == '-') {
            fprintf(stderr, "rmd0: unknown option %s\n", arg);
            goto done;
        } else {
            sources[source_count++].path = arg;
        }
    }
    if (source_count == 0) {
        usage(stderr);
        goto done;
    }
    if (output != NULL && mode != EMIT) {
        fputs("rmd0: -o requires assembly emission\n", stderr);
        goto done;
    }
    for (index = 0; index < source_count; ++index) {
        unsigned char *bytes;
        RmdUnit *unit;
        sources[index].identity = index + 1;
        if (rmd0_host_read_file(sources[index].path, &bytes, &sources[index].size) != 0) {
            fprintf(stderr, "rmd0: cannot read %s (input or allocation failure)\n",
                    sources[index].path);
            goto done;
        } else {
            sources[index].bytes = bytes;
        }
        if (!rmd_read(&ctx, &sources[index], &unit)) goto compile_error;
    }
    if (!rmd_collect(&ctx) || !rmd_resolve(&ctx) || !rmd_check(&ctx)) goto compile_error;
    if (exports) {
        for (argument = 1; argument < argc; ++argument) {
            if (strcmp(argv[argument], "-o") == 0 || strcmp(argv[argument], "--entry") == 0) {
                ++argument;
            } else if (strcmp(argv[argument], "--export") == 0) {
                RmdDecl *decl = rmd_driver_find(&ctx, argv[++argument]);
                if (decl == NULL || (decl->kind != RMD_D_FUNCTION && decl->kind != RMD_D_CONST)) {
                    fprintf(stderr, "rmd0: export '%s' must name a defined function or constant\n",
                            argv[argument]);
                    goto done;
                }
                decl->link_name = argv[argument];
            }
        }
    }
    if (mode == CHECK) {
        status = 0;
        goto done;
    }
    if (!rmd_driver_names(&ctx)) goto compile_error;
    if (!library) {
        entry = rmd_driver_find(&ctx, entry_name);
        if (!hosted_entry(entry)) {
            fprintf(stderr, "rmd0: entry '%s' must be a defined fn(i32, **u8) -> i32\n",
                    entry_name);
            goto done;
        }
    }
    if (!rmd_x64_prepare(&ctx, &program, entry)) goto compile_error;
    if (mode == PREPARE || emit_file(program, output)) {
        status = 0;
        goto done;
    }
    if (ctx.error_count == 0) goto done;
compile_error:
    rmd_driver_diagnostic(&ctx);
done:
    if (status == 0 && fflush(stdout) != 0) {
        fprintf(stderr, "rmd0: cannot flush standard output: %s\n", strerror(errno));
        status = 1;
    }
    rmd_context_destroy(&ctx);
    for (index = 0; index < source_count; ++index) {
        free((void *)sources[index].bytes);
    }
    free(sources);
    return status;
}
