/* SPDX-License-Identifier: Apache-2.0 */

#define _XOPEN_SOURCE 700
#include "crust0_host.h"
#include "proof.h"

#include <assert.h>
#include <dlfcn.h>
#include <ffi.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void (*Native)(void);
typedef char NativeSize[(sizeof(Native) == sizeof(void *)) ? 1 : -1];

static void diagnostic(const CrustContext *context)
{
    const CrustSource *source = context->error_loc.source;
    size_t line = 1;
    size_t column = 1;
    size_t index;
    if (source == NULL) {
        fprintf(stderr, "source-proof: %s\n", context->error);
        return;
    }
    for (index = 0; index < context->error_loc.offset && index < source->size; ++index) {
        if (source->bytes[index] == '\n') {
            ++line;
            column = 1;
        } else
            ++column;
    }
    fprintf(stderr, "%s:%zu:%zu: %s\n", source->path, line, column, context->error);
}

static bool error(CrustContext *context, CrustSource *source, size_t offset, const char *message)
{
    crust_set_error(context, source, offset, message);
    return false;
}

static CrustExpr *new_expression(CrustContext *context, CrustSource *source, size_t offset,
                                 CrustExprKind kind)
{
    CrustExpr *expression = crust_try_alloc(context, sizeof(*expression), CRUST_ALIGNOF(CrustExpr));
    if (expression != NULL) {
        expression->kind = kind;
        expression->loc.source = source;
        expression->loc.offset = offset;
    }
    return expression;
}

static bool whitespace(unsigned char byte)
{
    return byte == ' ' || byte == '\n' || byte == '\r' || byte == '\t';
}

static void skip_space(const CrustSource *source, size_t *offset)
{
    while (*offset < source->size && whitespace(source->bytes[*offset]))
        ++*offset;
}

static bool name_byte(unsigned char byte, bool first)
{
    return (byte >= 'a' && byte <= 'z') || (byte >= 'A' && byte <= 'Z') || byte == '_' ||
           (!first && byte >= '0' && byte <= '9');
}

static CrustExpr *read_name(CrustContext *context, CrustSource *source, size_t *offset)
{
    size_t start = *offset;
    CrustExpr *expression;
    if (start == source->size || !name_byte(source->bytes[start], true)) {
        error(context, source, start, "proof expected a name");
        return NULL;
    }
    do {
        ++*offset;
    } while (*offset < source->size && name_byte(source->bytes[*offset], false));
    expression = new_expression(context, source, start, CRUST_E_NAME);
    if (expression != NULL) {
        expression->name = crust_try_intern(context, source->bytes + start, *offset - start);
        if (expression->name == NULL)
            return NULL;
    }
    return expression;
}

static bool punctuation(CrustContext *context, CrustSource *source, size_t *offset,
                        unsigned char byte)
{
    skip_space(source, offset);
    if (*offset == source->size || source->bytes[*offset] != byte)
        return error(context, source, *offset, "proof call has unexpected punctuation");
    ++*offset;
    return true;
}

static CrustExpr *read_argument(CrustContext *context, CrustSource *source, size_t *offset)
{
    CrustExpr *expression;
    size_t start;
    skip_space(source, offset);
    if (*offset == source->size || source->bytes[*offset] != '"')
        return read_name(context, source, offset);
    start = ++*offset;
    while (*offset < source->size && source->bytes[*offset] != '"') {
        unsigned char byte = source->bytes[*offset];
        if (byte == 0 || byte == '\n' || byte == '\r' || byte == '\\') {
            error(context, source, *offset, "proof strings accept plain path bytes only");
            return NULL;
        }
        ++*offset;
    }
    if (*offset == source->size) {
        error(context, source, start, "unterminated proof string");
        return NULL;
    }
    expression = new_expression(context, source, start - 1, CRUST_E_STRING);
    if (expression == NULL)
        return NULL;
    expression->bytes = (const unsigned char *)crust_try_copy_string(context, source->bytes + start,
                                                                     *offset - start);
    expression->byte_count = *offset - start + 1;
    ++*offset;
    return expression->bytes == NULL ? NULL : expression;
}

