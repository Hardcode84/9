/* SPDX-License-Identifier: Apache-2.0 */

#ifndef SOURCE_ORDER_PROOF_H
#define SOURCE_ORDER_PROOF_H
#include "crust0.h"

typedef struct ProofSession ProofSession;
typedef struct ProofAction ProofAction;
struct ProofAction {
    CrustExpr *call;
    size_t next_offset;
};
struct ProofSession {
    CrustContext *owner;
    CrustSource *source;
    size_t cursor;
    int32_t (*reader)(void *, void *, void *);
    int32_t (*backend)(void *, void *, void *);
    CrustContext *target;
    char **argv;
    int32_t (*pending)(void *);
    CrustSource *target_source;
    size_t switch_offset;
    size_t selections;
    size_t reads;
    size_t includes;
    size_t emits;
    size_t allocations;
    size_t releases;
    int32_t argc;
    bool root_done;
    bool reader_active;
    bool custom_started;
};
#endif
