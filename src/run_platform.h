/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST_RUN_PLATFORM_H
#define CRUST_RUN_PLATFORM_H

#include "crust0_run.h"

typedef struct CrustNativeModule CrustNativeModule;

/* Return an absolute path in context storage without resolving symbolic links. */
char *crust_run_root_path(CrustContext *context, const char *path);
/* Keep loaded code live until crust_run_native_destroy. Paths are explicit. */
bool crust_run_native_link(CrustRun *run, CrustNativeModule **modules, const char *path);
/* Resolve one name across the process and loaded modules. Reject ambiguity. */
bool crust_run_native_resolve(CrustRun *run, CrustNativeModule *modules, CrustDecl *declaration,
                              void **result);
/* All native calls and callbacks must be complete. Report unload failures. */
bool crust_run_native_destroy(CrustRun *run, CrustNativeModule *modules);

#endif
