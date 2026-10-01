/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST0_EVAL_H
#define CRUST0_EVAL_H

#include "crust0.h"

typedef struct CrustEval CrustEval;

typedef struct {
    bool (*resolve)(void *user, CrustDecl *declaration, void **address);
    void *user;
} CrustEvalOptions;

/* The context owns all evaluator storage. Checked syntax and bound storage must
   remain live until destruction. An evaluator permits synchronous reentry, but
   requires exclusive access from one thread. A resolver failure must record a
   diagnostic in the context and return false. */
CrustEval *crust_eval_create(CrustContext *context, const CrustEvalOptions *options);
/* End all native uses of returned function pointers before destruction.
   Destroy the evaluator before its context and native library handles. */
void crust_eval_destroy(CrustEval *eval);

/* Register checked declaration facts without native symbol lookup. Native names
   must have compatible ABI types. A published callable cannot change identity. */
bool crust_eval_prepare(CrustEval *eval, CrustDecl *declaration);
/* Write a native function pointer to exact function-typed result storage. */
bool crust_eval_function(CrustEval *eval, CrustDecl *declaration, void *result);
/* Arguments and result point to exact typed storage. A unit result needs no
   storage. Resource and lookup failures return false with a diagnostic. */
bool crust_eval_call(CrustEval *eval, CrustDecl *declaration, void *const *arguments, size_t count,
                     void *result);
/* Local references must refer to persistent root variables or bound storage. */
bool crust_eval_expression(CrustEval *eval, CrustExpr *expression, void *result);
/* Execute one checked root statement. Top-level variables retain their storage.
   A root return sets returned and its i32 status. Other statements clear returned.
   Required traps and failures inside native callbacks end the process. */
bool crust_eval_statement(CrustEval *eval, CrustStmt *statement, bool *returned, int32_t *status);
/* Bind a root symbol to borrowed storage of its exact type. The storage address
   for a bound symbol cannot change before evaluator destruction. */
bool crust_eval_bind(CrustEval *eval, CrustSymbol *symbol, void *storage);

#endif
