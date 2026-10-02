/* SPDX-License-Identifier: Apache-2.0 */

#include "core_internal.h"

#include <limits.h>
#include <string.h>

#define CHECK_DEPTH_LIMIT 256u

typedef struct Identity Identity;
struct Identity {
    CrustDecl *decl;
    CrustMap fields;
    unsigned layout_depth;
    Identity *next;
    Identity *pending_next;
};

typedef struct BindWork BindWork;
struct BindWork {
    CrustDecl *decl;
    unsigned layout_state;
    unsigned layout_depth;
    BindWork *next;
};

typedef struct {
    unsigned state;
    unsigned depth;
} BoundType;

typedef struct {
    CrustContext *ctx;
    CrustMap pending;
    CrustMap visited;
    CrustMap types;
    Identity *identities;
    BindWork *work;
    BindWork **tail;
} Binding;

typedef struct {
    CrustContext *ctx;
    CrustType *return_type;
    CrustMap locals;
    CrustSymbol *scope;
    unsigned loop_depth;
    unsigned depth;
    bool constant;
} Checker;

static void resolve_declaration(CrustContext *ctx, CrustDecl *decl, unsigned depth);
static CrustType *resolve_syntax(CrustContext *ctx, CrustTypeSyntax *syntax, unsigned depth);
static void finish_layout(CrustContext *ctx, CrustType *type, CrustLoc loc, unsigned depth);
static CrustType *check_expr(Checker *checker, CrustExpr *expr);
static bool check_stmt(Checker *checker, CrustStmt *stmt);

static CrustLoc no_location(void)
{
    CrustLoc loc = {NULL, 0};
    return loc;
}

static void check_depth(CrustContext *ctx, CrustLoc loc, unsigned depth)
{
    if (depth >= CHECK_DEPTH_LIMIT)
        crust_fail(ctx, loc, "semantic traversal depth limit of %u exceeded", CHECK_DEPTH_LIMIT);
}

static bool same_name(const CrustName *a, const CrustName *b)
{
    return a == b ||
           (a != NULL && b != NULL && a->size == b->size && memcmp(a->text, b->text, a->size) == 0);
}

static CrustType *new_type(CrustContext *ctx, CrustTypeKind kind)
{
    CrustType *type = crust_alloc(ctx, sizeof(*type), CRUST_ALIGNOF(CrustType));
    type->kind = kind;
    return type;
}

bool crust_type_integer(const CrustType *type)
{
    return type != NULL && type->kind >= CRUST_T_I8 && type->kind <= CRUST_T_USIZE;
}

bool crust_type_signed(const CrustType *type)
{
    if (type == NULL)
        return false;
    switch (type->kind) {
    case CRUST_T_I8:
    case CRUST_T_I16:
    case CRUST_T_I32:
    case CRUST_T_I64:
    case CRUST_T_ISIZE:
        return true;
    default:
        return false;
    }
}

bool crust_type_scalar(const CrustType *type)
{
    return type != NULL && (crust_type_integer(type) || type->kind == CRUST_T_BOOL ||
                            type->kind == CRUST_T_POINTER || type->kind == CRUST_T_FUNCTION);
}

unsigned crust_type_bits(const CrustType *type)
{
    if (type == NULL)
        return 0;
    switch (type->kind) {
    case CRUST_T_I8:
    case CRUST_T_U8:
    case CRUST_T_BOOL:
        return 8;
    case CRUST_T_I16:
    case CRUST_T_U16:
        return 16;
    case CRUST_T_I32:
    case CRUST_T_U32:
        return 32;
    case CRUST_T_I64:
    case CRUST_T_U64:
    case CRUST_T_ISIZE:
    case CRUST_T_USIZE:
    case CRUST_T_POINTER:
    case CRUST_T_FUNCTION:
        return 64;
    default:
        return 0;
    }
}

static bool record_types_equal(const CrustType *a, const CrustType *b)
{
    if (a->record_decl == NULL || b->record_decl == NULL)
        return false;
    return a->record_decl == b->record_decl ||
           (a->record_decl->identity != 0 && b->record_decl->identity != 0 &&
            a->record_decl->identity == b->record_decl->identity &&
            a->record_decl->unit_identity == b->record_decl->unit_identity);
}

static bool type_equal(CrustContext *ctx, const CrustType *a, const CrustType *b);

static bool function_types_equal(CrustContext *ctx, const CrustType *a, const CrustType *b)
{
    size_t i;
    if (a->param_count != b->param_count)
        return false;
    if (crust_type_compare_seen(ctx, a, b))
        return true;
    if (!type_equal(ctx, a->base, b->base))
        return false;
    for (i = 0; i < a->param_count; ++i) {
        if (!type_equal(ctx, a->params[i], b->params[i]))
            return false;
    }
    return true;
}

static bool type_equal(CrustContext *ctx, const CrustType *a, const CrustType *b)
{
    if (a == b)
        return a != NULL;
    if (a == NULL || b == NULL || a->kind != b->kind)
        return false;
    switch (a->kind) {
    case CRUST_T_POINTER:
        return type_equal(ctx, a->base, b->base);
    case CRUST_T_ARRAY:
        return a->count == b->count && type_equal(ctx, a->base, b->base);
    case CRUST_T_FUNCTION:
        return function_types_equal(ctx, a, b);
    case CRUST_T_RECORD:
        return record_types_equal(a, b);
    case CRUST_T_NAME:
        return false;
    default:
        return true;
    }
}

bool crust_type_equal(CrustContext *ctx, const CrustType *a, const CrustType *b)
{
    bool result;
    crust_type_compare_reset(ctx);
    result = type_equal(ctx, a, b);
    crust_type_compare_reset(ctx);
    return result;
}

bool crust_try_type_equal(CrustContext *ctx, const CrustType *a, const CrustType *b, bool *result)
{
    CrustFailureFrame frame;
    bool equal;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    equal = crust_type_equal(ctx, a, b);
    ctx->failure = frame.previous;
    *result = equal;
    return true;
}

static uintptr_t identity_key(const CrustDecl *decl)
{
    uint64_t hash = decl->identity ^ (decl->unit_identity + UINT64_C(0x9e3779b97f4a7c15) +
                                      (decl->identity << 6) + (decl->identity >> 2));
    uintptr_t key = (uintptr_t)hash;
    return key == 0 ? 1 : key;
}

static Identity *identity_find(const CrustMap *map, const CrustDecl *decl)
{
    Identity *entry;
    for (entry = crust_map_get(map, identity_key(decl)); entry != NULL; entry = entry->next) {
        if (entry->decl->identity == decl->identity &&
            entry->decl->unit_identity == decl->unit_identity)
            return entry;
    }
    return NULL;
}

static void identity_insert(CrustContext *ctx, CrustMap *map, Identity *entry)
{
    uintptr_t key = identity_key(entry->decl);
    entry->next = crust_map_get(map, key);
    crust_map_set(ctx, map, key, entry);
}

static CrustExpr *ungroup(CrustContext *ctx, CrustExpr *expr, unsigned depth)
{
    while (expr->kind == CRUST_E_GROUP) {
        check_depth(ctx, expr->loc, depth++);
        expr = expr->left;
    }
    return expr;
}

static bool constant_bits(CrustExpr *expr, uint64_t *bits)
{
    unsigned width;
    switch (expr->kind) {
    case CRUST_E_INTEGER:
    case CRUST_E_BOOL:
    case CRUST_E_SIZEOF:
    case CRUST_E_ALIGNOF:
    case CRUST_E_OFFSETOF:
        *bits = expr->integer;
        return true;
    case CRUST_E_UNARY:
        if (expr->op != CRUST_OP_NEG || expr->left->kind != CRUST_E_INTEGER)
            return false;
        width = crust_type_bits(expr->type);
        *bits = (UINT64_C(0) - expr->left->integer) & (UINT64_MAX >> (64 - width));
        return true;
    case CRUST_E_NULL:
        *bits = 0;
        return true;
    default:
        return false;
    }
}

static bool constant_equal(CrustContext *ctx, CrustExpr *a, CrustExpr *b, unsigned depth);

