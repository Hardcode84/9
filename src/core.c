#include "crust0.h"

#include <stdarg.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if !defined(__linux__) || !defined(__x86_64__)
#error CRUST0 version 0.1 requires a Linux x86-64 host
#endif

typedef char CrustHostProfile[(CHAR_BIT == 8 && sizeof(void *) == 8 &&
                            sizeof(size_t) == 8 && sizeof(CrustTypeKind) == 4 &&
                            sizeof(short) == 2 && sizeof(int) == 4 && sizeof(long) == 8 &&
                            sizeof(bool) == 1 && sizeof(void (*)(void)) == 8) ? 1 : -1];

typedef union {
    long double floating;
    void *pointer;
    uint64_t integer;
    void (*function)(void);
} CrustArenaAlign;

struct CrustArenaBlock {
    CrustArenaBlock *next;
    size_t used;
    size_t capacity;
    CrustArenaAlign alignment;
    unsigned char data[];
};

static void *default_allocate(void *user, size_t size)
{
    (void)user;
    return malloc(size);
}

static void default_release(void *user, void *allocation)
{
    (void)user;
    free(allocation);
}

void crust_arena_init(CrustArena *arena, const CrustAllocator *allocator)
{
    memset(arena, 0, sizeof(*arena));
    if (allocator != NULL) {
        arena->allocator = *allocator;
    } else {
        arena->allocator.allocate = default_allocate;
        arena->allocator.release = default_release;
    }
}

void crust_arena_destroy(CrustArena *arena)
{
    CrustArenaBlock *block = arena->blocks;
    while (block != NULL) {
        CrustArenaBlock *next = block->next;
        arena->allocator.release(arena->allocator.user, block);
        block = next;
    }
    arena->blocks = NULL;
    arena->bytes_reserved = 0;
}

void *crust_arena_alloc(CrustArena *arena, size_t size, size_t alignment)
{
    CrustArenaBlock *block = arena->blocks;
    size_t offset;
    size_t capacity;
    size_t prefix = offsetof(CrustArenaBlock, data);
    if (size == 0 || alignment == 0 ||
        (alignment & (alignment - 1)) != 0 ||
        alignment > CRUST_ALIGNOF(CrustArenaAlign)) {
        return NULL;
    }
    if (block != NULL && block->used <= SIZE_MAX - (alignment - 1)) {
        offset = (block->used + alignment - 1) & ~(alignment - 1);
        if (offset <= block->capacity && size <= block->capacity - offset) {
            block->used = offset + size;
            return block->data + offset;
        }
    }
    capacity = size > 65536 ? size : 65536;
    if (capacity > SIZE_MAX - prefix ||
        arena->bytes_reserved > SIZE_MAX - (prefix + capacity)) {
        return NULL;
    }
    block = arena->allocator.allocate(arena->allocator.user, prefix + capacity);
    if (block == NULL) {
        return NULL;
    }
    block->next = arena->blocks;
    block->used = size;
    block->capacity = capacity;
    arena->blocks = block;
    arena->bytes_reserved += prefix + capacity;
    return block->data;
}

void crust_context_init(CrustContext *ctx, const CrustAllocator *allocator)
{
    static const unsigned sizes[] = {1, 1, 2, 2, 4, 4, 8, 8, 8, 8, 1, 0};
    size_t index;
    memset(ctx, 0, sizeof(*ctx));
    crust_arena_init(&ctx->arena, allocator);
    for (index = 0; index < sizeof(sizes) / sizeof(sizes[0]); ++index) {
        ctx->builtins[index].kind = (CrustTypeKind)index;
        ctx->builtins[index].size = sizes[index];
        ctx->builtins[index].align = sizes[index];
    }
}

void crust_context_destroy(CrustContext *ctx)
{
    crust_arena_destroy(&ctx->arena);
    memset(ctx, 0, sizeof(*ctx));
}

bool crust_run_stage(CrustContext *ctx, void (*stage)(CrustContext *, void *), void *data)
{
    CrustFailureFrame frame;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    stage(ctx, data);
    ctx->failure = frame.previous;
    return true;
}

