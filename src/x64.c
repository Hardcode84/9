#include "rmd0_x64.h"

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

static void callback_failure(RmdX64Emitter *emitter, size_t previous_errors, RmdLoc location)
{
    RmdContext *ctx = emitter->program->context;
    if (ctx->error_count == previous_errors)
        rmd_fail(ctx, location, "custom backend operation failed without a diagnostic");
    longjmp(ctx->failure->jump, 1);
}

static void emit_expression(RmdX64Emitter *emitter, RmdExpr *expression)
{
    if (emitter->operations && emitter->operations->expression) {
        size_t previous_errors = emitter->program->context->error_count;
        if (!emitter->operations->expression(emitter, expression))
            callback_failure(emitter, previous_errors, expression->loc);
    } else {
        rmd_x64_emit_expression(emitter, expression);
    }
}

static void emit_place(RmdX64Emitter *emitter, RmdExpr *expression)
{
    if (emitter->operations && emitter->operations->place) {
        size_t previous_errors = emitter->program->context->error_count;
        if (!emitter->operations->place(emitter, expression))
            callback_failure(emitter, previous_errors, expression->loc);
    } else {
        rmd_x64_emit_place(emitter, expression);
    }
}

static void emit_statement(RmdX64Emitter *emitter, RmdStmt *statement)
{
    if (emitter->operations && emitter->operations->statement) {
        size_t previous_errors = emitter->program->context->error_count;
        if (!emitter->operations->statement(emitter, statement))
            callback_failure(emitter, previous_errors, statement->loc);
    } else {
        rmd_x64_emit_statement(emitter, statement);
    }
}

static RmdLoc no_location(void)
{
    RmdLoc location = { NULL, 0 };
    return location;
}

static RmdContext *context(RmdX64Emitter *emitter)
{
    return emitter->program->context;
}

static void output_bytes(RmdX64Emitter *emitter, const char *bytes, size_t size)
{
    if (fwrite(bytes, 1, size, emitter->output) != size) {
        int error = errno;
        rmd_fail(context(emitter), no_location(), "assembly output failed: %s", strerror(error));
    }
}

static void output_text(RmdX64Emitter *emitter, const char *text)
{
    output_bytes(emitter, text, strlen(text));
}

typedef struct {
    RmdX64Emitter *emitter;
    char bytes[512];
    size_t size;
    int error;
    bool failed;
} OutputBuffer;

static void output_flush(OutputBuffer *buffer)
{
    if (!buffer->failed && buffer->size &&
        fwrite(buffer->bytes, 1, buffer->size, buffer->emitter->output) != buffer->size) {
        buffer->error = errno;
        buffer->failed = true;
    }
    buffer->size = 0;
}

static void output_append(OutputBuffer *buffer, const char *text, size_t size)
{
    while (size) {
        size_t count = sizeof(buffer->bytes) - buffer->size;
        if (count > size)
            count = size;
        memcpy(buffer->bytes + buffer->size, text, count);
        buffer->size += count;
        text += count;
        size -= count;
        if (buffer->size == sizeof(buffer->bytes))
            output_flush(buffer);
    }
}

static void output_number(OutputBuffer *buffer, uint64_t value, unsigned base, unsigned width)
{
    static const char digits[] = "0123456789abcdef";
    char number[32];
    char *end = number + sizeof(number);
    char *cursor = end;
    assert(width <= sizeof(number));
    do {
        if (base == 16) {
            *--cursor = digits[value & 15u];
            value >>= 4;
        } else if (base == 8) {
            *--cursor = digits[value & 7u];
            value >>= 3;
        } else {
            *--cursor = digits[value % 10];
            value /= 10;
        }
    } while (value);
    while ((size_t)(end - cursor) < width)
        *--cursor = '0';
    output_append(buffer, cursor, (size_t)(end - cursor));
}

static void output_format(RmdX64Emitter *emitter, const char *format, ...)
{
    OutputBuffer buffer;
    va_list arguments;
    buffer.emitter = emitter;
    buffer.size = 0;
    buffer.error = 0;
    buffer.failed = false;
    va_start(arguments, format);
    while (*format) {
        unsigned width = 0;
        if (*format != '%') {
            buffer.bytes[buffer.size++] = *format++;
            if (buffer.size == sizeof(buffer.bytes))
                output_flush(&buffer);
            continue;
        }
        ++format;
        if (*format == '0') {
            ++format;
            while (*format >= '0' && *format <= '9')
                width = width * 10 + (unsigned)(*format++ - '0');
        }
        if (*format == '%') {
            buffer.bytes[buffer.size++] = '%';
            if (buffer.size == sizeof(buffer.bytes))
                output_flush(&buffer);
            ++format;
        } else if (*format == 's') {
            const char *text = va_arg(arguments, const char *);
            while (*text) {
                buffer.bytes[buffer.size++] = *text++;
                if (buffer.size == sizeof(buffer.bytes))
                    output_flush(&buffer);
            }
            ++format;
        } else if (*format == 'c') {
            char byte = (char)va_arg(arguments, int);
            output_append(&buffer, &byte, 1);
            ++format;
        } else if (*format == 'u' || *format == 'o') {
            output_number(&buffer, va_arg(arguments, unsigned), *format == 'u' ? 10 : 8, width);
            ++format;
        } else if (strncmp(format, PRIu64, sizeof(PRIu64) - 1) == 0) {
            output_number(&buffer, va_arg(arguments, uint64_t), 10, width);
            format += sizeof(PRIu64) - 1;
        } else if (strncmp(format, PRIx64, sizeof(PRIx64) - 1) == 0) {
            output_number(&buffer, va_arg(arguments, uint64_t), 16, width);
            format += sizeof(PRIx64) - 1;
        } else {
            va_end(arguments);
            abort();
        }
    }
    va_end(arguments);
    output_flush(&buffer);
    if (buffer.failed)
        rmd_fail(context(emitter), no_location(), "assembly output failed: %s", strerror(buffer.error));
}

void rmd_x64_output(RmdX64Emitter *emitter, const char *format, ...)
{
    int result;
    int error;
    va_list arguments;
    va_start(arguments, format);
    result = vfprintf(emitter->output, format, arguments);
    error = errno;
    va_end(arguments);
    if (result < 0)
        rmd_fail(context(emitter), no_location(), "assembly output failed: %s",
                 strerror(error));
}

bool rmd_x64_write(RmdX64Emitter *emitter, const char *text)
{
    if (fputs(text, emitter->output) == EOF) {
        int error = errno;
        char message[512];
        (void)snprintf(message, sizeof(message), "assembly output failed: %s", strerror(error));
        rmd_set_error(context(emitter), NULL, 0, message);
        errno = error;
        return false;
    }
    return true;
}

