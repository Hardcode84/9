#include "crust0_eval.h"

#include <assert.h>
#include <ffi.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct EvalDecl EvalDecl;
typedef struct EvalNative EvalNative;
typedef struct EvalPlan EvalPlan;
typedef struct EvalFrame EvalFrame;
typedef struct EvalAbi EvalAbi;

typedef struct {
    uint64_t bits;
    unsigned char *aggregate;
} EvalValue;

typedef struct {
    size_t offset;
} EvalSlot;

typedef struct {
    size_t value;
    size_t arguments;
    size_t pointers;
    EvalAbi *abi;
} EvalExpr;

struct EvalAbi {
    ffi_cif cif;
    ffi_type **arguments;
    CrustType *type;
};

struct EvalFrame {
    EvalPlan *plan;
    unsigned char *storage;
    EvalFrame *next;
};

struct EvalPlan {
    CrustMap symbols;
    CrustMap expressions;
    size_t size;
    EvalFrame *available;
};

struct EvalNative {
    CrustDecl *prototype;
    EvalDecl *definition;
    void *address;
    bool published;
};

struct EvalDecl {
    CrustEval *eval;
    CrustDecl *declaration;
    EvalNative *native;
    EvalPlan *plan;
    unsigned char *constant;
    ffi_closure *closure;
    void *code;
    EvalDecl *identity_next;
    EvalDecl *next;
};

struct CrustEval {
    CrustContext *context;
    CrustEvalOptions options;
    CrustMap declarations;
    CrustMap identities;
    CrustMap natives;
    CrustMap functions;
    CrustMap abis;
    CrustMap roots;
    CrustMap statements;
    CrustMap expressions;
    EvalDecl *first;
};

typedef enum {
    EVAL_NEXT, EVAL_RETURN, EVAL_BREAK, EVAL_CONTINUE
} EvalFlow;

static bool eval_expression(CrustEval *eval, EvalFrame *frame,
                             CrustExpr *expression, EvalValue *result);
static bool eval_statement(CrustEval *eval, EvalFrame *frame,
                            CrustStmt *statement, EvalFlow *flow, EvalValue *result);
static bool call_declaration(CrustEval *eval, EvalDecl *declaration,
                              void *const *arguments, EvalValue *result);
static bool function_address(CrustEval *eval, EvalDecl *declaration, void **result);

static bool error_at(CrustEval *eval, CrustLoc location, const char *message)
{
    crust_set_error(eval->context, location.source, location.offset, message);
    return false;
}

static CrustLoc no_location(void)
{
    CrustLoc location = {NULL, 0};
    return location;
}

static void fatal_error(CrustEval *eval)
{
    CrustContext *context = eval->context;
    CrustSource *source = context->error_loc.source;
    if (source != NULL && source->path != NULL) {
        size_t line = 1;
        size_t column = 1;
        size_t index;
        for (index = 0; index < context->error_loc.offset && index < source->size; ++index) {
            if (source->bytes[index] == '\n') { ++line; column = 1; }
            else ++column;
        }
        fprintf(stderr, "%s:%zu:%zu: error: %s\n", source->path, line, column, context->error);
    } else
        fprintf(stderr, "CRUST evaluation failed: %s\n", context->error);
    (void)fflush(stderr);
    (void)fflush(stdout);
    abort();
}

static void required_trap(CrustEval *eval, CrustLoc location)
{
    (void)error_at(eval, location, "required execution trap");
    fatal_error(eval);
}

static void *allocate(CrustEval *eval, size_t size, size_t alignment)
{
    return crust_try_alloc(eval->context, size, alignment);
}

static bool aggregate_type(CrustType *type)
{
    return type->kind == CRUST_T_RECORD || type->kind == CRUST_T_ARRAY;
}

static uint64_t mask_bits(unsigned bits)
{
    return bits == 64 ? UINT64_MAX : (UINT64_C(1) << bits) - 1;
}

static uint64_t type_mask(CrustType *type)
{
    return mask_bits((unsigned)(type->size * 8));
}

static uint64_t extended_bits(uint64_t value, CrustType *type)
{
    unsigned bits = (unsigned)(type->size * 8);
    uint64_t mask = mask_bits(bits);
    value &= mask;
    if (crust_type_signed(type) && (value & (UINT64_C(1) << (bits - 1))) != 0)
        value |= ~mask;
    return value;
}

static uint64_t load_bits(const void *address, CrustType *type)
{
    uint64_t value = 0;
    if (type->kind != CRUST_T_UNIT)
        memcpy(&value, address, (size_t)type->size);
    return value;
}

static void store_value(void *address, CrustType *type, EvalValue value)
{
    if (type->kind == CRUST_T_UNIT)
        return;
    if (aggregate_type(type))
        memmove(address, value.aggregate, (size_t)type->size);
    else
        memcpy(address, &value.bits, (size_t)type->size);
}

static CrustTypeKind native_kind(CrustType *type)
{
    if (type->kind == CRUST_T_ISIZE) return CRUST_T_I64;
    if (type->kind == CRUST_T_USIZE) return CRUST_T_U64;
    return type->kind;
}

static bool native_type_equal(CrustType *left, CrustType *right)
{
    size_t index;
    if (left == right) return true;
    if (native_kind(left) != native_kind(right)) return false;
    if (left->kind != CRUST_T_FUNCTION)
        return !aggregate_type(left);
    if (left->param_count != right->param_count ||
        !native_type_equal(left->base, right->base)) return false;
    for (index = 0; index < left->param_count; ++index)
        if (!native_type_equal(left->params[index], right->params[index])) return false;
    return true;
}

