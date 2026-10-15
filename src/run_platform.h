/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST_RUN_PLATFORM_H
#define CRUST_RUN_PLATFORM_H

#include "crust0_run.h"

/* Return an absolute path in context storage without resolving symbolic links. */
char *crust_run_root_path(CrustContext *context, const char *path);
/* Keep loaded code live until crust_run_native_destroy. */
CrustLibrary *crust_run_native_open(CrustRun *run, CrustLibrary **modules, const char *path);
/* Resolve only the predefined process host interface. */
bool crust_run_native_host(CrustRun *run, CrustDecl *declaration, void **result);
/* Resolve an export owned by the selected library. */
bool crust_run_native_symbol(CrustRun *run, CrustLibrary *library, CrustDecl *declaration,
                             void **result);
/* All native calls and callbacks must be complete. Report unload failures. */
bool crust_run_native_destroy(CrustRun *run, CrustLibrary *modules);

#endif