static bool constant_function_equal(CrustExpr *a, CrustExpr *b)
{
    /* Native aliases denote the same callable value. */
    return a->symbol != NULL && b->symbol != NULL && a->symbol->decl->link_name != NULL &&
           b->symbol->decl->link_name != NULL &&
           strcmp(a->symbol->decl->link_name, b->symbol->decl->link_name) == 0;
}

static bool constant_array_equal(CrustContext *ctx, CrustExpr *a, CrustExpr *b, unsigned depth)
{
    size_t i;
    if (a->arg_count != b->arg_count)
        return false;
    for (i = 0; i < a->arg_count; ++i) {
        if (!constant_equal(ctx, a->args[i], b->args[i], depth + 1))
            return false;
    }
    return true;
}

static bool constant_record_equal(CrustContext *ctx, CrustExpr *a, CrustExpr *b, unsigned depth)
{
    CrustInit **fields;
    CrustInit *init;
    fields = crust_grow_array(ctx, NULL, 0, a->type->record_decl->field_count, sizeof(*fields),
                              CRUST_ALIGNOF(CrustInit *));
    for (init = a->inits; init != NULL; init = init->next)
        fields[init->field->index] = init;
    for (init = b->inits; init != NULL; init = init->next) {
        CrustInit *other = fields[init->field->index];
        if (other == NULL || !constant_equal(ctx, other->value, init->value, depth + 1))
            return false;
    }
    return true;
}

static bool constant_equal(CrustContext *ctx, CrustExpr *a, CrustExpr *b, unsigned depth)
{
    uint64_t left;
    uint64_t right;
    if (a == b)
        return a != NULL;
    if (a == NULL || b == NULL)
        return false;
    check_depth(ctx, a->loc, depth);
    a = ungroup(ctx, a, depth);
    b = ungroup(ctx, b, depth);
    if (!crust_type_equal(ctx, a->type, b->type))
        return false;
    if (constant_bits(a, &left) && constant_bits(b, &right))
        return left == right;
    if (a->kind != b->kind)
        return false;
    switch (a->kind) {
    case CRUST_E_STRING:
        return a->byte_count == b->byte_count && memcmp(a->bytes, b->bytes, a->byte_count) == 0;
    case CRUST_E_NAME:
        return constant_function_equal(a, b);
    case CRUST_E_ARRAY:
        return constant_array_equal(ctx, a, b, depth);
    case CRUST_E_RECORD:
        return constant_record_equal(ctx, a, b, depth);
    default:
        return false;
    }
}

static bool record_facts_equal(CrustContext *ctx, CrustDecl *a, CrustDecl *b)
{
    CrustField *left;
    CrustField *right;
    if (a->type->size != b->type->size || a->type->align != b->type->align ||
        a->field_count != b->field_count)
        return false;
    left = a->fields;
    right = b->fields;
    while (left != NULL && right != NULL) {
        if (!same_name(left->name, right->name) || left->offset != right->offset ||
            !crust_type_equal(ctx, left->type, right->type))
            return false;
        left = left->next;
        right = right->next;
    }
    return left == NULL && right == NULL;
}

static bool same_declaration_facts(CrustContext *ctx, CrustDecl *a, CrustDecl *b)
{
    bool a_function = a->kind == CRUST_D_FUNCTION || a->kind == CRUST_D_EXTERN;
    bool b_function = b->kind == CRUST_D_FUNCTION || b->kind == CRUST_D_EXTERN;
    if (a == b)
        return true;
    if ((!a_function || !b_function) && a->kind != b->kind)
        return false;
    if (!crust_type_equal(ctx, a->type, b->type))
        return false;
    if (a->kind == CRUST_D_RECORD)
        return record_facts_equal(ctx, a, b);
    if (a->link_name == NULL || b->link_name == NULL || strcmp(a->link_name, b->link_name) != 0)
        return false;
    return a_function || constant_equal(ctx, a->init, b->init, 0);
}

static Identity *binding_identity(Binding *binding, CrustDecl *decl)
{
    CrustContext *ctx = binding->ctx;
    Identity *entry = identity_find(&ctx->identities, decl);
    if (entry == NULL)
        entry = identity_find(&binding->pending, decl);
    if (entry != NULL) {
        if (!same_declaration_facts(ctx, entry->decl, decl))
            crust_fail(ctx, decl->loc, "conflicting facts for declaration identity");
        return entry;
    }
    entry = crust_alloc(ctx, sizeof(*entry), CRUST_ALIGNOF(Identity));
    entry->decl = decl;
    entry->pending_next = binding->identities;
    binding->identities = entry;
    identity_insert(ctx, &binding->pending, entry);
    return entry;
}

CrustType *crust_pointer_type(CrustContext *ctx, CrustType *base)
{
    CrustType *type;
    if (base == NULL || base->kind == CRUST_T_UNIT) {
        crust_fail(ctx, no_location(), "a pointer requires a storage type");
        return NULL;
    }
    type = new_type(ctx, CRUST_T_POINTER);
    type->size = 8;
    type->align = 8;
    type->base = base;
    return type;
}

CrustType *crust_try_pointer_type(CrustContext *ctx, CrustType *base)
{
    CrustFailureFrame frame;
    CrustType *result;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return NULL;
    }
    result = crust_pointer_type(ctx, base);
    ctx->failure = frame.previous;
    return result;
}

static CrustSymbol *global_symbol(CrustContext *ctx, CrustName *name, CrustLoc loc)
{
    CrustSymbol *symbol = crust_map_get(&ctx->globals, (uintptr_t)name);
    if (symbol == NULL)
        crust_fail(ctx, loc, "unknown name '%s'", name->text);
    return symbol;
}

static CrustSymbolKind declaration_kind(CrustDecl *decl)
{
    switch (decl->kind) {
    case CRUST_D_RECORD:
        return CRUST_SYM_RECORD;
    case CRUST_D_FUNCTION:
    case CRUST_D_EXTERN:
        return CRUST_SYM_FUNCTION;
    case CRUST_D_CONST:
        return CRUST_SYM_CONST;
    }
    return CRUST_SYM_RECORD;
}

static CrustSymbol *new_symbol(CrustContext *ctx, CrustName *name, CrustSymbolKind kind,
                               CrustLoc loc)
{
    CrustSymbol *symbol = crust_alloc(ctx, sizeof(*symbol), CRUST_ALIGNOF(CrustSymbol));
    symbol->name = name;
    symbol->kind = kind;
    symbol->loc = loc;
    return symbol;
}

static void require_storage(CrustContext *ctx, CrustType *type, CrustLoc loc, unsigned depth)
{
    if (type == NULL || type->kind == CRUST_T_UNIT) {
        crust_fail(ctx, loc, "unit is not a storage type");
        return;
    }
    finish_layout(ctx, type, loc, depth);
}

static void require_scalar(CrustContext *ctx, CrustType *type, CrustLoc loc)
{
    if (!crust_type_scalar(type))
        crust_fail(ctx, loc, "function arguments must have scalar types");
}

