#include "rmd0.h"

#include <limits.h>
#include <string.h>

#define CHECK_DEPTH_LIMIT 256u

typedef struct Identity Identity;
struct Identity {
    RmdDecl *decl;
    RmdMap fields;
    unsigned layout_depth;
    Identity *next;
    Identity *pending_next;
};

typedef struct BindWork BindWork;
struct BindWork {
    RmdDecl *decl;
    unsigned layout_state;
    unsigned layout_depth;
    BindWork *next;
};

typedef struct {
    RmdContext *ctx;
    RmdMap pending;
    RmdMap visited;
    Identity *identities;
    BindWork *work;
    BindWork **tail;
} Binding;

typedef struct {
    RmdContext *ctx;
    RmdType *return_type;
    RmdMap locals;
    RmdSymbol *scope;
    unsigned loop_depth;
    unsigned depth;
    bool constant;
} Checker;

static void resolve_declaration(RmdContext *ctx, RmdDecl *decl, unsigned depth);
static RmdType *resolve_syntax(RmdContext *ctx, RmdTypeSyntax *syntax, unsigned depth);
static void finish_layout(RmdContext *ctx, RmdType *type, RmdLoc loc, unsigned depth);
static RmdType *check_expr(Checker *checker, RmdExpr *expr);
static bool check_stmt(Checker *checker, RmdStmt *stmt);

static RmdLoc no_location(void)
{
    RmdLoc loc = { NULL, 0 };
    return loc;
}

static void check_depth(RmdContext *ctx, RmdLoc loc, unsigned depth)
{
    if (depth >= CHECK_DEPTH_LIMIT)
        rmd_fail(ctx, loc, "semantic nesting limit of %u exceeded", CHECK_DEPTH_LIMIT);
}

static bool same_name(const RmdName *a, const RmdName *b)
{
    return a == b || (a != NULL && b != NULL && a->size == b->size &&
                     memcmp(a->text, b->text, a->size) == 0);
}

static RmdType *new_type(RmdContext *ctx, RmdTypeKind kind)
{
    RmdType *type = rmd_alloc(ctx, sizeof(*type), RMD_ALIGNOF(RmdType));
    type->kind = kind;
    return type;
}

bool rmd_type_integer(const RmdType *type)
{
    return type != NULL && type->kind >= RMD_T_I8 &&
           type->kind <= RMD_T_USIZE;
}

bool rmd_type_signed(const RmdType *type)
{
    if (type == NULL)
        return false;
    switch (type->kind) {
    case RMD_T_I8:
    case RMD_T_I16:
    case RMD_T_I32:
    case RMD_T_I64:
    case RMD_T_ISIZE:
        return true;
    default:
        return false;
    }
}

bool rmd_type_scalar(const RmdType *type)
{
    return type != NULL &&
           (rmd_type_integer(type) || type->kind == RMD_T_BOOL ||
            type->kind == RMD_T_POINTER || type->kind == RMD_T_FUNCTION);
}

unsigned rmd_type_bits(const RmdType *type)
{
    if (type == NULL)
        return 0;
    switch (type->kind) {
    case RMD_T_I8:
    case RMD_T_U8:
    case RMD_T_BOOL:
        return 8;
    case RMD_T_I16:
    case RMD_T_U16:
        return 16;
    case RMD_T_I32:
    case RMD_T_U32:
        return 32;
    case RMD_T_I64:
    case RMD_T_U64:
    case RMD_T_ISIZE:
    case RMD_T_USIZE:
    case RMD_T_POINTER:
    case RMD_T_FUNCTION:
        return 64;
    default:
        return 0;
    }
}

bool rmd_type_equal(const RmdType *a, const RmdType *b)
{
    size_t i;
    if (a == b)
        return a != NULL;
    if (a == NULL || b == NULL || a->kind != b->kind)
        return false;
    switch (a->kind) {
    case RMD_T_POINTER:
        return rmd_type_equal(a->base, b->base);
    case RMD_T_ARRAY:
        return a->count == b->count && rmd_type_equal(a->base, b->base);
    case RMD_T_FUNCTION:
        if (a->param_count != b->param_count ||
            !rmd_type_equal(a->base, b->base))
            return false;
        for (i = 0; i < a->param_count; ++i) {
            if (!rmd_type_equal(a->params[i], b->params[i]))
                return false;
        }
        return true;
    case RMD_T_RECORD:
        if (a->record_decl == NULL || b->record_decl == NULL)
            return false;
        return a->record_decl == b->record_decl ||
               (a->record_decl->identity != 0 && b->record_decl->identity != 0 &&
                a->record_decl->identity == b->record_decl->identity &&
                a->record_decl->unit_identity == b->record_decl->unit_identity);
    case RMD_T_NAME:
        return false;
    default:
        return true;
    }
}

static uintptr_t identity_key(const RmdDecl *decl)
{
    uint64_t hash = decl->identity ^
        (decl->unit_identity + UINT64_C(0x9e3779b97f4a7c15) +
         (decl->identity << 6) + (decl->identity >> 2));
    uintptr_t key = (uintptr_t)hash;
    return key == 0 ? 1 : key;
}

static Identity *identity_find(const RmdMap *map, const RmdDecl *decl)
{
    Identity *entry;
    for (entry = rmd_map_get(map, identity_key(decl)); entry != NULL;
         entry = entry->next) {
        if (entry->decl->identity == decl->identity &&
            entry->decl->unit_identity == decl->unit_identity)
            return entry;
    }
    return NULL;
}

static void identity_insert(RmdContext *ctx, RmdMap *map, Identity *entry)
{
    uintptr_t key = identity_key(entry->decl);
    entry->next = rmd_map_get(map, key);
    rmd_map_set(ctx, map, key, entry);
}

static RmdExpr *ungroup(RmdContext *ctx, RmdExpr *expr, unsigned depth)
{
    while (expr->kind == RMD_E_GROUP) {
        check_depth(ctx, expr->loc, depth++);
        expr = expr->left;
    }
    return expr;
}

static bool constant_bits(RmdExpr *expr, uint64_t *bits)
{
    unsigned width;
    switch (expr->kind) {
    case RMD_E_INTEGER:
    case RMD_E_BOOL:
    case RMD_E_SIZEOF:
    case RMD_E_ALIGNOF:
    case RMD_E_OFFSETOF:
        *bits = expr->integer;
        return true;
    case RMD_E_UNARY:
        if (expr->op != RMD_OP_NEG || expr->left->kind != RMD_E_INTEGER)
            return false;
        width = rmd_type_bits(expr->type);
        *bits = (UINT64_C(0) - expr->left->integer) & (UINT64_MAX >> (64 - width));
        return true;
    case RMD_E_NULL:
        *bits = 0;
        return true;
    default:
        return false;
    }
}

