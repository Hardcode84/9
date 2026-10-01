#define _XOPEN_SOURCE 700
#include "driver.h"
#include "rmd0_host.h"
#include "rmd0_stage.h"
#include "rmd0_x64.h"

#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

typedef int32_t (*StageEntry)(RmdBuild *request);
typedef char StagePointerSize[(sizeof(StageEntry) == sizeof(void *)) ? 1 : -1];

static char *join_path(RmdContext *ctx, const char *prefix, size_t length,
                       const char *suffix)
{
    size_t size = strlen(suffix);
    char *result;
    if (size >= SIZE_MAX - length) {
        rmd_set_error(ctx, NULL, 0, "stage input path is too long");
        return NULL;
    }
    result = rmd_try_alloc(ctx, length + size + 1, 1);
    if (result != NULL) {
        memcpy(result, prefix, length);
        memcpy(result + length, suffix, size + 1);
    }
    return result;
}

static char *input_path(RmdContext *ctx, const RmdSource *root, RmdMetaInput *input)
{
    const char *slash = strrchr(root->path, '/');
    const char *path = input->path;
    char *absolute;
    char *result;
    if (path[0] != '/' && slash != NULL) {
        path = join_path(ctx, root->path, (size_t)(slash - root->path) + 1, path);
        if (path == NULL) return NULL;
    }
    absolute = realpath(path, NULL);
    if (absolute == NULL) {
        rmd_set_error(ctx, input->loc.source, input->loc.offset,
                      "cannot resolve stage input path");
        fprintf(stderr, "rmd0: %s: %s\n", path, strerror(errno));
        return NULL;
    }
    result = rmd_try_copy_string(ctx, (const unsigned char *)absolute, strlen(absolute));
    free(absolute);
    return result;
}

static int run_tool(char **arguments)
{
    pid_t child = fork();
    pid_t waited;
    int result;
    if (child < 0) {
        fprintf(stderr, "rmd0: cannot start %s: %s\n", arguments[0], strerror(errno));
        return 1;
    }
    if (child == 0) {
        execvp(arguments[0], arguments);
        fprintf(stderr, "rmd0: cannot execute %s: %s\n", arguments[0], strerror(errno));
        _exit(127);
    }
    do {
        waited = waitpid(child, &result, 0);
    } while (waited < 0 && errno == EINTR);
    if (waited < 0) {
        fprintf(stderr, "rmd0: cannot wait for %s: %s\n", arguments[0], strerror(errno));
        return 1;
    }
    if (WIFEXITED(result)) {
        result = WEXITSTATUS(result);
    } else if (WIFSIGNALED(result)) {
        result = 128 + WTERMSIG(result);
    } else {
        fputs("rmd0: unexpected stage tool process status\n", stderr);
        return 1;
    }
    if (result != 0)
        fprintf(stderr, "rmd0: stage tool %s failed with status %d\n", arguments[0], result);
    return result;
}

static bool remove_temporary(const char *path)
{
    if (path != NULL && unlink(path) != 0 && errno != ENOENT) {
        fprintf(stderr, "rmd0: cannot remove stage temporary %s: %s\n", path, strerror(errno));
        return false;
    }
    return true;
}

static bool cleanup(const char *directory, const char *assembly,
                    const char *object, const char *module)
{
    bool success = true;
    if (!remove_temporary(assembly)) success = false;
    if (!remove_temporary(object)) success = false;
    if (!remove_temporary(module)) success = false;
    if (rmdir(directory) != 0) {
        fprintf(stderr, "rmd0: cannot remove stage directory %s: %s\n", directory, strerror(errno));
        success = false;
    }
    return success;
}