static CrustType *resolve_syntax(CrustContext *ctx, CrustTypeSyntax *syntax, unsigned depth)
{
    CrustType *type;
    CrustSymbol *symbol;
    size_t i;
    if (syntax == NULL) {
        crust_fail(ctx, no_location(), "missing type description");
        return NULL;
    }
    check_depth(ctx, syntax->loc, depth);
    if (syntax->kind >= CRUST_T_I8 && syntax->kind <= CRUST_T_UNIT)
        return &ctx->builtins[syntax->kind];
    switch (syntax->kind) {
    case CRUST_T_NAME:
        symbol = global_symbol(ctx, syntax->name, syntax->loc);
        if (symbol->kind != CRUST_SYM_RECORD) {
            crust_fail(ctx, syntax->loc, "'%s' is not a record type", syntax->name->text);
            return NULL;
        }
        return symbol->type;
    case CRUST_T_POINTER:
        type = resolve_syntax(ctx, syntax->base, depth + 1);
        if (type->kind == CRUST_T_UNIT) {
            crust_fail(ctx, syntax->loc, "unit is not a pointer target");
            return NULL;
        }
        return crust_pointer_type(ctx, type);
    case CRUST_T_ARRAY:
        if (syntax->count == 0) {
            crust_fail(ctx, syntax->loc, "array count must be positive");
            return NULL;
        }
        type = new_type(ctx, CRUST_T_ARRAY);
        type->base = resolve_syntax(ctx, syntax->base, depth + 1);
        if (type->base->kind == CRUST_T_UNIT) {
            crust_fail(ctx, syntax->loc, "unit is not an array element type");
            return NULL;
        }
        type->count = syntax->count;
        return type;
    case CRUST_T_FUNCTION:
        type = new_type(ctx, CRUST_T_FUNCTION);
        type->size = 8;
        type->align = 8;
        type->base = resolve_syntax(ctx, syntax->base, depth + 1);
        if (type->base->kind != CRUST_T_UNIT && !crust_type_scalar(type->base)) {
            crust_fail(ctx, syntax->loc, "function results must be scalar or unit");
            return NULL;
        }
        type->param_count = syntax->param_count;
        type->params = crust_grow_array(ctx, NULL, 0, syntax->param_count, sizeof(*type->params),
                                        CRUST_ALIGNOF(CrustType *));
        for (i = 0; i < syntax->param_count; ++i) {
            type->params[i] = resolve_syntax(ctx, syntax->params[i], depth + 1);
            require_scalar(ctx, type->params[i], syntax->params[i]->loc);
        }
        return type;
    default:
        crust_fail(ctx, syntax->loc, "invalid type syntax");
        return NULL;
    }
}

static uint64_t align_size(CrustContext *ctx, uint64_t size, uint32_t align, CrustLoc loc)
{
    uint64_t remainder = size % align;
    uint64_t padding = remainder == 0 ? 0 : align - remainder;
    if (size > (uint64_t)INT64_MAX - padding) {
        crust_fail(ctx, loc, "type layout exceeds the isize limit");
        return 0;
    }
    return size + padding;
}

static unsigned check_bound_shape(Binding *binding, CrustType *type, CrustLoc loc, unsigned depth);

static unsigned check_bound_pointer(Binding *binding, CrustType *type, CrustLoc loc, unsigned depth)
{
    unsigned height = 1 + check_bound_shape(binding, type->base, loc, depth + 1);
    if (type->base->kind == CRUST_T_UNIT || type->size != 8 || type->align != 8)
        crust_fail(binding->ctx, loc, "invalid bound pointer type");
    return height;
}

static unsigned check_bound_array(Binding *binding, CrustType *type, CrustLoc loc, unsigned depth)
{
    unsigned height = 1 + check_bound_shape(binding, type->base, loc, depth + 1);
    if (type->base->kind == CRUST_T_UNIT || type->count == 0 ||
        type->count > (uint64_t)INT64_MAX / type->base->size ||
        type->size != type->count * type->base->size || type->align != type->base->align)
        crust_fail(binding->ctx, loc, "invalid bound array layout");
    return height;
}

static unsigned check_bound_function(Binding *binding, CrustType *type, CrustLoc loc,
                                     unsigned depth)
{
    CrustContext *ctx = binding->ctx;
    size_t i;
    unsigned height = 1 + check_bound_shape(binding, type->base, loc, depth + 1);
    if ((type->base->kind != CRUST_T_UNIT && !crust_type_scalar(type->base)) || type->size != 8 ||
        type->align != 8 || (type->param_count != 0 && type->params == NULL))
        crust_fail(ctx, loc, "invalid bound function signature");
    for (i = 0; i < type->param_count; ++i) {
        unsigned child = 1 + check_bound_shape(binding, type->params[i], loc, depth + 1);
        if (child > height)
            height = child;
        require_scalar(ctx, type->params[i], loc);
    }
    return height;
}

static void check_bound_record_identity(CrustContext *ctx, CrustType *type, CrustLoc loc)
{
    if (type->record_decl == NULL || type->record_decl->kind != CRUST_D_RECORD ||
        type->record_decl->type != type || type->record_decl->identity == 0)
        crust_fail(ctx, loc, "incomplete bound record identity");
}

static unsigned check_bound_composite(Binding *binding, CrustType *type, CrustLoc loc,
                                      unsigned depth)
{
    CrustContext *ctx = binding->ctx;
    BoundType *work = crust_map_get(&binding->types, (uintptr_t)type);
    if (work != NULL) {
        if (work->state == 1)
            crust_fail(ctx, loc, "cyclic structural type facts");
        check_depth(ctx, loc, depth + work->depth);
        return work->depth;
    }
    work = crust_alloc(ctx, sizeof(*work), CRUST_ALIGNOF(BoundType));
    work->state = 1;
    crust_map_set(ctx, &binding->types, (uintptr_t)type, work);
    switch (type->kind) {
    case CRUST_T_POINTER:
        work->depth = check_bound_pointer(binding, type, loc, depth);
        break;
    case CRUST_T_ARRAY:
        work->depth = check_bound_array(binding, type, loc, depth);
        break;
    case CRUST_T_FUNCTION:
        work->depth = check_bound_function(binding, type, loc, depth);
        break;
    default:
        crust_fail(ctx, loc, "invalid bound type kind");
    }
    check_depth(ctx, loc, depth + work->depth);
    work->state = 2;
    return work->depth;
}

static unsigned check_bound_shape(Binding *binding, CrustType *type, CrustLoc loc, unsigned depth)
{
    CrustContext *ctx = binding->ctx;
    check_depth(ctx, loc, depth);
    if (type == NULL)
        crust_fail(ctx, loc, "incomplete bound type facts");
    if (type->kind >= CRUST_T_I8 && type->kind <= CRUST_T_UNIT) {
        if (type->size != ctx->builtins[type->kind].size ||
            type->align != ctx->builtins[type->kind].align)
            crust_fail(ctx, loc, "bound scalar layout does not match the target profile");
        return 0;
    }
    if (type->size == 0 || type->size > (uint64_t)INT64_MAX || type->align == 0 ||
        type->align > 8 || (type->align & (type->align - 1)) != 0)
        crust_fail(ctx, loc, "incomplete bound storage layout");
    if (type->kind == CRUST_T_RECORD) {
        check_bound_record_identity(ctx, type, loc);
        return 0;
    }
    return check_bound_composite(binding, type, loc, depth);
}

static void bind_field_name(CrustContext *ctx, CrustMap *fields, CrustField *field)
{
    CrustName *name;
    if (field->name == NULL)
        crust_fail(ctx, field->loc, "incomplete bound field name");
    name = crust_intern(ctx, (const unsigned char *)field->name->text, field->name->size);
    if (crust_map_get(fields, (uintptr_t)name) != NULL)
        crust_fail(ctx, field->loc, "duplicate bound field '%s'", name->text);
    crust_map_set(ctx, fields, (uintptr_t)name, field);
}

static void queue_bound_record(Binding *binding, CrustDecl *decl)
{
    CrustContext *ctx = binding->ctx;
    CrustMap fields = {NULL, 0, 0};
    CrustField *field;
    BindWork *work;
    Identity *entry = identity_find(&ctx->identities, decl);
    uint64_t size = 0;
    uint32_t align = 1;
    size_t index = 0;
    if ((entry != NULL && entry->decl == decl) ||
        crust_map_get(&binding->visited, (uintptr_t)decl) != NULL)
        return;
    for (field = decl->fields; field != NULL; field = field->next) {
        bind_field_name(ctx, &fields, field);
        (void)check_bound_shape(binding, field->type, field->loc, 0);
        if (field->type->kind == CRUST_T_UNIT)
            crust_fail(ctx, field->loc, "unit is not a bound field type");
        size = align_size(ctx, size, field->type->align, field->loc);
        if (field->offset != size || field->index != index++)
            crust_fail(ctx, field->loc, "inconsistent bound field layout");
        if (field->type->size > (uint64_t)INT64_MAX - size)
            crust_fail(ctx, field->loc, "bound record layout exceeds the isize limit");
        size += field->type->size;
        if (field->type->align > align)
            align = field->type->align;
    }
    if (index == 0 || index != decl->field_count || decl->type->align != align ||
        decl->type->size != align_size(ctx, size, align, decl->loc))
        crust_fail(ctx, decl->loc, "incomplete or inconsistent bound record facts");
    entry = binding_identity(binding, decl);
    if (entry->fields.capacity == 0)
        entry->fields = fields;
    work = crust_alloc(ctx, sizeof(*work), CRUST_ALIGNOF(BindWork));
    work->decl = decl;
    crust_map_set(ctx, &binding->visited, (uintptr_t)decl, work);
    *binding->tail = work;
    binding->tail = &work->next;
}

