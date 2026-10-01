#define _XOPEN_SOURCE 700
#include "proof.h"
#include "rmd0_host.h"

#include <assert.h>
#include <dlfcn.h>
#include <ffi.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void (*Native)(void);
typedef char NativeSize[(sizeof(Native) == sizeof(void *)) ? 1 : -1];

static void diagnostic(const RmdContext *context)
{
    const RmdSource *source = context->error_loc.source;
    size_t line = 1;
    size_t column = 1;
    size_t index;
    if (source == NULL) { fprintf(stderr, "source-proof: %s\n", context->error); return; }
    for (index = 0; index < context->error_loc.offset && index < source->size; ++index) {
        if (source->bytes[index] == '\n') { ++line; column = 1; }
        else ++column;
    }
    fprintf(stderr, "%s:%zu:%zu: %s\n", source->path, line, column, context->error);
}

static bool error(RmdContext *context, RmdSource *source, size_t offset, const char *message)
{
    rmd_set_error(context, source, offset, message);
    return false;
}

static RmdExpr *new_expression(RmdContext *context, RmdSource *source,
                                size_t offset, RmdExprKind kind)
{
    RmdExpr *expression = rmd_try_alloc(context, sizeof(*expression), RMD_ALIGNOF(RmdExpr));
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

static void skip_space(const RmdSource *source, size_t *offset)
{
    while (*offset < source->size && whitespace(source->bytes[*offset])) ++*offset;
}

static bool name_byte(unsigned char byte, bool first)
{
    return (byte >= 'a' && byte <= 'z') || (byte >= 'A' && byte <= 'Z') ||
           byte == '_' || (!first && byte >= '0' && byte <= '9');
}

static RmdExpr *read_name(RmdContext *context, RmdSource *source, size_t *offset)
{
    size_t start = *offset;
    RmdExpr *expression;
    if (start == source->size || !name_byte(source->bytes[start], true)) {
        error(context, source, start, "proof expected a name");
        return NULL;
    }
    do { ++*offset; }
    while (*offset < source->size && name_byte(source->bytes[*offset], false));
    expression = new_expression(context, source, start, RMD_E_NAME);
    if (expression != NULL) {
        expression->name = rmd_try_intern(context, source->bytes + start, *offset - start);
        if (expression->name == NULL) return NULL;
    }
    return expression;
}

static bool punctuation(RmdContext *context, RmdSource *source,
                         size_t *offset, unsigned char byte)
{
    skip_space(source, offset);
    if (*offset == source->size || source->bytes[*offset] != byte)
        return error(context, source, *offset, "proof call has unexpected punctuation");
    ++*offset;
    return true;
}

static RmdExpr *read_argument(RmdContext *context, RmdSource *source, size_t *offset)
{
    RmdExpr *expression;
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
    expression = new_expression(context, source, start - 1, RMD_E_STRING);
    if (expression == NULL) return NULL;
    expression->bytes = (const unsigned char *)rmd_try_copy_string(context, source->bytes + start, *offset - start);
    expression->byte_count = *offset - start + 1;
    ++*offset;
    return expression->bytes == NULL ? NULL : expression;
}

static int32_t initial_reader(void *state, void *arena, void *result)
{
    ProofSession *session = state;
    RmdContext *context = arena;
    ProofAction *action = result;
    RmdSource *source = session->source;
    size_t offset = session->cursor;
    RmdExpr *call;
    skip_space(source, &offset);
    if (offset == source->size) { action->next_offset = offset; return 0; }
    call = new_expression(context, source, offset, RMD_E_CALL);
    if (call == NULL) return -1;
    call->left = read_name(context, source, &offset);
    if (call->left == NULL || !punctuation(context, source, &offset, '(')) return -1;
    call->args = rmd_try_alloc(context, 2 * sizeof(*call->args), RMD_ALIGNOF(RmdExpr *));
    if (call->args == NULL) return -1;
    do {
        if (call->arg_count == 2) {
            error(context, source, offset, "proof calls accept at most two arguments");
            return -1;
        }
        call->args[call->arg_count] = read_argument(context, source, &offset);
        if (call->args[call->arg_count] == NULL) return -1;
        ++call->arg_count;
        skip_space(source, &offset);
        if (offset == source->size || source->bytes[offset] != ',') break;
        ++offset;
    } while (true);
    if (!punctuation(context, source, &offset, ')') ||
        !punctuation(context, source, &offset, ';')) return -1;
    /* The action owns its semicolon. The next byte is not inspected here. */
    action->call = call;
    action->next_offset = offset;
    return 1;
}

static RmdDecl *lookup(RmdContext *provider, const char *text, size_t size)
{
    RmdName *name = rmd_try_intern(provider, (const unsigned char *)text, size);
    RmdSymbol *symbol;
    if (name == NULL) return NULL;
    symbol = rmd_map_get(&provider->globals, (uintptr_t)name);
    return symbol == NULL ? NULL : symbol->decl;
}

static bool bind_name(RmdContext *context, RmdContext *provider, RmdName *name, RmdLoc location)
{
    RmdDecl *declaration;
    if (rmd_map_get(&context->globals, (uintptr_t)name) != NULL) return true;
    declaration = lookup(provider, name->text, name->size);
    if (declaration == NULL)
        return error(context, location.source, location.offset, "unknown root binding");
    return rmd_bind(context, name, declaration);
}

static RmdDecl *check_action(RmdContext *context, RmdContext *provider, ProofAction *action)
{
    RmdDecl *session_record = lookup(provider, "ProofSession", sizeof("ProofSession") - 1);
    RmdDecl *function;
    RmdType *type;
    RmdParam *parameter;
    RmdStmt *block;
    RmdStmt *statement;
    RmdName *session_name;
    size_t index;
    RmdExpr *call = action->call;
    if (session_record == NULL) return NULL;
    assert(call->kind == RMD_E_CALL && call->left->kind == RMD_E_NAME);
    if (!rmd_bind(context, session_record->name, session_record) ||
        !bind_name(context, provider, call->left->name, call->left->loc)) return NULL;
    session_name = rmd_try_intern(context, (const unsigned char *)"session", 7);
    if (session_name == NULL) return NULL;
    for (index = 0; index < call->arg_count; ++index) {
        RmdExpr *argument = call->args[index];
        if (argument->kind == RMD_E_NAME && argument->name != session_name &&
            !bind_name(context, provider, argument->name, argument->loc)) return NULL;
    }
    function = rmd_try_alloc(context, sizeof(*function), RMD_ALIGNOF(RmdDecl));
    type = rmd_try_alloc(context, sizeof(*type), RMD_ALIGNOF(RmdType));
    parameter = rmd_try_alloc(context, sizeof(*parameter), RMD_ALIGNOF(RmdParam));
    block = rmd_try_alloc(context, sizeof(*block), RMD_ALIGNOF(RmdStmt));
    statement = rmd_try_alloc(context, sizeof(*statement), RMD_ALIGNOF(RmdStmt));
    if (function == NULL || type == NULL || parameter == NULL || block == NULL || statement == NULL) return NULL;
    parameter->name = session_name;
    parameter->loc = call->loc;
    parameter->type = rmd_try_pointer_type(context, session_record->type);
    type->params = rmd_try_alloc(context, sizeof(*type->params), RMD_ALIGNOF(RmdType *));
    if (parameter->type == NULL || type->params == NULL) return NULL;
    type->kind = RMD_T_FUNCTION;
    type->size = sizeof(Native);
    type->align = RMD_ALIGNOF(Native);
    type->base = &context->builtins[RMD_T_I32];
    type->param_count = 1;
    type->params[0] = parameter->type;
    block->kind = RMD_S_BLOCK;
    block->loc = call->loc;
    block->body = statement;
    statement->kind = RMD_S_RETURN;
    statement->loc = call->loc;
    statement->expr = call;
    function->kind = RMD_D_FUNCTION;
    function->loc = call->loc;
    function->type = type;
    function->params = parameter;
    function->param_count = 1;
    function->body = block;
    function->resolve_state = 2;
    return rmd_check_body(context, function) ? function : NULL;
}

static Native native_address(RmdContext *context, const RmdDecl *declaration,
                              void **libraries, size_t count)
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
        if (failure != NULL) continue;
        if (candidate == NULL || (address != NULL && address != candidate)) {
            error(context, declaration->loc.source, declaration->loc.offset, "conflicting native symbol");
            return NULL;
        }
        address = candidate;
    }
    if (address == NULL) {
        error(context, declaration->loc.source, declaration->loc.offset, "unresolved native symbol");
        return NULL;
    }
    memcpy(&result, &address, sizeof(result));
    return result;
}

