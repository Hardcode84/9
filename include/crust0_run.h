/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST0_RUN_H
#define CRUST0_RUN_H

#include "crust0.h"
#include "crust0_eval.h"

typedef struct CrustRun CrustRun;
typedef struct CrustRunState CrustRunState;
typedef struct CrustLibrary CrustLibrary;

/* A runner borrows its source and context through destruction. Readers advance
   cursor and return a non-null action, return null at source EOF, or set returned
   to finish the runner. Each action uses the reader, executor, and user pointer
   selected before its reader was called. Input-consuming execution can advance
   cursor further. Source storage remains immutable. */
struct CrustRun {
    CrustRootScope scope;
    CrustContext *context;
    CrustSource *source;
    size_t cursor;
    bool (*read)(CrustRun *run, void *user, void **action);
    bool (*execute)(CrustRun *run, void *user, void *action);
    void *user;
    CrustEval *eval;
    uint64_t next_identity;
    char **argv;
    CrustRunState *state;
    int32_t argc;
    int32_t status;
    bool returned;
};

/* Initialize an empty runner using a context with checked installed interfaces.
   Arguments exclude the executable and root path, and end with a null pointer.
   Failure retains a diagnostic. Destroy an initialized runner before context. */
bool crust_run_init(CrustRun *run, CrustContext *context, CrustSource *source, int32_t argc,
                    char **argv);
/* All operations and callbacks must be complete. Retain a diagnostic on failure. */
bool crust_run_destroy(CrustRun *run);
/* Execute in source order through EOF or explicit return. Retain a diagnostic
   on failure. The returned program status must be between zero and 255. */
bool crust_run_loop(CrustRun *run);
/* Read one CRUST action without interpreting bytes after its delimiter.
   The default reader ignores user. */
bool crust_run_read(CrustRun *run, void *user, void **action);
/* Check and execute an action from crust_run_read. Root locals persist.
   The default executor ignores user. */
bool crust_run_execute(CrustRun *run, void *user, void *action);
/* Check only this owned unit and prepare its host declarations. The unit must
   already be linked into context. Reject root-local name conflicts. */
bool crust_run_check_unit(CrustRun *run, CrustUnit *unit_value);
/* Load an explicit shared-library path containing '/'. Check its API digest.
   Retain the library through runner destruction. Loading publishes no symbols. */
CrustLibrary *crust_run_open(CrustRun *run, const char *path);
/* Bind a checked extern to its exact export in this library. No host or other
   library fallback. The library must belong to run. Bindings are immutable. */
bool crust_run_import(CrustRun *run, CrustLibrary *library, CrustDecl *declaration);
/* Check a unit and bind its extern declarations to this provider. */
bool crust_run_import_unit(CrustRun *run, CrustLibrary *library, CrustUnit *unit_value);
/* Print a retained diagnostic with its original source location. */
void crust_run_diagnostic(const CrustContext *context);

#endif
