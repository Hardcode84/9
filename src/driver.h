#ifndef RMD_DRIVER_H
#define RMD_DRIVER_H

#include "rmd0.h"

void rmd_driver_diagnostic(const RmdContext *ctx);
bool rmd_driver_names(RmdContext *ctx);
RmdDecl *rmd_driver_find(const RmdContext *ctx, const char *name);
int rmd_driver_stage(RmdContext *host, const RmdMeta *meta, RmdSource *source,
                     int argc, char **argv);

#endif
