/* SPDX-License-Identifier: Apache-2.0 */

#include "../runtime/windows_io.h"
#include "../src/driver_platform.h"
#include "../src/run_platform.h"
#include "crust0_host.h"
#include "crust0_run.h"

#include <assert.h>
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

typedef struct {
    size_t calls;
    size_t fail_at;
    size_t live;
} Allocation;

static void *allocate(void *user, size_t size)
{
    Allocation *state = user;
    void *result;
    if (++state->calls == state->fail_at)
        return NULL;
    result = malloc(size);
    if (result != NULL)
        ++state->live;
    return result;
}

static void release(void *user, void *data)
{
    Allocation *state = user;
    assert(state->live != 0);
    --state->live;
    free(data);
}

static void allocations(void)
{
    size_t alignment;
    assert(crust0_host_alloc(0, 1) == NULL);
    assert(crust0_host_alloc(8, 3) == NULL);
    assert(crust0_host_alloc(SIZE_MAX, 1) == NULL);
    for (alignment = 1; alignment <= 4096; alignment *= 2) {
        unsigned char *bytes = crust0_host_alloc(127, alignment);
        assert(bytes != NULL && (uintptr_t)bytes % alignment == 0);
        memset(bytes, 42, 127);
        crust0_host_free(bytes);
    }
    crust0_host_free(NULL);
}

static void file_roundtrip(const char *path)
{
    unsigned char expected[10000];
    unsigned char *bytes;
    size_t length;
    size_t index;
    for (index = 0; index < sizeof(expected); ++index)
        expected[index] = (unsigned char)index;
    assert(crust0_host_write_file(path, expected, sizeof(expected)) == 0);
    assert(crust0_host_read_file(path, &bytes, &length) == 0);
    assert(length == sizeof(expected) && memcmp(bytes, expected, length) == 0);
    crust0_host_free(bytes);
    assert(crust0_host_write_file(path, NULL, 0) == 0);
    assert(crust0_host_read_file(path, &bytes, &length) == 0 && bytes == NULL && length == 0);
    assert(crust0_host_read_file("missing-directory/input", &bytes, &length) != 0);
    assert(bytes == NULL && length == 0);
    assert(crust0_host_read_file("\xff", &bytes, &length) != 0);
    assert(bytes == NULL && length == 0);
    assert(crust0_host_write_file("missing-directory/output", NULL, 0) != 0);
    assert(crust0_host_write_stream(3, NULL, 0) != 0);
}

/* The adapter must preserve previous output when its emitter fails. */
bool crust_x64_emit_program(CrustX64Program *program, FILE *output)
{
    if (fputs("replacement", output) < 0)
        return false;
    return program->context->error_count == 0;
}

static void publication(const char *path)
{
    CrustContext context;
    CrustX64Program program;
    unsigned char *bytes;
    size_t size;
    memset(&program, 0, sizeof(program));
    crust_context_init(&context, NULL);
    program.context = &context;
    assert(crust0_host_write_file(path, (const unsigned char *)"previous", 8) == 0);
    context.error_count = 1;
    assert(!crust_driver_emit_file(&program, path));
    assert(crust0_host_read_file(path, &bytes, &size) == 0);
    assert(size == 8 && memcmp(bytes, "previous", size) == 0);
    crust0_host_free(bytes);
    context.error_count = 0;
    assert(crust_driver_emit_file(&program, path));
    assert(crust0_host_read_file(path, &bytes, &size) == 0);
    assert(size == 11 && memcmp(bytes, "replacement", size) == 0);
    crust0_host_free(bytes);
    assert(!crust_driver_emit_file(&program, "missing-directory/output"));
    assert(crust_driver_emit_file(&program, "NUL"));
    crust_context_destroy(&context);
}

static void library_lifetime(const char *path, size_t fail_at)
{
    Allocation state = {0, fail_at, 0};
    CrustAllocator allocator = {&state, allocate, release};
    CrustContext context;
    CrustSource source = {"test", (const unsigned char *)"", 0, 1};
    CrustRun run;
    CrustRun other;
    CrustDecl declaration;
    CrustLibrary *library;
    void *address;
    bool initialized;
    crust_context_init(&context, &allocator);
    initialized = crust_run_init(&run, &context, &source, 0, NULL);
    if (initialized) {
        library = crust_run_open(&run, path);
        if (library != NULL) {
            memset(&declaration, 0, sizeof(declaration));
            declaration.link_name = "seed_i8";
            assert(crust_run_native_symbol(&run, library, &declaration, &address));
            other = run;
            assert(!crust_run_native_symbol(&other, library, &declaration, &address));
        }
    }
    if (fail_at == 0)
        assert(initialized && library != NULL);
    assert(crust_run_destroy(&run));
    assert(GetModuleHandleW(L"windows_library.dll") == NULL);
    crust_context_destroy(&context);
    assert(state.live == 0);
}

static void float_locale(void)
{
    CrustContext context;
    CrustUnit *unit;
    const unsigned char text[] = "const value:f32=1.25f32;";
    CrustSource source = {"float", text, sizeof(text) - 1, 1};
    assert(setlocale(LC_NUMERIC, "German_Germany.1252") != NULL);
    crust_context_init(&context, NULL);
    assert(crust_read(&context, &source, &unit));
    assert(crust_collect(&context) && crust_resolve(&context) && crust_check(&context));
    crust_context_destroy(&context);
    assert(setlocale(LC_NUMERIC, "C") != NULL);
}

int main(int argc, char **argv)
{
    size_t failure;
    assert(argc == 3);
    allocations();
    file_roundtrip(argv[2]);
    publication(argv[2]);
    float_locale();
    library_lifetime(argv[1], 0);
    for (failure = 1; failure <= 32; ++failure)
        library_lifetime(argv[1], failure);
    puts(
        "Windows seed: host memory, files, output publication, locale, and runner lifetime passed");
    return 0;
}