static bool constant_equal(RmdContext *ctx, RmdExpr *a, RmdExpr *b, unsigned depth)
{
    uint64_t left;
    uint64_t right;
    RmdInit **fields;
    RmdInit *init;
    size_t i;
    if (a == b)
        return a != NULL;
    if (a == NULL || b == NULL)
        return false;
    check_depth(ctx, a->loc, depth);
    a = ungroup(ctx, a, depth);
    b = ungroup(ctx, b, depth);
    if (!rmd_type_equal(a->type, b->type))
        return false;
    if (constant_bits(a, &left) && constant_bits(b, &right))
        return left == right;
    if (a->kind != b->kind)
        return false;
    switch (a->kind) {
    case RMD_E_STRING:
        return a->byte_count == b->byte_count &&
               memcmp(a->bytes, b->bytes, a->byte_count) == 0;
    case RMD_E_NAME:
        return a->symbol != NULL && b->symbol != NULL &&
               a->symbol->decl->unit_identity == b->symbol->decl->unit_identity &&
               a->symbol->decl->identity == b->symbol->decl->identity &&
               a->symbol->decl->link_name != NULL && b->symbol->decl->link_name != NULL &&
               strcmp(a->symbol->decl->link_name, b->symbol->decl->link_name) == 0;
    case RMD_E_ARRAY:
        if (a->arg_count != b->arg_count)
            return false;
        for (i = 0; i < a->arg_count; ++i) {
            if (!constant_equal(ctx, a->args[i], b->args[i], depth + 1))
                return false;
        }
        return true;
    case RMD_E_RECORD:
        fields = rmd_grow_array(ctx, NULL, 0, a->type->record_decl->field_count,
                                sizeof(*fields), RMD_ALIGNOF(RmdInit *));
        for (init = a->inits; init != NULL; init = init->next)
            fields[init->field->index] = init;
        for (init = b->inits; init != NULL; init = init->next) {
            RmdInit *other = fields[init->field->index];
            if (other == NULL || !constant_equal(ctx, other->value, init->value, depth + 1))
                return false;
        }
        return true;
    default:
        return false;
    }
}

static bool same_declaration_facts(RmdContext *ctx, RmdDecl *a, RmdDecl *b)
{
    RmdField *left;
    RmdField *right;
    bool a_function = a->kind == RMD_D_FUNCTION || a->kind == RMD_D_EXTERN;
    bool b_function = b->kind == RMD_D_FUNCTION || b->kind == RMD_D_EXTERN;
    if (a == b)
        return true;
    if ((!a_function || !b_function) && a->kind != b->kind)
        return false;
    if (!rmd_type_equal(a->type, b->type))
        return false;
    if (a->kind == RMD_D_RECORD) {
        if (a->type->size != b->type->size || a->type->align != b->type->align ||
            a->field_count != b->field_count)
            return false;
        left = a->fields;
        right = b->fields;
        while (left != NULL && right != NULL) {
            if (!same_name(left->name, right->name) || left->offset != right->offset ||
                !rmd_type_equal(left->type, right->type))
                return false;
            left = left->next;
            right = right->next;
        }
        return left == NULL && right == NULL;
    }
    if (a->link_name == NULL || b->link_name == NULL ||
        strcmp(a->link_name, b->link_name) != 0)
        return false;
    return a_function || constant_equal(ctx, a->init, b->init, 0);
}

static Identity *binding_identity(Binding *binding, RmdDecl *decl)
{
    RmdContext *ctx = binding->ctx;
    Identity *entry = identity_find(&ctx->identities, decl);
    if (entry == NULL)
        entry = identity_find(&binding->pending, decl);
    if (entry != NULL) {
        if (!same_declaration_facts(ctx, entry->decl, decl))
            rmd_fail(ctx, decl->loc, "conflicting facts for declaration identity");
        return entry;
    }
    entry = rmd_alloc(ctx, sizeof(*entry), RMD_ALIGNOF(Identity));
    entry->decl = decl;
    entry->pending_next = binding->identities;
    binding->identities = entry;
    identity_insert(ctx, &binding->pending, entry);
    return entry;
}

RmdType *rmd_pointer_type(RmdContext *ctx, RmdType *base)
{
    RmdType *type;
    if (base == NULL || base->kind == RMD_T_UNIT) {
        rmd_fail(ctx, no_location(), "a pointer requires a storage type");
        return NULL;
    }
    type = new_type(ctx, RMD_T_POINTER);
    type->size = 8;
    type->align = 8;
    type->base = base;
    return type;
}

RmdType *rmd_try_pointer_type(RmdContext *ctx, RmdType *base)
{
    RmdFailureFrame frame;
    RmdType *result;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return NULL;
    }
    result = rmd_pointer_type(ctx, base);
    ctx->failure = frame.previous;
    return result;
}

static RmdSymbol *global_symbol(RmdContext *ctx, RmdName *name, RmdLoc loc)
{
    RmdSymbol *symbol = rmd_map_get(&ctx->globals, (uintptr_t)name);
    if (symbol == NULL)
        rmd_fail(ctx, loc, "unknown name '%s'", name->text);
    return symbol;
}

static RmdSymbolKind declaration_kind(RmdDecl *decl)
{
    switch (decl->kind) {
    case RMD_D_RECORD:
        return RMD_SYM_RECORD;
    case RMD_D_FUNCTION:
    case RMD_D_EXTERN:
        return RMD_SYM_FUNCTION;
    case RMD_D_CONST:
        return RMD_SYM_CONST;
    }
    return RMD_SYM_RECORD;
}

static RmdSymbol *new_symbol(RmdContext *ctx, RmdName *name,
                             RmdSymbolKind kind, RmdLoc loc)
{
    RmdSymbol *symbol = rmd_alloc(ctx, sizeof(*symbol), RMD_ALIGNOF(RmdSymbol));
    symbol->name = name;
    symbol->kind = kind;
    symbol->loc = loc;
    return symbol;
}

static void require_storage(RmdContext *ctx, RmdType *type, RmdLoc loc, unsigned depth)
{
    if (type == NULL || type->kind == RMD_T_UNIT) {
        rmd_fail(ctx, loc, "unit is not a storage type");
        return;
    }
    finish_layout(ctx, type, loc, depth);
}

static void require_scalar(RmdContext *ctx, RmdType *type, RmdLoc loc)
{
    if (!rmd_type_scalar(type))
        rmd_fail(ctx, loc, "function arguments must have scalar types");
}