RmdX64Slot rmd_x64_reserve(RmdContext *ctx, RmdX64Function *function,
                          uint64_t size, uint32_t alignment, RmdLoc location)
{
    RmdX64Slot slot;
    uint64_t end;
    if (!alignment || (alignment & (alignment - 1u)))
        rmd_fail(ctx, location, "invalid backend slot alignment");
    if (size > INT64_MAX || function->frame_size > INT64_MAX - size)
        rmd_fail(ctx, location, "backend stack frame exceeds target address space");
    end = function->frame_size + size;
    if (end > (uint64_t)INT64_MAX - (alignment - 1u))
        rmd_fail(ctx, location, "backend stack frame alignment overflow");
    end = (end + alignment - 1u) & ~(uint64_t)(alignment - 1u);
    slot.offset = end;
    slot.size = size;
    slot.align = alignment;
    function->frame_size = end;
    return slot;
}

bool rmd_x64_try_reserve(RmdContext *ctx, RmdX64Function *function,
                          uint64_t size, uint32_t alignment, RmdSource *source,
                          size_t offset, RmdX64Slot *result)
{
    RmdFailureFrame failure;
    failure.previous = ctx->failure;
    ctx->failure = &failure;
    if (setjmp(failure.jump)) {
        ctx->failure = failure.previous;
        return false;
    }
    *result = rmd_x64_reserve(ctx, function, size, alignment, (RmdLoc){ source, offset });
    ctx->failure = failure.previous;
    return true;
}

static void prepare_string(RmdX64Program *program, RmdExpr *expression)
{
    RmdX64String *string;
    if (rmd_map_get(&program->string_map, (uintptr_t)expression))
        return;
    string = rmd_alloc(program->context, sizeof(*string), RMD_ALIGNOF(RmdX64String));
    string->expression = expression;
    string->identity = program->next_identity++;
    if (program->last_string)
        program->last_string->next = string;
    else
        program->strings = string;
    program->last_string = string;
    rmd_map_set(program->context, &program->string_map, (uintptr_t)expression, string);
}

static RmdTypeKind native_kind(RmdType *type)
{
    if (type->kind == RMD_T_ISIZE)
        return RMD_T_I64;
    if (type->kind == RMD_T_USIZE)
        return RMD_T_U64;
    return type->kind;
}

static bool native_type_equal(RmdType *left, RmdType *right)
{
    size_t index;
    if (left == right)
        return true;
    if (native_kind(left) != native_kind(right))
        return false;
    if (left->kind != RMD_T_FUNCTION)
        return left->kind != RMD_T_RECORD && left->kind != RMD_T_ARRAY;
    if (left->param_count != right->param_count || !native_type_equal(left->base, right->base))
        return false;
    for (index = 0; index < left->param_count; ++index)
        if (!native_type_equal(left->params[index], right->params[index]))
            return false;
    return true;
}

static bool function_symbol(RmdDecl *declaration)
{
    return declaration->kind == RMD_D_FUNCTION || declaration->kind == RMD_D_EXTERN;
}

static void prepare_alias(RmdX64Program *program, RmdDecl *declaration, bool definition)
{
    const unsigned char *cursor;
    RmdX64Alias *alias;
    RmdName *name;
    RmdX64Alias *previous;
    alias = rmd_map_get(&program->alias_map, (uintptr_t)declaration);
    if (alias && (!definition || alias->definition))
        return;
    if (!declaration->link_name || !declaration->link_name[0])
        rmd_fail(program->context, declaration->loc, "backend declaration has no nonempty link name");
    for (cursor = (const unsigned char *)declaration->link_name; *cursor; ++cursor)
        if (*cursor > 127)
            rmd_fail(program->context, declaration->loc, "native link name is not ASCII");
    if (program->entry && strcmp(declaration->link_name, "main") == 0)
        rmd_fail(program->context, declaration->loc, "native symbol main conflicts with the hosted entry adapter");
    name = rmd_intern(program->context, (const unsigned char *)declaration->link_name,
                       (size_t)(cursor - (const unsigned char *)declaration->link_name));
    previous = rmd_map_get(&program->native_symbols, (uintptr_t)name);
    if (previous) {
        if (function_symbol(previous->declaration) != function_symbol(declaration) ||
            (function_symbol(declaration) ? !native_type_equal(previous->declaration->type, declaration->type) :
             !rmd_type_equal(previous->declaration->type, declaration->type)))
            rmd_fail(program->context, declaration->loc, "conflicting native ABI for symbol %s", declaration->link_name);
        if (previous != alias && previous->definition && definition)
            rmd_fail(program->context, declaration->loc, "duplicate native definition for symbol %s", declaration->link_name);
    }
    if (!alias) {
        alias = rmd_alloc(program->context, sizeof(*alias), RMD_ALIGNOF(RmdX64Alias));
        alias->declaration = declaration;
        alias->identity = program->next_identity++;
        alias->next = program->aliases;
        program->aliases = alias;
        ++program->alias_count;
        rmd_map_set(program->context, &program->alias_map, (uintptr_t)declaration, alias);
    }
    alias->definition = definition;
    if (!previous || definition)
        rmd_map_set(program->context, &program->native_symbols, (uintptr_t)name, alias);
}

static void choose_label_prefix(RmdX64Program *program)
{
    unsigned char *used;
    RmdX64Alias *alias;
    size_t candidate;
    used = rmd_alloc(program->context, program->alias_count + 1, 1);
    for (alias = program->aliases; alias; alias = alias->next) {
        const char *name = alias->declaration->link_name;
        uint64_t value = 0;
        const char *cursor;
        if (strncmp(name, ".Lrmd_", 6) != 0)
            continue;
        cursor = name + 6;
        if (*cursor < '0' || *cursor > '9')
            continue;
        while (*cursor >= '0' && *cursor <= '9') {
            unsigned digit = (unsigned)(*cursor - '0');
            if (digit > program->alias_count || value > ((uint64_t)program->alias_count - digit) / 10)
                break;
            value = value * 10 + digit;
            ++cursor;
        }
        if (*cursor == '_' && value <= program->alias_count)
            used[(size_t)value] = 1;
    }
    for (candidate = 0; candidate <= program->alias_count; ++candidate)
        if (!used[candidate])
            break;
    (void)snprintf(program->label_prefix, sizeof(program->label_prefix), ".Lrmd_%zu_", candidate);
}