static bool stage_entry(const RmdDecl *decl)
{
    static const struct {
        size_t offset;
        RmdTypeKind kind;
        unsigned pointers;
        const char *record;
    } fields[] = {
        {offsetof(RmdBuild, context), RMD_T_RECORD, 1, "RmdContext"},
        {offsetof(RmdBuild, source), RMD_T_RECORD, 1, "RmdSource"},
        {offsetof(RmdBuild, target_begin), RMD_T_USIZE, 0, NULL},
        {offsetof(RmdBuild, argc), RMD_T_I32, 0, NULL},
        {offsetof(RmdBuild, argv), RMD_T_U8, 2, NULL}
    };
    const RmdType *type;
    const RmdType *parameter;
    const RmdField *field;
    size_t index;
    if (decl == NULL || decl->kind != RMD_D_FUNCTION) return false;
    type = decl->type;
    if (type->kind != RMD_T_FUNCTION || type->param_count != 1 ||
        type->base->kind != RMD_T_I32) return false;
    parameter = type->params[0];
    if (parameter->kind != RMD_T_POINTER || parameter->base->kind != RMD_T_RECORD ||
        strcmp(parameter->base->record_decl->name->text, "RmdBuild") != 0 ||
        parameter->base->size != sizeof(RmdBuild) ||
        parameter->base->align != RMD_ALIGNOF(RmdBuild) ||
        parameter->base->record_decl->field_count != sizeof(fields) / sizeof(fields[0]))
        return false;
    field = parameter->base->record_decl->fields;
    for (index = 0; index < sizeof(fields) / sizeof(fields[0]); ++index) {
        unsigned depth;
        type = field->type;
        if (field->offset != fields[index].offset) return false;
        for (depth = 0; depth < fields[index].pointers; ++depth) {
            if (type->kind != RMD_T_POINTER) return false;
            type = type->base;
        }
        if (type->kind != fields[index].kind ||
            (fields[index].record != NULL &&
             strcmp(type->record_decl->name->text, fields[index].record) != 0))
            return false;
        field = field->next;
    }
    return true;
}