static void bind_type_records(Binding *binding, CrustType *type)
{
    BoundType *work;
    size_t i;
    if (type->kind == CRUST_T_RECORD) {
        queue_bound_record(binding, type->record_decl);
        return;
    }
    if (type->kind <= CRUST_T_UNIT)
        return;
    work = crust_map_get(&binding->types, (uintptr_t)type);
    if (work->state == 3)
        return;
    work->state = 3;
    switch (type->kind) {
    case CRUST_T_POINTER:
    case CRUST_T_ARRAY:
        bind_type_records(binding, type->base);
        break;
    case CRUST_T_FUNCTION:
        bind_type_records(binding, type->base);
        for (i = 0; i < type->param_count; ++i)
            bind_type_records(binding, type->params[i]);
        break;
    default:
        break;
    }
}

static void bind_constant_function(Binding *binding, CrustExpr *expr)
{
    CrustContext *ctx = binding->ctx;
    CrustDecl *function;
    if (expr->symbol == NULL || expr->symbol->kind != CRUST_SYM_FUNCTION ||
        expr->symbol->decl == NULL)
        crust_fail(ctx, expr->loc, "incomplete bound constant function reference");
    function = expr->symbol->decl;
    (void)check_bound_shape(binding, function->type, function->loc, 0);
    if ((function->kind != CRUST_D_FUNCTION && function->kind != CRUST_D_EXTERN) ||
        function->identity == 0 || function->type->kind != CRUST_T_FUNCTION ||
        function->link_name == NULL || function->link_name[0] == '\0' ||
        !crust_type_equal(ctx, function->type, expr->type))
        crust_fail(ctx, expr->loc, "incomplete bound constant function facts");
    (void)binding_identity(binding, function);
    bind_type_records(binding, function->type);
}

static void check_bound_constant_leaf(CrustContext *ctx, CrustExpr *expr)
{
    switch (expr->kind) {
    case CRUST_E_UNARY:
        if (expr->op != CRUST_OP_NEG || expr->left->kind != CRUST_E_INTEGER)
            crust_fail(ctx, expr->loc, "invalid bound constant operation");
        break;
    case CRUST_E_INTEGER:
    case CRUST_E_BOOL:
    case CRUST_E_STRING:
    case CRUST_E_NULL:
    case CRUST_E_SIZEOF:
    case CRUST_E_ALIGNOF:
    case CRUST_E_OFFSETOF:
        break;
    default:
        crust_fail(ctx, expr->loc, "invalid bound constant initializer");
    }
}

static void bind_constant_dependencies(Binding *binding, CrustExpr *expr, unsigned depth)
{
    CrustContext *ctx = binding->ctx;
    CrustInit *init;
    size_t i;
    check_depth(ctx, expr->loc, depth);
    switch (expr->kind) {
    case CRUST_E_NAME:
        bind_constant_function(binding, expr);
        break;
    case CRUST_E_GROUP:
        bind_constant_dependencies(binding, expr->left, depth + 1);
        break;
    case CRUST_E_RECORD:
        for (init = expr->inits; init != NULL; init = init->next)
            bind_constant_dependencies(binding, init->value, depth + 1);
        break;
    case CRUST_E_ARRAY:
        for (i = 0; i < expr->arg_count; ++i)
            bind_constant_dependencies(binding, expr->args[i], depth + 1);
        break;
    default:
        check_bound_constant_leaf(ctx, expr);
        break;
    }
}

static unsigned bound_layout_path(Binding *binding, CrustType *type, unsigned depth)
{
    BindWork *work;
    CrustField *field;
    unsigned height = 0;
    check_depth(binding->ctx, no_location(), depth);
    if (type->kind == CRUST_T_ARRAY) {
        height = 1 + bound_layout_path(binding, type->base, depth + 1);
    } else if (type->kind == CRUST_T_RECORD) {
        work = crust_map_get(&binding->visited, (uintptr_t)type->record_decl);
        if (work == NULL)
            return identity_find(&binding->ctx->identities, type->record_decl)->layout_depth;
        if (work->layout_state == 2)
            return work->layout_depth;
        if (work->layout_state == 1)
            crust_fail(binding->ctx, type->record_decl->loc,
                       "by-value cycle in bound record facts");
        work->layout_state = 1;
        for (field = type->record_decl->fields; field != NULL; field = field->next) {
            unsigned field_height = 1 + bound_layout_path(binding, field->type, depth + 1);
            if (field_height > height)
                height = field_height;
        }
        work->layout_depth = height;
        work->layout_state = 2;
    }
    check_depth(binding->ctx, no_location(), height);
    return height;
}

static void finish_layout(CrustContext *ctx, CrustType *type, CrustLoc loc, unsigned depth)
{
    check_depth(ctx, loc, depth);
    if (type->kind == CRUST_T_RECORD && type->align == 0) {
        resolve_declaration(ctx, type->record_decl, depth);
    } else if (type->kind == CRUST_T_ARRAY && type->align == 0) {
        require_storage(ctx, type->base, loc, depth + 1);
        if (type->count > (uint64_t)INT64_MAX / type->base->size) {
            crust_fail(ctx, loc, "array layout exceeds the isize limit");
            return;
        }
        type->size = type->base->size * type->count;
        type->align = type->base->align;
    }
}

static unsigned storage_depth(CrustContext *ctx, CrustType *type)
{
    if (type->kind == CRUST_T_ARRAY)
        return 1 + storage_depth(ctx, type->base);
    if (type->kind == CRUST_T_RECORD)
        return identity_find(&ctx->identities, type->record_decl)->layout_depth;
    return 0;
}

static void finish_components(CrustContext *ctx, CrustType *type, CrustLoc loc, unsigned depth)
{
    size_t i;
    check_depth(ctx, loc, depth);
    switch (type->kind) {
    case CRUST_T_POINTER:
        finish_components(ctx, type->base, loc, depth + 1);
        break;
    case CRUST_T_ARRAY:
        finish_layout(ctx, type, loc, depth);
        finish_components(ctx, type->base, loc, depth + 1);
        break;
    case CRUST_T_FUNCTION:
        finish_components(ctx, type->base, loc, depth + 1);
        for (i = 0; i < type->param_count; ++i)
            finish_components(ctx, type->params[i], loc, depth + 1);
        break;
    case CRUST_T_RECORD:
        finish_layout(ctx, type, loc, depth);
        break;
    default:
        break;
    }
}

CrustType *crust_resolve_type(CrustContext *ctx, CrustTypeSyntax *syntax)
{
    CrustType *type = resolve_syntax(ctx, syntax, 0);
    finish_components(ctx, type, syntax->loc, 0);
    return type;
}

CrustType *crust_try_resolve_type(CrustContext *ctx, CrustTypeSyntax *syntax)
{
    CrustFailureFrame frame;
    CrustType *result;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return NULL;
    }
    result = crust_resolve_type(ctx, syntax);
    ctx->failure = frame.previous;
    return result;
}