static RmdX64Expr *prepare_storage(RmdX64Program *program, RmdX64Function *function,
                                    RmdExpr *expression, bool value, bool scratch)
{
    RmdX64Expr *plan;
    plan = rmd_map_get(&function->expressions, (uintptr_t)expression);
    if (!plan) {
        plan = rmd_alloc(program->context, sizeof(*plan), RMD_ALIGNOF(RmdX64Expr));
        plan->expression = expression;
        rmd_map_set(program->context, &function->expressions, (uintptr_t)expression, plan);
    }
    if (value && !plan->value.size)
        plan->value = rmd_x64_reserve(program->context, function,
            expression->type->size, expression->type->align, expression->loc);
    if (scratch && !plan->scratch.size)
        plan->scratch = rmd_x64_reserve(program->context, function, 8, 8, expression->loc);
    return plan;
}

static void prepare_expression(RmdX64Program *program, RmdX64Function *function,
                               RmdExpr *expression, bool place)
{
    RmdInit *init;
    size_t index;
    bool left_place;
    if (!expression)
        return;
    if (expression->kind == RMD_E_STRING)
        prepare_string(program, expression);
    if (expression->kind == RMD_E_NAME && expression->symbol &&
        (expression->symbol->kind == RMD_SYM_FUNCTION || expression->symbol->kind == RMD_SYM_CONST))
        prepare_alias(program, expression->symbol->decl, false);
    if (function) {
        bool scratch = expression->kind == RMD_E_CALL || expression->kind == RMD_E_INDEX ||
            (expression->kind == RMD_E_BINARY && expression->op != RMD_OP_AND && expression->op != RMD_OP_OR);
        bool value = !place && !rmd_type_scalar(expression->type) && expression->type->kind != RMD_T_UNIT;
        if (scratch || value) {
            RmdX64Expr *plan = prepare_storage(program, function, expression, value, scratch);
            if (expression->kind == RMD_E_CALL && expression->arg_count && !plan->arguments.size) {
                if (expression->arg_count > (uint64_t)INT64_MAX / 8)
                    rmd_fail(program->context, expression->loc, "too many backend call arguments");
                plan->arguments = rmd_x64_reserve(program->context, function,
                    (uint64_t)expression->arg_count * 8, 8, expression->loc);
            }
        }
    }
    left_place = (expression->kind == RMD_E_GROUP && place) ||
        (expression->kind == RMD_E_UNARY && expression->op == RMD_OP_ADDRESS) ||
        ((expression->kind == RMD_E_FIELD || expression->kind == RMD_E_INDEX) &&
         expression->left->place && expression->left->type->kind != RMD_T_POINTER);
    prepare_expression(program, function, expression->left, left_place);
    prepare_expression(program, function, expression->right, false);
    for (index = 0; index < expression->arg_count; ++index)
        prepare_expression(program, function, expression->args[index], false);
    for (init = expression->inits; init; init = init->next)
        prepare_expression(program, function, init->value, false);
}

static void prepare_statements(RmdX64Program *program, RmdX64Function *function,
                               RmdStmt *statement)
{
    for (; statement; statement = statement->next) {
        if (statement->kind == RMD_S_VAR) {
            RmdX64Slot *slot = rmd_alloc(program->context, sizeof(*slot),
                                         RMD_ALIGNOF(RmdX64Slot));
            *slot = rmd_x64_reserve(program->context, function,
                statement->symbol->type->size, statement->symbol->type->align,
                statement->loc);
            rmd_map_set(program->context, &function->symbols,
                         (uintptr_t)statement->symbol, slot);
        }
        prepare_expression(program, function, statement->expr, statement->kind == RMD_S_ASSIGN);
        if (statement->kind == RMD_S_ASSIGN)
            (void)prepare_storage(program, function, statement->expr, false, true);
        prepare_expression(program, function, statement->value, false);
        prepare_statements(program, function, statement->body);
        prepare_statements(program, function, statement->otherwise);
    }
}

void rmd_x64_prepare_function(RmdX64Program *program, RmdX64Function *function)
{
    RmdParam *parameter;
    for (parameter = function->declaration->params; parameter; parameter = parameter->next) {
        RmdX64Slot *slot = rmd_alloc(program->context, sizeof(*slot), RMD_ALIGNOF(RmdX64Slot));
        *slot = rmd_x64_reserve(program->context, function,
            parameter->type->size, parameter->type->align, parameter->loc);
        rmd_map_set(program->context, &function->symbols, (uintptr_t)parameter->symbol, slot);
    }
    prepare_statements(program, function, function->declaration->body);
    (void)rmd_x64_reserve(program->context, function, 0, 16, function->declaration->loc);
}

bool rmd_x64_try_prepare_function(RmdX64Program *program, RmdX64Function *function)
{
    RmdContext *ctx = program->context;
    RmdFailureFrame failure;
    failure.previous = ctx->failure;
    ctx->failure = &failure;
    if (setjmp(failure.jump)) {
        ctx->failure = failure.previous;
        return false;
    }
    rmd_x64_prepare_function(program, function);
    ctx->failure = failure.previous;
    return true;
}

bool rmd_x64_prepare(RmdContext *ctx, RmdX64Program **result, RmdDecl *entry)
{
    RmdFailureFrame failure;
    RmdX64Program *program;
    RmdUnit *unit;
    failure.previous = ctx->failure;
    ctx->failure = &failure;
    if (setjmp(failure.jump)) {
        ctx->failure = failure.previous;
        *result = NULL;
        return false;
    }
    program = rmd_alloc(ctx, sizeof(*program), RMD_ALIGNOF(RmdX64Program));
    program->context = ctx;
    program->entry = entry;
    program->next_identity = 1;
    for (unit = ctx->units; unit; unit = unit->next) {
        RmdDecl *declaration;
        for (declaration = unit->declarations; declaration; declaration = declaration->next)
            if (declaration->kind != RMD_D_RECORD)
                prepare_alias(program, declaration, declaration->kind != RMD_D_EXTERN);
    }
    if (entry)
        prepare_alias(program, entry, false);
    for (unit = ctx->units; unit; unit = unit->next) {
        RmdDecl *declaration;
        for (declaration = unit->declarations; declaration; declaration = declaration->next) {
            if (declaration->kind == RMD_D_FUNCTION) {
                RmdX64Function *function = rmd_alloc(ctx, sizeof(*function),
                                                     RMD_ALIGNOF(RmdX64Function));
                function->declaration = declaration;
                function->identity = program->next_identity++;
                if (program->last_function)
                    program->last_function->next = function;
                else
                    program->functions = function;
                program->last_function = function;
                rmd_x64_prepare_function(program, function);
            } else if (declaration->kind == RMD_D_CONST) {
                prepare_expression(program, NULL, declaration->init, false);
            }
        }
    }
    choose_label_prefix(program);
    *result = program;
    ctx->failure = failure.previous;
    return true;
}

static RmdX64Expr *expression_plan(RmdX64Emitter *emitter, RmdExpr *expression)
{
    return rmd_map_get(&emitter->function->expressions, (uintptr_t)expression);
}

