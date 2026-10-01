/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST_CORE_INTERNAL_H
#define CRUST_CORE_INTERNAL_H

#include "crust0.h"

void crust_map_reserve(CrustContext *ctx, CrustMap *map, size_t count);
void crust_type_compare_reset(CrustContext *ctx);
bool crust_type_compare_seen(CrustContext *ctx, const CrustType *left, const CrustType *right);

#endif
