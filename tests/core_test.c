/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0.h"
#include "crust0_x64.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    size_t calls;
    size_t live;
    size_t fail_at;
} AllocationCounts;

static unsigned checks;
static unsigned failures;

static void check(bool condition, const char *message)
{
    ++checks;
    if (!condition) {
        ++failures;
        fprintf(stderr, "core check failed: %s\n", message);
    }
}

static void *count_allocate(void *user, size_t size)
{
    AllocationCounts *counts = user;
    void *allocation;
    if (++counts->calls == counts->fail_at)
        return NULL;
    allocation = malloc(size);
    if (allocation != NULL)
        ++counts->live;
    return allocation;
}

static void count_release(void *user, void *allocation)
{
    AllocationCounts *counts = user;
    check(counts->live != 0, "allocator release has a live allocation");
    --counts->live;
    free(allocation);
}

static void test_arena(void)
{
    AllocationCounts counts = {0, 0, 0};
    CrustAllocator allocator = {&counts, count_allocate, count_release};
    CrustArena arena;
    size_t alignment;
    unsigned char *large;
    crust_arena_init(&arena, &allocator);
    check(crust_arena_alloc(&arena, 0, 1) == NULL, "zero size allocates nothing");
    check(crust_arena_alloc(&arena, 1, 3) == NULL, "non-power alignment fails");
    check(crust_arena_alloc(&arena, 1, 0) == NULL, "zero alignment fails");
    check(crust_arena_alloc(&arena, SIZE_MAX, 1) == NULL, "size overflow fails");
    check(counts.calls == 0, "invalid requests do not call the allocator");
    for (alignment = 1; alignment <= CRUST_ALIGNOF(long double); alignment *= 2) {
        unsigned char *value;
        (void)crust_arena_alloc(&arena, 1, 1);
        value = crust_arena_alloc(&arena, 31, alignment);
        check(value != NULL && (uintptr_t)value % alignment == 0, "arena alignment");
        memset(value, 0xa5, 31);
    }
    large = crust_arena_alloc(&arena, 100000, CRUST_ALIGNOF(long double));
    check(large != NULL, "large arena allocation");
    large[0] = 23;
    large[99999] = 42;
    check(arena.bytes_reserved >= 165536, "arena accounts for both blocks");
    crust_arena_destroy(&arena);
    check(counts.live == 0 && arena.bytes_reserved == 0, "arena releases all blocks");
    crust_arena_destroy(&arena);
}

static void tables_stage(CrustContext *ctx, void *data)
{
    CrustMap map = {NULL, 0, 0};
    CrustName *first = NULL;
    size_t index;
    int *values = crust_alloc(ctx, 10000 * sizeof(*values), CRUST_ALIGNOF(int));
    (void)data;
    for (index = 0; index < 10000; ++index) {
        char name[32];
        int length = snprintf(name, sizeof(name), "name_%zu", index);
        CrustName *interned = crust_intern(ctx, (const unsigned char *)name, (size_t)length);
        if (index == 0)
            first = interned;
        values[index] = (int)index;
        crust_map_set(ctx, &map, index + 1, &values[index]);
    }
    check(first == crust_intern(ctx, (const unsigned char *)"name_0", 6),
          "interned names remain stable across table growth");
    check(crust_intern(ctx, NULL, 0) == crust_intern(ctx, NULL, 0), "empty interned name");
    for (index = 0; index < 10000; ++index) {
        check(crust_map_get(&map, index + 1) == &values[index], "map retains values");
    }
    crust_map_set(ctx, &map, 100, NULL);
    check(crust_map_get(&map, 100) == NULL, "map removes a scoped value");
    crust_map_set(ctx, &map, 100, &values[0]);
    check(crust_map_get(&map, 100) == &values[0], "map reuses a scoped key");
    check(crust_map_get(&map, 0) == NULL && crust_map_get(&map, 10001) == NULL,
          "missing map values");
    {
        int *grown = crust_grow_array(ctx, values, 10, 20, sizeof(*values), CRUST_ALIGNOF(int));
        check(grown[9] == 9 && grown[10] == 0 && grown[19] == 0,
              "array growth retains values and zeroes new storage");
    }
}

static void error_stage(CrustContext *ctx, void *data)
{
    CrustLoc location = {NULL, 0};
    (void)data;
    crust_fail(ctx, location, "stage error");
}

static void overflow_stage(CrustContext *ctx, void *data)
{
    (void)data;
    (void)crust_grow_array(ctx, NULL, 0, SIZE_MAX, 2, 1);
}

static void nested_stage(CrustContext *ctx, void *data)
{
    CrustFailureFrame *outer = ctx->failure;
    (void)data;
    check(!crust_run_stage(ctx, error_stage, NULL), "nested stage reports failure");
    check(ctx->failure == outer, "nested stage restores the outer failure frame");
}