static void symbol_name(RmdX64Emitter *emitter, const char *name)
{
    const unsigned char *cursor = (const unsigned char *)name;
    output_text(emitter, "\"");
    while (*cursor) {
        if (*cursor == '\\' || *cursor == '"') {
            output_format(emitter, "\\%c", *cursor);
            ++cursor;
        } else if (*cursor < 32 || *cursor >= 127) {
            output_format(emitter, "\\%03o", (unsigned)*cursor);
            ++cursor;
        } else {
            const unsigned char *start = cursor;
            do {
                ++cursor;
            } while (*cursor >= 32 && *cursor < 127 && *cursor != '\\' && *cursor != '"');
            output_bytes(emitter, (const char *)start, (size_t)(cursor - start));
        }
    }
    output_text(emitter, "\"");
}

static void address_slot(RmdX64Emitter *emitter, uint64_t offset, const char *reg)
{
    if (offset <= INT32_MAX)
        output_format(emitter, "\tleaq -%" PRIu64 "(%%rbp), %%%s\n", offset, reg);
    else
        output_format(emitter, "\tmovabsq $0x%016" PRIx64 ", %%%s\n\taddq %%rbp, %%%s\n",
                        (uint64_t)0 - offset, reg, reg);
}

static void load_slot64(RmdX64Emitter *emitter, uint64_t offset, const char *reg)
{
    if (offset <= INT32_MAX)
        output_format(emitter, "\tmovq -%" PRIu64 "(%%rbp), %%%s\n", offset, reg);
    else {
        address_slot(emitter, offset, reg);
        output_format(emitter, "\tmovq (%%%s), %%%s\n", reg, reg);
    }
}

static void save_slot64(RmdX64Emitter *emitter, uint64_t offset)
{
    if (offset <= INT32_MAX)
        output_format(emitter, "\tmovq %%rax, -%" PRIu64 "(%%rbp)\n", offset);
    else {
        address_slot(emitter, offset, "r10");
        output_text(emitter, "\tmovq %rax, (%r10)\n");
    }
}

static void normalize(RmdX64Emitter *emitter, RmdType *type)
{
    if (type->size == 1)
        output_text(emitter, rmd_type_signed(type) ? "\tmovsbq %al, %rax\n" : "\tmovzbq %al, %rax\n");
    else if (type->size == 2)
        output_text(emitter, rmd_type_signed(type) ? "\tmovswq %ax, %rax\n" : "\tmovzwq %ax, %rax\n");
    else if (type->size == 4)
        output_text(emitter, rmd_type_signed(type) ? "\tmovslq %eax, %rax\n" : "\tmovl %eax, %eax\n");
}

static void load_value(RmdX64Emitter *emitter, RmdType *type)
{
    if (!rmd_type_scalar(type))
        return;
    if (type->size == 1)
        output_text(emitter, rmd_type_signed(type) ? "\tmovsbq (%rax), %rax\n" : "\tmovzbq (%rax), %rax\n");
    else if (type->size == 2)
        output_text(emitter, rmd_type_signed(type) ? "\tmovswq (%rax), %rax\n" : "\tmovzwq (%rax), %rax\n");
    else if (type->size == 4)
        output_text(emitter, rmd_type_signed(type) ? "\tmovslq (%rax), %rax\n" : "\tmovl (%rax), %eax\n");
    else
        output_text(emitter, "\tmovq (%rax), %rax\n");
}

static void load_scalar_slot(RmdX64Emitter *emitter, RmdType *type, uint64_t offset)
{
    const char *instruction;
    if (offset > INT32_MAX) {
        address_slot(emitter, offset, "rax");
        load_value(emitter, type);
        return;
    }
    instruction = type->size == 1 ? (rmd_type_signed(type) ? "movsbq" : "movzbq") :
        type->size == 2 ? (rmd_type_signed(type) ? "movswq" : "movzwq") :
        type->size == 4 ? (rmd_type_signed(type) ? "movslq" : "movl") : "movq";
    output_format(emitter, "\t%s -%" PRIu64 "(%%rbp), %%%s\n", instruction, offset,
                    type->size == 4 && !rmd_type_signed(type) ? "eax" : "rax");
}

static void store_value(RmdX64Emitter *emitter, RmdType *type)
{
    if (!rmd_type_scalar(type))
        output_format(emitter, "\tmovq %%rax, %%rsi\n\tmovabsq $%" PRIu64 ", %%rcx\n\trep movsb\n", type->size);
    else if (type->size == 1)
        output_text(emitter, "\tmovb %al, (%rdi)\n");
    else if (type->size == 2)
        output_text(emitter, "\tmovw %ax, (%rdi)\n");
    else if (type->size == 4)
        output_text(emitter, "\tmovl %eax, (%rdi)\n");
    else
        output_text(emitter, "\tmovq %rax, (%rdi)\n");
}

static void finish_value(RmdX64Emitter *emitter, RmdExpr *expression)
{
    RmdX64Expr *plan;
    if (rmd_type_scalar(expression->type) || expression->type->kind == RMD_T_UNIT)
        return;
    plan = expression_plan(emitter, expression);
    address_slot(emitter, plan->value.offset, "rdi");
    store_value(emitter, expression->type);
    address_slot(emitter, plan->value.offset, "rax");
}

static void symbol_address(RmdX64Emitter *emitter, RmdDecl *declaration)
{
    RmdX64Alias *alias = rmd_map_get(&emitter->program->alias_map, (uintptr_t)declaration);
    output_format(emitter, "\tmovq %salias_%" PRIu64 "@GOTPCREL(%%rip), %%rax\n",
                    emitter->program->label_prefix, alias->identity);
}

static void emit_label(RmdX64Emitter *emitter, uint64_t identity)
{
    output_format(emitter, "%slabel_%" PRIu64 ":\n", emitter->program->label_prefix, identity);
}

static void emit_jump(RmdX64Emitter *emitter, const char *instruction, uint64_t identity)
{
    output_format(emitter, "\t%s %slabel_%" PRIu64 "\n", instruction, emitter->program->label_prefix, identity);
}

static void reserve_stack(RmdX64Emitter *emitter, uint64_t size)
{
    if (size >= 4096) {
        uint64_t label = emitter->next_label++;
        output_format(emitter, "\tmovabsq $%" PRIu64 ", %%r10\n", size / 4096);
        emit_label(emitter, label);
        output_text(emitter, "\tsubq $4096, %rsp\n\torq $0, (%rsp)\n\tdecq %r10\n");
        emit_jump(emitter, "jne", label);
        size %= 4096;
        if (size)
            output_format(emitter, "\tsubq $%" PRIu64 ", %%rsp\n\torq $0, (%%rsp)\n", size);
    } else if (size) {
        output_format(emitter, "\tsubq $%" PRIu64 ", %%rsp\n", size);
    }
}

