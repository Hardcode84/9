#ifndef RMD0_STAGE_H
#define RMD0_STAGE_H

#include "rmd0.h"

/* The compilation entry borrows this request. Its context is initially empty.
   Source bytes and arguments remain live through context destruction.
   argv contains the arguments after the source path; argc can be zero. */
typedef struct {
    RmdContext *context;
    RmdSource *source;
    size_t target_begin;
    int32_t argc;
    char **argv;
} RmdBuild;

#endif