static int32_t initial_reader(void *state, void *arena, void *result)
{
    ProofSession *session = state;
    CrustContext *context = arena;
    ProofAction *action = result;
    CrustSource *source = session->source;
    size_t offset = session->cursor;
    CrustExpr *call;
    skip_space(source, &offset);
    if (offset == source->size) {
        action->next_offset = offset;
        return 0;
    }
    call = new_expression(context, source, offset, CRUST_E_CALL);
    if (call == NULL)
        return -1;
    call->left = read_name(context, source, &offset);
    if (call->left == NULL || !punctuation(context, source, &offset, '('))
        return -1;
    call->args = crust_try_alloc(context, 2 * sizeof(*call->args), CRUST_ALIGNOF(CrustExpr *));
    if (call->args == NULL)
        return -1;
    do {
        if (call->arg_count == 2) {
            error(context, source, offset, "proof calls accept at most two arguments");
            return -1;
        }
        call->args[call->arg_count] = read_argument(context, source, &offset);
        if (call->args[call->arg_count] == NULL)
            return -1;
        ++call->arg_count;
        skip_space(source, &offset);
        if (offset == source->size || source->bytes[offset] != ',')
            break;
        ++offset;
    } while (true);
    if (!punctuation(context, source, &offset, ')') || !punctuation(context, source, &offset, ';'))
        return -1;
    /* The action owns its semicolon. The next byte is not inspected here. */
    action->call = call;
    action->next_offset = offset;
    return 1;
}

static CrustDecl *lookup(CrustContext *provider, const char *text, size_t size)
{
    CrustName *name = crust_try_intern(provider, (const unsigned char *)text, size);
    CrustSymbol *symbol;
    if (name == NULL)
        return NULL;
    symbol = crust_map_get(&provider->globals, (uintptr_t)name);
    return symbol == NULL ? NULL : symbol->decl;
}

static bool bind_name(CrustContext *context, CrustContext *provider, CrustName *name,
                      CrustLoc location)
{
    CrustDecl *declaration;
    if (crust_map_get(&context->globals, (uintptr_t)name) != NULL)
        return true;
    declaration = lookup(provider, name->text, name->size);
    if (declaration == NULL)
        return error(context, location.source, location.offset, "unknown root binding");
    return crust_bind(context, name, declaration);
}

static CrustDecl *check_action(CrustContext *context, CrustContext *provider, ProofAction *action)
{
    CrustDecl *session_record = lookup(provider, "ProofSession", sizeof("ProofSession") - 1);
    CrustDecl *function;
    CrustType *type;
    CrustParam *parameter;
    CrustStmt *block;
    CrustStmt *statement;
    CrustName *session_name;
    size_t index;
    CrustExpr *call = action->call;
    if (session_record == NULL)
        return NULL;
    assert(call->kind == CRUST_E_CALL && call->left->kind == CRUST_E_NAME);
    if (!crust_bind(context, session_record->name, session_record) ||
        !bind_name(context, provider, call->left->name, call->left->loc))
        return NULL;
    session_name = crust_try_intern(context, (const unsigned char *)"session", 7);
    if (session_name == NULL)
        return NULL;
    for (index = 0; index < call->arg_count; ++index) {
        CrustExpr *argument = call->args[index];
        if (argument->kind == CRUST_E_NAME && argument->name != session_name &&
            !bind_name(context, provider, argument->name, argument->loc))
            return NULL;
    }
    function = crust_try_alloc(context, sizeof(*function), CRUST_ALIGNOF(CrustDecl));
    type = crust_try_alloc(context, sizeof(*type), CRUST_ALIGNOF(CrustType));
    parameter = crust_try_alloc(context, sizeof(*parameter), CRUST_ALIGNOF(CrustParam));
    block = crust_try_alloc(context, sizeof(*block), CRUST_ALIGNOF(CrustStmt));
    statement = crust_try_alloc(context, sizeof(*statement), CRUST_ALIGNOF(CrustStmt));
    if (function == NULL || type == NULL || parameter == NULL || block == NULL || statement == NULL)
        return NULL;
    parameter->name = session_name;
    parameter->loc = call->loc;
    parameter->type = crust_try_pointer_type(context, session_record->type);
    type->params = crust_try_alloc(context, sizeof(*type->params), CRUST_ALIGNOF(CrustType *));
    if (parameter->type == NULL || type->params == NULL)
        return NULL;
    type->kind = CRUST_T_FUNCTION;
    type->size = sizeof(Native);
    type->align = CRUST_ALIGNOF(Native);
    type->base = &context->builtins[CRUST_T_I32];
    type->param_count = 1;
    type->params[0] = parameter->type;
    block->kind = CRUST_S_BLOCK;
    block->loc = call->loc;
    block->body = statement;
    statement->kind = CRUST_S_RETURN;
    statement->loc = call->loc;
    statement->expr = call;
    function->kind = CRUST_D_FUNCTION;
    function->loc = call->loc;
    function->type = type;
    function->params = parameter;
    function->param_count = 1;
    function->body = block;
    function->resolve_state = 2;
    return crust_check_body(context, function) ? function : NULL;
}

