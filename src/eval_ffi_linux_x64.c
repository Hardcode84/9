#include "core_internal.h"
#include "eval_native.h"

#include <ffi.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>

struct CrustEvalAbi {
    ffi_cif cif;
    ffi_type **arguments;
    CrustType *type;
};

struct CrustEvalClosure {
    ffi_closure *allocation;
    CrustEvalAbi *abi;
    CrustEvalCallback callback;
    void *user;
};

static CrustTypeKind native_kind(CrustType *type)
{
    if (type->kind == CRUST_T_ISIZE)
        return CRUST_T_I64;
    if (type->kind == CRUST_T_USIZE)
        return CRUST_T_U64;
    return type->kind;
}

static bool native_type_equal(CrustContext *context, CrustType *left, CrustType *right)
{
    size_t index;
    if (left == right)
        return true;
    if (native_kind(left) != native_kind(right))
        return false;
    if (left->kind != CRUST_T_FUNCTION)
        return left->kind != CRUST_T_RECORD && left->kind != CRUST_T_ARRAY;
    if (left->param_count != right->param_count)
        return false;
    if (crust_type_compare_seen(context, left, right))
        return true;
    if (!native_type_equal(context, left->base, right->base))
        return false;
    for (index = 0; index < left->param_count; ++index)
        if (!native_type_equal(context, left->params[index], right->params[index]))
            return false;
    return true;
}

bool crust_eval_native_type_equal(CrustContext *context, CrustType *left, CrustType *right,
                                  bool *result)
{
    CrustFailureFrame frame;
    bool equal;
    frame.previous = context->failure;
    context->failure = &frame;
    if (setjmp(frame.jump) != 0) {
        context->failure = frame.previous;
        return false;
    }
    crust_type_compare_reset(context);
    equal = native_type_equal(context, left, right);
    crust_type_compare_reset(context);
    context->failure = frame.previous;
    *result = equal;
    return true;
}

static ffi_type *ffi_value_type(CrustType *type)
{
    switch (type->kind) {
    case CRUST_T_I8:
        return &ffi_type_sint8;
    case CRUST_T_U8:
    case CRUST_T_BOOL:
        return &ffi_type_uint8;
    case CRUST_T_I16:
        return &ffi_type_sint16;
    case CRUST_T_U16:
        return &ffi_type_uint16;
    case CRUST_T_I32:
        return &ffi_type_sint32;
    case CRUST_T_U32:
        return &ffi_type_uint32;
    case CRUST_T_I64:
    case CRUST_T_ISIZE:
        return &ffi_type_sint64;
    case CRUST_T_U64:
    case CRUST_T_USIZE:
        return &ffi_type_uint64;
    case CRUST_T_UNIT:
        return &ffi_type_void;
    case CRUST_T_POINTER:
    case CRUST_T_FUNCTION:
        return &ffi_type_pointer;
    default:
        abort();
    }
}

CrustEvalAbi *crust_eval_native_abi(CrustContext *context, CrustType *type, CrustLoc location)
{
    CrustEvalAbi *abi;
    size_t index;
    if (type->param_count > UINT_MAX || type->param_count > SIZE_MAX / sizeof(ffi_type *)) {
        crust_set_error(context, location.source, location.offset,
                        "native parameter count exceeds the libffi limit");
        return NULL;
    }
    abi = crust_try_alloc(context, sizeof(*abi), CRUST_ALIGNOF(CrustEvalAbi));
    if (abi == NULL)
        return NULL;
    abi->type = type;
    if (type->param_count != 0) {
        abi->arguments = crust_try_alloc(context, type->param_count * sizeof(*abi->arguments),
                                         CRUST_ALIGNOF(ffi_type *));
        if (abi->arguments == NULL)
            return NULL;
    }
    for (index = 0; index < type->param_count; ++index)
        abi->arguments[index] = ffi_value_type(type->params[index]);
    if (ffi_prep_cif(&abi->cif, FFI_DEFAULT_ABI, (unsigned)type->param_count,
                     ffi_value_type(type->base), abi->arguments) != FFI_OK) {
        crust_set_error(context, location.source, location.offset,
                        "libffi rejected the native function signature");
        return NULL;
    }
    return abi;
}

uint64_t crust_eval_native_call(CrustEvalAbi *abi, void *address, void *const *arguments)
{
    void (*function)(void);
    ffi_arg returned = 0;
    uint64_t mask;
    memcpy(&function, &address, sizeof(function));
    ffi_call(&abi->cif, function, &returned, (void **)arguments);
    if (abi->type->base->kind == CRUST_T_UNIT)
        return 0;
    mask = UINT64_MAX >> (64 - (unsigned)(abi->type->base->size * 8));
    return (uint64_t)returned & mask;
}

static void native_callback(ffi_cif *cif, void *returned, void **arguments, void *user)
{
    CrustEvalClosure *closure = user;
    CrustType *type = closure->abi->type->base;
    uint64_t value = closure->callback(closure->user, arguments);
    unsigned width;
    uint64_t mask;
    ffi_arg bits;
    (void)cif;
    if (type->kind == CRUST_T_UNIT)
        return;
    width = (unsigned)(type->size * 8);
    mask = UINT64_MAX >> (64 - width);
    value &= mask;
    if (crust_type_signed(type) && (value & (UINT64_C(1) << (width - 1))) != 0)
        value |= ~mask;
    bits = (ffi_arg)value;
    memcpy(returned, &bits, sizeof(bits));
}

CrustEvalClosure *crust_eval_native_closure(CrustContext *context, CrustEvalAbi *abi,
                                            CrustEvalCallback callback, void *user,
                                            CrustLoc location, void **address)
{
    CrustEvalClosure *closure =
        crust_try_alloc(context, sizeof(*closure), CRUST_ALIGNOF(CrustEvalClosure));
    if (closure == NULL)
        return NULL;
    closure->abi = abi;
    closure->callback = callback;
    closure->user = user;
    closure->allocation = ffi_closure_alloc(sizeof(ffi_closure), address);
    if (closure->allocation == NULL) {
        crust_set_error(context, location.source, location.offset,
                        "native callback allocation failed");
        return NULL;
    }
    if (ffi_prep_closure_loc(closure->allocation, &abi->cif, native_callback, closure, *address) !=
        FFI_OK) {
        ffi_closure_free(closure->allocation);
        crust_set_error(context, location.source, location.offset,
                        "libffi rejected the native callback");
        return NULL;
    }
    return closure;
}

void crust_eval_native_closure_free(CrustEvalClosure *closure)
{
    ffi_closure_free(closure->allocation);
}
