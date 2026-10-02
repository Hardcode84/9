/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST_CORE_INTERNAL_H
#define CRUST_CORE_INTERNAL_H

#include "crust0.h"

#ifdef CRUST_AMALGAMATED
#define CRUST_STATIC static
#else
#define CRUST_STATIC
#endif

CRUST_STATIC void crust_map_reserve(CrustContext *ctx, CrustMap *map, size_t count);

/* These helpers cross the allocator or native ABI translation-unit boundary. */
void *crust_profile_allocate(size_t size);
void crust_type_compare_reset(CrustContext *ctx);
bool crust_type_compare_seen(CrustContext *ctx, const CrustType *left, const CrustType *right);

#endif