static bool execute_action(ProofSession *session, RmdContext *context,
                            RmdDecl *function, ProofAction *action,
                            void **libraries, size_t library_count)
{
    RmdExpr *call = action->call;
    RmdDecl *declaration = call->left->symbol->decl;
    Native native;
    ffi_cif interface;
    ffi_type *types[2];
    void *values[2];
    union { void *pointer; Native function; } storage[2];
    ffi_arg result = 0;
    uint32_t bits;
    int32_t status;
    size_t index;
    if (declaration->kind != RMD_D_EXTERN || declaration->type->base->kind != RMD_T_I32 || call->arg_count > 2)
        return error(context, call->loc.source, call->loc.offset, "proof requires an external status-returning call");
    native = native_address(context, declaration, libraries, library_count);
    if (native == NULL) return false;
    for (index = 0; index < call->arg_count; ++index) {
        RmdExpr *argument = call->args[index];
        types[index] = &ffi_type_pointer;
        if (argument->kind == RMD_E_NAME && argument->symbol == function->params->symbol) {
            storage[index].pointer = session;
            values[index] = &storage[index].pointer;
        } else if (argument->kind == RMD_E_NAME && argument->type->kind == RMD_T_FUNCTION &&
                   argument->symbol->decl->kind == RMD_D_EXTERN) {
            storage[index].function = native_address(context, argument->symbol->decl, libraries, library_count);
            if (storage[index].function == NULL) return false;
            values[index] = &storage[index].function;
        } else if (argument->kind == RMD_E_STRING) {
            storage[index].pointer = (void *)argument->bytes;
            values[index] = &storage[index].pointer;
        } else {
            return error(context, argument->loc.source, argument->loc.offset, "unsupported proof argument expression");
        }
    }
    if (ffi_prep_cif(&interface, FFI_DEFAULT_ABI, (unsigned)call->arg_count, &ffi_type_sint32, types) != FFI_OK)
        return error(context, call->loc.source, call->loc.offset, "libffi rejected a checked call signature");
    ffi_call(&interface, native, &result, values);
    bits = (uint32_t)result;
    memcpy(&status, &bits, sizeof(status));
    if (status != 0 && session->owner->error_count == 0 && session->target->error_count == 0)
        return error(context, call->loc.source, call->loc.offset, "root operation failed");
    return status == 0;
}

