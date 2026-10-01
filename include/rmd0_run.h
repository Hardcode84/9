#ifndef RMD0_RUN_H
#define RMD0_RUN_H

#include "rmd0.h"
#include "rmd0_eval.h"

typedef struct RmdRun RmdRun;
typedef struct RmdRunState RmdRunState;

/* A runner borrows its source and context through destruction. Readers advance
   cursor and return a non-null action, return null at source EOF, or set returned
   to finish the runner. Each action
   uses the executor selected before its reader was called. Input-consuming
   execution can advance cursor further. Source storage remains immutable. */
struct RmdRun {
    RmdContext *context;
    RmdSource *source;
    size_t cursor;
    bool (*read)(RmdRun *run, void **action);
    bool (*execute)(RmdRun *run, void *action);
    void *user;
    RmdEval *eval;
    RmdRootScope scope;
    uint64_t next_identity;
    int32_t argc;
    char **argv;
    bool returned;
    int32_t status;
    RmdRunState *state;
};

/* Initialize an empty runner using a context with checked installed interfaces.
   Arguments exclude the executable and root path, and end with a null pointer.
   Failure retains a diagnostic. Destroy an initialized runner before context. */
bool rmd_run_init(RmdRun *run, RmdContext *context, RmdSource *source,
                  int32_t argc, char **argv);
/* All operations and callbacks must be complete. Retain a diagnostic on failure. */
bool rmd_run_destroy(RmdRun *run);
/* Execute in source order through EOF or explicit return. Retain a diagnostic
   on failure. The returned program status must be between zero and 255. */
bool rmd_run_loop(RmdRun *run);
/* Read one RMD action without interpreting bytes after its delimiter. */
bool rmd_run_read(RmdRun *run, void **action);
/* Check and execute an action from rmd_run_read. Root locals persist. */
bool rmd_run_execute(RmdRun *run, void *action);
/* Check only this owned unit and prepare its host declarations. The unit must
   already be linked into context. Reject root-local name conflicts. */
bool rmd_run_check_unit(RmdRun *run, RmdUnit *unit_value);
/* Load an explicit native path containing '/'. Keep its code live through
   runner destruction. Check symbol conflicts on first resolution; a resolved
   callable keeps its address for the evaluator lifetime. */
bool rmd_run_link(RmdRun *run, const char *path);
/* Print a retained diagnostic with its original source location. */
void rmd_run_diagnostic(const RmdContext *context);

#endif