static bool is_function(CrustDecl *declaration)
{
    return declaration->kind == CRUST_D_FUNCTION || declaration->kind == CRUST_D_EXTERN;
}

static uintptr_t identity_key(CrustDecl *declaration)
{
    uint64_t identity = declaration->identity;
    uintptr_t key = (uintptr_t)(identity ^ (declaration->unit_identity +
        UINT64_C(0x9e3779b97f4a7c15) + (identity << 6) + (identity >> 2)));
    return key == 0 ? 1 : key;
}

static EvalDecl *find_declaration(CrustEval *eval, CrustDecl *declaration)
{
    return crust_map_get(&eval->declarations, (uintptr_t)declaration);
}

static ffi_type *ffi_value_type(CrustType *type)
{
    switch (type->kind) {
    case CRUST_T_I8: return &ffi_type_sint8;
    case CRUST_T_U8: case CRUST_T_BOOL: return &ffi_type_uint8;
    case CRUST_T_I16: return &ffi_type_sint16;
    case CRUST_T_U16: return &ffi_type_uint16;
    case CRUST_T_I32: return &ffi_type_sint32;
    case CRUST_T_U32: return &ffi_type_uint32;
    case CRUST_T_I64: case CRUST_T_ISIZE: return &ffi_type_sint64;
    case CRUST_T_U64: case CRUST_T_USIZE: return &ffi_type_uint64;
    case CRUST_T_UNIT: return &ffi_type_void;
    case CRUST_T_POINTER: case CRUST_T_FUNCTION: return &ffi_type_pointer;
    default: abort();
    }
}

static EvalAbi *prepare_abi(CrustEval *eval, CrustType *type, CrustLoc location)
{
    EvalAbi *abi = crust_map_get(&eval->abis, (uintptr_t)type);
    size_t index;
    if (abi != NULL) return abi;
    if (type->param_count > UINT_MAX || type->param_count > SIZE_MAX / sizeof(ffi_type *)) {
        (void)error_at(eval, location, "native parameter count exceeds the libffi limit");
        return NULL;
    }
    abi = allocate(eval, sizeof(*abi), CRUST_ALIGNOF(EvalAbi));
    if (abi == NULL) return NULL;
    abi->type = type;
    if (type->param_count != 0) {
        abi->arguments = allocate(eval, type->param_count * sizeof(*abi->arguments),
                                  CRUST_ALIGNOF(ffi_type *));
        if (abi->arguments == NULL) return NULL;
    }
    for (index = 0; index < type->param_count; ++index)
        abi->arguments[index] = ffi_value_type(type->params[index]);
    if (ffi_prep_cif(&abi->cif, FFI_DEFAULT_ABI, (unsigned)type->param_count,
                     ffi_value_type(type->base), abi->arguments) != FFI_OK) {
        (void)error_at(eval, location, "libffi rejected the native function signature");
        return NULL;
    }
    if (!crust_try_map_set(eval->context, &eval->abis, (uintptr_t)type, abi)) return NULL;
    return abi;
}

CrustEval *crust_eval_create(CrustContext *context, const CrustEvalOptions *options)
{
    CrustEval *eval;
    if (context == NULL) return NULL;
    eval = crust_try_alloc(context, sizeof(*eval), CRUST_ALIGNOF(CrustEval));
    if (eval == NULL) return NULL;
    eval->context = context;
    if (options != NULL) eval->options = *options;
    return eval;
}

void crust_eval_destroy(CrustEval *eval)
{
    EvalDecl *declaration;
    if (eval == NULL) return;
    for (declaration = eval->first; declaration != NULL; declaration = declaration->next) {
        if (declaration->closure != NULL) {
            ffi_closure_free(declaration->closure);
            declaration->closure = NULL;
        }
    }
}

