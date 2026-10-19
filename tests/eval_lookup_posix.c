/* SPDX-License-Identifier: Apache-2.0 */

#define _GNU_SOURCE
#include "eval_lookup.h"
#include <dlfcn.h>

void *eval_test_lookup(const char *name) { return dlsym(RTLD_DEFAULT, name); }
