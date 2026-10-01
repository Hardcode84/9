#ifndef CRUST_EVAL_STORAGE_H
#define CRUST_EVAL_STORAGE_H

#include "crust0.h"

#include <string.h>

/* Read exact scalar storage. Unit has no storage and returns zero. */
static inline uint64_t crust_eval_load_bits(const void *address, CrustType *type)
{
    uint64_t value = 0;
    if (type->kind != CRUST_T_UNIT)
        memcpy(&value, address, (size_t)type->size);
    return value;
}

/* Write the value to exact non-unit scalar storage. */
static inline void crust_eval_store_bits(void *address, CrustType *type, uint64_t value)
{
    memcpy(address, &value, (size_t)type->size);
}

/* An argument cell begins with its scalar value in native representation. */
static inline void crust_eval_argument_bits(uint64_t *storage, uint64_t value) { *storage = value; }

/* Return the root status from its low 32 value bits. */
static inline int32_t crust_eval_status_bits(uint64_t value)
{
    int32_t status;
    memcpy(&status, &value, sizeof(status));
    return status;
}

#endif