static void resolve_record(CrustContext *ctx, CrustDecl *decl, unsigned depth)
{
    CrustField *field;
    CrustMap field_names = {NULL, 0, 0};
    uint64_t size;
    uint32_t align;
    size_t index;
    unsigned layout_depth = 0;
    if (decl->fields == NULL) {
        crust_fail(ctx, decl->loc, "records must have at least one field");
        return;
    }
    size = 0;
    align = 1;
    index = 0;
    for (field = decl->fields; field != NULL; field = field->next) {
        unsigned field_depth;
        if (crust_map_get(&field_names, (uintptr_t)field->name) != NULL) {
            crust_fail(ctx, field->loc, "duplicate field '%s'", field->name->text);
            return;
        }
        crust_map_set(ctx, &field_names, (uintptr_t)field->name, field);
        field->type = resolve_syntax(ctx, field->syntax_type, 0);
        require_storage(ctx, field->type, field->loc, depth + 1);
        field_depth = 1 + storage_depth(ctx, field->type);
        check_depth(ctx, field->loc, field_depth);
        if (field_depth > layout_depth)
            layout_depth = field_depth;
        size = align_size(ctx, size, field->type->align, field->loc);
        field->offset = size;
        field->index = index++;
        if (field->type->size > (uint64_t)INT64_MAX - size) {
            crust_fail(ctx, field->loc, "record layout exceeds the isize limit");
            return;
        }
        size += field->type->size;
        if (field->type->align > align)
            align = field->type->align;
    }
    decl->field_count = index;
    decl->type->size = align_size(ctx, size, align, decl->loc);
    decl->type->align = align;
    identity_find(&ctx->identities, decl)->fields = field_names;
    identity_find(&ctx->identities, decl)->layout_depth = layout_depth;
}

static void resolve_declaration(CrustContext *ctx, CrustDecl *decl, unsigned depth)
{
    CrustParam *param;
    CrustType *type;
    CrustMap field_names = {NULL, 0, 0};
    size_t index;
    check_depth(ctx, decl->loc, depth);
    if (decl->resolve_state == 2)
        return;
    if (decl->resolve_state == 1) {
        crust_fail(ctx, decl->loc, "by-value layout cycle involving '%s'", decl->name->text);
        return;
    }
    decl->resolve_state = 1;
    switch (decl->kind) {
    case CRUST_D_RECORD:
        resolve_record(ctx, decl, depth);
        break;
    case CRUST_D_FUNCTION:
    case CRUST_D_EXTERN:
        type = new_type(ctx, CRUST_T_FUNCTION);
        type->size = 8;
        type->align = 8;
        type->base = resolve_syntax(ctx, decl->syntax_type, 0);
        if (type->base->kind != CRUST_T_UNIT && !crust_type_scalar(type->base)) {
            crust_fail(ctx, decl->loc, "function results must be scalar or unit");
            return;
        }
        index = 0;
        for (param = decl->params; param != NULL; param = param->next)
            ++index;
        type->param_count = index;
        decl->param_count = index;
        type->params = crust_grow_array(ctx, NULL, 0, index, sizeof(*type->params),
                                        CRUST_ALIGNOF(CrustType *));
        index = 0;
        for (param = decl->params; param != NULL; param = param->next) {
            if (crust_map_get(&field_names, (uintptr_t)param->name) != NULL ||
                crust_map_get(&ctx->globals, (uintptr_t)param->name) != NULL)
                crust_fail(ctx, param->loc, "name '%s' is already visible", param->name->text);
            crust_map_set(ctx, &field_names, (uintptr_t)param->name, param);
            param->type = resolve_syntax(ctx, param->syntax_type, 0);
            require_scalar(ctx, param->type, param->loc);
            type->params[index++] = param->type;
        }
        decl->type = type;
        break;
    case CRUST_D_CONST:
        decl->type = resolve_syntax(ctx, decl->syntax_type, 0);
        require_storage(ctx, decl->type, decl->loc, depth + 1);
        break;
    }
    decl->symbol->type = decl->type;
    decl->resolve_state = 2;
}

static void collect_unit_impl(CrustContext *ctx, CrustUnit *unit)
{
    CrustDecl *decl;
    uint64_t ordinal = 0;
    for (decl = unit->declarations; decl != NULL; decl = decl->next) {
        CrustSymbol *old;
        Identity *entry;
        if (ordinal == UINT64_MAX)
            crust_fail(ctx, decl->loc, "too many declarations");
        ++ordinal;
        old = crust_map_get(&ctx->globals, (uintptr_t)decl->name);
        if (old != NULL) {
            if (old == decl->symbol && old->decl == decl)
                continue;
            crust_fail(ctx, decl->loc, "duplicate name '%s'", decl->name->text);
            return;
        }
        if (decl->identity == 0) {
            decl->unit_identity = unit->source->identity;
            decl->identity = ordinal;
        }
        entry = identity_find(&ctx->identities, decl);
        if (entry != NULL && entry->decl != decl)
            crust_fail(ctx, decl->loc, "distinct declarations share one identity");
        if (entry == NULL) {
            entry = crust_alloc(ctx, sizeof(*entry), CRUST_ALIGNOF(Identity));
            entry->decl = decl;
            identity_insert(ctx, &ctx->identities, entry);
        }
        decl->symbol = new_symbol(ctx, decl->name, declaration_kind(decl), decl->loc);
        decl->symbol->decl = decl;
        if (decl->kind == CRUST_D_RECORD) {
            decl->type = new_type(ctx, CRUST_T_RECORD);
            decl->type->record_decl = decl;
            decl->symbol->type = decl->type;
        }
        crust_map_set(ctx, &ctx->globals, (uintptr_t)decl->name, decl->symbol);
    }
}

bool crust_collect(CrustContext *ctx)
{
    CrustFailureFrame frame;
    CrustUnit *unit;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    for (unit = ctx->units; unit != NULL; unit = unit->next)
        collect_unit_impl(ctx, unit);
    ctx->failure = frame.previous;
    return true;
}

bool crust_collect_unit(CrustContext *ctx, CrustUnit *unit_value)
{
    CrustFailureFrame frame;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    collect_unit_impl(ctx, unit_value);
    ctx->failure = frame.previous;
    return true;
}

static void bind_constant_facts(Binding *binding, CrustDecl *decl)
{
    CrustContext *ctx = binding->ctx;
    Identity *entry;
    if (decl->type->kind == CRUST_T_UNIT || decl->link_name == NULL || decl->link_name[0] == '\0' ||
        decl->init == NULL || !decl->checked ||
        !crust_type_equal(ctx, decl->type, decl->init->type))
        crust_fail(ctx, decl->loc, "incomplete bound constant facts");
    entry = identity_find(&ctx->identities, decl);
    if (entry == NULL || entry->decl != decl)
        bind_constant_dependencies(binding, decl->init, 0);
    (void)binding_identity(binding, decl);
}

static void bind_declaration_facts(Binding *binding, CrustDecl *decl)
{
    CrustContext *ctx = binding->ctx;
    if (decl->kind == CRUST_D_FUNCTION || decl->kind == CRUST_D_EXTERN) {
        if (decl->type->kind != CRUST_T_FUNCTION)
            crust_fail(ctx, decl->loc, "invalid bound function signature");
        if (decl->link_name == NULL || decl->link_name[0] == '\0')
            crust_fail(ctx, decl->loc, "a bound function requires a link identity");
        (void)binding_identity(binding, decl);
    } else if (decl->kind == CRUST_D_RECORD) {
        if (decl->type->kind != CRUST_T_RECORD || decl->type->record_decl != decl)
            crust_fail(ctx, decl->loc, "incomplete bound record facts");
    } else if (decl->kind == CRUST_D_CONST) {
        bind_constant_facts(binding, decl);
    } else {
        crust_fail(ctx, decl->loc, "invalid bound declaration kind");
    }
}

static void reserve_binding_publication(Binding *binding)
{
    CrustContext *ctx = binding->ctx;
    Identity *entry;
    size_t count = ctx->identities.count;
    for (entry = binding->identities; entry != NULL; entry = entry->pending_next) {
        if (count == SIZE_MAX)
            crust_fail(ctx, entry->decl->loc, "too many declaration identities");
        ++count;
    }
    crust_map_reserve(ctx, &ctx->identities, count);
    crust_map_reserve(ctx, &ctx->globals, ctx->globals.count + 1);
}