bool crust_eval_prepare(CrustEval *eval, CrustDecl *declaration)
{
    EvalDecl *prepared;
    EvalDecl *same;
    EvalNative *native = NULL;
    CrustName *name = NULL;
    const unsigned char *cursor;
    uintptr_t key;
    if (declaration == NULL || declaration->type == NULL)
        return error_at(eval, no_location(), "evaluation requires a checked declaration");
    if (find_declaration(eval, declaration) != NULL) return true;
    if (declaration->kind == CRUST_D_RECORD) return true;
    if (declaration->kind == CRUST_D_FUNCTION && !declaration->checked)
        return error_at(eval, declaration->loc, "evaluation requires a checked function body");
    if (declaration->kind == CRUST_D_CONST && !declaration->checked)
        return error_at(eval, declaration->loc, "evaluation requires a checked constant");
    key = identity_key(declaration);
    if (declaration->identity != 0) {
        for (same = crust_map_get(&eval->identities, key); same != NULL; same = same->identity_next) {
            if (same->declaration->identity == declaration->identity &&
                same->declaration->unit_identity == declaration->unit_identity)
                return crust_try_map_set(eval->context, &eval->declarations,
                                        (uintptr_t)declaration, same);
        }
    }
    if (declaration->kind == CRUST_D_EXTERN && declaration->link_name == NULL)
        return error_at(eval, declaration->loc, "external function has no native link name");
    if (declaration->link_name != NULL) {
        cursor = (const unsigned char *)declaration->link_name;
        if (*cursor == 0)
            return error_at(eval, declaration->loc, "native link name is empty");
        while (*cursor != 0) {
            if (*cursor > 127)
                return error_at(eval, declaration->loc, "native link name is not ASCII");
            ++cursor;
        }
        name = crust_try_intern(eval->context, (const unsigned char *)declaration->link_name,
                               (size_t)(cursor - (const unsigned char *)declaration->link_name));
        if (name == NULL) return false;
        native = crust_map_get(&eval->natives, (uintptr_t)name);
        if (native != NULL) {
            if (is_function(native->prototype) != is_function(declaration) ||
                (is_function(declaration) ?
                 !native_type_equal(native->prototype->type, declaration->type) :
                 !crust_type_equal(native->prototype->type, declaration->type)))
                return error_at(eval, declaration->loc, "conflicting native ABI for symbol");
            if (declaration->kind != CRUST_D_EXTERN && native->definition != NULL)
                return error_at(eval, declaration->loc, "duplicate native definition for symbol");
            if (declaration->kind != CRUST_D_EXTERN && native->published)
                return error_at(eval, declaration->loc, "native callable identity was already published");
        }
    }
    prepared = allocate(eval, sizeof(*prepared), CRUST_ALIGNOF(EvalDecl));
    if (prepared == NULL) return false;
    prepared->eval = eval;
    prepared->declaration = declaration;
    if (name != NULL && native == NULL) {
        native = allocate(eval, sizeof(*native), CRUST_ALIGNOF(EvalNative));
        if (native == NULL) return false;
        native->prototype = declaration;
        if (!crust_try_map_set(eval->context, &eval->natives, (uintptr_t)name, native)) return false;
    }
    prepared->native = native;
    prepared->next = eval->first;
    eval->first = prepared;
    if (native != NULL && declaration->kind != CRUST_D_EXTERN) native->definition = prepared;
    if (declaration->identity != 0) {
        prepared->identity_next = crust_map_get(&eval->identities, key);
        if (!crust_try_map_set(eval->context, &eval->identities, key, prepared)) {
            if (native != NULL && native->definition == prepared) native->definition = NULL;
            return false;
        }
    }
    if (!crust_try_map_set(eval->context, &eval->declarations, (uintptr_t)declaration, prepared)) {
        if (declaration->identity == 0 && native != NULL && native->definition == prepared)
            native->definition = NULL;
        return false;
    }
    return true;
}

static EvalDecl *get_declaration(CrustEval *eval, CrustDecl *declaration)
{
    if (!crust_eval_prepare(eval, declaration)) return NULL;
    return find_declaration(eval, declaration);
}

static bool reserve_slot(CrustEval *eval, EvalPlan *plan, size_t size,
                          size_t alignment, CrustLoc location, size_t *result)
{
    size_t offset;
    if (plan->size > SIZE_MAX - (alignment - 1))
        return error_at(eval, location, "evaluation frame size overflow");
    offset = (plan->size + alignment - 1) & ~(alignment - 1);
    if (size > SIZE_MAX - offset)
        return error_at(eval, location, "evaluation frame size overflow");
    *result = offset;
    plan->size = offset + size;
    return true;
}

static bool prepare_symbol(CrustEval *eval, EvalPlan *plan, CrustSymbol *symbol)
{
    EvalSlot *slot = allocate(eval, sizeof(*slot), CRUST_ALIGNOF(EvalSlot));
    if (slot == NULL || !reserve_slot(eval, plan, (size_t)symbol->type->size,
                                      symbol->type->align, symbol->loc, &slot->offset)) return false;
    return crust_try_map_set(eval->context, &plan->symbols, (uintptr_t)symbol, slot);
}

static bool prepare_expression(CrustEval *eval, EvalPlan *plan, CrustExpr *expression)
{
    EvalExpr *prepared;
    CrustInit *init;
    size_t index;
    if (expression == NULL) return true;
    if (aggregate_type(expression->type) || expression->kind == CRUST_E_CALL) {
        prepared = allocate(eval, sizeof(*prepared), CRUST_ALIGNOF(EvalExpr));
        if (prepared == NULL) return false;
        if (aggregate_type(expression->type) &&
            !reserve_slot(eval, plan, (size_t)expression->type->size, expression->type->align,
                            expression->loc, &prepared->value)) return false;
        if (expression->kind == CRUST_E_CALL) {
            if (expression->arg_count > SIZE_MAX / sizeof(uint64_t) ||
                expression->arg_count > SIZE_MAX / sizeof(void *))
                return error_at(eval, expression->loc, "evaluation argument storage overflow");
            if (!reserve_slot(eval, plan, expression->arg_count * sizeof(uint64_t),
                                CRUST_ALIGNOF(uint64_t), expression->loc, &prepared->arguments) ||
                !reserve_slot(eval, plan, expression->arg_count * sizeof(void *),
                                CRUST_ALIGNOF(void *), expression->loc, &prepared->pointers)) return false;
        }
        if (!crust_try_map_set(eval->context, &plan->expressions, (uintptr_t)expression, prepared))
            return false;
    }
    if (!prepare_expression(eval, plan, expression->left) ||
        !prepare_expression(eval, plan, expression->right)) return false;
    for (index = 0; index < expression->arg_count; ++index)
        if (!prepare_expression(eval, plan, expression->args[index])) return false;
    for (init = expression->inits; init != NULL; init = init->next)
        if (!prepare_expression(eval, plan, init->value)) return false;
    return true;
}