static bool compile_text(CrustContext *ctx, CrustSource *source)
{
    CrustUnit *unit;
    CrustDecl *decl;
    CrustX64Program *program;
    if (!crust_read(ctx, source, &unit) || !crust_collect(ctx) || !crust_resolve(ctx) ||
        !crust_check(ctx))
        return false;
    for (decl = unit->declarations; decl != NULL; decl = decl->next) {
        decl->link_name = decl->name->text;
    }
    return crust_x64_prepare(ctx, &program, NULL);
}

static void test_allocation_failure(void)
{
    char text[20000];
    size_t used = 0;
    size_t index;
    size_t allocation_count;
    CrustSource source = {"allocation-test", (const unsigned char *)text, 0, 1};
    AllocationCounts counts = {0, 0, 0};
    CrustAllocator allocator = {&counts, count_allocate, count_release};
    CrustContext ctx;
    for (index = 0; index < 200; ++index) {
        int length = snprintf(text + used, sizeof(text) - used,
                              "fn f%zu(p:u64)->u64{return p+%zuu64;}\n", index, index);
        if (length < 0 || (size_t)length >= sizeof(text) - used)
            abort();
        used += (size_t)length;
    }
    source.size = used;
    crust_context_init(&ctx, &allocator);
    check(compile_text(&ctx, &source), "complete source compiles with counted allocator");
    allocation_count = counts.calls;
    crust_context_destroy(&ctx);
    check(counts.live == 0, "successful compilation releases all arena blocks");
    for (index = 1; index <= allocation_count; ++index) {
        counts.calls = 0;
        counts.fail_at = index;
        crust_context_init(&ctx, &allocator);
        check(!compile_text(&ctx, &source), "each injected allocation failure is reported");
        check(ctx.error_count != 0 && strstr(ctx.error, "allocation") != NULL,
              "allocation failure retains a diagnostic");
        check(ctx.failure == NULL, "failed compilation restores failure frame");
        crust_context_destroy(&ctx);
        check(counts.live == 0, "failed compilation releases all arena blocks");
    }
    printf("allocation sweep: %zu failure points\n", allocation_count);
}

static void wrappers_stage(CrustContext *ctx, void *data)
{
    CrustFailureFrame *outer = ctx->failure;
    const int values[] = {17, 29};
    const unsigned char text[] = {'a', 0, 'b'};
    CrustMap map = {NULL, 0, 0};
    CrustTypeSyntax scalar;
    CrustTypeSyntax pointer;
    CrustType *type;
    int *grown;
    char *copy;
    size_t errors;
    (void)data;
    grown = crust_try_grow_array(ctx, values, 2, 3, sizeof(*values), CRUST_ALIGNOF(int));
    check(grown != NULL && grown[0] == 17 && grown[1] == 29 && grown[2] == 0 &&
              ctx->failure == outer,
          "nonthrowing growth copies values and restores the frame");
    errors = ctx->error_count;
    check(crust_try_grow_array(ctx, NULL, 0, 0, sizeof(int), CRUST_ALIGNOF(int)) == NULL &&
              ctx->error_count == errors && ctx->failure == outer,
          "zero-capacity growth returns null without a diagnostic");
    check(crust_try_grow_array(ctx, values, 2, 1, sizeof(*values), CRUST_ALIGNOF(int)) == NULL &&
              ctx->error_count == errors + 1 && ctx->failure == outer,
          "invalid growth reports failure inside the wrapper");
    copy = crust_try_copy_string(ctx, text, sizeof(text));
    check(copy != NULL && memcmp(copy, text, sizeof(text)) == 0 && copy[3] == '\0' &&
              ctx->failure == outer,
          "nonthrowing copy retains embedded zero bytes");
    copy = crust_try_copy_string(ctx, NULL, 0);
    check(copy != NULL && copy[0] == '\0' && ctx->failure == outer,
          "nonthrowing empty copy creates a terminator");
    errors = ctx->error_count;
    check(crust_try_copy_string(ctx, NULL, SIZE_MAX) == NULL && ctx->error_count == errors + 1 &&
              ctx->failure == outer,
          "copy overflow reports failure inside the wrapper");
    check(crust_try_map_set(ctx, &map, 7, grown) && crust_map_get(&map, 7) == grown &&
              ctx->failure == outer,
          "nonthrowing map update restores the frame");
    errors = ctx->error_count;
    check(!crust_try_map_set(ctx, &map, 0, grown) && ctx->error_count == errors + 1 &&
              ctx->failure == outer,
          "invalid map key reports failure inside the wrapper");
    check(crust_try_map_set(ctx, &map, 7, NULL) && crust_map_get(&map, 7) == NULL,
          "nonthrowing map update removes a scoped value");
    memset(&scalar, 0, sizeof(scalar));
    memset(&pointer, 0, sizeof(pointer));
    scalar.kind = CRUST_T_U32;
    pointer.kind = CRUST_T_POINTER;
    pointer.base = &scalar;
    type = crust_try_resolve_type(ctx, &pointer);
    check(type != NULL && type->kind == CRUST_T_POINTER &&
              type->base == &ctx->builtins[CRUST_T_U32] && ctx->failure == outer,
          "nonthrowing type resolution restores the frame");
    errors = ctx->error_count;
    pointer.base = NULL;
    check(crust_try_resolve_type(ctx, &pointer) == NULL && ctx->error_count == errors + 1 &&
              ctx->failure == outer,
          "nested type failure stays inside the native wrapper");
    type = crust_try_pointer_type(ctx, &ctx->builtins[CRUST_T_U64]);
    check(type != NULL && type->base == &ctx->builtins[CRUST_T_U64] && type->size == 8 &&
              ctx->failure == outer,
          "nonthrowing pointer construction restores the frame");
    errors = ctx->error_count;
    check(crust_try_pointer_type(ctx, &ctx->builtins[CRUST_T_UNIT]) == NULL &&
              ctx->error_count == errors + 1 && ctx->failure == outer,
          "invalid pointer target reports failure inside the wrapper");
}

