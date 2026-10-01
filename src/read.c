#include "rmd0.h"

#include <limits.h>
#include <string.h>

enum {
    TOK_EOF = 256, TOK_NAME, TOK_INTEGER, TOK_COUNT, TOK_STRING,
    TOK_TYPE, TOK_RECORD, TOK_FN, TOK_EXTERN, TOK_CONST, TOK_VAR,
    TOK_UNINIT, TOK_IF, TOK_ELSE, TOK_WHILE, TOK_BREAK, TOK_CONTINUE,
    TOK_RETURN, TOK_TRAP, TOK_AS, TOK_MAKE, TOK_NULL, TOK_SIZEOF,
    TOK_ALIGNOF, TOK_OFFSETOF, TOK_TRUE, TOK_FALSE, TOK_ARROW,
    TOK_EQ, TOK_NE, TOK_LE, TOK_GE, TOK_SHL, TOK_SHR, TOK_AND, TOK_OR
};

typedef struct {
    int kind;
    RmdLoc loc;
    RmdName *name;
    uint64_t integer;
    RmdTypeKind integer_type;
    const unsigned char *bytes;
    size_t byte_count;
} Token;

typedef struct {
    RmdContext *ctx;
    RmdSource *source;
    size_t offset;
    size_t end;
    unsigned depth;
    Token token;
} Reader;

typedef struct {
    const char *text;
    size_t size;
    int token;
    RmdTypeKind type;
} Keyword;

#define KEYWORD(text, token) { text, sizeof(text) - 1, token, RMD_T_UNIT }
#define TYPEWORD(text, type) { text, sizeof(text) - 1, TOK_TYPE, type }
#define NEW(reader, type) rmd_alloc((reader)->ctx, sizeof(type), RMD_ALIGNOF(type))
#define READ_DEPTH_LIMIT 256u

static const Keyword keywords[] = {
    KEYWORD("record", TOK_RECORD), KEYWORD("fn", TOK_FN),
    KEYWORD("extern", TOK_EXTERN), KEYWORD("const", TOK_CONST),
    KEYWORD("var", TOK_VAR), KEYWORD("uninit", TOK_UNINIT),
    KEYWORD("if", TOK_IF), KEYWORD("else", TOK_ELSE),
    KEYWORD("while", TOK_WHILE), KEYWORD("break", TOK_BREAK),
    KEYWORD("continue", TOK_CONTINUE), KEYWORD("return", TOK_RETURN),
    KEYWORD("trap", TOK_TRAP), KEYWORD("as", TOK_AS),
    KEYWORD("make", TOK_MAKE), KEYWORD("null", TOK_NULL),
    KEYWORD("sizeof", TOK_SIZEOF), KEYWORD("alignof", TOK_ALIGNOF),
    KEYWORD("offsetof", TOK_OFFSETOF), KEYWORD("true", TOK_TRUE),
    KEYWORD("false", TOK_FALSE),
    TYPEWORD("i8", RMD_T_I8), TYPEWORD("u8", RMD_T_U8),
    TYPEWORD("i16", RMD_T_I16), TYPEWORD("u16", RMD_T_U16),
    TYPEWORD("i32", RMD_T_I32), TYPEWORD("u32", RMD_T_U32),
    TYPEWORD("i64", RMD_T_I64), TYPEWORD("u64", RMD_T_U64),
    TYPEWORD("isize", RMD_T_ISIZE), TYPEWORD("usize", RMD_T_USIZE),
    TYPEWORD("bool", RMD_T_BOOL), TYPEWORD("unit", RMD_T_UNIT)
};

static bool name_start(unsigned char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
}

static bool name_continue(unsigned char c)
{
    return name_start(c) || (c >= '0' && c <= '9');
}