static Native native_address(CrustContext *context, const CrustDecl *declaration, void **libraries,
                             size_t count)
{
    void *address = NULL;
    Native result = NULL;
    size_t index;
    for (index = 0; index < count; ++index) {
        void *candidate;
        const char *failure;
        dlerror();
        candidate = dlsym(libraries[index], declaration->link_name);
        failure = dlerror();
        if (failure != NULL)
            continue;
        if (candidate == NULL || (address != NULL && address != candidate)) {
            error(context, declaration->loc.source, declaration->loc.offset,
                  "conflicting native symbol");
            return NULL;
        }
        address = candidate;
    }
    if (address == NULL) {
        error(context, declaration->loc.source, declaration->loc.offset,
              "unresolved native symbol");
        return NULL;
    }
    memcpy(&result, &address, sizeof(result));
    return result;
}

static bool execute_action(ProofSession *session, CrustContext *context, CrustDecl *function,
                           ProofAction *action, void **libraries, size_t library_count)
{
    CrustExpr *call = action->call;
    CrustDecl *declaration = call->left->symbol->decl;
    Native native;
    ffi_cif interface;
    ffi_type *types[2];
    void *values[2];
    union {
        void *pointer;
        Native function;
    } storage[2];
    ffi_arg result = 0;
    uint32_t bits;
    int32_t status;
    size_t index;
    if (declaration->kind != CRUST_D_EXTERN || declaration->type->base->kind != CRUST_T_I32 ||
        call->arg_count > 2)
        return error(context, call->loc.source, call->loc.offset,
                     "proof requires an external status-returning call");
    native = native_address(context, declaration, libraries, library_count);
    if (native == NULL)
        return false;
    for (index = 0; index < call->arg_count; ++index) {
        CrustExpr *argument = call->args[index];
        types[index] = &ffi_type_pointer;
        if (argument->kind == CRUST_E_NAME && argument->symbol == function->params->symbol) {
            storage[index].pointer = session;
            values[index] = &storage[index].pointer;
        } else if (argument->kind == CRUST_E_NAME && argument->type->kind == CRUST_T_FUNCTION &&
                   argument->symbol->decl->kind == CRUST_D_EXTERN) {
            storage[index].function =
                native_address(context, argument->symbol->decl, libraries, library_count);
            if (storage[index].function == NULL)
                return false;
            values[index] = &storage[index].function;
        } else if (argument->kind == CRUST_E_STRING) {
            storage[index].pointer = (void *)argument->bytes;
            values[index] = &storage[index].pointer;
        } else {
            return error(context, argument->loc.source, argument->loc.offset,
                         "unsupported proof argument expression");
        }
    }
    if (ffi_prep_cif(&interface, FFI_DEFAULT_ABI, (unsigned)call->arg_count, &ffi_type_sint32,
                     types) != FFI_OK)
        return error(context, call->loc.source, call->loc.offset,
                     "libffi rejected a checked call signature");
    ffi_call(&interface, native, &result, values);
    bits = (uint32_t)result;
    memcpy(&status, &bits, sizeof(status));
    if (status != 0 && session->owner->error_count == 0 && session->target->error_count == 0)
        return error(context, call->loc.source, call->loc.offset, "root operation failed");
    return status == 0;
}

