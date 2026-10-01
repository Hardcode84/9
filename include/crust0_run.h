#ifndef CRUST0_RUN_H
#define CRUST0_RUN_H

#include "crust0.h"
#include "crust0_eval.h"

typedef struct CrustRun CrustRun;
typedef struct CrustRunState CrustRunState;

/* A runner borrows its source and context through destruction. Readers advance
   cursor and return a non-null action, return null at source EOF, or set returned
   to finish the runner. Each action
   uses the executor selected before its reader was called. Input-consuming
   execution can advance cursor further. Source storage remains immutable. */
struct CrustRun {
    CrustContext *context;
    CrustSource *source;
    size_t cursor;
    bool (*read)(CrustRun *run, void **action);
    bool (*execute)(CrustRun *run, void *action);
    void *user;
    CrustEval *eval;
    CrustRootScope scope;
    uint64_t next_identity;
    int32_t argc;
    char **argv;
    bool returned;
    int32_t status;
    CrustRunState *state;
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
/* Read one CRUST action without interpreting bytes after its delimiter. */
bool crust_run_read(CrustRun *run, void **action);
/* Check and execute an action from crust_run_read. Root locals persist. */
bool crust_run_execute(CrustRun *run, void *action);
/* Check only this owned unit and prepare its host declarations. The unit must
   already be linked into context. Reject root-local name conflicts. */
bool crust_run_check_unit(CrustRun *run, CrustUnit *unit_value);
/* Load an explicit native path containing '/'. Keep its code live through
   runner destruction. Check symbol conflicts on first resolution; a resolved
   callable keeps its address for the evaluator lifetime. */
bool crust_run_link(CrustRun *run, const char *path);
/* Print a retained diagnostic with its original source location. */
void crust_run_diagnostic(const CrustContext *context);

#endif