void rmd_x64_emit_place(RmdX64Emitter *emitter, RmdExpr *expression)
{
    RmdX64Slot *slot;
    switch (expression->kind) {
    case RMD_E_NAME:
        if (expression->symbol->kind == RMD_SYM_CONST)
            symbol_address(emitter, expression->symbol->decl);
        else {
            slot = rmd_map_get(&emitter->function->symbols, (uintptr_t)expression->symbol);
            address_slot(emitter, slot->offset, "rax");
        }
        return;
    case RMD_E_GROUP:
        emit_place(emitter, expression->left);
        return;
    case RMD_E_UNARY:
        if (expression->op == RMD_OP_DEREF) {
            emit_expression(emitter, expression->left);
            return;
        }
        break;
    case RMD_E_FIELD:
        if (expression->left->place)
            emit_place(emitter, expression->left);
        else
            emit_expression(emitter, expression->left);
        output_format(emitter, "\tmovabsq $%" PRIu64 ", %%r10\n\taddq %%r10, %%rax\n",
                        expression->field->offset);
        return;
    case RMD_E_INDEX: {
        RmdX64Expr *plan = expression_plan(emitter, expression);
        if (expression->left->type->kind == RMD_T_POINTER || !expression->left->place)
            emit_expression(emitter, expression->left);
        else
            emit_place(emitter, expression->left);
        save_slot64(emitter, plan->scratch.offset);
        emit_expression(emitter, expression->right);
        output_format(emitter, "\tmovabsq $%" PRIu64 ", %%r10\n\timulq %%r10, %%rax\n\tmovq %%rax, %%rcx\n",
                        expression->type->size);
        load_slot64(emitter, plan->scratch.offset, "rax");
        output_text(emitter, "\taddq %rcx, %rax\n");
        return;
    }
    default:
        break;
    }
    abort();
}

static void emit_call(RmdX64Emitter *emitter, RmdExpr *expression)
{
    static const char *const registers[] = { "rdi", "rsi", "rdx", "rcx", "r8", "r9" };
    RmdX64Expr *plan = expression_plan(emitter, expression);
    size_t index;
    uint64_t stack_size = expression->arg_count > 6 ? (uint64_t)(expression->arg_count - 6) * 8 : 0;
    stack_size = (stack_size + 15) & ~(uint64_t)15;
    emit_expression(emitter, expression->left);
    save_slot64(emitter, plan->scratch.offset);
    for (index = 0; index < expression->arg_count; ++index) {
        emit_expression(emitter, expression->args[index]);
        save_slot64(emitter, plan->arguments.offset - (uint64_t)index * 8);
    }
    reserve_stack(emitter, stack_size);
    for (index = 6; index < expression->arg_count; ++index) {
        load_slot64(emitter, plan->arguments.offset - (uint64_t)index * 8, "rax");
        output_format(emitter, "\tmovabsq $%" PRIu64 ", %%r10\n\taddq %%rsp, %%r10\n\tmovq %%rax, (%%r10)\n",
                        (uint64_t)(index - 6) * 8);
    }
    for (index = 0; index < expression->arg_count && index < 6; ++index)
        load_slot64(emitter, plan->arguments.offset - (uint64_t)index * 8, registers[index]);
    load_slot64(emitter, plan->scratch.offset, "r11");
    output_text(emitter, "\tcall *%r11\n");
    if (stack_size)
        output_format(emitter, "\tmovabsq $%" PRIu64 ", %%r10\n\taddq %%r10, %%rsp\n", stack_size);
    if (expression->type->kind != RMD_T_UNIT)
        normalize(emitter, expression->type);
}

static void emit_binary(RmdX64Emitter *emitter, RmdExpr *expression)
{
    RmdX64Expr *plan;
    const char *condition;
    bool signed_type = rmd_type_signed(expression->left->type);
    emit_expression(emitter, expression->left);
    if (expression->op == RMD_OP_AND || expression->op == RMD_OP_OR) {
        uint64_t end = emitter->next_label++;
        output_text(emitter, "\ttestq %rax, %rax\n");
        emit_jump(emitter, expression->op == RMD_OP_AND ? "je" : "jne", end);
        emit_expression(emitter, expression->right);
        emit_label(emitter, end);
        return;
    }
    plan = expression_plan(emitter, expression);
    save_slot64(emitter, plan->scratch.offset);
    emit_expression(emitter, expression->right);
    output_text(emitter, "\tmovq %rax, %rcx\n");
    load_slot64(emitter, plan->scratch.offset, "rax");
    if (expression->left->type->kind == RMD_T_POINTER &&
        (expression->op == RMD_OP_ADD || expression->op == RMD_OP_SUB))
        output_format(emitter, "\tmovabsq $%" PRIu64 ", %%r10\n\timulq %%r10, %%rcx\n",
                        expression->left->type->base->size);
    switch (expression->op) {
    case RMD_OP_ADD: output_text(emitter, "\taddq %rcx, %rax\n"); break;
    case RMD_OP_SUB: output_text(emitter, "\tsubq %rcx, %rax\n"); break;
    case RMD_OP_MUL: output_text(emitter, "\timulq %rcx, %rax\n"); break;
    case RMD_OP_BIT_AND: output_text(emitter, "\tandq %rcx, %rax\n"); break;
    case RMD_OP_BIT_OR: output_text(emitter, "\torq %rcx, %rax\n"); break;
    case RMD_OP_BIT_XOR: output_text(emitter, "\txorq %rcx, %rax\n"); break;
    case RMD_OP_DIV:
    case RMD_OP_REM: {
        uint64_t nonzero = emitter->next_label++;
        output_text(emitter, "\ttestq %rcx, %rcx\n");
        emit_jump(emitter, "jne", nonzero);
        output_text(emitter, "\tud2\n");
        emit_label(emitter, nonzero);
        if (signed_type) {
            unsigned bits = rmd_type_bits(expression->type);
            uint64_t valid = emitter->next_label++;
            uint64_t minimum = UINT64_MAX << (bits - 1);
            output_text(emitter, "\tcmpq $-1, %rcx\n");
            emit_jump(emitter, "jne", valid);
            output_format(emitter, "\tmovabsq $0x%016" PRIx64 ", %%r10\n\tcmpq %%r10, %%rax\n", minimum);
            emit_jump(emitter, "jne", valid);
            output_text(emitter, "\tud2\n");
            emit_label(emitter, valid);
            output_text(emitter, "\tcqto\n\tidivq %rcx\n");
        } else {
            output_text(emitter, "\txorl %edx, %edx\n\tdivq %rcx\n");
        }
        if (expression->op == RMD_OP_REM)
            output_text(emitter, "\tmovq %rdx, %rax\n");
        break;
    }
    case RMD_OP_SHL:
    case RMD_OP_SHR: {
        uint64_t valid = emitter->next_label++;
        output_format(emitter, "\tcmpq $%u, %%rcx\n", rmd_type_bits(expression->type));
        emit_jump(emitter, "jb", valid);
        output_text(emitter, "\tud2\n");
        emit_label(emitter, valid);
        output_format(emitter, "\t%s %%cl, %%rax\n",
                        expression->op == RMD_OP_SHL ? "shlq" : signed_type ? "sarq" : "shrq");
        break;
    }
    case RMD_OP_EQ: condition = "e"; goto compare;
    case RMD_OP_NE: condition = "ne"; goto compare;
    case RMD_OP_LT: condition = signed_type ? "l" : "b"; goto compare;
    case RMD_OP_LE: condition = signed_type ? "le" : "be"; goto compare;
    case RMD_OP_GT: condition = signed_type ? "g" : "a"; goto compare;
    case RMD_OP_GE: condition = signed_type ? "ge" : "ae"; goto compare;
    default:
        abort();
    }
    normalize(emitter, expression->type);
    return;
compare:
    output_format(emitter, "\tcmpq %%rcx, %%rax\n\tset%s %%al\n\tmovzbq %%al, %%rax\n", condition);
}