bool crust_bind(CrustContext *ctx, CrustName *name, CrustDecl *decl)
{
    CrustFailureFrame frame;
    Binding binding;
    CrustSymbol *symbol;
    BindWork *work;
    Identity *entry;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    if (name == NULL || decl == NULL || decl->type == NULL || decl->identity == 0)
        crust_fail(ctx, no_location(), "a binding requires a resolved declaration and identity");
    name = crust_intern(ctx, (const unsigned char *)name->text, name->size);
    if (crust_map_get(&ctx->globals, (uintptr_t)name) != NULL)
        crust_fail(ctx, decl->loc, "duplicate name '%s'", name->text);
    memset(&binding, 0, sizeof(binding));
    binding.ctx = ctx;
    binding.tail = &binding.work;
    (void)check_bound_shape(&binding, decl->type, decl->loc, 0);
    bind_declaration_facts(&binding, decl);
    bind_type_records(&binding, decl->type);
    for (work = binding.work; work != NULL; work = work->next) {
        CrustField *field;
        for (field = work->decl->fields; field != NULL; field = field->next)
            bind_type_records(&binding, field->type);
    }
    for (work = binding.work; work != NULL; work = work->next)
        (void)bound_layout_path(&binding, work->decl->type, 0);
    symbol = new_symbol(ctx, name, declaration_kind(decl), decl->loc);
    symbol->type = decl->type;
    symbol->decl = decl;
    reserve_binding_publication(&binding);
    for (entry = binding.identities; entry != NULL; entry = entry->pending_next) {
        if (entry->decl->kind == CRUST_D_RECORD) {
            work = crust_map_get(&binding.visited, (uintptr_t)entry->decl);
            entry->layout_depth = work->layout_depth;
        }
        identity_insert(ctx, &ctx->identities, entry);
    }
    crust_map_set(ctx, &ctx->globals, (uintptr_t)name, symbol);
    ctx->failure = frame.previous;
    return true;
}

static void resolve_unit_declarations(CrustContext *ctx, CrustUnit *unit)
{
    CrustDecl *decl;
    for (decl = unit->declarations; decl != NULL; decl = decl->next) {
        if (decl->symbol == NULL)
            crust_fail(ctx, decl->loc, "declarations must be collected before resolution");
        resolve_declaration(ctx, decl, 0);
    }
}

static void finish_unit_types(CrustContext *ctx, CrustUnit *unit)
{
    CrustDecl *decl;
    CrustField *field;
    for (decl = unit->declarations; decl != NULL; decl = decl->next) {
        finish_components(ctx, decl->type, decl->loc, 0);
        for (field = decl->fields; field != NULL; field = field->next)
            finish_components(ctx, field->type, field->loc, 0);
    }
}

bool crust_resolve(CrustContext *ctx)
{
    CrustFailureFrame frame;
    CrustUnit *unit;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    for (unit = ctx->units; unit != NULL; unit = unit->next)
        resolve_unit_declarations(ctx, unit);
    for (unit = ctx->units; unit != NULL; unit = unit->next)
        finish_unit_types(ctx, unit);
    ctx->failure = frame.previous;
    return true;
}

bool crust_resolve_unit(CrustContext *ctx, CrustUnit *unit_value)
{
    CrustFailureFrame frame;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    resolve_unit_declarations(ctx, unit_value);
    finish_unit_types(ctx, unit_value);
    ctx->failure = frame.previous;
    return true;
}

static void same_type(Checker *checker, CrustType *expected, CrustType *actual, CrustLoc loc)
{
    if (!crust_type_equal(checker->ctx, expected, actual))
        crust_fail(checker->ctx, loc, "type mismatch");
}

static CrustField *find_field(Checker *checker, CrustType *type, CrustName *name, CrustLoc loc)
{
    CrustField *field;
    if (type->kind != CRUST_T_RECORD) {
        crust_fail(checker->ctx, loc, "field access requires a record value");
        return NULL;
    }
    field = crust_map_get(&identity_find(&checker->ctx->identities, type->record_decl)->fields,
                          (uintptr_t)name);
    if (field != NULL)
        return field;
    crust_fail(checker->ctx, loc, "record has no field '%s'", name->text);
    return NULL;
}

static CrustType *check_integer(Checker *checker, CrustExpr *expr, bool negated)
{
    CrustType *type;
    unsigned bits;
    uint64_t limit;
    if (expr->literal_type < CRUST_T_I8 || expr->literal_type > CRUST_T_USIZE) {
        crust_fail(checker->ctx, expr->loc, "invalid integer literal type");
        return NULL;
    }
    type = &checker->ctx->builtins[expr->literal_type];
    bits = crust_type_bits(type);
    if (crust_type_signed(type)) {
        limit = UINT64_C(1) << (bits - 1);
        if (!negated)
            --limit;
    } else {
        limit = UINT64_MAX >> (64 - bits);
    }
    if (expr->integer > limit)
        crust_fail(checker->ctx, expr->loc, "integer literal is outside its type's range");
    expr->type = type;
    return type;
}

static void check_constant_operation(CrustContext *ctx, CrustExpr *expr)
{
    switch (expr->kind) {
    case CRUST_E_NAME:
    case CRUST_E_INTEGER:
    case CRUST_E_BOOL:
    case CRUST_E_STRING:
    case CRUST_E_GROUP:
    case CRUST_E_RECORD:
    case CRUST_E_ARRAY:
    case CRUST_E_NULL:
    case CRUST_E_SIZEOF:
    case CRUST_E_ALIGNOF:
    case CRUST_E_OFFSETOF:
        break;
    case CRUST_E_UNARY:
        if (expr->op == CRUST_OP_NEG && expr->left->kind == CRUST_E_INTEGER)
            break;
        /* Fall through. */
    default:
        crust_fail(ctx, expr->loc, "operation is not permitted in a constant initializer");
    }
}

static CrustType *check_name(Checker *checker, CrustExpr *expr)
{
    CrustContext *ctx = checker->ctx;
    CrustSymbol *symbol;
    CrustType *type;
    symbol = crust_map_get(&checker->locals, (uintptr_t)expr->name);
    if (symbol == NULL)
        symbol = global_symbol(ctx, expr->name, expr->loc);
    if (symbol->kind == CRUST_SYM_RECORD) {
        crust_fail(ctx, expr->loc, "a record name is not a value");
        return NULL;
    }
    expr->symbol = symbol;
    if (checker->constant && symbol->kind != CRUST_SYM_FUNCTION)
        crust_fail(ctx, expr->loc, "only function names are permitted in constant initializers");
    type = symbol->type;
    expr->place = symbol->kind != CRUST_SYM_FUNCTION;
    expr->writable = symbol->kind == CRUST_SYM_LOCAL || symbol->kind == CRUST_SYM_PARAM;
    return type;
}

static CrustType *check_unary(Checker *checker, CrustExpr *expr)
{
    CrustContext *ctx = checker->ctx;
    CrustType *left;
    CrustType *type = NULL;
    if (expr->op == CRUST_OP_NEG && expr->left->kind == CRUST_E_INTEGER)
        left = check_integer(checker, expr->left, true);
    else
        left = check_expr(checker, expr->left);
    switch (expr->op) {
    case CRUST_OP_ADDRESS:
        if (!expr->left->place)
            crust_fail(ctx, expr->loc, "address-taking requires a place");
        type = crust_pointer_type(ctx, left);
        break;
    case CRUST_OP_DEREF:
        if (left->kind != CRUST_T_POINTER)
            crust_fail(ctx, expr->loc, "dereference requires a data pointer");
        type = left->base;
        expr->place = true;
        expr->writable = true;
        break;
    case CRUST_OP_NOT:
        if (left->kind != CRUST_T_BOOL)
            crust_fail(ctx, expr->loc, "logical not requires bool");
        type = left;
        break;
    case CRUST_OP_NEG:
    case CRUST_OP_BIT_NOT:
        if (!crust_type_integer(left))
            crust_fail(ctx, expr->loc, "integer unary operation requires an integer");
        type = left;
        break;
    default:
        crust_fail(ctx, expr->loc, "invalid unary operation");
        break;
    }
    return type;
}