static RmdType *resolve_syntax(RmdContext *ctx, RmdTypeSyntax *syntax, unsigned depth)
{
    RmdType *type;
    RmdSymbol *symbol;
    size_t i;
    if (syntax == NULL) {
        rmd_fail(ctx, no_location(), "missing type description");
        return NULL;
    }
    check_depth(ctx, syntax->loc, depth);
    if (syntax->kind >= RMD_T_I8 && syntax->kind <= RMD_T_UNIT)
        return &ctx->builtins[syntax->kind];
    switch (syntax->kind) {
    case RMD_T_NAME:
        symbol = global_symbol(ctx, syntax->name, syntax->loc);
        if (symbol->kind != RMD_SYM_RECORD) {
            rmd_fail(ctx, syntax->loc, "'%s' is not a record type",
                     syntax->name->text);
            return NULL;
        }
        return symbol->type;
    case RMD_T_POINTER:
        type = resolve_syntax(ctx, syntax->base, depth + 1);
        if (type->kind == RMD_T_UNIT) {
            rmd_fail(ctx, syntax->loc, "unit is not a pointer target");
            return NULL;
        }
        return rmd_pointer_type(ctx, type);
    case RMD_T_ARRAY:
        if (syntax->count == 0) {
            rmd_fail(ctx, syntax->loc, "array count must be positive");
            return NULL;
        }
        type = new_type(ctx, RMD_T_ARRAY);
        type->base = resolve_syntax(ctx, syntax->base, depth + 1);
        if (type->base->kind == RMD_T_UNIT) {
            rmd_fail(ctx, syntax->loc, "unit is not an array element type");
            return NULL;
        }
        type->count = syntax->count;
        return type;
    case RMD_T_FUNCTION:
        type = new_type(ctx, RMD_T_FUNCTION);
        type->size = 8;
        type->align = 8;
        type->base = resolve_syntax(ctx, syntax->base, depth + 1);
        if (type->base->kind != RMD_T_UNIT && !rmd_type_scalar(type->base)) {
            rmd_fail(ctx, syntax->loc, "function results must be scalar or unit");
            return NULL;
        }
        type->param_count = syntax->param_count;
        type->params = rmd_grow_array(ctx, NULL, 0, syntax->param_count,
                                      sizeof(*type->params),
                                      RMD_ALIGNOF(RmdType *));
        for (i = 0; i < syntax->param_count; ++i) {
            type->params[i] = resolve_syntax(ctx, syntax->params[i], depth + 1);
            require_scalar(ctx, type->params[i], syntax->params[i]->loc);
        }
        return type;
    default:
        rmd_fail(ctx, syntax->loc, "invalid type syntax");
        return NULL;
    }
}

static uint64_t align_size(RmdContext *ctx, uint64_t size, uint32_t align,
                           RmdLoc loc)
{
    uint64_t remainder = size % align;
    uint64_t padding = remainder == 0 ? 0 : align - remainder;
    if (size > (uint64_t)INT64_MAX - padding) {
        rmd_fail(ctx, loc, "type layout exceeds the isize limit");
        return 0;
    }
    return size + padding;
}

static void check_bound_shape(RmdContext *ctx, RmdType *type, RmdLoc loc, unsigned depth)
{
    size_t i;
    check_depth(ctx, loc, depth);
    if (type == NULL)
        rmd_fail(ctx, loc, "incomplete bound type facts");
    if (type->kind >= RMD_T_I8 && type->kind <= RMD_T_UNIT) {
        if (type->size != ctx->builtins[type->kind].size ||
            type->align != ctx->builtins[type->kind].align)
            rmd_fail(ctx, loc, "bound scalar layout does not match the target profile");
        return;
    }
    if (type->size == 0 || type->size > (uint64_t)INT64_MAX ||
        type->align == 0 || type->align > 8 ||
        (type->align & (type->align - 1)) != 0)
        rmd_fail(ctx, loc, "incomplete bound storage layout");
    switch (type->kind) {
    case RMD_T_POINTER:
        check_bound_shape(ctx, type->base, loc, depth + 1);
        if (type->base->kind == RMD_T_UNIT || type->size != 8 || type->align != 8)
            rmd_fail(ctx, loc, "invalid bound pointer type");
        break;
    case RMD_T_ARRAY:
        check_bound_shape(ctx, type->base, loc, depth + 1);
        if (type->base->kind == RMD_T_UNIT || type->count == 0 ||
            type->count > (uint64_t)INT64_MAX / type->base->size ||
            type->size != type->count * type->base->size ||
            type->align != type->base->align)
            rmd_fail(ctx, loc, "invalid bound array layout");
        break;
    case RMD_T_FUNCTION:
        check_bound_shape(ctx, type->base, loc, depth + 1);
        if ((type->base->kind != RMD_T_UNIT && !rmd_type_scalar(type->base)) ||
            type->size != 8 || type->align != 8 ||
            (type->param_count != 0 && type->params == NULL))
            rmd_fail(ctx, loc, "invalid bound function signature");
        for (i = 0; i < type->param_count; ++i) {
            check_bound_shape(ctx, type->params[i], loc, depth + 1);
            require_scalar(ctx, type->params[i], loc);
        }
        break;
    case RMD_T_RECORD:
        if (type->record_decl == NULL || type->record_decl->kind != RMD_D_RECORD ||
            type->record_decl->type != type || type->record_decl->identity == 0)
            rmd_fail(ctx, loc, "incomplete bound record identity");
        break;
    default:
        rmd_fail(ctx, loc, "invalid bound type kind");
    }
}

static void queue_bound_record(Binding *binding, RmdDecl *decl)
{
    RmdContext *ctx = binding->ctx;
    RmdMap fields = { NULL, 0, 0 };
    RmdField *field;
    BindWork *work;
    Identity *entry = identity_find(&ctx->identities, decl);
    uint64_t size = 0;
    uint32_t align = 1;
    size_t index = 0;
    if ((entry != NULL && entry->decl == decl) ||
        rmd_map_get(&binding->visited, (uintptr_t)decl) != NULL)
        return;
    for (field = decl->fields; field != NULL; field = field->next) {
        RmdName *name;
        if (field->name == NULL)
            rmd_fail(ctx, field->loc, "incomplete bound field name");
        name = rmd_intern(ctx, (const unsigned char *)field->name->text, field->name->size);
        if (rmd_map_get(&fields, (uintptr_t)name) != NULL)
            rmd_fail(ctx, field->loc, "duplicate bound field '%s'", name->text);
        rmd_map_set(ctx, &fields, (uintptr_t)name, field);
        check_bound_shape(ctx, field->type, field->loc, 0);
        if (field->type->kind == RMD_T_UNIT)
            rmd_fail(ctx, field->loc, "unit is not a bound field type");
        size = align_size(ctx, size, field->type->align, field->loc);
        if (field->offset != size || field->index != index++)
            rmd_fail(ctx, field->loc, "inconsistent bound field layout");
        if (field->type->size > (uint64_t)INT64_MAX - size)
            rmd_fail(ctx, field->loc, "bound record layout exceeds the isize limit");
        size += field->type->size;
        if (field->type->align > align)
            align = field->type->align;
    }
    if (index == 0 || index != decl->field_count || decl->type->align != align ||
        decl->type->size != align_size(ctx, size, align, decl->loc))
        rmd_fail(ctx, decl->loc, "incomplete or inconsistent bound record facts");
    entry = binding_identity(binding, decl);
    if (entry->fields.capacity == 0)
        entry->fields = fields;
    work = rmd_alloc(ctx, sizeof(*work), RMD_ALIGNOF(BindWork));
    work->decl = decl;
    rmd_map_set(ctx, &binding->visited, (uintptr_t)decl, work);
    *binding->tail = work;
    binding->tail = &work->next;
}