void rmd_x64_emit_expression(RmdX64Emitter *emitter, RmdExpr *expression)
{
    switch (expression->kind) {
    case RMD_E_INTEGER:
    case RMD_E_BOOL:
    case RMD_E_SIZEOF:
    case RMD_E_ALIGNOF:
    case RMD_E_OFFSETOF:
        output_format(emitter, "\tmovabsq $0x%016" PRIx64 ", %%rax\n", expression->integer);
        normalize(emitter, expression->type);
        break;
    case RMD_E_NULL:
        output_text(emitter, "\txorl %eax, %eax\n");
        break;
    case RMD_E_STRING: {
        RmdX64String *string = rmd_map_get(&emitter->program->string_map, (uintptr_t)expression);
        output_format(emitter, "\tleaq %sstring_%" PRIu64 "(%%rip), %%rax\n",
                        emitter->program->label_prefix, string->identity);
        break;
    }
    case RMD_E_NAME:
        if (expression->symbol->kind == RMD_SYM_FUNCTION) {
            symbol_address(emitter, expression->symbol->decl);
            break;
        }
        if (expression->symbol->kind != RMD_SYM_CONST && rmd_type_scalar(expression->type) &&
            (!emitter->operations || !emitter->operations->place)) {
            RmdX64Slot *slot = rmd_map_get(&emitter->function->symbols, (uintptr_t)expression->symbol);
            load_scalar_slot(emitter, expression->type, slot->offset);
            break;
        }
        emit_place(emitter, expression);
        load_value(emitter, expression->type);
        break;
    case RMD_E_GROUP:
        emit_expression(emitter, expression->left);
        break;
    case RMD_E_FIELD:
    case RMD_E_INDEX:
        emit_place(emitter, expression);
        load_value(emitter, expression->type);
        break;
    case RMD_E_UNARY:
        if (expression->op == RMD_OP_ADDRESS) {
            emit_place(emitter, expression->left);
            break;
        }
        if (expression->op == RMD_OP_DEREF) {
            emit_place(emitter, expression);
            load_value(emitter, expression->type);
            break;
        }
        emit_expression(emitter, expression->left);
        if (expression->op == RMD_OP_NEG)
            output_text(emitter, "\tnegq %rax\n");
        else if (expression->op == RMD_OP_BIT_NOT)
            output_text(emitter, "\tnotq %rax\n");
        else if (expression->op == RMD_OP_NOT)
            output_text(emitter, "\txorq $1, %rax\n");
        if (rmd_type_scalar(expression->type))
            normalize(emitter, expression->type);
        break;
    case RMD_E_CAST:
        emit_expression(emitter, expression->left);
        if (expression->type->kind == RMD_T_BOOL)
            output_text(emitter, "\ttestq %rax, %rax\n\tsetne %al\n\tmovzbq %al, %rax\n");
        else
            normalize(emitter, expression->type);
        break;
    case RMD_E_CALL:
        emit_call(emitter, expression);
        break;
    case RMD_E_BINARY:
        emit_binary(emitter, expression);
        break;
    case RMD_E_RECORD: {
        RmdX64Expr *plan = expression_plan(emitter, expression);
        RmdInit *init;
        for (init = expression->inits; init; init = init->next) {
            emit_expression(emitter, init->value);
            address_slot(emitter, plan->value.offset - init->field->offset, "rdi");
            store_value(emitter, init->field->type);
        }
        address_slot(emitter, plan->value.offset, "rax");
        return;
    }
    case RMD_E_ARRAY: {
        RmdX64Expr *plan = expression_plan(emitter, expression);
        size_t index;
        for (index = 0; index < expression->arg_count; ++index) {
            emit_expression(emitter, expression->args[index]);
            address_slot(emitter, plan->value.offset - (uint64_t)index * expression->type->base->size, "rdi");
            store_value(emitter, expression->type->base);
        }
        address_slot(emitter, plan->value.offset, "rax");
        return;
    }
    default:
        abort();
    }
    finish_value(emitter, expression);
}

