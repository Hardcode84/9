#ifndef RMD0_EVAL_H
#define RMD0_EVAL_H

#include "rmd0.h"

typedef struct RmdEval RmdEval;

typedef struct {
    bool (*resolve)(void *user, RmdDecl *declaration, void **address);
    void *user;
} RmdEvalOptions;

/* The context owns all evaluator storage. Checked syntax and bound storage must
   remain live until destruction. An evaluator permits synchronous reentry, but
   requires exclusive access from one thread. A resolver failure must record a
   diagnostic in the context and return false. */
RmdEval *rmd_eval_create(RmdContext *context, const RmdEvalOptions *options);
/* End all native uses of returned function pointers before destruction.
   Destroy the evaluator before its context and native library handles. */
void rmd_eval_destroy(RmdEval *eval);

/* Register checked declaration facts without native symbol lookup. Native names
   must have compatible ABI types. A published callable cannot change identity. */
bool rmd_eval_prepare(RmdEval *eval, RmdDecl *declaration);
/* Write a native function pointer to exact function-typed result storage. */
bool rmd_eval_function(RmdEval *eval, RmdDecl *declaration, void *result);
/* Arguments and result point to exact typed storage. A unit result needs no
   storage. Resource and lookup failures return false with a diagnostic. */
bool rmd_eval_call(RmdEval *eval, RmdDecl *declaration,
                   void *const *arguments, size_t count, void *result);
/* Local references must refer to persistent root variables or bound storage. */
bool rmd_eval_expression(RmdEval *eval, RmdExpr *expression, void *result);
/* Execute one checked root statement. Top-level variables retain their storage.
   A root return sets returned and its i32 status. Other statements clear returned.
   Required traps and failures inside native callbacks end the process. */
bool rmd_eval_statement(RmdEval *eval, RmdStmt *statement,
                        bool *returned, int32_t *status);
/* Bind a root symbol to borrowed storage of its exact type. The storage address
   for a bound symbol cannot change before evaluator destruction. */
bool rmd_eval_bind(RmdEval *eval, RmdSymbol *symbol, void *storage);

#endif