static CrustType *check_binary(Checker *checker, CrustExpr *expr)
{
    CrustContext *ctx = checker->ctx;
    CrustType *left;
    CrustType *right;
    CrustType *type;
    left = check_expr(checker, expr->left);
    right = check_expr(checker, expr->right);
    if ((expr->op == CRUST_OP_ADD || expr->op == CRUST_OP_SUB) && left->kind == CRUST_T_POINTER) {
        if (right->kind != CRUST_T_ISIZE)
            crust_fail(ctx, expr->loc, "pointer offsets require isize");
        require_storage(ctx, left->base, expr->loc, 0);
        type = left;
        return type;
    }
    same_type(checker, left, right, expr->loc);
    if (expr->op == CRUST_OP_AND || expr->op == CRUST_OP_OR) {
        if (left->kind != CRUST_T_BOOL)
            crust_fail(ctx, expr->loc, "logical operations require bool");
        type = left;
    } else if (expr->op == CRUST_OP_EQ || expr->op == CRUST_OP_NE) {
        if (!crust_type_scalar(left))
            crust_fail(ctx, expr->loc, "equality requires matching scalar types");
        type = &ctx->builtins[CRUST_T_BOOL];
    } else {
        if (!crust_type_integer(left))
            crust_fail(ctx, expr->loc, "integer operation requires matching integer types");
        type = expr->op >= CRUST_OP_LT && expr->op <= CRUST_OP_GE ? &ctx->builtins[CRUST_T_BOOL]
                                                                  : left;
    }
    return type;
}

static CrustType *check_call(Checker *checker, CrustExpr *expr)
{
    CrustContext *ctx = checker->ctx;
    CrustType *left;
    CrustType *type;
    size_t i;
    left = check_expr(checker, expr->left);
    if (left->kind != CRUST_T_FUNCTION)
        crust_fail(ctx, expr->loc, "call requires a function value");
    if (expr->arg_count != left->param_count)
        crust_fail(ctx, expr->loc, "wrong number of call arguments");
    for (i = 0; i < expr->arg_count; ++i)
        same_type(checker, left->params[i], check_expr(checker, expr->args[i]), expr->args[i]->loc);
    type = left->base;
    return type;
}

static CrustType *check_index(Checker *checker, CrustExpr *expr)
{
    CrustContext *ctx = checker->ctx;
    CrustType *left;
    CrustType *right;
    CrustType *type;
    left = check_expr(checker, expr->left);
    right = check_expr(checker, expr->right);
    if (left->kind != CRUST_T_ARRAY && left->kind != CRUST_T_POINTER)
        crust_fail(ctx, expr->loc, "indexing requires an array or data pointer");
    if (right->kind != CRUST_T_USIZE)
        crust_fail(ctx, expr->right->loc, "indexing requires usize");
    type = left->base;
    expr->place = left->kind == CRUST_T_POINTER || expr->left->place;
    expr->writable = left->kind == CRUST_T_POINTER || expr->left->writable;
    return type;
}

static CrustType *check_record(Checker *checker, CrustExpr *expr)
{
    CrustContext *ctx = checker->ctx;
    CrustType *type;
    CrustInit *init;
    unsigned char *seen;
    size_t i;
    type = crust_resolve_type(ctx, expr->syntax_type);
    if (type->kind != CRUST_T_RECORD)
        crust_fail(ctx, expr->loc, "record construction requires a record type");
    seen = crust_alloc(ctx, type->record_decl->field_count, 1);
    i = 0;
    for (init = expr->inits; init != NULL; init = init->next) {
        init->field = find_field(checker, type, init->name, init->loc);
        if (seen[init->field->index] != 0)
            crust_fail(ctx, init->loc, "duplicate initializer for '%s'", init->name->text);
        seen[init->field->index] = 1;
        same_type(checker, init->field->type, check_expr(checker, init->value), init->value->loc);
        ++i;
    }
    if (i != type->record_decl->field_count)
        crust_fail(ctx, expr->loc, "record construction must initialize every field");
    return type;
}

static CrustType *check_array(Checker *checker, CrustExpr *expr)
{
    CrustContext *ctx = checker->ctx;
    CrustType *type;
    size_t i;
    type = crust_resolve_type(ctx, expr->syntax_type);
    if (type->kind != CRUST_T_ARRAY)
        crust_fail(ctx, expr->loc, "array construction requires an array type");
    if (type->count != expr->arg_count)
        crust_fail(ctx, expr->loc, "array construction must initialize every element");
    for (i = 0; i < expr->arg_count; ++i)
        same_type(checker, type->base, check_expr(checker, expr->args[i]), expr->args[i]->loc);
    return type;
}

static bool valid_cast(CrustContext *ctx, CrustType *left, CrustType *type)
{
    if (crust_type_integer(left) || left->kind == CRUST_T_BOOL)
        return crust_type_integer(type) || type->kind == CRUST_T_BOOL ||
               (left->kind == CRUST_T_USIZE && type->kind == CRUST_T_POINTER);
    if (left->kind == CRUST_T_POINTER)
        return type->kind == CRUST_T_POINTER || type->kind == CRUST_T_USIZE;
    return crust_type_scalar(left) && crust_type_equal(ctx, left, type);
}

static CrustType *check_typed_expr(Checker *checker, CrustExpr *expr)
{
    CrustContext *ctx = checker->ctx;
    CrustType *left;
    CrustType *type = NULL;
    switch (expr->kind) {
    case CRUST_E_CAST:
        left = check_expr(checker, expr->left);
        type = crust_resolve_type(ctx, expr->syntax_type);
        if (!valid_cast(ctx, left, type))
            crust_fail(ctx, expr->loc, "invalid cast");
        break;
    case CRUST_E_RECORD:
        return check_record(checker, expr);
    case CRUST_E_ARRAY:
        return check_array(checker, expr);
    case CRUST_E_NULL:
        type = crust_resolve_type(ctx, expr->syntax_type);
        if (type->kind != CRUST_T_POINTER && type->kind != CRUST_T_FUNCTION)
            crust_fail(ctx, expr->loc, "null requires a pointer or function type");
        break;
    case CRUST_E_SIZEOF:
    case CRUST_E_ALIGNOF:
        left = crust_resolve_type(ctx, expr->syntax_type);
        require_storage(ctx, left, expr->loc, 0);
        expr->integer = expr->kind == CRUST_E_SIZEOF ? left->size : left->align;
        type = &ctx->builtins[CRUST_T_USIZE];
        break;
    case CRUST_E_OFFSETOF:
        left = crust_resolve_type(ctx, expr->syntax_type);
        expr->field = find_field(checker, left, expr->field_name, expr->loc);
        expr->integer = expr->field->offset;
        type = &ctx->builtins[CRUST_T_USIZE];
        break;
    default:
        break;
    }
    return type;
}

static CrustType *check_expr(Checker *checker, CrustExpr *expr)
{
    CrustContext *ctx = checker->ctx;
    CrustType *left;
    CrustType *type = NULL;
    check_depth(ctx, expr->loc, checker->depth++);
    expr->place = false;
    expr->writable = false;
    if (checker->constant)
        check_constant_operation(ctx, expr);
    switch (expr->kind) {
    case CRUST_E_NAME:
        type = check_name(checker, expr);
        break;
    case CRUST_E_INTEGER:
        type = check_integer(checker, expr, false);
        break;
    case CRUST_E_BOOL:
        type = &ctx->builtins[CRUST_T_BOOL];
        break;
    case CRUST_E_STRING:
        type = crust_pointer_type(ctx, &ctx->builtins[CRUST_T_U8]);
        break;
    case CRUST_E_GROUP:
        type = check_expr(checker, expr->left);
        expr->place = expr->left->place;
        expr->writable = expr->left->writable;
        break;
    case CRUST_E_UNARY:
        type = check_unary(checker, expr);
        break;
    case CRUST_E_BINARY:
        type = check_binary(checker, expr);
        break;
    case CRUST_E_CALL:
        type = check_call(checker, expr);
        break;
    case CRUST_E_INDEX:
        type = check_index(checker, expr);
        break;
    case CRUST_E_FIELD:
        left = check_expr(checker, expr->left);
        expr->field = find_field(checker, left, expr->field_name, expr->loc);
        type = expr->field->type;
        expr->place = expr->left->place;
        expr->writable = expr->left->writable;
        break;
    default:
        type = check_typed_expr(checker, expr);
        break;
    }
    expr->type = type;
    --checker->depth;
    return type;
}

