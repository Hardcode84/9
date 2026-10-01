#ifndef CRUST_DRIVER_PLATFORM_H
#define CRUST_DRIVER_PLATFORM_H

#include "crust0_x64.h"

/* Publish regular files atomically. Open other paths as streams. A null path
   or "-" selects stdout. Report output failures and retain backend diagnostics. */
bool crust_driver_emit_file(CrustX64Program *program, const char *path);

#endif