void crust_set_error(CrustContext *ctx, CrustSource *source, size_t offset, const char *message)
{
    size_t length = 0;
    while (length < sizeof(ctx->error) - 1 && message[length] != '\0') ++length;
    memmove(ctx->error, message, length);
    ctx->error[length] = '\0';
    ctx->error_loc.source = source;
    ctx->error_loc.offset = offset;
    ++ctx->error_count;
}

typedef struct { size_t size; size_t alignment; void *result; } AllocRequest;
typedef struct { const unsigned char *text; size_t size; CrustName *result; } NameRequest;

static void allocate_stage(CrustContext *ctx, void *data)
{
    AllocRequest *request = data;
    request->result = crust_alloc(ctx, request->size, request->alignment);
}

void *crust_try_alloc(CrustContext *ctx, size_t size, size_t alignment)
{
    AllocRequest request = {size, alignment, NULL};
    (void)crust_run_stage(ctx, allocate_stage, &request);
    return request.result;
}

static void intern_stage(CrustContext *ctx, void *data)
{
    NameRequest *request = data;
    request->result = crust_intern(ctx, request->text, request->size);
}

CrustName *crust_try_intern(CrustContext *ctx, const unsigned char *text, size_t size)
{
    NameRequest request = {text, size, NULL};
    (void)crust_run_stage(ctx, intern_stage, &request);
    return request.result;
}

void *crust_try_grow_array(CrustContext *ctx, const void *old, size_t count,
                         size_t capacity, size_t item_size, size_t alignment)
{
    CrustFailureFrame frame;
    void *result;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return NULL;
    }
    result = crust_grow_array(ctx, old, count, capacity, item_size, alignment);
    ctx->failure = frame.previous;
    return result;
}

char *crust_try_copy_string(CrustContext *ctx, const unsigned char *text, size_t size)
{
    CrustFailureFrame frame;
    char *result;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return NULL;
    }
    result = crust_copy_string(ctx, text, size);
    ctx->failure = frame.previous;
    return result;
}

bool crust_try_map_set(CrustContext *ctx, CrustMap *map, uintptr_t key, void *value)
{
    CrustFailureFrame frame;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    crust_map_set(ctx, map, key, value);
    ctx->failure = frame.previous;
    return true;
}

void crust_fail(CrustContext *ctx, CrustLoc loc, const char *format, ...)
{
    va_list args;
    ctx->error_loc = loc;
    ++ctx->error_count;
    va_start(args, format);
    if (vsnprintf(ctx->error, sizeof(ctx->error), format, args) < 0) {
        memcpy(ctx->error, "diagnostic formatting failed", 29);
    }
    va_end(args);
    if (ctx->failure != NULL) {
        longjmp(ctx->failure->jump, 1);
    }
    fprintf(stderr, "crust0: %s\n", ctx->error);
    abort();
}

void *crust_alloc(CrustContext *ctx, size_t size, size_t alignment)
{
    void *result;
    if (size == 0) {
        return NULL;
    }
    result = crust_arena_alloc(&ctx->arena, size, alignment);
    if (result == NULL) {
        CrustLoc loc = {NULL, 0};
        crust_fail(ctx, loc, "allocation failed for %zu bytes", size);
    }
    memset(result, 0, size);
    return result;
}

void *crust_grow_array(CrustContext *ctx, const void *old, size_t count,
                    size_t capacity, size_t item_size, size_t alignment)
{
    void *result;
    if (item_size == 0 || count > capacity || capacity > SIZE_MAX / item_size) {
        CrustLoc loc = {NULL, 0};
        crust_fail(ctx, loc, "array allocation size overflow");
    }
    result = crust_alloc(ctx, capacity * item_size, alignment);
    if (count != 0) {
        memcpy(result, old, count * item_size);
    }
    return result;
}

char *crust_copy_string(CrustContext *ctx, const unsigned char *text, size_t size)
{
    char *result;
    if (size == SIZE_MAX) {
        CrustLoc loc = {NULL, 0};
        crust_fail(ctx, loc, "string allocation size overflow");
    }
    result = crust_alloc(ctx, size + 1, 1);
    if (size != 0) {
        memcpy(result, text, size);
    }
    return result;
}