static CrustSymbol *add_local(Checker *checker, CrustName *name, CrustType *type,
                              CrustSymbolKind kind, CrustLoc loc)
{
    CrustSymbol *symbol;
    if (crust_map_get(&checker->locals, (uintptr_t)name) != NULL ||
        crust_map_get(&checker->ctx->globals, (uintptr_t)name) != NULL)
        crust_fail(checker->ctx, loc, "name '%s' is already visible", name->text);
    symbol = new_symbol(checker->ctx, name, kind, loc);
    symbol->type = type;
    symbol->scope_next = checker->scope;
    checker->scope = symbol;
    crust_map_set(checker->ctx, &checker->locals, (uintptr_t)name, symbol);
    return symbol;
}

static void pop_scope(Checker *checker, CrustSymbol *saved)
{
    while (checker->scope != saved) {
        CrustSymbol *symbol = checker->scope;
        crust_map_set(checker->ctx, &checker->locals, (uintptr_t)symbol->name, NULL);
        checker->scope = symbol->scope_next;
    }
}

static bool check_block(Checker *checker, CrustStmt *stmt)
{
    CrustStmt *child;
    CrustSymbol *saved;
    bool falls;
    bool branch;
    saved = checker->scope;
    falls = true;
    for (child = stmt->body; child != NULL; child = child->next) {
        branch = check_stmt(checker, child);
        if (falls)
            falls = branch;
    }
    pop_scope(checker, saved);
    return falls;
}

static bool check_return(Checker *checker, CrustStmt *stmt)
{
    CrustContext *ctx = checker->ctx;
    CrustType *type;
    type = checker->return_type;
    if (stmt->expr == NULL) {
        if (type->kind != CRUST_T_UNIT)
            crust_fail(ctx, stmt->loc, "return requires a value");
    } else {
        if (type->kind == CRUST_T_UNIT)
            crust_fail(ctx, stmt->loc, "unit function must use return without a value");
        same_type(checker, type, check_expr(checker, stmt->expr), stmt->expr->loc);
    }
    return false;
}

static bool check_assignment(Checker *checker, CrustStmt *stmt)
{
    CrustContext *ctx = checker->ctx;
    CrustType *type;
    type = check_expr(checker, stmt->expr);
    if (!stmt->expr->place || !stmt->expr->writable)
        crust_fail(ctx, stmt->expr->loc, "assignment requires a writable place");
    same_type(checker, type, check_expr(checker, stmt->value), stmt->value->loc);
    return true;
}

static bool check_if(Checker *checker, CrustStmt *stmt)
{
    CrustContext *ctx = checker->ctx;
    CrustType *type;
    bool falls;
    bool branch;
    type = check_expr(checker, stmt->expr);
    if (type->kind != CRUST_T_BOOL)
        crust_fail(ctx, stmt->expr->loc, "if condition must have type bool");
    falls = check_stmt(checker, stmt->body);
    branch = stmt->otherwise == NULL ? true : check_stmt(checker, stmt->otherwise);
    return falls || branch;
}

static bool check_stmt_impl(Checker *checker, CrustStmt *stmt)
{
    CrustContext *ctx = checker->ctx;
    CrustType *type;
    switch (stmt->kind) {
    case CRUST_S_BLOCK:
        return check_block(checker, stmt);
    case CRUST_S_VAR:
        type = crust_resolve_type(ctx, stmt->syntax_type);
        require_storage(ctx, type, stmt->loc, 0);
        if (!stmt->uninitialized)
            same_type(checker, type, check_expr(checker, stmt->value), stmt->loc);
        stmt->symbol = add_local(checker, stmt->name, type, CRUST_SYM_LOCAL, stmt->loc);
        return true;
    case CRUST_S_IF:
        return check_if(checker, stmt);
    case CRUST_S_WHILE:
        type = check_expr(checker, stmt->expr);
        if (type->kind != CRUST_T_BOOL)
            crust_fail(ctx, stmt->expr->loc, "while condition must have type bool");
        ++checker->loop_depth;
        (void)check_stmt(checker, stmt->body);
        --checker->loop_depth;
        return true;
    case CRUST_S_BREAK:
    case CRUST_S_CONTINUE:
        if (checker->loop_depth == 0)
            crust_fail(ctx, stmt->loc, "loop exit used outside a loop");
        return false;
    case CRUST_S_RETURN:
        return check_return(checker, stmt);
    case CRUST_S_TRAP:
        return false;
    case CRUST_S_EXPR:
        (void)check_expr(checker, stmt->expr);
        return true;
    case CRUST_S_ASSIGN:
        return check_assignment(checker, stmt);
    }
    crust_fail(ctx, stmt->loc, "invalid statement kind");
    return false;
}

static bool check_stmt(Checker *checker, CrustStmt *stmt)
{
    bool falls;
    check_depth(checker->ctx, stmt->loc, checker->depth++);
    falls = check_stmt_impl(checker, stmt);
    --checker->depth;
    return falls;
}

static void check_constant(CrustContext *ctx, CrustDecl *decl)
{
    Checker checker;
    memset(&checker, 0, sizeof(checker));
    checker.ctx = ctx;
    checker.constant = true;
    decl->checked = false;
    same_type(&checker, decl->type, check_expr(&checker, decl->init), decl->loc);
    decl->checked = true;
}

static void check_body_impl(CrustContext *ctx, CrustDecl *function)
{
    Checker checker;
    CrustParam *param;
    bool falls;
    if (function == NULL || function->kind != CRUST_D_FUNCTION || function->type == NULL ||
        function->resolve_state != 2)
        crust_fail(ctx, no_location(), "body checking requires a resolved function");
    memset(&checker, 0, sizeof(checker));
    checker.ctx = ctx;
    checker.return_type = function->type->base;
    function->checked = false;
    for (param = function->params; param != NULL; param = param->next)
        param->symbol = add_local(&checker, param->name, param->type, CRUST_SYM_PARAM, param->loc);
    falls = check_stmt(&checker, function->body);
    if (falls && function->type->base->kind != CRUST_T_UNIT)
        crust_fail(ctx, function->loc, "non-unit function can reach the end of its body");
    function->checked = true;
}

bool crust_check_body(CrustContext *ctx, CrustDecl *function)
{
    CrustFailureFrame frame;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    check_body_impl(ctx, function);
    ctx->failure = frame.previous;
    return true;
}

static void check_unit_impl(CrustContext *ctx, CrustUnit *unit)
{
    CrustDecl *decl;
    for (decl = unit->declarations; decl != NULL; decl = decl->next) {
        if (decl->kind == CRUST_D_CONST)
            check_constant(ctx, decl);
        if (decl->kind == CRUST_D_FUNCTION)
            check_body_impl(ctx, decl);
    }
}

bool crust_check(CrustContext *ctx)
{
    CrustFailureFrame frame;
    CrustUnit *unit;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    for (unit = ctx->units; unit != NULL; unit = unit->next)
        check_unit_impl(ctx, unit);
    ctx->failure = frame.previous;
    return true;
}

bool crust_check_unit(CrustContext *ctx, CrustUnit *unit_value)
{
    CrustFailureFrame frame;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    check_unit_impl(ctx, unit_value);
    ctx->failure = frame.previous;
    return true;
}

bool crust_check_root(CrustContext *ctx, CrustRootScope *scope, CrustStmt *statement)
{
    CrustFailureFrame frame;
    Checker checker;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    memset(&checker, 0, sizeof(checker));
    checker.ctx = ctx;
    checker.return_type = &ctx->builtins[CRUST_T_I32];
    checker.locals = scope->locals;
    checker.scope = scope->scope;
    (void)check_stmt(&checker, statement);
    scope->locals = checker.locals;
    scope->scope = checker.scope;
    ctx->failure = frame.previous;
    return true;
}