int rmd_driver_stage(RmdContext *host, const RmdMeta *meta, RmdSource *source,
                     int argc, char **argv)
{
    RmdMetaInput *input;
    RmdSource *sources = NULL;
    size_t source_count = 0;
    size_t input_count = 0;
    size_t index;
    char **native = NULL;
    size_t native_count = 0;
    char **arguments = NULL;
    RmdDecl *entry;
    RmdX64Program *program;
    char *directory = NULL;
    char *assembly = NULL;
    char *object = NULL;
    char *module = NULL;
    bool directory_created = false;
    void *handle = NULL;
    void *address;
    StageEntry execute;
    RmdContext target;
    RmdBuild request;
    int status = 1;
    const char *temporary_root = getenv("TMPDIR");
    rmd_context_init(&target, NULL);
    for (input = meta->inputs; input != NULL; input = input->next) ++input_count;
    sources = rmd_try_alloc(host, (input_count + 1) * sizeof(*sources), RMD_ALIGNOF(RmdSource));
    native = rmd_try_alloc(host, (input_count + 1) * sizeof(*native), RMD_ALIGNOF(char *));
    arguments = rmd_try_alloc(host, (3 * input_count + 16) * sizeof(*arguments), RMD_ALIGNOF(char *));
    if (sources == NULL || native == NULL || arguments == NULL) goto done;
    for (input = meta->inputs; input != NULL; input = input->next) {
        char *path = input_path(host, source, input);
        if (path == NULL) goto done;
        if (input->native) {
            native[native_count++] = path;
        } else {
            unsigned char *bytes;
            RmdSource *next = &sources[source_count];
            RmdUnit *unit;
            next->path = path;
            next->identity = source_count + 2;
            if (rmd0_host_read_file(path, &bytes, &next->size) != 0) {
                rmd_set_error(host, input->loc.source, input->loc.offset,
                              "cannot read stage source input");
                goto done;
            }
            next->bytes = (const unsigned char *)rmd_try_copy_string(host, bytes, next->size);
            free(bytes);
            if (next->bytes == NULL) goto done;
            ++source_count;
            if (!rmd_read(host, next, &unit)) goto done;
        }
    }
    if (!rmd_collect(host) || !rmd_resolve(host) || !rmd_check(host)) goto done;
    entry = rmd_driver_find(host, "build");
    if (!stage_entry(entry)) {
        rmd_set_error(host, meta->loc.source, meta->loc.offset,
                      "meta entry must be a defined fn build(*RmdBuild) -> i32");
        goto done;
    }
    entry->link_name = "rmd_meta_entry";
    if (!rmd_driver_names(host) || !rmd_x64_prepare(host, &program, NULL)) goto done;
    if (temporary_root == NULL || temporary_root[0] == '\0') temporary_root = "/tmp";
    directory = join_path(host, temporary_root, strlen(temporary_root), "/rmd-stage-XXXXXX");
    if (directory == NULL) goto done;
    if (mkdtemp(directory) == NULL) {
        fprintf(stderr, "rmd0: cannot create stage directory: %s\n", strerror(errno));
        goto done;
    }
    directory_created = true;
    {
        char *absolute = realpath(directory, NULL);
        if (absolute == NULL) {
            fprintf(stderr, "rmd0: cannot resolve stage directory: %s\n", strerror(errno));
            goto done;
        }
        {
            char *copied = rmd_try_copy_string(host, (const unsigned char *)absolute, strlen(absolute));
            free(absolute);
            if (copied == NULL) goto done;
            directory = copied;
        }
    }
    assembly = join_path(host, directory, strlen(directory), "/stage.s");
    object = join_path(host, directory, strlen(directory), "/stage.o");
    module = join_path(host, directory, strlen(directory), "/stage.so");
    if (assembly == NULL || object == NULL || module == NULL) goto done;
    {
        FILE *file = fopen(assembly, "wb");
        bool success;
        if (file == NULL) {
            fprintf(stderr, "rmd0: cannot write stage assembly: %s\n", strerror(errno));
            goto done;
        }
        success = rmd_x64_emit_program(program, file);
        if (fclose(file) != 0) {
            fprintf(stderr, "rmd0: cannot close stage assembly: %s\n", strerror(errno));
            success = false;
        }
        if (!success) goto done;
    }
    arguments[0] = "as";
    arguments[1] = "--64";
    arguments[2] = "-o";
    arguments[3] = object;
    arguments[4] = assembly;
    arguments[5] = NULL;
    status = run_tool(arguments);
    if (status != 0) goto done;
    arguments[0] = "ld";
    arguments[1] = "-shared";
    arguments[2] = "-Bsymbolic";
    arguments[3] = "-z";
    arguments[4] = "text";
    arguments[5] = "-z";
    arguments[6] = "relro";
    arguments[7] = "-z";
    arguments[8] = "now";
    arguments[9] = "-o";
    arguments[10] = module;
    arguments[11] = object;
    {
        size_t count = 12;
        for (index = 0; index < native_count; ++index) {
            const char *slash = strrchr(native[index], '/');
            char *search = rmd_try_copy_string(host, (const unsigned char *)native[index],
                                               (size_t)(slash - native[index]));
            if (search == NULL) goto done;
            arguments[count++] = "-rpath";
            arguments[count++] = search[0] == '\0' ? "/" : search;
            arguments[count++] = native[index];
        }
        arguments[count++] = "-lc";
        arguments[count] = NULL;
    }
    status = run_tool(arguments);
    if (status != 0) goto done;
    status = 1;
    handle = dlopen(module, RTLD_NOW | RTLD_LOCAL);
    if (handle == NULL) {
        fprintf(stderr, "rmd0: cannot load stage: %s\n", dlerror());
        goto done;
    }
    address = dlsym(handle, "rmd_meta_entry");
    if (address == NULL) {
        fprintf(stderr, "rmd0: cannot find stage entry: %s\n", dlerror());
        goto done;
    }
    directory_created = false;
    if (!cleanup(directory, assembly, object, module)) goto done;
    /* The selected host ABI has equal data and function pointer sizes. */
    memcpy(&execute, &address, sizeof(execute));
    request.context = &target;
    request.source = source;
    request.target_begin = meta->target_begin;
    request.argc = (int32_t)argc;
    request.argv = argv;
    status = execute(&request);
    if (status < 0 || status > 255) {
        fputs("rmd0: compilation entry status must be between 0 and 255\n", stderr);
        status = 1;
    }
done:
    if (host->error_count != 0) {
        rmd_driver_diagnostic(host);
        if (status == 0) status = 1;
    }
    if (target.error_count != 0) {
        rmd_driver_diagnostic(&target);
        if (status == 0) status = 1;
    }
    rmd_context_destroy(&target);
    if (handle != NULL && dlclose(handle) != 0) {
        fprintf(stderr, "rmd0: cannot unload stage: %s\n", dlerror());
        if (status == 0) status = 1;
    }
    if (directory_created && !cleanup(directory, assembly, object, module) && status == 0)
        status = 1;
    return status;
}
