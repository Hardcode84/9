/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0.h"
#include "crust0_host.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

bool memory_alloc_verify(CrustContext *context, CrustSource *source, const char *summary);
void *__real_crust0_host_alloc(size_t size, size_t alignment);
void __real_crust0_host_free(void *allocation);
void *__wrap_crust0_host_alloc(size_t size, size_t alignment);
void __wrap_crust0_host_free(void *allocation);

typedef struct MemoryAllocState {
    size_t calls;
    size_t fail_at;
    size_t live;
    bool active;
    bool rejected;
    bool host_failed;
} MemoryAllocState;

static MemoryAllocState allocation_state;

void *__wrap_crust0_host_alloc(size_t size, size_t alignment)
{
    void *result;
    if (!allocation_state.active) {
        fputs("host allocation occurred outside verification\n", stderr);
        abort();
    }
    ++allocation_state.calls;
    if (allocation_state.calls == allocation_state.fail_at) {
        allocation_state.rejected = true;
        return NULL;
    }
    result = __real_crust0_host_alloc(size, alignment);
    if (result == NULL)
        allocation_state.host_failed = true;
    else
        ++allocation_state.live;
    return result;
}

void __wrap_crust0_host_free(void *allocation)
{
    if (allocation != NULL) {
        if (!allocation_state.active || allocation_state.live == 0) {
            fputs("host release has no live verification allocation\n", stderr);
            abort();
        }
        --allocation_state.live;
    }
    __real_crust0_host_free(allocation);
}

static bool valid_result(CrustContext *context, size_t fail_at, bool success)
{
    if (allocation_state.live != 0 || allocation_state.host_failed || context->failure != NULL)
        return false;
    if (fail_at == 0)
        return success && !allocation_state.rejected && context->error_count == 0;
    return !success && allocation_state.rejected && context->error_count != 0 &&
           context->error[0] != '\0';
}

static bool attempt(CrustSource *source, const char *summary, size_t fail_at, size_t *calls)
{
    CrustContext context;
    bool success;
    bool valid = false;
    crust_context_init(&context, NULL);
    memset(&allocation_state, 0, sizeof(allocation_state));
    allocation_state.active = true;
    allocation_state.fail_at = fail_at;
    success = memory_alloc_verify(&context, source, summary);
    allocation_state.active = false;
    *calls = allocation_state.calls;
    valid = valid_result(&context, fail_at, success);
    if (!valid) {
        fprintf(stderr, "%s: allocation %zu: invalid verifier result or lifetime state: %s\n",
                source->path, fail_at, context.error);
    }
    crust_context_destroy(&context);
    return valid;
}

static bool read_source(const char *path, CrustSource *source)
{
    FILE *stream = fopen(path, "rb");
    long length;
    unsigned char *bytes;
    bool success;
    if (stream == NULL)
        return false;
    if (fseek(stream, 0, SEEK_END) != 0 || (length = ftell(stream)) <= 0 ||
        fseek(stream, 0, SEEK_SET) != 0) {
        fclose(stream);
        return false;
    }
    bytes = malloc((size_t)length);
    if (bytes == NULL) {
        fclose(stream);
        return false;
    }
    success = fread(bytes, 1, (size_t)length, stream) == (size_t)length;
    if (fclose(stream) != 0)
        success = false;
    if (!success) {
        free(bytes);
        return false;
    }
    source->path = path;
    source->bytes = bytes;
    source->size = (size_t)length;
    source->identity = 1;
    return true;
}

static int check_source(CrustSource *source, const char *summary)
{
    size_t count = 0;
    size_t fail_at;
    size_t calls;
    if (!attempt(source, summary, 0, &count) || count == 0)
        return EXIT_FAILURE;
    for (fail_at = 1; fail_at <= count; ++fail_at) {
        if (!attempt(source, summary, fail_at, &calls))
            return EXIT_FAILURE;
    }
    if (!attempt(source, summary, 0, &calls) || calls != count) {
        fputs("verification did not recover after injected failures\n", stderr);
        return EXIT_FAILURE;
    }
    printf("memory allocation: %zu failure points checked\n", count);
    return EXIT_SUCCESS;
}

int main(int argc, char **argv)
{
    CrustSource source;
    int result;
    if (argc != 2 && argc != 3) {
        fputs("usage: memory-alloc SOURCE [SUMMARY]\n", stderr);
        return EXIT_FAILURE;
    }
    if (!read_source(argv[1], &source)) {
        fprintf(stderr, "cannot read source: %s\n", argv[1]);
        return EXIT_FAILURE;
    }
    result = check_source(&source, argc == 3 ? argv[2] : NULL);
    free((void *)source.bytes);
    return result;
}