static void bind_type_records(Binding *binding, RmdType *type, unsigned depth)
{
    size_t i;
    check_depth(binding->ctx, no_location(), depth);
    switch (type->kind) {
    case RMD_T_POINTER:
    case RMD_T_ARRAY:
        bind_type_records(binding, type->base, depth + 1);
        break;
    case RMD_T_FUNCTION:
        bind_type_records(binding, type->base, depth + 1);
        for (i = 0; i < type->param_count; ++i)
            bind_type_records(binding, type->params[i], depth + 1);
        break;
    case RMD_T_RECORD:
        queue_bound_record(binding, type->record_decl);
        break;
    default:
        break;
    }
}

static void bind_constant_dependencies(Binding *binding, RmdExpr *expr, unsigned depth)
{
    RmdContext *ctx = binding->ctx;
    RmdDecl *function;
    RmdInit *init;
    size_t i;
    check_depth(ctx, expr->loc, depth);
    switch (expr->kind) {
    case RMD_E_NAME:
        if (expr->symbol == NULL || expr->symbol->kind != RMD_SYM_FUNCTION ||
            expr->symbol->decl == NULL)
            rmd_fail(ctx, expr->loc, "incomplete bound constant function reference");
        function = expr->symbol->decl;
        check_bound_shape(ctx, function->type, function->loc, 0);
        if ((function->kind != RMD_D_FUNCTION && function->kind != RMD_D_EXTERN) ||
            function->identity == 0 || function->type->kind != RMD_T_FUNCTION ||
            function->link_name == NULL || function->link_name[0] == '\0' ||
            !rmd_type_equal(function->type, expr->type))
            rmd_fail(ctx, expr->loc, "incomplete bound constant function facts");
        (void)binding_identity(binding, function);
        bind_type_records(binding, function->type, 0);
        break;
    case RMD_E_GROUP:
        bind_constant_dependencies(binding, expr->left, depth + 1);
        break;
    case RMD_E_UNARY:
        if (expr->op != RMD_OP_NEG || expr->left->kind != RMD_E_INTEGER)
            rmd_fail(ctx, expr->loc, "invalid bound constant operation");
        break;
    case RMD_E_RECORD:
        for (init = expr->inits; init != NULL; init = init->next)
            bind_constant_dependencies(binding, init->value, depth + 1);
        break;
    case RMD_E_ARRAY:
        for (i = 0; i < expr->arg_count; ++i)
            bind_constant_dependencies(binding, expr->args[i], depth + 1);
        break;
    case RMD_E_INTEGER:
    case RMD_E_BOOL:
    case RMD_E_STRING:
    case RMD_E_NULL:
    case RMD_E_SIZEOF:
    case RMD_E_ALIGNOF:
    case RMD_E_OFFSETOF:
        break;
    default:
        rmd_fail(ctx, expr->loc, "invalid bound constant initializer");
    }
}

