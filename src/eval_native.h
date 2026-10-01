/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST_EVAL_NATIVE_H
#define CRUST_EVAL_NATIVE_H

#include "crust0.h"

typedef struct CrustEvalAbi CrustEvalAbi;
typedef struct CrustEvalClosure CrustEvalClosure;
typedef uint64_t (*CrustEvalCallback)(void *user, void **arguments);

/* Inputs must have complete, checked scalar signature facts.
   Failure retains an allocation diagnostic and leaves result unchanged. */
bool crust_eval_native_type_equal(CrustContext *context, CrustType *left, CrustType *right,
                                  bool *result);
/* The context owns the result. Failure returns null with a diagnostic. */
CrustEvalAbi *crust_eval_native_abi(CrustContext *context, CrustType *type, CrustLoc location);
/* Call a non-null address with this exact ABI. Arguments point to typed storage.
   Return scalar value bits, or zero for a unit result. */
uint64_t crust_eval_native_call(CrustEvalAbi *abi, void *address, void *const *arguments);
/* Keep the ABI, callback, and user state live until the last call. The callback
   returns scalar value bits. Failure returns null with a diagnostic. */
CrustEvalClosure *crust_eval_native_closure(CrustContext *context, CrustEvalAbi *abi,
                                            CrustEvalCallback callback, void *user,
                                            CrustLoc location, void **address);
/* End every use of the callable address before this call. */
void crust_eval_native_closure_free(CrustEvalClosure *closure);

#endif
