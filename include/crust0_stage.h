/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST0_STAGE_H
#define CRUST0_STAGE_H

#include "crust0.h"

/* The compilation entry borrows this request. Its context is initially empty.
   Source bytes and arguments remain live through context destruction.
   argv contains the arguments after the source path; argc can be zero. */
typedef struct {
    CrustContext *context;
    CrustSource *source;
    size_t target_begin;
    int32_t argc;
    char **argv;
} CrustBuild;

#endif