static unsigned bound_layout_path(Binding *binding, RmdType *type, unsigned depth)
{
    BindWork *work;
    RmdField *field;
    unsigned height = 0;
    check_depth(binding->ctx, no_location(), depth);
    if (type->kind == RMD_T_ARRAY) {
        height = 1 + bound_layout_path(binding, type->base, depth + 1);
    } else if (type->kind == RMD_T_RECORD) {
        work = rmd_map_get(&binding->visited, (uintptr_t)type->record_decl);
        if (work == NULL)
            return identity_find(&binding->ctx->identities, type->record_decl)->layout_depth;
        if (work->layout_state == 2)
            return work->layout_depth;
        if (work->layout_state == 1)
            rmd_fail(binding->ctx, type->record_decl->loc, "by-value cycle in bound record facts");
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

static void finish_layout(RmdContext *ctx, RmdType *type, RmdLoc loc, unsigned depth)
{
    check_depth(ctx, loc, depth);
    if (type->kind == RMD_T_RECORD && type->align == 0) {
        resolve_declaration(ctx, type->record_decl, depth);
    } else if (type->kind == RMD_T_ARRAY && type->align == 0) {
        require_storage(ctx, type->base, loc, depth + 1);
        if (type->count > (uint64_t)INT64_MAX / type->base->size) {
            rmd_fail(ctx, loc, "array layout exceeds the isize limit");
            return;
        }
        type->size = type->base->size * type->count;
        type->align = type->base->align;
    }
}

static unsigned storage_depth(RmdContext *ctx, RmdType *type)
{
    if (type->kind == RMD_T_ARRAY)
        return 1 + storage_depth(ctx, type->base);
    if (type->kind == RMD_T_RECORD)
        return identity_find(&ctx->identities, type->record_decl)->layout_depth;
    return 0;
}

static void finish_components(RmdContext *ctx, RmdType *type, RmdLoc loc, unsigned depth)
{
    size_t i;
    check_depth(ctx, loc, depth);
    switch (type->kind) {
    case RMD_T_POINTER:
        finish_components(ctx, type->base, loc, depth + 1);
        break;
    case RMD_T_ARRAY:
        finish_layout(ctx, type, loc, depth);
        finish_components(ctx, type->base, loc, depth + 1);
        break;
    case RMD_T_FUNCTION:
        finish_components(ctx, type->base, loc, depth + 1);
        for (i = 0; i < type->param_count; ++i)
            finish_components(ctx, type->params[i], loc, depth + 1);
        break;
    case RMD_T_RECORD:
        finish_layout(ctx, type, loc, depth);
        break;
    default:
        break;
    }
}

RmdType *rmd_resolve_type(RmdContext *ctx, RmdTypeSyntax *syntax)
{
    RmdType *type = resolve_syntax(ctx, syntax, 0);
    finish_components(ctx, type, syntax->loc, 0);
    return type;
}

RmdType *rmd_try_resolve_type(RmdContext *ctx, RmdTypeSyntax *syntax)
{
    RmdFailureFrame frame;
    RmdType *result;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return NULL;
    }
    result = rmd_resolve_type(ctx, syntax);
    ctx->failure = frame.previous;
    return result;
}

static void resolve_declaration(RmdContext *ctx, RmdDecl *decl, unsigned depth)
{
    RmdField *field;
    RmdParam *param;
    RmdType *type;
    RmdMap field_names = { NULL, 0, 0 };
    uint64_t size;
    uint32_t align;
    size_t index;
    unsigned layout_depth = 0;
    check_depth(ctx, decl->loc, depth);
    if (decl->resolve_state == 2)
        return;
    if (decl->resolve_state == 1) {
        rmd_fail(ctx, decl->loc, "by-value layout cycle involving '%s'",
                 decl->name->text);
        return;
    }
    decl->resolve_state = 1;
    switch (decl->kind) {
    case RMD_D_RECORD:
        if (decl->fields == NULL) {
            rmd_fail(ctx, decl->loc, "records must have at least one field");
            return;
        }
        size = 0;
        align = 1;
        index = 0;
        for (field = decl->fields; field != NULL; field = field->next) {
            unsigned field_depth;
            if (rmd_map_get(&field_names, (uintptr_t)field->name) != NULL) {
                rmd_fail(ctx, field->loc, "duplicate field '%s'", field->name->text);
                return;
            }
            rmd_map_set(ctx, &field_names, (uintptr_t)field->name, field);
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
                rmd_fail(ctx, field->loc, "record layout exceeds the isize limit");
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
        break;
    case RMD_D_FUNCTION:
    case RMD_D_EXTERN:
        type = new_type(ctx, RMD_T_FUNCTION);
        type->size = 8;
        type->align = 8;
        type->base = resolve_syntax(ctx, decl->syntax_type, 0);
        if (type->base->kind != RMD_T_UNIT && !rmd_type_scalar(type->base)) {
            rmd_fail(ctx, decl->loc, "function results must be scalar or unit");
            return;
        }
        index = 0;
        for (param = decl->params; param != NULL; param = param->next)
            ++index;
        type->param_count = index;
        decl->param_count = index;
        type->params = rmd_grow_array(ctx, NULL, 0, index, sizeof(*type->params),
                                      RMD_ALIGNOF(RmdType *));
        index = 0;
        for (param = decl->params; param != NULL; param = param->next) {
            if (rmd_map_get(&field_names, (uintptr_t)param->name) != NULL ||
                rmd_map_get(&ctx->globals, (uintptr_t)param->name) != NULL)
                rmd_fail(ctx, param->loc, "name '%s' is already visible", param->name->text);
            rmd_map_set(ctx, &field_names, (uintptr_t)param->name, param);
            param->type = resolve_syntax(ctx, param->syntax_type, 0);
            require_scalar(ctx, param->type, param->loc);
            type->params[index++] = param->type;
        }
        decl->type = type;
        break;
    case RMD_D_CONST:
        decl->type = resolve_syntax(ctx, decl->syntax_type, 0);
        require_storage(ctx, decl->type, decl->loc, depth + 1);
        break;
    }
    decl->symbol->type = decl->type;
    decl->resolve_state = 2;
}

static void collect_unit_impl(RmdContext *ctx, RmdUnit *unit)
{
    RmdDecl *decl;
    uint64_t ordinal = 0;
    for (decl = unit->declarations; decl != NULL; decl = decl->next) {
        RmdSymbol *old;
        Identity *entry;
        if (ordinal == UINT64_MAX)
            rmd_fail(ctx, decl->loc, "too many declarations");
        ++ordinal;
        old = rmd_map_get(&ctx->globals, (uintptr_t)decl->name);
        if (old != NULL) {
            if (old == decl->symbol && old->decl == decl)
                continue;
            rmd_fail(ctx, decl->loc, "duplicate name '%s'", decl->name->text);
            return;
        }
        if (decl->identity == 0) {
            decl->unit_identity = unit->source->identity;
            decl->identity = ordinal;
        }
        entry = identity_find(&ctx->identities, decl);
        if (entry != NULL && entry->decl != decl)
            rmd_fail(ctx, decl->loc, "distinct declarations share one identity");
        if (entry == NULL) {
            entry = rmd_alloc(ctx, sizeof(*entry), RMD_ALIGNOF(Identity));
            entry->decl = decl;
            identity_insert(ctx, &ctx->identities, entry);
        }
        decl->symbol = new_symbol(ctx, decl->name, declaration_kind(decl),
                                  decl->loc);
        decl->symbol->decl = decl;
        if (decl->kind == RMD_D_RECORD) {
            decl->type = new_type(ctx, RMD_T_RECORD);
            decl->type->record_decl = decl;
            decl->symbol->type = decl->type;
        }
        rmd_map_set(ctx, &ctx->globals, (uintptr_t)decl->name, decl->symbol);
    }
}

bool rmd_collect(RmdContext *ctx)
{
    RmdFailureFrame frame;
    RmdUnit *unit;
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

bool rmd_collect_unit(RmdContext *ctx, RmdUnit *unit_value)
{
    RmdFailureFrame frame;
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

bool rmd_bind(RmdContext *ctx, RmdName *name, RmdDecl *decl)
{
    RmdFailureFrame frame;
    Binding binding;
    RmdSymbol *symbol;
    BindWork *work;
    Identity *entry;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    if (name == NULL || decl == NULL || decl->type == NULL || decl->identity == 0)
        rmd_fail(ctx, no_location(), "a binding requires a resolved declaration and identity");
    name = rmd_intern(ctx, (const unsigned char *)name->text, name->size);
    if (rmd_map_get(&ctx->globals, (uintptr_t)name) != NULL)
        rmd_fail(ctx, decl->loc, "duplicate name '%s'", name->text);
    memset(&binding, 0, sizeof(binding));
    binding.ctx = ctx;
    binding.tail = &binding.work;
    check_bound_shape(ctx, decl->type, decl->loc, 0);
    if (decl->kind == RMD_D_FUNCTION || decl->kind == RMD_D_EXTERN) {
        if (decl->type->kind != RMD_T_FUNCTION)
            rmd_fail(ctx, decl->loc, "invalid bound function signature");
        if (decl->link_name == NULL || decl->link_name[0] == '\0')
            rmd_fail(ctx, decl->loc, "a bound function requires a link identity");
        (void)binding_identity(&binding, decl);
    } else if (decl->kind == RMD_D_RECORD) {
        if (decl->type->kind != RMD_T_RECORD || decl->type->record_decl != decl)
            rmd_fail(ctx, decl->loc, "incomplete bound record facts");
    } else if (decl->kind == RMD_D_CONST) {
        if (decl->type->kind == RMD_T_UNIT || decl->link_name == NULL ||
            decl->link_name[0] == '\0' || decl->init == NULL || !decl->checked ||
            !rmd_type_equal(decl->type, decl->init->type))
            rmd_fail(ctx, decl->loc, "incomplete bound constant facts");
        entry = identity_find(&ctx->identities, decl);
        if (entry == NULL || entry->decl != decl)
            bind_constant_dependencies(&binding, decl->init, 0);
        (void)binding_identity(&binding, decl);
    } else {
        rmd_fail(ctx, decl->loc, "invalid bound declaration kind");
    }
    bind_type_records(&binding, decl->type, 0);
    for (work = binding.work; work != NULL; work = work->next) {
        RmdField *field;
        for (field = work->decl->fields; field != NULL; field = field->next)
            bind_type_records(&binding, field->type, 0);
    }
    for (work = binding.work; work != NULL; work = work->next)
        (void)bound_layout_path(&binding, work->decl->type, 0);
    symbol = new_symbol(ctx, name, declaration_kind(decl), decl->loc);
    symbol->type = decl->type;
    symbol->decl = decl;
    for (entry = binding.identities; entry != NULL; entry = entry->pending_next) {
        if (entry->decl->kind == RMD_D_RECORD) {
            work = rmd_map_get(&binding.visited, (uintptr_t)entry->decl);
            entry->layout_depth = work->layout_depth;
        }
        identity_insert(ctx, &ctx->identities, entry);
    }
    rmd_map_set(ctx, &ctx->globals, (uintptr_t)name, symbol);
    ctx->failure = frame.previous;
    return true;
}

static void resolve_unit_declarations(RmdContext *ctx, RmdUnit *unit)
{
    RmdDecl *decl;
    for (decl = unit->declarations; decl != NULL; decl = decl->next) {
        if (decl->symbol == NULL)
            rmd_fail(ctx, decl->loc, "declarations must be collected before resolution");
        resolve_declaration(ctx, decl, 0);
    }
}

static void finish_unit_types(RmdContext *ctx, RmdUnit *unit)
{
    RmdDecl *decl;
    RmdField *field;
    for (decl = unit->declarations; decl != NULL; decl = decl->next) {
        finish_components(ctx, decl->type, decl->loc, 0);
        for (field = decl->fields; field != NULL; field = field->next)
            finish_components(ctx, field->type, field->loc, 0);
    }
}

bool rmd_resolve(RmdContext *ctx)
{
    RmdFailureFrame frame;
    RmdUnit *unit;
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

bool rmd_resolve_unit(RmdContext *ctx, RmdUnit *unit_value)
{
    RmdFailureFrame frame;
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

static void same_type(Checker *checker, RmdType *expected, RmdType *actual,
                      RmdLoc loc)
{
    if (!rmd_type_equal(expected, actual))
        rmd_fail(checker->ctx, loc, "type mismatch");
}

static RmdField *find_field(Checker *checker, RmdType *type, RmdName *name,
                            RmdLoc loc)
{
    RmdField *field;
    if (type->kind != RMD_T_RECORD) {
        rmd_fail(checker->ctx, loc, "field access requires a record value");
        return NULL;
    }
    field = rmd_map_get(&identity_find(&checker->ctx->identities, type->record_decl)->fields,
                        (uintptr_t)name);
    if (field != NULL)
        return field;
    rmd_fail(checker->ctx, loc, "record has no field '%s'", name->text);
    return NULL;
}

static RmdType *check_integer(Checker *checker, RmdExpr *expr, bool negated)
{
    RmdType *type;
    unsigned bits;
    uint64_t limit;
    if (expr->literal_type < RMD_T_I8 || expr->literal_type > RMD_T_USIZE) {
        rmd_fail(checker->ctx, expr->loc, "invalid integer literal type");
        return NULL;
    }
    type = &checker->ctx->builtins[expr->literal_type];
    bits = rmd_type_bits(type);
    if (rmd_type_signed(type)) {
        limit = UINT64_C(1) << (bits - 1);
        if (!negated)
            --limit;
    } else {
        limit = UINT64_MAX >> (64 - bits);
    }
    if (expr->integer > limit)
        rmd_fail(checker->ctx, expr->loc, "integer literal is outside its type's range");
    expr->type = type;
    return type;
}

static RmdType *check_expr(Checker *checker, RmdExpr *expr)
{
    RmdContext *ctx = checker->ctx;
    RmdType *left;
    RmdType *right;
    RmdType *type = NULL;
    RmdSymbol *symbol;
    RmdInit *init;
    unsigned char *seen;
    size_t i;
    check_depth(ctx, expr->loc, checker->depth++);
    expr->place = false;
    expr->writable = false;
    if (checker->constant) {
        switch (expr->kind) {
        case RMD_E_NAME:
        case RMD_E_INTEGER:
        case RMD_E_BOOL:
        case RMD_E_STRING:
        case RMD_E_GROUP:
        case RMD_E_RECORD:
        case RMD_E_ARRAY:
        case RMD_E_NULL:
        case RMD_E_SIZEOF:
        case RMD_E_ALIGNOF:
        case RMD_E_OFFSETOF:
            break;
        case RMD_E_UNARY:
            if (expr->op == RMD_OP_NEG && expr->left->kind == RMD_E_INTEGER)
                break;
            /* Fall through. */
        default:
            rmd_fail(ctx, expr->loc, "operation is not permitted in a constant initializer");
        }
    }
    switch (expr->kind) {
    case RMD_E_NAME:
        symbol = rmd_map_get(&checker->locals, (uintptr_t)expr->name);
        if (symbol == NULL)
            symbol = global_symbol(ctx, expr->name, expr->loc);
        if (symbol->kind == RMD_SYM_RECORD) {
            rmd_fail(ctx, expr->loc, "a record name is not a value");
            return NULL;
        }
        expr->symbol = symbol;
        if (checker->constant && symbol->kind != RMD_SYM_FUNCTION)
            rmd_fail(ctx, expr->loc, "only function names are permitted in constant initializers");
        type = symbol->type;
        expr->place = symbol->kind != RMD_SYM_FUNCTION;
        expr->writable = symbol->kind == RMD_SYM_LOCAL ||
                         symbol->kind == RMD_SYM_PARAM;
        break;
    case RMD_E_INTEGER:
        type = check_integer(checker, expr, false);
        break;
    case RMD_E_BOOL:
        type = &ctx->builtins[RMD_T_BOOL];
        break;
    case RMD_E_STRING:
        type = rmd_pointer_type(ctx, &ctx->builtins[RMD_T_U8]);
        break;
    case RMD_E_GROUP:
        type = check_expr(checker, expr->left);
        expr->place = expr->left->place;
        expr->writable = expr->left->writable;
        break;
    case RMD_E_UNARY:
        if (expr->op == RMD_OP_NEG && expr->left->kind == RMD_E_INTEGER)
            left = check_integer(checker, expr->left, true);
        else
            left = check_expr(checker, expr->left);
        switch (expr->op) {
        case RMD_OP_ADDRESS:
            if (!expr->left->place)
                rmd_fail(ctx, expr->loc, "address-taking requires a place");
            type = rmd_pointer_type(ctx, left);
            break;
        case RMD_OP_DEREF:
            if (left->kind != RMD_T_POINTER)
                rmd_fail(ctx, expr->loc, "dereference requires a data pointer");
            type = left->base;
            expr->place = true;
            expr->writable = true;
            break;
        case RMD_OP_NOT:
            if (left->kind != RMD_T_BOOL)
                rmd_fail(ctx, expr->loc, "logical not requires bool");
            type = left;
            break;
        case RMD_OP_NEG:
        case RMD_OP_BIT_NOT:
            if (!rmd_type_integer(left))
                rmd_fail(ctx, expr->loc, "integer unary operation requires an integer");
            type = left;
            break;
        default:
            rmd_fail(ctx, expr->loc, "invalid unary operation");
            break;
        }
        break;
    case RMD_E_BINARY:
        left = check_expr(checker, expr->left);
        right = check_expr(checker, expr->right);
        if ((expr->op == RMD_OP_ADD || expr->op == RMD_OP_SUB) &&
            left->kind == RMD_T_POINTER) {
            if (right->kind != RMD_T_ISIZE)
                rmd_fail(ctx, expr->loc, "pointer offsets require isize");
            require_storage(ctx, left->base, expr->loc, 0);
            type = left;
            break;
        }
        same_type(checker, left, right, expr->loc);
        if (expr->op == RMD_OP_AND || expr->op == RMD_OP_OR) {
            if (left->kind != RMD_T_BOOL)
                rmd_fail(ctx, expr->loc, "logical operations require bool");
            type = left;
        } else if (expr->op == RMD_OP_EQ || expr->op == RMD_OP_NE) {
            if (!rmd_type_scalar(left))
                rmd_fail(ctx, expr->loc, "equality requires matching scalar types");
            type = &ctx->builtins[RMD_T_BOOL];
        } else {
            if (!rmd_type_integer(left))
                rmd_fail(ctx, expr->loc, "integer operation requires matching integer types");
            type = expr->op >= RMD_OP_LT && expr->op <= RMD_OP_GE ?
                   &ctx->builtins[RMD_T_BOOL] : left;
        }
        break;
    case RMD_E_CALL:
        left = check_expr(checker, expr->left);
        if (left->kind != RMD_T_FUNCTION)
            rmd_fail(ctx, expr->loc, "call requires a function value");
        if (expr->arg_count != left->param_count)
            rmd_fail(ctx, expr->loc, "wrong number of call arguments");
        for (i = 0; i < expr->arg_count; ++i)
            same_type(checker, left->params[i], check_expr(checker, expr->args[i]),
                      expr->args[i]->loc);
        type = left->base;
        break;
    case RMD_E_INDEX:
        left = check_expr(checker, expr->left);
        right = check_expr(checker, expr->right);
        if (left->kind != RMD_T_ARRAY && left->kind != RMD_T_POINTER)
            rmd_fail(ctx, expr->loc, "indexing requires an array or data pointer");
        if (right->kind != RMD_T_USIZE)
            rmd_fail(ctx, expr->right->loc, "indexing requires usize");
        type = left->base;
        expr->place = left->kind == RMD_T_POINTER || expr->left->place;
        expr->writable = left->kind == RMD_T_POINTER || expr->left->writable;
        break;
    case RMD_E_FIELD:
        left = check_expr(checker, expr->left);
        expr->field = find_field(checker, left, expr->field_name, expr->loc);
        type = expr->field->type;
        expr->place = expr->left->place;
        expr->writable = expr->left->writable;
        break;
    case RMD_E_CAST:
        left = check_expr(checker, expr->left);
        type = rmd_resolve_type(ctx, expr->syntax_type);
        if ((rmd_type_integer(left) && rmd_type_integer(type)) ||
            (left->kind == RMD_T_BOOL && rmd_type_integer(type)) ||
            (rmd_type_integer(left) && type->kind == RMD_T_BOOL) ||
            (left->kind == RMD_T_POINTER && type->kind == RMD_T_POINTER) ||
            (left->kind == RMD_T_POINTER && type->kind == RMD_T_USIZE) ||
            (left->kind == RMD_T_USIZE && type->kind == RMD_T_POINTER) ||
            (rmd_type_scalar(left) && rmd_type_equal(left, type)))
            break;
        rmd_fail(ctx, expr->loc, "invalid cast");
        break;
    case RMD_E_RECORD:
        type = rmd_resolve_type(ctx, expr->syntax_type);
        if (type->kind != RMD_T_RECORD)
            rmd_fail(ctx, expr->loc, "record construction requires a record type");
        seen = rmd_alloc(ctx, type->record_decl->field_count, 1);
        i = 0;
        for (init = expr->inits; init != NULL; init = init->next) {
            init->field = find_field(checker, type, init->name, init->loc);
            if (seen[init->field->index] != 0)
                rmd_fail(ctx, init->loc, "duplicate initializer for '%s'", init->name->text);
            seen[init->field->index] = 1;
            same_type(checker, init->field->type, check_expr(checker, init->value),
                      init->value->loc);
            ++i;
        }
        if (i != type->record_decl->field_count)
            rmd_fail(ctx, expr->loc, "record construction must initialize every field");
        break;
    case RMD_E_ARRAY:
        type = rmd_resolve_type(ctx, expr->syntax_type);
        if (type->kind != RMD_T_ARRAY)
            rmd_fail(ctx, expr->loc, "array construction requires an array type");
        if (type->count != expr->arg_count)
            rmd_fail(ctx, expr->loc, "array construction must initialize every element");
        for (i = 0; i < expr->arg_count; ++i)
            same_type(checker, type->base, check_expr(checker, expr->args[i]),
                      expr->args[i]->loc);
        break;
    case RMD_E_NULL:
        type = rmd_resolve_type(ctx, expr->syntax_type);
        if (type->kind != RMD_T_POINTER && type->kind != RMD_T_FUNCTION)
            rmd_fail(ctx, expr->loc, "null requires a pointer or function type");
        break;
    case RMD_E_SIZEOF:
    case RMD_E_ALIGNOF:
        left = rmd_resolve_type(ctx, expr->syntax_type);
        require_storage(ctx, left, expr->loc, 0);
        expr->integer = expr->kind == RMD_E_SIZEOF ? left->size : left->align;
        type = &ctx->builtins[RMD_T_USIZE];
        break;
    case RMD_E_OFFSETOF:
        left = rmd_resolve_type(ctx, expr->syntax_type);
        expr->field = find_field(checker, left, expr->field_name, expr->loc);
        expr->integer = expr->field->offset;
        type = &ctx->builtins[RMD_T_USIZE];
        break;
    }
    expr->type = type;
    --checker->depth;
    return type;
}

static RmdSymbol *add_local(Checker *checker, RmdName *name, RmdType *type,
                            RmdSymbolKind kind, RmdLoc loc)
{
    RmdSymbol *symbol;
    if (rmd_map_get(&checker->locals, (uintptr_t)name) != NULL ||
        rmd_map_get(&checker->ctx->globals, (uintptr_t)name) != NULL)
        rmd_fail(checker->ctx, loc, "name '%s' is already visible", name->text);
    symbol = new_symbol(checker->ctx, name, kind, loc);
    symbol->type = type;
    symbol->scope_next = checker->scope;
    checker->scope = symbol;
    rmd_map_set(checker->ctx, &checker->locals, (uintptr_t)name, symbol);
    return symbol;
}

static void pop_scope(Checker *checker, RmdSymbol *saved)
{
    while (checker->scope != saved) {
        RmdSymbol *symbol = checker->scope;
        rmd_map_set(checker->ctx, &checker->locals, (uintptr_t)symbol->name, NULL);
        checker->scope = symbol->scope_next;
    }
}

static bool check_stmt_impl(Checker *checker, RmdStmt *stmt)
{
    RmdContext *ctx = checker->ctx;
    RmdStmt *child;
    RmdSymbol *saved;
    RmdType *type;
    bool falls;
    bool branch;
    switch (stmt->kind) {
    case RMD_S_BLOCK:
        saved = checker->scope;
        falls = true;
        for (child = stmt->body; child != NULL; child = child->next) {
            branch = check_stmt(checker, child);
            if (falls)
                falls = branch;
        }
        pop_scope(checker, saved);
        return falls;
    case RMD_S_VAR:
        type = rmd_resolve_type(ctx, stmt->syntax_type);
        require_storage(ctx, type, stmt->loc, 0);
        if (!stmt->uninitialized)
            same_type(checker, type, check_expr(checker, stmt->value), stmt->loc);
        stmt->symbol = add_local(checker, stmt->name, type, RMD_SYM_LOCAL, stmt->loc);
        return true;
    case RMD_S_IF:
        type = check_expr(checker, stmt->expr);
        if (type->kind != RMD_T_BOOL)
            rmd_fail(ctx, stmt->expr->loc, "if condition must have type bool");
        falls = check_stmt(checker, stmt->body);
        branch = stmt->otherwise == NULL ? true : check_stmt(checker, stmt->otherwise);
        return falls || branch;
    case RMD_S_WHILE:
        type = check_expr(checker, stmt->expr);
        if (type->kind != RMD_T_BOOL)
            rmd_fail(ctx, stmt->expr->loc, "while condition must have type bool");
        ++checker->loop_depth;
        (void)check_stmt(checker, stmt->body);
        --checker->loop_depth;
        return true;
    case RMD_S_BREAK:
    case RMD_S_CONTINUE:
        if (checker->loop_depth == 0)
            rmd_fail(ctx, stmt->loc, "loop exit used outside a loop");
        return false;
    case RMD_S_RETURN:
        type = checker->return_type;
        if (stmt->expr == NULL) {
            if (type->kind != RMD_T_UNIT)
                rmd_fail(ctx, stmt->loc, "return requires a value");
        } else {
            if (type->kind == RMD_T_UNIT)
                rmd_fail(ctx, stmt->loc, "unit function must use return without a value");
            same_type(checker, type, check_expr(checker, stmt->expr), stmt->expr->loc);
        }
        return false;
    case RMD_S_TRAP:
        return false;
    case RMD_S_EXPR:
        (void)check_expr(checker, stmt->expr);
        return true;
    case RMD_S_ASSIGN:
        type = check_expr(checker, stmt->expr);
        if (!stmt->expr->place || !stmt->expr->writable)
            rmd_fail(ctx, stmt->expr->loc, "assignment requires a writable place");
        same_type(checker, type, check_expr(checker, stmt->value), stmt->value->loc);
        return true;
    }
    rmd_fail(ctx, stmt->loc, "invalid statement kind");
    return false;
}

static bool check_stmt(Checker *checker, RmdStmt *stmt)
{
    bool falls;
    check_depth(checker->ctx, stmt->loc, checker->depth++);
    falls = check_stmt_impl(checker, stmt);
    --checker->depth;
    return falls;
}

static void check_constant(RmdContext *ctx, RmdDecl *decl)
{
    Checker checker;
    memset(&checker, 0, sizeof(checker));
    checker.ctx = ctx;
    checker.constant = true;
    decl->checked = false;
    same_type(&checker, decl->type, check_expr(&checker, decl->init), decl->loc);
    decl->checked = true;
}

static void check_body_impl(RmdContext *ctx, RmdDecl *function)
{
    Checker checker;
    RmdParam *param;
    bool falls;
    if (function == NULL || function->kind != RMD_D_FUNCTION ||
        function->type == NULL || function->resolve_state != 2)
        rmd_fail(ctx, no_location(), "body checking requires a resolved function");
    memset(&checker, 0, sizeof(checker));
    checker.ctx = ctx;
    checker.return_type = function->type->base;
    function->checked = false;
    for (param = function->params; param != NULL; param = param->next)
        param->symbol = add_local(&checker, param->name, param->type,
                                  RMD_SYM_PARAM, param->loc);
    falls = check_stmt(&checker, function->body);
    if (falls && function->type->base->kind != RMD_T_UNIT)
        rmd_fail(ctx, function->loc, "non-unit function can reach the end of its body");
    function->checked = true;
}

bool rmd_check_body(RmdContext *ctx, RmdDecl *function)
{
    RmdFailureFrame frame;
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

static void check_unit_impl(RmdContext *ctx, RmdUnit *unit)
{
    RmdDecl *decl;
    for (decl = unit->declarations; decl != NULL; decl = decl->next) {
        if (decl->kind == RMD_D_CONST)
            check_constant(ctx, decl);
        if (decl->kind == RMD_D_FUNCTION)
            check_body_impl(ctx, decl);
    }
}

bool rmd_check(RmdContext *ctx)
{
    RmdFailureFrame frame;
    RmdUnit *unit;
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

bool rmd_check_unit(RmdContext *ctx, RmdUnit *unit_value)
{
    RmdFailureFrame frame;
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

bool rmd_check_root(RmdContext *ctx, RmdRootScope *scope, RmdStmt *statement)
{
    RmdFailureFrame frame;
    Checker checker;
    frame.previous = ctx->failure;
    ctx->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        ctx->failure = frame.previous;
        return false;
    }
    memset(&checker, 0, sizeof(checker));
    checker.ctx = ctx;
    checker.return_type = &ctx->builtins[RMD_T_I32];
    checker.locals = scope->locals;
    checker.scope = scope->scope;
    (void)check_stmt(&checker, statement);
    scope->locals = checker.locals;
    scope->scope = checker.scope;
    ctx->failure = frame.previous;
    return true;
}