static bool prepare_statement(CrustEval *eval, EvalPlan *plan, CrustStmt *statement,
                               bool persistent)
{
    CrustStmt *child;
    if (statement == NULL) return true;
    if (statement->kind == CRUST_S_VAR) {
        if (persistent) {
            void *storage = crust_map_get(&eval->roots, (uintptr_t)statement->symbol);
            if (storage == NULL) {
                storage = allocate(eval, (size_t)statement->symbol->type->size,
                                     statement->symbol->type->align);
                if (storage == NULL || !crust_try_map_set(eval->context, &eval->roots,
                       (uintptr_t)statement->symbol, storage)) return false;
            }
        } else if (!prepare_symbol(eval, plan, statement->symbol)) return false;
    }
    if (!prepare_expression(eval, plan, statement->expr) ||
        !prepare_expression(eval, plan, statement->value)) return false;
    if (statement->kind == CRUST_S_BLOCK) {
        for (child = statement->body; child != NULL; child = child->next)
            if (!prepare_statement(eval, plan, child, false)) return false;
    } else if (!prepare_statement(eval, plan, statement->body, false)) return false;
    return prepare_statement(eval, plan, statement->otherwise, false);
}

static EvalPlan *function_plan(CrustEval *eval, EvalDecl *declaration)
{
    EvalPlan *plan;
    CrustParam *param;
    if (declaration->plan != NULL) return declaration->plan;
    plan = allocate(eval, sizeof(*plan), CRUST_ALIGNOF(EvalPlan));
    if (plan == NULL) return NULL;
    for (param = declaration->declaration->params; param != NULL; param = param->next)
        if (!prepare_symbol(eval, plan, param->symbol)) return NULL;
    if (!prepare_statement(eval, plan, declaration->declaration->body, false)) return NULL;
    declaration->plan = plan;
    return plan;
}

static EvalFrame *acquire_frame(CrustEval *eval, EvalPlan *plan)
{
    EvalFrame *frame = plan->available;
    if (frame != NULL) {
        plan->available = frame->next;
        return frame;
    }
    frame = allocate(eval, sizeof(*frame), CRUST_ALIGNOF(EvalFrame));
    if (frame == NULL) return NULL;
    frame->plan = plan;
    frame->storage = crust_arena_alloc(&eval->context->arena, plan->size == 0 ? 1 : plan->size,
                                      CRUST_ALIGNOF(uint64_t));
    if (frame->storage == NULL) {
        (void)error_at(eval, no_location(), "evaluation frame allocation failed");
        return NULL;
    }
    return frame;
}

static void release_frame(EvalFrame *frame)
{
    frame->next = frame->plan->available;
    frame->plan->available = frame;
}

static void *symbol_address(CrustEval *eval, EvalFrame *frame, CrustSymbol *symbol)
{
    EvalSlot *slot = crust_map_get(&frame->plan->symbols, (uintptr_t)symbol);
    if (slot != NULL) return frame->storage + slot->offset;
    return crust_map_get(&eval->roots, (uintptr_t)symbol);
}

static unsigned char *expression_storage(EvalFrame *frame, CrustExpr *expression)
{
    EvalExpr *prepared = crust_map_get(&frame->plan->expressions, (uintptr_t)expression);
    return frame->storage + prepared->value;
}

static bool constant_address(CrustEval *eval, EvalDecl *declaration, void **result)
{
    CrustDecl *syntax = declaration->declaration;
    unsigned char *storage;
    if (declaration->constant != NULL) {
        *result = declaration->constant;
        return true;
    }
    storage = allocate(eval, (size_t)syntax->type->size, syntax->type->align);
    if (storage == NULL || !crust_eval_expression(eval, syntax->init, storage)) return false;
    declaration->constant = storage;
    *result = storage;
    return true;
}

static bool eval_place(CrustEval *eval, EvalFrame *frame, CrustExpr *expression,
                        void **result)
{
    EvalValue value;
    EvalValue index;
    void *address;
    EvalDecl *declaration;
    switch (expression->kind) {
    case CRUST_E_NAME:
        if (expression->symbol->kind == CRUST_SYM_CONST) {
            declaration = get_declaration(eval, expression->symbol->decl);
            return declaration != NULL && constant_address(eval, declaration, result);
        }
        *result = symbol_address(eval, frame, expression->symbol);
        assert(*result != NULL);
        return true;
    case CRUST_E_GROUP:
        return eval_place(eval, frame, expression->left, result);
    case CRUST_E_UNARY:
        assert(expression->op == CRUST_OP_DEREF);
        if (!eval_expression(eval, frame, expression->left, &value)) return false;
        *result = (void *)(uintptr_t)value.bits;
        return true;
    case CRUST_E_FIELD:
        if (expression->left->place) {
            if (!eval_place(eval, frame, expression->left, &address)) return false;
        } else {
            if (!eval_expression(eval, frame, expression->left, &value)) return false;
            address = value.aggregate;
        }
        *result = (void *)((uintptr_t)address + (uintptr_t)expression->field->offset);
        return true;
    case CRUST_E_INDEX:
        if (expression->left->type->kind == CRUST_T_POINTER) {
            if (!eval_expression(eval, frame, expression->left, &value)) return false;
            address = (void *)(uintptr_t)value.bits;
        } else if (expression->left->place) {
            if (!eval_place(eval, frame, expression->left, &address)) return false;
        } else {
            if (!eval_expression(eval, frame, expression->left, &value)) return false;
            address = value.aggregate;
        }
        if (!eval_expression(eval, frame, expression->right, &index)) return false;
        *result = (void *)((uintptr_t)address + (uintptr_t)(index.bits * expression->type->size));
        return true;
    default: abort();
    }
}