void rmd_x64_emit_statement(RmdX64Emitter *emitter, RmdStmt *statement)
{
    RmdX64Slot *slot;
    uint64_t first;
    uint64_t second;
    RmdStmt *child;
    switch (statement->kind) {
    case RMD_S_BLOCK:
        for (child = statement->body; child; child = child->next)
            emit_statement(emitter, child);
        return;
    case RMD_S_VAR:
        if (statement->uninitialized)
            return;
        emit_expression(emitter, statement->value);
        slot = rmd_map_get(&emitter->function->symbols, (uintptr_t)statement->symbol);
        address_slot(emitter, slot->offset, "rdi");
        store_value(emitter, statement->symbol->type);
        return;
    case RMD_S_ASSIGN: {
        RmdX64Expr *plan = expression_plan(emitter, statement->expr);
        emit_place(emitter, statement->expr);
        save_slot64(emitter, plan->scratch.offset);
        emit_expression(emitter, statement->value);
        load_slot64(emitter, plan->scratch.offset, "rdi");
        store_value(emitter, statement->expr->type);
        return;
    }
    case RMD_S_EXPR:
        emit_expression(emitter, statement->expr);
        return;
    case RMD_S_RETURN:
        if (statement->expr)
            emit_expression(emitter, statement->expr);
        emit_jump(emitter, "jmp", emitter->return_label);
        return;
    case RMD_S_TRAP:
        output_text(emitter, "\tud2\n");
        return;
    case RMD_S_IF:
        first = emitter->next_label++;
        second = emitter->next_label++;
        emit_expression(emitter, statement->expr);
        output_text(emitter, "\ttestq %rax, %rax\n");
        emit_jump(emitter, "je", first);
        emit_statement(emitter, statement->body);
        emit_jump(emitter, "jmp", second);
        emit_label(emitter, first);
        if (statement->otherwise)
            emit_statement(emitter, statement->otherwise);
        emit_label(emitter, second);
        return;
    case RMD_S_WHILE: {
        RmdX64Loop loop;
        loop.test_label = emitter->next_label++;
        loop.end_label = emitter->next_label++;
        loop.previous = emitter->loop;
        emitter->loop = &loop;
        emit_label(emitter, loop.test_label);
        emit_expression(emitter, statement->expr);
        output_text(emitter, "\ttestq %rax, %rax\n");
        emit_jump(emitter, "je", loop.end_label);
        emit_statement(emitter, statement->body);
        emit_jump(emitter, "jmp", loop.test_label);
        emit_label(emitter, loop.end_label);
        emitter->loop = loop.previous;
        return;
    }
    case RMD_S_BREAK:
        emit_jump(emitter, "jmp", emitter->loop->end_label);
        return;
    case RMD_S_CONTINUE:
        emit_jump(emitter, "jmp", emitter->loop->test_label);
        return;
    default:
        abort();
    }
}

static bool try_operation(RmdX64Emitter *emitter, void *node, unsigned operation)
{
    RmdContext *ctx = context(emitter);
    RmdFailureFrame failure;
    RmdX64Loop *saved_loop = emitter->loop;
    failure.previous = ctx->failure;
    ctx->failure = &failure;
    if (setjmp(failure.jump)) {
        ctx->failure = failure.previous;
        emitter->loop = saved_loop;
        return false;
    }
    if (operation == 0)
        rmd_x64_emit_expression(emitter, node);
    else if (operation == 1)
        rmd_x64_emit_place(emitter, node);
    else if (operation == 2)
        rmd_x64_emit_statement(emitter, node);
    else if (operation == 3)
        rmd_x64_emit_constant(emitter, node);
    else if (operation == 4)
        rmd_x64_emit_constant_value(emitter, node);
    else
        rmd_x64_emit_function(emitter, node);
    ctx->failure = failure.previous;
    return true;
}

bool rmd_x64_try_emit_expression(RmdX64Emitter *emitter, RmdExpr *expression)
{
    return try_operation(emitter, expression, 0);
}

bool rmd_x64_try_emit_place(RmdX64Emitter *emitter, RmdExpr *expression)
{
    return try_operation(emitter, expression, 1);
}

bool rmd_x64_try_emit_statement(RmdX64Emitter *emitter, RmdStmt *statement)
{
    return try_operation(emitter, statement, 2);
}

bool rmd_x64_try_emit_constant(RmdX64Emitter *emitter, RmdDecl *declaration)
{
    return try_operation(emitter, declaration, 3);
}

bool rmd_x64_try_emit_constant_value(RmdX64Emitter *emitter, RmdExpr *expression)
{
    return try_operation(emitter, expression, 4);
}

bool rmd_x64_try_emit_function(RmdX64Emitter *emitter, RmdX64Function *function)
{
    return try_operation(emitter, function, 5);
}

const RmdX64Ops rmd_x64_default_ops = {
    rmd_x64_try_emit_expression, rmd_x64_try_emit_place, rmd_x64_try_emit_statement
};

void rmd_x64_emit_function(RmdX64Emitter *emitter, RmdX64Function *function)
{
    static const char *const registers[] = { "rdi", "rsi", "rdx", "rcx", "r8", "r9" };
    static const char *const narrow_registers[][6] = {
        { "dil", "sil", "dl", "cl", "r8b", "r9b" },
        { "di", "si", "dx", "cx", "r8w", "r9w" },
        { "edi", "esi", "edx", "ecx", "r8d", "r9d" }
    };
    RmdParam *parameter;
    size_t index;
    emitter->function = function;
    emitter->return_label = emitter->next_label++;
    output_text(emitter, "\t.text\n\t.globl ");
    symbol_name(emitter, function->declaration->link_name);
    output_format(emitter, "\n\t.type %sfunction_%" PRIu64 ", @function\n%sfunction_%" PRIu64
                    ":\n\tpushq %%rbp\n\tmovq %%rsp, %%rbp\n", emitter->program->label_prefix,
                    function->identity, emitter->program->label_prefix, function->identity);
    reserve_stack(emitter, function->frame_size);
    for (parameter = function->declaration->params, index = 0; parameter;
         parameter = parameter->next, ++index) {
        RmdX64Slot *slot = rmd_map_get(&function->symbols, (uintptr_t)parameter->symbol);
        if (index < 6 && slot->offset <= INT32_MAX) {
            unsigned width = parameter->type->size == 1 ? 0 : parameter->type->size == 2 ? 1 : 2;
            const char *reg = parameter->type->size == 8 ? registers[index] : narrow_registers[width][index];
            const char *instruction = parameter->type->size == 1 ? "movb" :
                parameter->type->size == 2 ? "movw" : parameter->type->size == 4 ? "movl" : "movq";
            output_format(emitter, "\t%s %%%s, -%" PRIu64 "(%%rbp)\n", instruction, reg, slot->offset);
            continue;
        }
        if (index < 6)
            output_format(emitter, "\tmovq %%%s, %%rax\n", registers[index]);
        else
            output_format(emitter, "\tmovabsq $%" PRIu64 ", %%r10\n\taddq %%rbp, %%r10\n\tmovq (%%r10), %%rax\n",
                            16 + (uint64_t)(index - 6) * 8);
        address_slot(emitter, slot->offset, "r10");
        if (parameter->type->size == 1)
            output_text(emitter, "\tmovb %al, (%r10)\n");
        else if (parameter->type->size == 2)
            output_text(emitter, "\tmovw %ax, (%r10)\n");
        else if (parameter->type->size == 4)
            output_text(emitter, "\tmovl %eax, (%r10)\n");
        else
            output_text(emitter, "\tmovq %rax, (%r10)\n");
    }
    emit_statement(emitter, function->declaration->body);
    emit_label(emitter, emitter->return_label);
    output_format(emitter, "\tleave\n\tret\n\t.size %sfunction_%" PRIu64
                    ", .-%sfunction_%" PRIu64 "\n\t.set ", emitter->program->label_prefix,
                    function->identity, emitter->program->label_prefix, function->identity);
    symbol_name(emitter, function->declaration->link_name);
    output_format(emitter, ", %sfunction_%" PRIu64 "\n", emitter->program->label_prefix, function->identity);
}

