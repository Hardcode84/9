#ifndef SOURCE_ORDER_PROOF_H
#define SOURCE_ORDER_PROOF_H
#include "rmd0.h"

typedef struct ProofSession ProofSession;
typedef struct ProofAction ProofAction;
struct ProofAction { RmdExpr *call; size_t next_offset; };
struct ProofSession {
    RmdContext *owner;
    RmdSource *source;
    size_t cursor;
    int32_t (*reader)(void *, void *, void *);
    int32_t (*backend)(void *, void *, void *);
    RmdContext *target;
    int32_t argc;
    char **argv;
    int32_t (*pending)(void *);
    RmdSource *target_source;
    size_t switch_offset;
    size_t selections;
    size_t reads;
    size_t includes;
    size_t emits;
    size_t allocations;
    size_t releases;
    bool root_done;
    bool reader_active;
    bool custom_started;
};
#endif