static int hex_digit(unsigned char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static const Keyword *keyword(const unsigned char *text, size_t size)
{
    size_t i;
    for (i = 0; i < sizeof(keywords) / sizeof(keywords[0]); ++i) {
        if (keywords[i].size == size &&
            memcmp(keywords[i].text, text, size) == 0) return &keywords[i];
    }
    return NULL;
}

static unsigned char escape_byte(unsigned char c)
{
    switch (c) {
    case 'n': return '\n';
    case 'r': return '\r';
    case 't': return '\t';
    case '0': return 0;
    default: return c;
    }
}

static void read_string(Reader *reader)
{
    const unsigned char *source = reader->source->bytes;
    size_t size = reader->end;
    size_t start = reader->offset + 1;
    size_t end = start;
    size_t decoded = 0;
    size_t i;
    unsigned char *bytes;
    while (end < size && source[end] != '"') {
        unsigned char c = source[end++];
        if (c == 0 || c == '\n' || c == '\r')
            rmd_fail(reader->ctx, reader->token.loc, "invalid byte in string literal");
        if (c == '\\') {
            if (end == size)
                rmd_fail(reader->ctx, reader->token.loc, "unterminated string escape");
            c = source[end++];
            if (c == 'x') {
                if (size - end < 2 || hex_digit(source[end]) < 0 ||
                    hex_digit(source[end + 1]) < 0)
                    rmd_fail(reader->ctx, reader->token.loc, "expected two hexadecimal escape digits");
                end += 2;
            } else if (c != '\\' && c != '"' && c != 'n' && c != 'r' &&
                       c != 't' && c != '0') {
                rmd_fail(reader->ctx, reader->token.loc, "unknown string escape");
            }
        }
        ++decoded;
    }
    if (end == size)
        rmd_fail(reader->ctx, reader->token.loc, "unterminated string literal");
    if (decoded == SIZE_MAX)
        rmd_fail(reader->ctx, reader->token.loc, "string literal is too large");
    bytes = rmd_alloc(reader->ctx, decoded + 1, RMD_ALIGNOF(unsigned char));
    i = 0;
    while (start < end) {
        unsigned char c = source[start++];
        if (c == '\\') {
            c = source[start++];
            if (c == 'x') {
                c = (unsigned char)(hex_digit(source[start]) * 16 +
                                    hex_digit(source[start + 1]));
                start += 2;
            } else {
                c = escape_byte(c);
            }
        }
        bytes[i++] = c;
    }
    bytes[decoded] = 0;
    reader->token.kind = TOK_STRING;
    reader->token.bytes = bytes;
    reader->token.byte_count = decoded + 1;
    reader->offset = end + 1;
}

static void read_number(Reader *reader)
{
    const unsigned char *source = reader->source->bytes;
    size_t size = reader->end;
    size_t start = reader->offset;
    size_t end = start;
    size_t digits;
    unsigned base = 10;
    uint64_t value = 0;
    const Keyword *suffix;
    while (end < size && name_continue(source[end])) ++end;
    if (end - start >= 2 && source[start] == '0' && source[start + 1] == 'x') {
        base = 16;
        start += 2;
    }
    digits = start;
    while (start < end) {
        int digit = hex_digit(source[start]);
        if (digit < 0 || (unsigned)digit >= base) break;
        if (value > (UINT64_MAX - (unsigned)digit) / base)
            rmd_fail(reader->ctx, reader->token.loc, "integer token exceeds 64 bits");
        value = value * base + (unsigned)digit;
        ++start;
    }
    if (start == digits)
        rmd_fail(reader->ctx, reader->token.loc, "integer token has no digits");
    if (start == end && base == 10) {
        reader->token.kind = TOK_COUNT;
    } else {
        suffix = keyword(source + start, end - start);
        if (suffix == NULL || suffix->token != TOK_TYPE || suffix->type > RMD_T_USIZE)
            rmd_fail(reader->ctx, reader->token.loc, "invalid integer type suffix");
        reader->token.kind = TOK_INTEGER;
        reader->token.integer_type = suffix->type;
    }
    reader->token.integer = value;
    reader->offset = end;
}

static inline void skip_trivia(Reader *reader)
{
    const unsigned char *source = reader->source->bytes;
    size_t size = reader->end;
    unsigned char c;
    for (;;) {
        while (reader->offset < size) {
            c = source[reader->offset];
            if (c != ' ' && c != '\t' && c != '\r' && c != '\n') break;
            ++reader->offset;
        }
        if (size - reader->offset < 2 || source[reader->offset] != '/' ||
            source[reader->offset + 1] != '/') break;
        reader->offset += 2;
        while (reader->offset < size && source[reader->offset] != '\n') {
            if (source[reader->offset] == 0) {
                RmdLoc loc;
                loc.source = reader->source;
                loc.offset = reader->offset;
                rmd_fail(reader->ctx, loc, "zero byte in source");
            }
            ++reader->offset;
        }
    }
}

static void next_token(Reader *reader)
{
    const unsigned char *source = reader->source->bytes;
    size_t size = reader->end;
    size_t start;
    unsigned char c;
    const Keyword *word;
    memset(&reader->token, 0, sizeof(reader->token));
    skip_trivia(reader);
    reader->token.loc.source = reader->source;
    reader->token.loc.offset = reader->offset;
    if (reader->offset == size) {
        reader->token.kind = TOK_EOF;
        return;
    }
    start = reader->offset;
    c = source[start];
    if (name_start(c)) {
        ++reader->offset;
        while (reader->offset < size && name_continue(source[reader->offset]))
            ++reader->offset;
        word = keyword(source + start, reader->offset - start);
        if (word != NULL) {
            reader->token.kind = word->token;
            reader->token.integer_type = word->type;
        } else {
            reader->token.kind = TOK_NAME;
            reader->token.name = rmd_intern(reader->ctx, source + start, reader->offset - start);
        }
        return;
    }
    if (c >= '0' && c <= '9') {
        read_number(reader);
        return;
    }
    if (c == '"') {
        read_string(reader);
        return;
    }
    reader->token.kind = c;
    ++reader->offset;
    if (c == ';' || c == '}') return;
    if (reader->offset < size) {
        unsigned char second = source[reader->offset];
        if (c == '-' && second == '>') reader->token.kind = TOK_ARROW;
        else if (c == '=' && second == '=') reader->token.kind = TOK_EQ;
        else if (c == '!' && second == '=') reader->token.kind = TOK_NE;
        else if (c == '<' && second == '=') reader->token.kind = TOK_LE;
        else if (c == '>' && second == '=') reader->token.kind = TOK_GE;
        else if (c == '<' && second == '<') reader->token.kind = TOK_SHL;
        else if (c == '>' && second == '>') reader->token.kind = TOK_SHR;
        else if (c == '&' && second == '&') reader->token.kind = TOK_AND;
        else if (c == '|' && second == '|') reader->token.kind = TOK_OR;
        if (reader->token.kind != c) {
            ++reader->offset;
            return;
        }
    }
    if (c == 0 || strchr("{}()[]:;,.=+-*/%&|^!~<>", c) == NULL)
        rmd_fail(reader->ctx, reader->token.loc, "invalid source byte 0x%02x", (unsigned)c);
}

static bool take(Reader *reader, int kind)
{
    if (reader->token.kind != kind) return false;
    next_token(reader);
    return true;
}

static void expect(Reader *reader, int kind, const char *description)
{
    if (!take(reader, kind))
        rmd_fail(reader->ctx, reader->token.loc, "expected %s", description);
}

static void expect_current(Reader *reader, int kind, const char *description)
{
    if (reader->token.kind != kind)
        rmd_fail(reader->ctx, reader->token.loc, "expected %s", description);
}

static RmdName *read_name(Reader *reader)
{
    RmdName *name = reader->token.name;
    expect(reader, TOK_NAME, "an identifier");
    return name;
}

static void enter(Reader *reader)
{
    if (reader->depth == READ_DEPTH_LIMIT)
        rmd_fail(reader->ctx, reader->token.loc, "parser nesting limit of %u exceeded", READ_DEPTH_LIMIT);
    ++reader->depth;
}

static size_t grow_capacity(Reader *reader, size_t capacity)
{
    if (capacity > SIZE_MAX / 2)
        rmd_fail(reader->ctx, reader->token.loc, "too many list entries");
    return capacity == 0 ? 4 : capacity * 2;
}

static RmdTypeSyntax *read_type(Reader *reader);
static RmdExpr *read_expr(Reader *reader);
static RmdStmt *read_block(Reader *reader);
static RmdStmt *read_block_contents(Reader *reader);

static RmdTypeSyntax *read_type(Reader *reader)
{
    RmdTypeSyntax *type;
    enter(reader);
    type = NEW(reader, RmdTypeSyntax);
    type->loc = reader->token.loc;
    if (reader->token.kind == TOK_TYPE) {
        type->kind = reader->token.integer_type;
        next_token(reader);
    } else if (reader->token.kind == TOK_NAME) {
        type->kind = RMD_T_NAME;
        type->name = read_name(reader);
    } else if (take(reader, '*')) {
        type->kind = RMD_T_POINTER;
        type->base = read_type(reader);
    } else if (take(reader, '[')) {
        type->kind = RMD_T_ARRAY;
        type->base = read_type(reader);
        expect(reader, ';', "';' in array type");
        if (reader->token.kind != TOK_COUNT)
            rmd_fail(reader->ctx, reader->token.loc, "expected an unsuffixed decimal array count");
        type->count = reader->token.integer;
        next_token(reader);
        expect(reader, ']', "']'");
    } else if (take(reader, TOK_FN)) {
        size_t capacity = 0;
        type->kind = RMD_T_FUNCTION;
        expect(reader, '(', "'('");
        if (reader->token.kind != ')') {
            for (;;) {
                if (type->param_count == capacity) {
                    capacity = grow_capacity(reader, capacity);
                    type->params = rmd_grow_array(reader->ctx, type->params, type->param_count,
                        capacity, sizeof(*type->params), RMD_ALIGNOF(RmdTypeSyntax *));
                }
                type->params[type->param_count++] = read_type(reader);
                if (!take(reader, ',') || reader->token.kind == ')') break;
            }
        }
        expect(reader, ')', "')'");
        expect(reader, TOK_ARROW, "'->'");
        type->base = read_type(reader);
    } else {
        rmd_fail(reader->ctx, reader->token.loc, "expected a type");
    }
    --reader->depth;
    return type;
}

static RmdExpr *new_expr(Reader *reader, RmdExprKind kind, RmdLoc loc)
{
    RmdExpr *expr = NEW(reader, RmdExpr);
    expr->kind = kind;
    expr->loc = loc;
    return expr;
}

static void read_arguments(Reader *reader, RmdExpr *expr, int end)
{
    size_t capacity = 0;
    if (reader->token.kind != end) {
        for (;;) {
            if (expr->arg_count == capacity) {
                capacity = grow_capacity(reader, capacity);
                expr->args = rmd_grow_array(reader->ctx, expr->args, expr->arg_count,
                    capacity, sizeof(*expr->args), RMD_ALIGNOF(RmdExpr *));
            }
            expr->args[expr->arg_count++] = read_expr(reader);
            if (!take(reader, ',') || reader->token.kind == end) break;
        }
    }
    expect(reader, end, end == ')' ? "')'" : "'}'");
}

static RmdExpr *read_constructor(Reader *reader, RmdLoc loc)
{
    RmdExpr *expr;
    if (reader->token.kind == '[') {
        expr = new_expr(reader, RMD_E_ARRAY, loc);
        expr->syntax_type = read_type(reader);
        expect(reader, '{', "'{'");
        read_arguments(reader, expr, '}');
    } else if (reader->token.kind == TOK_NAME) {
        RmdInit **tail;
        expr = new_expr(reader, RMD_E_RECORD, loc);
        expr->syntax_type = read_type(reader);
        tail = &expr->inits;
        expect(reader, '{', "'{'");
        if (reader->token.kind != '}') {
            for (;;) {
                RmdInit *init = NEW(reader, RmdInit);
                init->loc = reader->token.loc;
                init->name = read_name(reader);
                expect(reader, ':', "':'");
                init->value = read_expr(reader);
                *tail = init;
                tail = &init->next;
                if (!take(reader, ',') || reader->token.kind == '}') break;
            }
        }
        expect(reader, '}', "'}'");
    } else {
        rmd_fail(reader->ctx, reader->token.loc, "expected a record name or an array type after 'make'");
        return NULL;
    }
    return expr;
}

static RmdExpr *read_primary(Reader *reader)
{
    Token token = reader->token;
    RmdExpr *expr;
    switch (token.kind) {
    case TOK_NAME:
        expr = new_expr(reader, RMD_E_NAME, token.loc);
        expr->name = token.name;
        next_token(reader);
        return expr;
    case TOK_INTEGER:
        expr = new_expr(reader, RMD_E_INTEGER, token.loc);
        expr->integer = token.integer;
        expr->literal_type = token.integer_type;
        next_token(reader);
        return expr;
    case TOK_TRUE:
    case TOK_FALSE:
        expr = new_expr(reader, RMD_E_BOOL, token.loc);
        expr->integer = token.kind == TOK_TRUE;
        next_token(reader);
        return expr;
    case TOK_STRING:
        expr = new_expr(reader, RMD_E_STRING, token.loc);
        expr->bytes = token.bytes;
        expr->byte_count = token.byte_count;
        next_token(reader);
        return expr;
    case '(':
        next_token(reader);
        expr = new_expr(reader, RMD_E_GROUP, token.loc);
        expr->left = read_expr(reader);
        expect(reader, ')', "')'");
        return expr;
    case TOK_MAKE:
        next_token(reader);
        return read_constructor(reader, token.loc);
    case TOK_NULL:
    case TOK_SIZEOF:
    case TOK_ALIGNOF:
        next_token(reader);
        expr = new_expr(reader, token.kind == TOK_NULL ? RMD_E_NULL :
            token.kind == TOK_SIZEOF ? RMD_E_SIZEOF : RMD_E_ALIGNOF, token.loc);
        expect(reader, '(', "'('");
        expr->syntax_type = read_type(reader);
        expect(reader, ')', "')'");
        return expr;
    case TOK_OFFSETOF:
        next_token(reader);
        expr = new_expr(reader, RMD_E_OFFSETOF, token.loc);
        expect(reader, '(', "'('");
        expr->syntax_type = NEW(reader, RmdTypeSyntax);
        expr->syntax_type->kind = RMD_T_NAME;
        expr->syntax_type->loc = reader->token.loc;
        expr->syntax_type->name = read_name(reader);
        expect(reader, ',', "','");
        expr->field_name = read_name(reader);
        expect(reader, ')', "')'");
        return expr;
    default:
        rmd_fail(reader->ctx, token.loc, "expected an expression");
        return NULL;
    }
}

static RmdExpr *read_postfix(Reader *reader)
{
    RmdExpr *expr = read_primary(reader);
    for (;;) {
        RmdLoc loc = reader->token.loc;
        RmdExpr *next;
        if (take(reader, '(')) {
            next = new_expr(reader, RMD_E_CALL, loc);
            next->left = expr;
            read_arguments(reader, next, ')');
        } else if (take(reader, '[')) {
            next = new_expr(reader, RMD_E_INDEX, loc);
            next->left = expr;
            next->right = read_expr(reader);
            expect(reader, ']', "']'");
        } else if (take(reader, '.')) {
            next = new_expr(reader, RMD_E_FIELD, loc);
            next->left = expr;
            next->field_name = read_name(reader);
        } else {
            return expr;
        }
        expr = next;
    }
}

static RmdExpr *read_unary(Reader *reader)
{
    RmdOp op;
    RmdExpr *expr;
    RmdLoc loc = reader->token.loc;
    enter(reader);
    switch (reader->token.kind) {
    case '-': op = RMD_OP_NEG; break;
    case '!': op = RMD_OP_NOT; break;
    case '~': op = RMD_OP_BIT_NOT; break;
    case '*': op = RMD_OP_DEREF; break;
    case '&': op = RMD_OP_ADDRESS; break;
    default:
        expr = read_postfix(reader);
        --reader->depth;
        return expr;
    }
    next_token(reader);
    expr = new_expr(reader, RMD_E_UNARY, loc);
    expr->op = op;
    expr->left = read_unary(reader);
    --reader->depth;
    return expr;
}

static RmdExpr *read_cast(Reader *reader)
{
    RmdExpr *expr = read_unary(reader);
    while (reader->token.kind == TOK_AS) {
        RmdExpr *cast = new_expr(reader, RMD_E_CAST, reader->token.loc);
        next_token(reader);
        cast->left = expr;
        cast->syntax_type = read_type(reader);
        expr = cast;
    }
    return expr;
}

static unsigned binary_operator(int token, RmdOp *op)
{
    switch (token) {
    case TOK_OR: *op = RMD_OP_OR; return 1;
    case TOK_AND: *op = RMD_OP_AND; return 2;
    case '|': *op = RMD_OP_BIT_OR; return 3;
    case '^': *op = RMD_OP_BIT_XOR; return 4;
    case '&': *op = RMD_OP_BIT_AND; return 5;
    case TOK_EQ: *op = RMD_OP_EQ; return 6;
    case TOK_NE: *op = RMD_OP_NE; return 6;
    case '<': *op = RMD_OP_LT; return 7;
    case TOK_LE: *op = RMD_OP_LE; return 7;
    case '>': *op = RMD_OP_GT; return 7;
    case TOK_GE: *op = RMD_OP_GE; return 7;
    case TOK_SHL: *op = RMD_OP_SHL; return 8;
    case TOK_SHR: *op = RMD_OP_SHR; return 8;
    case '+': *op = RMD_OP_ADD; return 9;
    case '-': *op = RMD_OP_SUB; return 9;
    case '*': *op = RMD_OP_MUL; return 10;
    case '/': *op = RMD_OP_DIV; return 10;
    case '%': *op = RMD_OP_REM; return 10;
    default: return 0;
    }
}

static RmdExpr *read_binary(Reader *reader, unsigned minimum)
{
    RmdExpr *left = read_cast(reader);
    bool compared = false;
    bool equated = false;
    for (;;) {
        RmdOp op = RMD_OP_ADD;
        unsigned precedence = binary_operator(reader->token.kind, &op);
        RmdExpr *expr;
        if (precedence < minimum) return left;
        if ((precedence == 7 && compared) || (precedence == 6 && equated))
            rmd_fail(reader->ctx, reader->token.loc, "comparisons cannot chain at the same precedence");
        if (precedence == 7) compared = true;
        if (precedence == 6) equated = true;
        expr = new_expr(reader, RMD_E_BINARY, reader->token.loc);
        expr->op = op;
        expr->left = left;
        next_token(reader);
        expr->right = read_binary(reader, precedence + 1);
        left = expr;
    }
}

static RmdExpr *read_expr(Reader *reader)
{
    RmdExpr *expr;
    enter(reader);
    expr = read_binary(reader, 1);
    --reader->depth;
    return expr;
}

static RmdStmt *new_stmt(Reader *reader, RmdStmtKind kind, RmdLoc loc)
{
    RmdStmt *stmt = NEW(reader, RmdStmt);
    stmt->kind = kind;
    stmt->loc = loc;
    return stmt;
}

static RmdStmt *read_simple_statement(Reader *reader)
{
    RmdStmt *stmt;
    RmdLoc loc = reader->token.loc;
    if (take(reader, TOK_VAR)) {
        stmt = new_stmt(reader, RMD_S_VAR, loc);
        stmt->name = read_name(reader);
        expect(reader, ':', "':'");
        stmt->syntax_type = read_type(reader);
        expect(reader, '=', "'='");
        stmt->uninitialized = take(reader, TOK_UNINIT);
        if (!stmt->uninitialized) stmt->value = read_expr(reader);
    } else if (take(reader, TOK_BREAK)) {
        stmt = new_stmt(reader, RMD_S_BREAK, loc);
    } else if (take(reader, TOK_CONTINUE)) {
        stmt = new_stmt(reader, RMD_S_CONTINUE, loc);
    } else if (take(reader, TOK_TRAP)) {
        stmt = new_stmt(reader, RMD_S_TRAP, loc);
    } else if (take(reader, TOK_RETURN)) {
        stmt = new_stmt(reader, RMD_S_RETURN, loc);
        if (reader->token.kind != ';') stmt->expr = read_expr(reader);
    } else {
        stmt = new_stmt(reader, RMD_S_EXPR, loc);
        stmt->expr = read_expr(reader);
        if (take(reader, '=')) {
            stmt->kind = RMD_S_ASSIGN;
            stmt->value = read_expr(reader);
        }
    }
    expect_current(reader, ';', "';'");
    return stmt;
}

static RmdStmt *read_statement(Reader *reader)
{
    RmdStmt *stmt;
    RmdLoc loc = reader->token.loc;
    if (reader->token.kind == '{') return read_block(reader);
    if (take(reader, TOK_IF)) {
        stmt = new_stmt(reader, RMD_S_IF, loc);
        stmt->expr = read_expr(reader);
        stmt->body = read_block(reader);
        if (take(reader, TOK_ELSE)) stmt->otherwise = read_block(reader);
        return stmt;
    }
    if (take(reader, TOK_WHILE)) {
        stmt = new_stmt(reader, RMD_S_WHILE, loc);
        stmt->expr = read_expr(reader);
        stmt->body = read_block(reader);
        return stmt;
    }
    stmt = read_simple_statement(reader);
    next_token(reader);
    return stmt;
}

static RmdStmt *read_block_contents(Reader *reader)
{
    RmdStmt *block;
    RmdStmt **tail;
    enter(reader);
    block = new_stmt(reader, RMD_S_BLOCK, reader->token.loc);
    expect(reader, '{', "'{'");
    tail = &block->body;
    while (reader->token.kind != '}') {
        if (reader->token.kind == TOK_EOF)
            rmd_fail(reader->ctx, reader->token.loc, "expected '}' before end of input");
        *tail = read_statement(reader);
        tail = &(*tail)->next;
    }
    --reader->depth;
    return block;
}

static RmdStmt *read_block(Reader *reader)
{
    RmdStmt *block = read_block_contents(reader);
    next_token(reader);
    return block;
}

static RmdDecl *read_declaration(Reader *reader)
{
    Token token = reader->token;
    RmdDecl *decl = NEW(reader, RmdDecl);
    decl->loc = token.loc;
    if (take(reader, TOK_RECORD)) {
        RmdField **tail = &decl->fields;
        decl->kind = RMD_D_RECORD;
        decl->name = read_name(reader);
        expect(reader, '{', "'{'");
        do {
            RmdField *field = NEW(reader, RmdField);
            field->loc = reader->token.loc;
            field->name = read_name(reader);
            expect(reader, ':', "':'");
            field->syntax_type = read_type(reader);
            expect(reader, ';', "';'");
            field->index = decl->field_count++;
            *tail = field;
            tail = &field->next;
        } while (reader->token.kind != '}');
    } else if (token.kind == TOK_FN || token.kind == TOK_EXTERN) {
        RmdParam **tail = &decl->params;
        decl->kind = token.kind == TOK_FN ? RMD_D_FUNCTION : RMD_D_EXTERN;
        next_token(reader);
        if (decl->kind == RMD_D_EXTERN) expect(reader, TOK_FN, "'fn'");
        decl->name = read_name(reader);
        expect(reader, '(', "'('");
        if (reader->token.kind != ')') {
            for (;;) {
                RmdParam *param = NEW(reader, RmdParam);
                param->loc = reader->token.loc;
                param->name = read_name(reader);
                expect(reader, ':', "':'");
                param->syntax_type = read_type(reader);
                *tail = param;
                tail = &param->next;
                ++decl->param_count;
                if (!take(reader, ',') || reader->token.kind == ')') break;
            }
        }
        expect(reader, ')', "')'");
        expect(reader, TOK_ARROW, "'->'");
        decl->syntax_type = read_type(reader);
        if (decl->kind == RMD_D_FUNCTION) {
            decl->body = read_block_contents(reader);
        } else {
            size_t i;
            expect(reader, '=', "'='");
            if (reader->token.kind != TOK_STRING)
                rmd_fail(reader->ctx, reader->token.loc, "expected a native symbol string");
            if (reader->token.byte_count == 1)
                rmd_fail(reader->ctx, reader->token.loc, "native symbol name must not be empty");
            for (i = 0; i + 1 < reader->token.byte_count; ++i) {
                if (reader->token.bytes[i] == 0 || reader->token.bytes[i] >= 128)
                    rmd_fail(reader->ctx, reader->token.loc, "native symbol name must be ASCII without zero bytes");
            }
            decl->link_name = (const char *)reader->token.bytes;
            next_token(reader);
            expect_current(reader, ';', "';'");
        }
    } else if (take(reader, TOK_CONST)) {
        decl->kind = RMD_D_CONST;
        decl->name = read_name(reader);
        expect(reader, ':', "':'");
        decl->syntax_type = read_type(reader);
        expect(reader, '=', "'='");
        decl->init = read_expr(reader);
        expect_current(reader, ';', "';'");
    } else {
        rmd_fail(reader->ctx, token.loc, "expected a declaration");
    }
    return decl;
}

static RmdUnit *read_unit(RmdContext *ctx, RmdSource *source, size_t begin, size_t end)
{
    Reader reader;
    RmdUnit *unit;
    RmdDecl **tail;
    uint64_t ordinal = 0;
    memset(&reader, 0, sizeof(reader));
    reader.ctx = ctx;
    reader.source = source;
    reader.offset = begin;
    reader.end = end;
    unit = NEW(&reader, RmdUnit);
    unit->source = source;
    tail = &unit->declarations;
    next_token(&reader);
    while (reader.token.kind != TOK_EOF) {
        RmdDecl *decl = read_declaration(&reader);
        if (ordinal == UINT64_MAX)
            rmd_fail(ctx, decl->loc, "too many declarations");
        decl->unit_identity = source->identity;
        decl->identity = ++ordinal;
        *tail = decl;
        tail = &decl->next;
        next_token(&reader);
    }
    return unit;
}

bool rmd_read_range(RmdContext *ctx, RmdSource *source, size_t begin, size_t end,
                    RmdUnit **result)
{
    RmdFailureFrame failure;
    RmdUnit *unit;
    *result = NULL;
    if (begin > end || end > source->size) {
        rmd_set_error(ctx, source, begin <= source->size ? begin : source->size,
                      "source range must satisfy begin <= end <= source size");
        return false;
    }
    failure.previous = ctx->failure;
    ctx->failure = &failure;
    if (setjmp(failure.jump) != 0) {
        ctx->failure = failure.previous;
        return false;
    }
    unit = read_unit(ctx, source, begin, end);
    if (ctx->last_unit == NULL) ctx->units = unit;
    else ctx->last_unit->next = unit;
    ctx->last_unit = unit;
    *result = unit;
    ctx->failure = failure.previous;
    return true;
}

bool rmd_read_one(RmdContext *ctx, RmdSource *source, size_t begin, size_t end,
                  RmdAction *result)
{
    RmdFailureFrame failure;
    Reader reader;
    memset(result, 0, sizeof(*result));
    if (begin > end || end > source->size) {
        rmd_set_error(ctx, source, begin <= source->size ? begin : source->size,
                      "source range must satisfy begin <= end <= source size");
        return false;
    }
    failure.previous = ctx->failure;
    ctx->failure = &failure;
    if (setjmp(failure.jump) != 0) {
        memset(result, 0, sizeof(*result));
        ctx->failure = failure.previous;
        return false;
    }
    memset(&reader, 0, sizeof(reader));
    reader.ctx = ctx;
    reader.source = source;
    reader.offset = begin;
    reader.end = end;
    next_token(&reader);
    if (reader.token.kind == TOK_RECORD || reader.token.kind == TOK_FN ||
        reader.token.kind == TOK_EXTERN || reader.token.kind == TOK_CONST) {
        RmdDecl *decl = read_declaration(&reader);
        if (decl->loc.offset >= UINT64_MAX)
            rmd_fail(ctx, decl->loc, "declaration offset exceeds the identity limit");
        decl->unit_identity = source->identity;
        decl->identity = (uint64_t)decl->loc.offset + 1;
        result->declaration = decl;
    } else if (reader.token.kind != TOK_EOF) {
        if (reader.token.kind == '{' || reader.token.kind == TOK_IF ||
            reader.token.kind == TOK_WHILE) {
            result->statement = read_statement(&reader);
            expect_current(&reader, ';', "';' after a root block, if, or while");
        } else {
            result->statement = read_simple_statement(&reader);
        }
    }
    result->end = reader.offset;
    ctx->failure = failure.previous;
    return true;
}

bool rmd_read(RmdContext *ctx, RmdSource *source, RmdUnit **result)
{
    return rmd_read_range(ctx, source, 0, source->size, result);
}