static bool read_place(CrustEval *eval, EvalFrame *frame, CrustExpr *expression,
                        EvalValue *result)
{
    void *address;
    if (!eval_place(eval, frame, expression, &address)) return false;
    if (aggregate_type(expression->type)) {
        result->aggregate = expression_storage(frame, expression);
        memcpy(result->aggregate, address, (size_t)expression->type->size);
    } else result->bits = load_bits(address, expression->type);
    return true;
}

static uint64_t divide_bits(CrustEval *eval, CrustExpr *expression,
                             uint64_t left, uint64_t right)
{
    CrustType *type = expression->left->type;
    unsigned bits = (unsigned)(type->size * 8);
    uint64_t mask = mask_bits(bits);
    uint64_t sign = UINT64_C(1) << (bits - 1);
    bool negative_left;
    bool negative_right;
    uint64_t a;
    uint64_t b;
    uint64_t value;
    if (right == 0) required_trap(eval, expression->loc);
    if (!crust_type_signed(type))
        return expression->op == CRUST_OP_DIV ? left / right : left % right;
    if (left == sign && right == mask) required_trap(eval, expression->loc);
    negative_left = (left & sign) != 0;
    negative_right = (right & sign) != 0;
    a = negative_left ? (UINT64_C(0) - left) & mask : left;
    b = negative_right ? (UINT64_C(0) - right) & mask : right;
    value = expression->op == CRUST_OP_DIV ? a / b : a % b;
    if (expression->op == CRUST_OP_DIV ? negative_left != negative_right : negative_left)
        value = UINT64_C(0) - value;
    return value & mask;
}

static bool binary_expression(CrustEval *eval, EvalFrame *frame,
                               CrustExpr *expression, EvalValue *result)
{
    EvalValue left;
    EvalValue right;
    CrustType *type = expression->left->type;
    uint64_t a;
    uint64_t b;
    uint64_t sign;
    unsigned bits = (unsigned)(type->size * 8);
    if (!eval_expression(eval, frame, expression->left, &left)) return false;
    if (expression->op == CRUST_OP_AND && left.bits == 0) {
        result->bits = 0;
        return true;
    }
    if (expression->op == CRUST_OP_OR && left.bits != 0) {
        result->bits = 1;
        return true;
    }
    if (!eval_expression(eval, frame, expression->right, &right)) return false;
    a = left.bits;
    b = right.bits;
    if (type->kind == CRUST_T_POINTER &&
        (expression->op == CRUST_OP_ADD || expression->op == CRUST_OP_SUB)) {
        b *= type->base->size;
        result->bits = expression->op == CRUST_OP_ADD ? a + b : a - b;
        return true;
    }
    switch (expression->op) {
    case CRUST_OP_ADD: result->bits = a + b; break;
    case CRUST_OP_SUB: result->bits = a - b; break;
    case CRUST_OP_MUL: result->bits = a * b; break;
    case CRUST_OP_DIV: case CRUST_OP_REM:
        result->bits = divide_bits(eval, expression, a, b); break;
    case CRUST_OP_SHL: case CRUST_OP_SHR:
        if (b >= bits) required_trap(eval, expression->loc);
        if (expression->op == CRUST_OP_SHL) result->bits = a << (unsigned)b;
        else {
            result->bits = a >> (unsigned)b;
            if (b != 0 && crust_type_signed(type) &&
                (a & (UINT64_C(1) << (bits - 1))) != 0)
                result->bits |= mask_bits(bits) ^ mask_bits(bits - (unsigned)b);
        }
        break;
    case CRUST_OP_BIT_AND: result->bits = a & b; break;
    case CRUST_OP_BIT_OR: result->bits = a | b; break;
    case CRUST_OP_BIT_XOR: result->bits = a ^ b; break;
    case CRUST_OP_EQ: result->bits = a == b; return true;
    case CRUST_OP_NE: result->bits = a != b; return true;
    case CRUST_OP_LT: case CRUST_OP_LE: case CRUST_OP_GT: case CRUST_OP_GE:
        if (crust_type_signed(type)) {
            sign = UINT64_C(1) << (bits - 1);
            a ^= sign;
            b ^= sign;
        }
        if (expression->op == CRUST_OP_LT) result->bits = a < b;
        else if (expression->op == CRUST_OP_LE) result->bits = a <= b;
        else if (expression->op == CRUST_OP_GT) result->bits = a > b;
        else result->bits = a >= b;
        return true;
    case CRUST_OP_AND: case CRUST_OP_OR: result->bits = b != 0; return true;
    default: abort();
    }
    result->bits &= type_mask(expression->type);
    return true;
}