static bool interface_layout(RmdContext *provider)
{
    static const size_t offsets[] = {
        offsetof(ProofSession, owner), offsetof(ProofSession, source), offsetof(ProofSession, cursor),
        offsetof(ProofSession, reader), offsetof(ProofSession, backend), offsetof(ProofSession, target),
        offsetof(ProofSession, argc), offsetof(ProofSession, argv), offsetof(ProofSession, pending),
        offsetof(ProofSession, target_source), offsetof(ProofSession, switch_offset),
        offsetof(ProofSession, selections), offsetof(ProofSession, reads), offsetof(ProofSession, includes),
        offsetof(ProofSession, emits), offsetof(ProofSession, allocations), offsetof(ProofSession, releases),
        offsetof(ProofSession, root_done), offsetof(ProofSession, reader_active), offsetof(ProofSession, custom_started)
    };
    RmdDecl *declaration = lookup(provider, "ProofSession", 12);
    RmdDecl *action = lookup(provider, "ProofAction", 11);
    RmdField *field;
    size_t index;
    if (declaration == NULL || declaration->kind != RMD_D_RECORD ||
        declaration->type->size != sizeof(ProofSession) || declaration->type->align != RMD_ALIGNOF(ProofSession) ||
        declaration->field_count != sizeof(offsets) / sizeof(offsets[0]) ||
        action == NULL || action->kind != RMD_D_RECORD || action->type->size != sizeof(ProofAction) ||
        action->type->align != RMD_ALIGNOF(ProofAction) || action->field_count != 2 ||
        action->fields->offset != offsetof(ProofAction, call) ||
        action->fields->next->offset != offsetof(ProofAction, next_offset))
        return error(provider, NULL, 0, "proof interface layout differs from the runner");
    field = declaration->fields;
    for (index = 0; index < sizeof(offsets) / sizeof(offsets[0]); ++index, field = field->next)
        if (field->offset != offsets[index])
            return error(provider, NULL, 0, "proof session field offset differs from the runner");
    return true;
}

static bool read_provider(RmdContext *context, const char *path, uint64_t identity)
{
    RmdSource *source = rmd_try_alloc(context, sizeof(*source), RMD_ALIGNOF(RmdSource));
    RmdUnit *parsed;
    unsigned char *bytes;
    if (source == NULL) return false;
    source->path = path;
    source->identity = identity;
    if (rmd0_host_read_file(path, &bytes, &source->size) != 0)
        return error(context, NULL, 0, "cannot read proof host interface");
    source->bytes = (const unsigned char *)rmd_try_copy_string(context, bytes, source->size);
    free(bytes);
    return source->bytes != NULL && rmd_read(context, source, &parsed);
}