static bool interface_layout(CrustContext *provider)
{
    static const size_t offsets[] = {
        offsetof(ProofSession, owner),         offsetof(ProofSession, source),
        offsetof(ProofSession, cursor),        offsetof(ProofSession, reader),
        offsetof(ProofSession, backend),       offsetof(ProofSession, target),
        offsetof(ProofSession, argv),          offsetof(ProofSession, pending),
        offsetof(ProofSession, target_source), offsetof(ProofSession, switch_offset),
        offsetof(ProofSession, selections),    offsetof(ProofSession, reads),
        offsetof(ProofSession, includes),      offsetof(ProofSession, emits),
        offsetof(ProofSession, allocations),   offsetof(ProofSession, releases),
        offsetof(ProofSession, argc),          offsetof(ProofSession, root_done),
        offsetof(ProofSession, reader_active), offsetof(ProofSession, custom_started)};
    CrustDecl *declaration = lookup(provider, "ProofSession", 12);
    CrustDecl *action = lookup(provider, "ProofAction", 11);
    CrustField *field;
    size_t index;
    if (declaration == NULL || declaration->kind != CRUST_D_RECORD ||
        declaration->type->size != sizeof(ProofSession) ||
        declaration->type->align != CRUST_ALIGNOF(ProofSession) ||
        declaration->field_count != sizeof(offsets) / sizeof(offsets[0]) || action == NULL ||
        action->kind != CRUST_D_RECORD || action->type->size != sizeof(ProofAction) ||
        action->type->align != CRUST_ALIGNOF(ProofAction) || action->field_count != 2 ||
        action->fields->offset != offsetof(ProofAction, call) ||
        action->fields->next->offset != offsetof(ProofAction, next_offset))
        return error(provider, NULL, 0, "proof interface layout differs from the runner");
    field = declaration->fields;
    for (index = 0; index < sizeof(offsets) / sizeof(offsets[0]); ++index, field = field->next)
        if (field->offset != offsets[index])
            return error(provider, NULL, 0, "proof session field offset differs from the runner");
    return true;
}

static bool read_provider(CrustContext *context, const char *path, uint64_t identity)
{
    CrustSource *source = crust_try_alloc(context, sizeof(*source), CRUST_ALIGNOF(CrustSource));
    CrustUnit *parsed;
    unsigned char *bytes;
    if (source == NULL)
        return false;
    source->path = path;
    source->identity = identity;
    if (crust0_host_read_file(path, &bytes, &source->size) != 0)
        return error(context, NULL, 0, "cannot read proof host interface");
    source->bytes = (const unsigned char *)crust_try_copy_string(context, bytes, source->size);
    free(bytes);
    return source->bytes != NULL && crust_read(context, source, &parsed);
}