static bool call_native(CrustEval *eval, EvalAbi *abi, void *address,
                         void *const *arguments, EvalValue *result)
{
    void (*function)(void);
    ffi_arg returned = 0;
    (void)eval;
    memcpy(&function, &address, sizeof(function));
    ffi_call(&abi->cif, function, &returned, (void **)arguments);
    result->bits = (uint64_t)returned;
    if (abi->type->base->kind != CRUST_T_UNIT) result->bits &= type_mask(abi->type->base);
    return true;
}

static bool call_expression(CrustEval *eval, EvalFrame *frame,
                             CrustExpr *expression, EvalValue *result)
{
    EvalExpr *prepared = crust_map_get(&frame->plan->expressions, (uintptr_t)expression);
    CrustExpr *callee = expression->left;
    EvalDecl *declaration = NULL;
    EvalValue value;
    void *address = NULL;
    void **arguments = (void **)(void *)(frame->storage + prepared->pointers);
    uint64_t *values = (uint64_t *)(void *)(frame->storage + prepared->arguments);
    size_t index;
    while (callee->kind == CRUST_E_GROUP) callee = callee->left;
    if (callee->kind == CRUST_E_NAME && callee->symbol->kind == CRUST_SYM_FUNCTION) {
        declaration = get_declaration(eval, callee->symbol->decl);
        if (declaration == NULL) return false;
        if (declaration->native != NULL && declaration->native->definition != NULL)
            declaration = declaration->native->definition;
        if (declaration->declaration->kind == CRUST_D_EXTERN &&
            !function_address(eval, declaration, &address)) return false;
    } else {
        if (!eval_expression(eval, frame, expression->left, &value)) return false;
        address = (void *)(uintptr_t)value.bits;
        declaration = crust_map_get(&eval->functions, (uintptr_t)address);
    }
    for (index = 0; index < expression->arg_count; ++index) {
        if (!eval_expression(eval, frame, expression->args[index], &value)) return false;
        values[index] = value.bits;
        arguments[index] = &values[index];
    }
    if (declaration != NULL && declaration->declaration->kind == CRUST_D_FUNCTION)
        return call_declaration(eval, declaration, arguments, result);
    if (prepared->abi == NULL) {
        prepared->abi = prepare_abi(eval, expression->left->type, expression->loc);
        if (prepared->abi == NULL) return false;
    }
    return call_native(eval, prepared->abi, address, arguments, result);
}

static bool eval_expression(CrustEval *eval, EvalFrame *frame,
                             CrustExpr *expression, EvalValue *result)
{
    EvalValue value;
    EvalDecl *declaration;
    void *address;
    CrustInit *init;
    size_t index;
    result->bits = 0;
    result->aggregate = NULL;
    switch (expression->kind) {
    case CRUST_E_NAME:
        if (expression->symbol->kind != CRUST_SYM_FUNCTION)
            return read_place(eval, frame, expression, result);
        declaration = get_declaration(eval, expression->symbol->decl);
        if (declaration == NULL || !function_address(eval, declaration, &address)) return false;
        result->bits = (uint64_t)(uintptr_t)address;
        return true;
    case CRUST_E_INTEGER: case CRUST_E_BOOL: case CRUST_E_SIZEOF:
    case CRUST_E_ALIGNOF: case CRUST_E_OFFSETOF:
        result->bits = expression->integer;
        return true;
    case CRUST_E_STRING:
        result->bits = (uint64_t)(uintptr_t)expression->bytes;
        return true;
    case CRUST_E_NULL:
        return true;
    case CRUST_E_GROUP:
        return eval_expression(eval, frame, expression->left, result);
    case CRUST_E_UNARY:
        if (expression->op == CRUST_OP_DEREF)
            return read_place(eval, frame, expression, result);
        if (expression->op == CRUST_OP_ADDRESS) {
            if (!eval_place(eval, frame, expression->left, &address)) return false;
            result->bits = (uint64_t)(uintptr_t)address;
            return true;
        }
        if (!eval_expression(eval, frame, expression->left, &value)) return false;
        if (expression->op == CRUST_OP_NEG) result->bits = UINT64_C(0) - value.bits;
        else if (expression->op == CRUST_OP_NOT) result->bits = value.bits == 0;
        else result->bits = ~value.bits;
        result->bits &= type_mask(expression->type);
        return true;
    case CRUST_E_BINARY:
        return binary_expression(eval, frame, expression, result);
    case CRUST_E_CALL:
        return call_expression(eval, frame, expression, result);
    case CRUST_E_INDEX: case CRUST_E_FIELD:
        return read_place(eval, frame, expression, result);
    case CRUST_E_CAST:
        if (!eval_expression(eval, frame, expression->left, &value)) return false;
        if (expression->type->kind == CRUST_T_BOOL) result->bits = value.bits != 0;
        else result->bits = extended_bits(value.bits, expression->left->type) & type_mask(expression->type);
        return true;
    case CRUST_E_RECORD:
        result->aggregate = expression_storage(frame, expression);
        for (init = expression->inits; init != NULL; init = init->next) {
            if (!eval_expression(eval, frame, init->value, &value)) return false;
            store_value(result->aggregate + init->field->offset, init->field->type, value);
        }
        return true;
    case CRUST_E_ARRAY:
        result->aggregate = expression_storage(frame, expression);
        for (index = 0; index < expression->arg_count; ++index) {
            if (!eval_expression(eval, frame, expression->args[index], &value)) return false;
            store_value(result->aggregate + index * expression->type->base->size,
                         expression->type->base, value);
        }
        return true;
    default: abort();
    }
}

