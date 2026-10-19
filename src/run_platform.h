/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST_RUN_PLATFORM_H
#define CRUST_RUN_PLATFORM_H

#include "crust0_run.h"

/* Execute the launcher with UTF-8 arguments. */
int crust_run_main(int argc, char **argv);
/* Return the selected host ABI name for the launcher version. */
const char *crust_run_profile_name(void);

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