static uint64_t string_hash(const unsigned char *text, size_t size)
{
    uint64_t hash = UINT64_C(14695981039346656037);
    size_t index;
    for (index = 0; index < size; ++index) {
        hash ^= text[index];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

static void grow_names(CrustContext *ctx)
{
    size_t capacity = ctx->name_capacity == 0 ? 256 : ctx->name_capacity * 2;
    CrustName **entries;
    size_t index;
    if (capacity < ctx->name_capacity) {
        CrustLoc loc = {NULL, 0};
        crust_fail(ctx, loc, "name table size overflow");
    }
    entries = crust_grow_array(ctx, NULL, 0, capacity, sizeof(*entries),
                             CRUST_ALIGNOF(CrustName *));
    for (index = 0; index < ctx->name_capacity; ++index) {
        CrustName *name = ctx->names[index];
        if (name != NULL) {
            size_t slot = (size_t)name->hash & (capacity - 1);
            while (entries[slot] != NULL) {
                slot = (slot + 1) & (capacity - 1);
            }
            entries[slot] = name;
        }
    }
    ctx->names = entries;
    ctx->name_capacity = capacity;
}

CrustName *crust_intern(CrustContext *ctx, const unsigned char *text, size_t size)
{
    uint64_t hash = string_hash(text, size);
    size_t slot;
    CrustName *name;
    if (ctx->name_count >= ctx->name_capacity / 2) {
        grow_names(ctx);
    }
    slot = (size_t)hash & (ctx->name_capacity - 1);
    while ((name = ctx->names[slot]) != NULL) {
        if (name->hash == hash && name->size == size &&
            (size == 0 || memcmp(name->text, text, size) == 0)) {
            return name;
        }
        slot = (slot + 1) & (ctx->name_capacity - 1);
    }
    name = crust_alloc(ctx, sizeof(*name), CRUST_ALIGNOF(CrustName));
    name->text = crust_copy_string(ctx, text, size);
    name->size = size;
    name->hash = hash;
    ctx->names[slot] = name;
    ++ctx->name_count;
    return name;
}

static size_t map_hash(uintptr_t key)
{
    uint64_t value = (uint64_t)key;
    value ^= value >> 30;
    value *= UINT64_C(0xbf58476d1ce4e5b9);
    value ^= value >> 27;
    value *= UINT64_C(0x94d049bb133111eb);
    value ^= value >> 31;
    return (size_t)value;
}

void *crust_map_get(const CrustMap *map, uintptr_t key)
{
    size_t slot;
    if (map->capacity == 0 || key == 0) {
        return NULL;
    }
    slot = map_hash(key) & (map->capacity - 1);
    while (map->entries[slot].key != 0) {
        if (map->entries[slot].key == key) {
            return map->entries[slot].value;
        }
        slot = (slot + 1) & (map->capacity - 1);
    }
    return NULL;
}

void crust_map_set(CrustContext *ctx, CrustMap *map, uintptr_t key, void *value)
{
    size_t slot;
    if (key == 0) {
        CrustLoc loc = {NULL, 0};
        crust_fail(ctx, loc, "zero is not a table key");
    }
    if (map->count >= map->capacity / 2) {
        size_t capacity = map->capacity == 0 ? 64 : map->capacity * 2;
        CrustMapEntry *entries;
        size_t index;
        if (capacity < map->capacity) {
            CrustLoc loc = {NULL, 0};
            crust_fail(ctx, loc, "map allocation size overflow");
        }
        entries = crust_grow_array(ctx, NULL, 0, capacity, sizeof(*entries),
                                 CRUST_ALIGNOF(CrustMapEntry));
        for (index = 0; index < map->capacity; ++index) {
            if (map->entries[index].key != 0) {
                slot = map_hash(map->entries[index].key) & (capacity - 1);
                while (entries[slot].key != 0) {
                    slot = (slot + 1) & (capacity - 1);
                }
                entries[slot] = map->entries[index];
            }
        }
        map->entries = entries;
        map->capacity = capacity;
    }
    slot = map_hash(key) & (map->capacity - 1);
    while (map->entries[slot].key != 0 && map->entries[slot].key != key) {
        slot = (slot + 1) & (map->capacity - 1);
    }
    if (map->entries[slot].key == 0) {
        map->entries[slot].key = key;
        ++map->count;
    }
    map->entries[slot].value = value;
}