void rmd_x64_emit_constant_value(RmdX64Emitter *emitter, RmdExpr *expression)
{
    RmdType *type = expression->type;
    uint64_t value;
    const char *directive;
    switch (expression->kind) {
    case RMD_E_GROUP:
        rmd_x64_emit_constant_value(emitter, expression->left);
        return;
    case RMD_E_RECORD: {
        RmdExpr **values;
        RmdInit *init;
        RmdField *field;
        uint64_t offset = 0;
        values = rmd_alloc(context(emitter), type->record_decl->field_count * sizeof(*values), RMD_ALIGNOF(RmdExpr *));
        for (init = expression->inits; init; init = init->next)
            values[init->field->index] = init->value;
        for (field = type->record_decl->fields; field; field = field->next) {
            if (offset < field->offset)
                output_format(emitter, "\t.zero %" PRIu64 "\n", field->offset - offset);
            rmd_x64_emit_constant_value(emitter, values[field->index]);
            offset = field->offset + field->type->size;
        }
        if (offset < type->size)
            output_format(emitter, "\t.zero %" PRIu64 "\n", type->size - offset);
        return;
    }
    case RMD_E_ARRAY: {
        size_t index;
        for (index = 0; index < expression->arg_count; ++index)
            rmd_x64_emit_constant_value(emitter, expression->args[index]);
        return;
    }
    case RMD_E_STRING: {
        RmdX64String *string = rmd_map_get(&emitter->program->string_map, (uintptr_t)expression);
        output_format(emitter, "\t.quad %sstring_%" PRIu64 "\n", emitter->program->label_prefix, string->identity);
        return;
    }
    case RMD_E_NAME: {
        RmdX64Alias *alias = rmd_map_get(&emitter->program->alias_map, (uintptr_t)expression->symbol->decl);
        output_format(emitter, "\t.quad %salias_%" PRIu64 "\n", emitter->program->label_prefix, alias->identity);
        return;
    }
    case RMD_E_NULL:
        value = 0;
        break;
    case RMD_E_UNARY:
        value = (uint64_t)0 - expression->left->integer;
        break;
    case RMD_E_INTEGER:
    case RMD_E_BOOL:
    case RMD_E_SIZEOF:
    case RMD_E_ALIGNOF:
    case RMD_E_OFFSETOF:
        value = expression->integer;
        break;
    default:
        abort();
    }
    if (type->size < 8)
        value &= (UINT64_C(1) << (type->size * 8)) - 1;
    directive = type->size == 1 ? "byte" : type->size == 2 ? "short" : type->size == 4 ? "long" : "quad";
    output_format(emitter, "\t.%s 0x%016" PRIx64 "\n", directive, value);
}

void rmd_x64_emit_constant(RmdX64Emitter *emitter, RmdDecl *declaration)
{
    uint64_t identity = emitter->next_label++;
    output_format(emitter, "\t.section .rodata\n\t.balign %u\n\t.globl ", declaration->type->align);
    symbol_name(emitter, declaration->link_name);
    output_format(emitter, "\n\t.type %sdata_%" PRIu64 ", @object\n%sdata_%" PRIu64 ":\n",
                    emitter->program->label_prefix, identity, emitter->program->label_prefix, identity);
    rmd_x64_emit_constant_value(emitter, declaration->init);
    output_format(emitter, "\t.size %sdata_%" PRIu64 ", %" PRIu64 "\n\t.set ",
                    emitter->program->label_prefix, identity, declaration->type->size);
    symbol_name(emitter, declaration->link_name);
    output_format(emitter, ", %sdata_%" PRIu64 "\n", emitter->program->label_prefix, identity);
}

bool rmd_x64_emit_program_with_ops(RmdX64Program *program, FILE *output,
                                    const RmdX64Ops *operations)
{
    RmdContext *ctx = program->context;
    RmdFailureFrame failure;
    RmdX64Emitter emitter;
    RmdX64Function *function;
    RmdX64String *string;
    RmdX64Alias *alias;
    RmdUnit *unit;
    memset(&emitter, 0, sizeof(emitter));
    emitter.program = program;
    emitter.output = output;
    emitter.operations = operations;
    emitter.next_label = 1;
    failure.previous = ctx->failure;
    ctx->failure = &failure;
    if (setjmp(failure.jump)) {
        ctx->failure = failure.previous;
        return false;
    }
    for (alias = program->aliases; alias; alias = alias->next) {
        output_text(&emitter, "\t.globl ");
        symbol_name(&emitter, alias->declaration->link_name);
        output_format(&emitter, "\n\t.weakref %salias_%" PRIu64 ", ", program->label_prefix, alias->identity);
        symbol_name(&emitter, alias->declaration->link_name);
        output_text(&emitter, "\n");
    }
    for (unit = ctx->units; unit; unit = unit->next) {
        RmdDecl *declaration;
        for (declaration = unit->declarations; declaration; declaration = declaration->next)
            if (declaration->kind == RMD_D_CONST)
                rmd_x64_emit_constant(&emitter, declaration);
    }
    output_text(&emitter, "\t.section .rodata\n");
    for (string = program->strings; string; string = string->next) {
        size_t index;
        output_format(&emitter, "%sstring_%" PRIu64 ":\n", program->label_prefix, string->identity);
        for (index = 0; index < string->expression->byte_count; ++index)
            output_format(&emitter, "\t.byte %u\n", (unsigned)string->expression->bytes[index]);
    }
    for (function = program->functions; function; function = function->next)
        rmd_x64_emit_function(&emitter, function);
    if (program->entry) {
        output_text(&emitter, "\t.text\n\t.globl main\n\t.type main, @function\nmain:\n");
        symbol_address(&emitter, program->entry);
        output_text(&emitter, "\tjmp *%rax\n\t.size main, .-main\n");
    }
    output_text(&emitter, "\t.section .note.GNU-stack,\"\",@progbits\n");
    if (fflush(output) == EOF)
        rmd_fail(ctx, no_location(), "assembly output flush failed: %s", strerror(errno));
    ctx->failure = failure.previous;
    return true;
}

bool rmd_x64_emit_program(RmdX64Program *program, FILE *output)
{
    return rmd_x64_emit_program_with_ops(program, output, NULL);
}

bool rmd_x64_emit(RmdContext *ctx, FILE *output, RmdDecl *entry)
{
    RmdX64Program *program;
    if (!rmd_x64_prepare(ctx, &program, entry))
        return false;
    return rmd_x64_emit_program(program, output);
}