static bool grow_request(CrustContext *ctx)
{
    return crust_try_grow_array(ctx, NULL, 0, 2, sizeof(int), CRUST_ALIGNOF(int)) != NULL;
}

static bool copy_request(CrustContext *ctx)
{
    return crust_try_copy_string(ctx, (const unsigned char *)"copy", 4) != NULL;
}

static bool map_request(CrustContext *ctx)
{
    CrustMap map = {NULL, 0, 0};
    return crust_try_map_set(ctx, &map, 1, ctx);
}

static bool resolve_request(CrustContext *ctx)
{
    CrustTypeSyntax scalar;
    CrustTypeSyntax pointer;
    memset(&scalar, 0, sizeof(scalar));
    memset(&pointer, 0, sizeof(pointer));
    scalar.kind = CRUST_T_U8;
    pointer.kind = CRUST_T_POINTER;
    pointer.base = &scalar;
    return crust_try_resolve_type(ctx, &pointer) != NULL;
}

static bool pointer_request(CrustContext *ctx)
{
    return crust_try_pointer_type(ctx, &ctx->builtins[CRUST_T_U8]) != NULL;
}

static void test_wrapper_allocation_failures(void)
{
    static bool (*const requests[])(CrustContext *) = {grow_request, copy_request, map_request,
                                                       resolve_request, pointer_request};
    size_t index;
    for (index = 0; index < sizeof(requests) / sizeof(requests[0]); ++index) {
        AllocationCounts counts = {0, 0, 1};
        CrustAllocator allocator = {&counts, count_allocate, count_release};
        CrustContext ctx;
        crust_context_init(&ctx, &allocator);
        check(!requests[index](&ctx) && ctx.error_count == 1 && ctx.failure == NULL &&
                  strstr(ctx.error, "allocation") != NULL,
              "nonthrowing helper reports allocator failure without escaping its frame");
        check(requests[index](&ctx) && ctx.failure == NULL,
              "nonthrowing helper can retry after allocator failure");
        crust_context_destroy(&ctx);
        check(counts.live == 0, "nonthrowing helper releases owned storage at destruction");
    }
}

int main(void)
{
    CrustContext ctx;
    AllocationCounts counts = {0, 0, 1};
    CrustAllocator allocator = {&counts, count_allocate, count_release};
    test_arena();
    crust_context_init(&ctx, NULL);
    crust_set_error(&ctx, NULL, 0, "first diagnostic");
    crust_set_error(&ctx, NULL, 3, ctx.error);
    check(strcmp(ctx.error, "first diagnostic") == 0 && ctx.error_loc.offset == 3,
          "diagnostic can retain its message and change its location");
    crust_set_error(&ctx, NULL, 4, ctx.error + 6);
    check(strcmp(ctx.error, "diagnostic") == 0, "diagnostic supports partial overlap");
    check(crust_run_stage(&ctx, tables_stage, NULL), "construction stage succeeds");
    check(crust_run_stage(&ctx, nested_stage, NULL), "outer stage can handle a nested error");
    check(crust_run_stage(&ctx, wrappers_stage, NULL), "native wrappers retain the outer stage");
    check(!crust_run_stage(&ctx, overflow_stage, NULL), "array multiplication overflow fails");
    check(ctx.failure == NULL, "public stage restores its failure frame");
    crust_context_destroy(&ctx);
    crust_context_init(&ctx, &allocator);
    check(crust_try_alloc(&ctx, 32, 8) == NULL && ctx.error_count == 1 && ctx.failure == NULL,
          "nonthrowing allocation reports failure");
    crust_context_destroy(&ctx);
    counts.calls = 0;
    crust_context_init(&ctx, &allocator);
    check(crust_try_intern(&ctx, (const unsigned char *)"name", 4) == NULL &&
              ctx.error_count == 1 && ctx.failure == NULL,
          "nonthrowing interning reports failure");
    check(crust_try_intern(&ctx, (const unsigned char *)"name", 4) != NULL,
          "interning can retry after a reported allocation failure");
    crust_context_destroy(&ctx);
    check(counts.live == 0, "nonthrowing constructors retain no allocation after destruction");
    test_allocation_failure();
    test_wrapper_allocation_failures();
    printf("core: %u/%u checks passed\n", checks - failures, checks);
    return failures == 0 ? 0 : 1;
}