int main(int argc, char **argv)
{
    RmdContext provider;
    RmdContext target;
    RmdSource source;
    ProofSession session;
    void **libraries;
    size_t library_count = 0;
    uint64_t identity = 1000;
    const char *report = NULL;
    unsigned char *root_bytes = NULL;
    int index;
    int status = 1;
    if (argc < 2) { fputs("usage: runner ROOT --api FILE --load LIBRARY [--report FILE] -- ROOT_ARGUMENTS\n", stderr); return 1; }
    libraries = calloc((size_t)argc, sizeof(*libraries));
    if (libraries == NULL) { perror("source-proof: libraries"); return 1; }
    rmd_context_init(&provider, NULL);
    rmd_context_init(&target, NULL);
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
        if (++index == argc) { fputs("source-proof: missing option value\n", stderr); goto done; }
        if (strcmp(option, "--api") == 0) {
            if (!read_provider(&provider, argv[index], identity++)) goto done;
        } else if (strcmp(option, "--load") == 0) {
            libraries[library_count] = dlopen(argv[index], RTLD_NOW | RTLD_LOCAL);
            if (libraries[library_count] == NULL) {
                fprintf(stderr, "source-proof: cannot load library: %s\n", dlerror()); goto done;
            }
            ++library_count;
        } else if (strcmp(option, "--report") == 0) {
            report = argv[index];
        } else { fputs("source-proof: unknown launcher option\n", stderr); goto done; }
    }
    if (!rmd_collect(&provider) || !rmd_resolve(&provider) || !rmd_check(&provider) ||
        !interface_layout(&provider)) goto done;
    if (rmd0_host_read_file(source.path, &root_bytes, &source.size) != 0) {
        error(&provider, NULL, 0, "cannot read root source"); goto done;
    }
    source.bytes = root_bytes;
    while (session.cursor < source.size) {
        RmdContext action_context;
        ProofAction action;
        RmdDecl *function;
        size_t start = session.cursor;
        int32_t read_status;
        bool success = false;
        rmd_context_init(&action_context, NULL);
        memset(&action, 0, sizeof(action));
        session.reader_active = true;
        read_status = session.reader(&session, &action_context, &action);
        session.reader_active = false;
        if (read_status < 0) goto action_done;
        if (action.next_offset > source.size ||
            (read_status != 0 && action.next_offset <= start) ||
            (read_status == 0 && action.next_offset != source.size)) {
            error(&action_context, &source, start, "reader returned an invalid cursor boundary");
            goto action_done;
        }
        session.cursor = action.next_offset;
        if (read_status == 0) { success = true; goto action_done; }
        function = check_action(&action_context, &provider, &action);
        if (function != NULL)
            success = execute_action(&session, &action_context, function, &action, libraries, library_count);
action_done:
        if (action_context.error_count != 0) { diagnostic(&action_context); success = false; }
        rmd_context_destroy(&action_context);
        if (!success || provider.error_count != 0 || target.error_count != 0) goto done;
    }
    session.root_done = true;
    if (session.pending != NULL) {
        int32_t (*pending)(void *) = session.pending;
        session.pending = NULL;
        status = pending(&session);
    } else status = 0;
done:
    if (provider.error_count != 0) { diagnostic(&provider); status = 1; }
    if (target.error_count != 0) { diagnostic(&target); status = 1; }
    rmd_context_destroy(&target);
    if (session.allocations != session.releases) {
        fputs("source-proof: target allocator callbacks did not balance\n", stderr); status = 1;
    }
    if (report != NULL) {
        FILE *file = fopen(report, "wb");
        if (file == NULL) { perror("source-proof: report"); status = 1; }
        else {
            bool success = fprintf(file,
                "{\"status\":%d,\"cursor\":%zu,\"size\":%zu,\"switch_offset\":%zu,"
                "\"selections\":%zu,\"reads\":%zu,\"includes\":%zu,\"emits\":%zu,"
                "\"allocations\":%zu,\"releases\":%zu,\"root_done\":%s}\n",
                status, session.cursor, source.size, session.switch_offset, session.selections,
                session.reads, session.includes, session.emits, session.allocations, session.releases,
                session.root_done ? "true" : "false") >= 0;
            if (fclose(file) != 0) success = false;
            if (!success) { perror("source-proof: report write"); status = 1; }
        }
    }
    rmd_context_destroy(&provider);
    while (library_count != 0) {
        --library_count;
        if (dlclose(libraries[library_count]) != 0) { fputs("source-proof: unload failed\n", stderr); status = 1; }
    }
    free(root_bytes);
    free(libraries);
    if (fflush(stdout) != 0) { perror("source-proof: stdout"); status = 1; }
    return status;
}