static bool eval_statement(CrustEval *eval, EvalFrame *frame,
                            CrustStmt *statement, EvalFlow *flow, EvalValue *result)
{
    EvalValue value;
    void *address;
    CrustStmt *child;
    *flow = EVAL_NEXT;
    switch (statement->kind) {
    case CRUST_S_BLOCK:
        for (child = statement->body; child != NULL; child = child->next) {
            if (!eval_statement(eval, frame, child, flow, result)) return false;
            if (*flow != EVAL_NEXT) break;
        }
        return true;
    case CRUST_S_VAR:
        if (statement->uninitialized) return true;
        if (!eval_expression(eval, frame, statement->value, &value)) return false;
        address = symbol_address(eval, frame, statement->symbol);
        assert(address != NULL);
        store_value(address, statement->symbol->type, value);
        return true;
    case CRUST_S_IF:
        if (!eval_expression(eval, frame, statement->expr, &value)) return false;
        child = value.bits != 0 ? statement->body : statement->otherwise;
        return child == NULL || eval_statement(eval, frame, child, flow, result);
    case CRUST_S_WHILE:
        for (;;) {
            if (!eval_expression(eval, frame, statement->expr, &value)) return false;
            if (value.bits == 0) return true;
            if (!eval_statement(eval, frame, statement->body, flow, result)) return false;
            if (*flow == EVAL_RETURN) return true;
            if (*flow == EVAL_BREAK) { *flow = EVAL_NEXT; return true; }
            *flow = EVAL_NEXT;
        }
    case CRUST_S_BREAK: *flow = EVAL_BREAK; return true;
    case CRUST_S_CONTINUE: *flow = EVAL_CONTINUE; return true;
    case CRUST_S_RETURN:
        if (statement->expr != NULL && !eval_expression(eval, frame, statement->expr, result)) return false;
        *flow = EVAL_RETURN;
        return true;
    case CRUST_S_TRAP:
        required_trap(eval, statement->loc);
        return false;
    case CRUST_S_EXPR:
        return eval_expression(eval, frame, statement->expr, &value);
    case CRUST_S_ASSIGN:
        if (!eval_place(eval, frame, statement->expr, &address) ||
            !eval_expression(eval, frame, statement->value, &value)) return false;
        store_value(address, statement->expr->type, value);
        return true;
    default: abort();
    }
}

static bool call_declaration(CrustEval *eval, EvalDecl *declaration,
                              void *const *arguments, EvalValue *result)
{
    EvalPlan *plan;
    EvalFrame *frame;
    CrustParam *param;
    EvalFlow flow = EVAL_NEXT;
    size_t index = 0;
    bool success;
    void *address;
    EvalAbi *abi;
    if (declaration->native != NULL && declaration->native->definition != NULL)
        declaration = declaration->native->definition;
    if (declaration->declaration->kind == CRUST_D_EXTERN) {
        if (!function_address(eval, declaration, &address)) return false;
        abi = prepare_abi(eval, declaration->declaration->type, declaration->declaration->loc);
        return abi != NULL && call_native(eval, abi, address, arguments, result);
    }
    plan = function_plan(eval, declaration);
    if (plan == NULL) return false;
    frame = acquire_frame(eval, plan);
    if (frame == NULL) return false;
    for (param = declaration->declaration->params; param != NULL; param = param->next) {
        memcpy(symbol_address(eval, frame, param->symbol), arguments[index], (size_t)param->type->size);
        ++index;
    }
    result->bits = 0;
    result->aggregate = NULL;
    success = eval_statement(eval, frame, declaration->declaration->body, &flow, result);
    release_frame(frame);
    return success;
}

static void native_callback(ffi_cif *cif, void *returned, void **arguments, void *user)
{
    EvalDecl *declaration = user;
    EvalValue result;
    CrustType *type = declaration->declaration->type->base;
    ffi_arg bits;
    (void)cif;
    if (!call_declaration(declaration->eval, declaration, arguments, &result))
        fatal_error(declaration->eval);
    if (type->kind != CRUST_T_UNIT) {
        bits = (ffi_arg)extended_bits(result.bits, type);
        memcpy(returned, &bits, sizeof(bits));
    }
}

static bool function_address(CrustEval *eval, EvalDecl *declaration, void **result)
{
    EvalAbi *abi;
    size_t errors;
    void *address;
    if (declaration->native != NULL && declaration->native->definition != NULL)
        declaration = declaration->native->definition;
    if (declaration->native != NULL && declaration->native->published) {
        *result = declaration->native->address;
        return true;
    }
    if (declaration->declaration->kind == CRUST_D_EXTERN) {
        if (eval->options.resolve == NULL)
            return error_at(eval, declaration->declaration->loc, "no native symbol resolver was supplied");
        errors = eval->context->error_count;
        address = NULL;
        if (!eval->options.resolve(eval->options.user, declaration->declaration, &address)) {
            if (eval->context->error_count == errors)
                (void)error_at(eval, declaration->declaration->loc, "native symbol resolver failed without a diagnostic");
            return false;
        }
        if (address == NULL)
            return error_at(eval, declaration->declaration->loc, "native symbol resolver returned a null address");
        declaration->native->address = address;
        declaration->native->published = true;
        *result = address;
        return true;
    }
    if (declaration->code != NULL) {
        *result = declaration->code;
        return true;
    }
    abi = prepare_abi(eval, declaration->declaration->type, declaration->declaration->loc);
    if (abi == NULL) return false;
    declaration->closure = ffi_closure_alloc(sizeof(ffi_closure), &address);
    if (declaration->closure == NULL)
        return error_at(eval, declaration->declaration->loc, "native callback allocation failed");
    if (ffi_prep_closure_loc(declaration->closure, &abi->cif, native_callback,
                             declaration, address) != FFI_OK) {
        ffi_closure_free(declaration->closure);
        declaration->closure = NULL;
        return error_at(eval, declaration->declaration->loc, "libffi rejected the native callback");
    }
    if (!crust_try_map_set(eval->context, &eval->functions, (uintptr_t)address, declaration)) {
        ffi_closure_free(declaration->closure);
        declaration->closure = NULL;
        return false;
    }
    declaration->code = address;
    if (declaration->native != NULL) {
        declaration->native->address = address;
        declaration->native->published = true;
    }
    *result = address;
    return true;
}