int main(int argc, char **argv)
{
    CrustContext provider;
    CrustContext target;
    CrustSource source;
    ProofSession session;
    void **libraries;
    size_t library_count = 0;
    uint64_t identity = 1000;
    const char *report = NULL;
    unsigned char *root_bytes = NULL;
    int index;
    int status = 1;
    if (argc < 2) {
        fputs("usage: runner ROOT --api FILE --load LIBRARY [--report FILE] -- ROOT_ARGUMENTS\n",
              stderr);
        return 1;
    }
    libraries = calloc((size_t)argc, sizeof(*libraries));
    if (libraries == NULL) {
        perror("source-proof: libraries");
        return 1;
    }
    crust_context_init(&provider, NULL);
    crust_context_init(&target, NULL);
    memset(&session, 0, sizeof(session));
    session.owner = &provider;
    session.source = &source;
    session.reader = initial_reader;
    session.target = &target;
    source.path = argv[1];
    source.identity = 1;
    source.bytes = NULL;
    source.size = 0;
    for (index = 2; index < argc; ++index) {
        const char *option = argv[index];
        if (strcmp(option, "--") == 0) {
            session.argc = (int32_t)(argc - index - 1);
            session.argv = argv + index + 1;
            break;
        }
        if (++index == argc) {
            fputs("source-proof: missing option value\n", stderr);
            goto done;
        }
        if (strcmp(option, "--api") == 0) {
            if (!read_provider(&provider, argv[index], identity++))
                goto done;
        } else if (strcmp(option, "--load") == 0) {
            libraries[library_count] = dlopen(argv[index], RTLD_NOW | RTLD_LOCAL);
            if (libraries[library_count] == NULL) {
                fprintf(stderr, "source-proof: cannot load library: %s\n", dlerror());
                goto done;
            }
            ++library_count;
        } else if (strcmp(option, "--report") == 0) {
            report = argv[index];
        } else {
            fputs("source-proof: unknown launcher option\n", stderr);
            goto done;
        }
    }
    if (!crust_collect(&provider) || !crust_resolve(&provider) || !crust_check(&provider) ||
        !interface_layout(&provider))
        goto done;
    if (crust0_host_read_file(source.path, &root_bytes, &source.size) != 0) {
        error(&provider, NULL, 0, "cannot read root source");
        goto done;
    }
    source.bytes = root_bytes;
    while (session.cursor < source.size) {
        CrustContext action_context;
        ProofAction action;
        CrustDecl *function;
        size_t start = session.cursor;
        int32_t read_status;
        bool success = false;
        crust_context_init(&action_context, NULL);
        memset(&action, 0, sizeof(action));
        session.reader_active = true;
        read_status = session.reader(&session, &action_context, &action);
        session.reader_active = false;
        if (read_status < 0)
            goto action_done;
        if (action.next_offset > source.size || (read_status != 0 && action.next_offset <= start) ||
            (read_status == 0 && action.next_offset != source.size)) {
            error(&action_context, &source, start, "reader returned an invalid cursor boundary");
            goto action_done;
        }
        session.cursor = action.next_offset;
        if (read_status == 0) {
            success = true;
            goto action_done;
        }
        function = check_action(&action_context, &provider, &action);
        if (function != NULL)
            success = execute_action(&session, &action_context, function, &action, libraries,
                                     library_count);
    action_done:
        if (action_context.error_count != 0) {
            diagnostic(&action_context);
            success = false;
        }
        crust_context_destroy(&action_context);
        if (!success || provider.error_count != 0 || target.error_count != 0)
            goto done;
    }
    session.root_done = true;
    if (session.pending != NULL) {
        int32_t (*pending)(void *) = session.pending;
        session.pending = NULL;
        status = pending(&session);
    } else
        status = 0;
done:
    if (provider.error_count != 0) {
        diagnostic(&provider);
        status = 1;
    }
    if (target.error_count != 0) {
        diagnostic(&target);
        status = 1;
    }
    crust_context_destroy(&target);
    if (session.allocations != session.releases) {
        fputs("source-proof: target allocator callbacks did not balance\n", stderr);
        status = 1;
    }
    if (report != NULL) {
        FILE *file = fopen(report, "wb");
        if (file == NULL) {
            perror("source-proof: report");
            status = 1;
        } else {
            bool success =
                fprintf(file,
                        "{\"status\":%d,\"cursor\":%zu,\"size\":%zu,\"switch_offset\":%zu,"
                        "\"selections\":%zu,\"reads\":%zu,\"includes\":%zu,\"emits\":%zu,"
                        "\"allocations\":%zu,\"releases\":%zu,\"root_done\":%s}\n",
                        status, session.cursor, source.size, session.switch_offset,
                        session.selections, session.reads, session.includes, session.emits,
                        session.allocations, session.releases,
                        session.root_done ? "true" : "false") >= 0;
            if (fclose(file) != 0)
                success = false;
            if (!success) {
                perror("source-proof: report write");
                status = 1;
            }
        }
    }
    crust_context_destroy(&provider);
    while (library_count != 0) {
        --library_count;
        if (dlclose(libraries[library_count]) != 0) {
            fputs("source-proof: unload failed\n", stderr);
            status = 1;
        }
    }
    free(root_bytes);
    free(libraries);
    if (fflush(stdout) != 0) {
        perror("source-proof: stdout");
        status = 1;
    }
    return status;
}