bool crust_eval_function(CrustEval *eval, CrustDecl *declaration, void *result)
{
    EvalDecl *prepared;
    void *address;
    if (declaration == NULL || !is_function(declaration) || result == NULL)
        return error_at(eval, no_location(), "function evaluation requires a function and result storage");
    prepared = get_declaration(eval, declaration);
    if (prepared == NULL || !function_address(eval, prepared, &address)) return false;
    memcpy(result, &address, sizeof(address));
    return true;
}

bool crust_eval_call(CrustEval *eval, CrustDecl *declaration,
                   void *const *arguments, size_t count, void *result)
{
    EvalDecl *prepared;
    EvalValue value;
    size_t index;
    if (declaration == NULL || !is_function(declaration) || declaration->type == NULL)
        return error_at(eval, no_location(), "call evaluation requires a checked function");
    if (count != declaration->type->param_count || (count != 0 && arguments == NULL))
        return error_at(eval, declaration->loc, "evaluation argument count mismatch");
    for (index = 0; index < count; ++index)
        if (arguments[index] == NULL)
            return error_at(eval, declaration->loc, "evaluation argument storage is null");
    if (declaration->type->base->kind != CRUST_T_UNIT && result == NULL)
        return error_at(eval, declaration->loc, "evaluation result storage is null");
    prepared = get_declaration(eval, declaration);
    if (prepared == NULL || !call_declaration(eval, prepared, arguments, &value)) return false;
    store_value(result, declaration->type->base, value);
    return true;
}

bool crust_eval_expression(CrustEval *eval, CrustExpr *expression, void *result)
{
    EvalPlan *plan;
    EvalFrame *frame;
    EvalValue value;
    bool success;
    if (expression == NULL || expression->type == NULL ||
        (expression->type->kind != CRUST_T_UNIT && result == NULL))
        return error_at(eval, no_location(), "expression evaluation requires checked syntax and result storage");
    plan = crust_map_get(&eval->expressions, (uintptr_t)expression);
    if (plan == NULL) {
        plan = allocate(eval, sizeof(*plan), CRUST_ALIGNOF(EvalPlan));
        if (plan == NULL || !prepare_expression(eval, plan, expression) ||
            !crust_try_map_set(eval->context, &eval->expressions, (uintptr_t)expression, plan)) return false;
    }
    frame = acquire_frame(eval, plan);
    if (frame == NULL) return false;
    success = eval_expression(eval, frame, expression, &value);
    if (success) store_value(result, expression->type, value);
    release_frame(frame);
    return success;
}

bool crust_eval_statement(CrustEval *eval, CrustStmt *statement, bool *returned, int32_t *status)
{
    EvalPlan *plan;
    EvalFrame *frame;
    EvalValue value = {0, NULL};
    EvalFlow flow = EVAL_NEXT;
    bool success;
    if (statement == NULL || returned == NULL || status == NULL)
        return error_at(eval, no_location(), "statement evaluation requires syntax and return storage");
    *returned = false;
    *status = 0;
    plan = crust_map_get(&eval->statements, (uintptr_t)statement);
    if (plan == NULL) {
        plan = allocate(eval, sizeof(*plan), CRUST_ALIGNOF(EvalPlan));
        if (plan == NULL || !prepare_statement(eval, plan, statement, true) ||
            !crust_try_map_set(eval->context, &eval->statements, (uintptr_t)statement, plan)) return false;
    }
    frame = acquire_frame(eval, plan);
    if (frame == NULL) return false;
    success = eval_statement(eval, frame, statement, &flow, &value);
    if (success && flow == EVAL_RETURN) {
        *returned = true;
        memcpy(status, &value.bits, sizeof(*status));
    }
    release_frame(frame);
    return success;
}

bool crust_eval_bind(CrustEval *eval, CrustSymbol *symbol, void *storage)
{
    void *previous;
    if (symbol == NULL || symbol->type == NULL || storage == NULL ||
        (symbol->kind != CRUST_SYM_LOCAL && symbol->kind != CRUST_SYM_PARAM))
        return error_at(eval, no_location(), "evaluation binding requires a local symbol and storage");
    previous = crust_map_get(&eval->roots, (uintptr_t)symbol);
    if (previous != NULL && previous != storage)
        return error_at(eval, symbol->loc, "evaluation binding storage cannot change");
    return crust_try_map_set(eval->context, &eval->roots, (uintptr_t)symbol, storage);
}
