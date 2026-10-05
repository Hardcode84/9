/* SPDX-License-Identifier: Apache-2.0 */
#include <inttypes.h>
#include <stdio.h>

int32_t ub_print(uint64_t value);
int32_t ub_row(const unsigned char *name, uint64_t value);

int32_t ub_print(uint64_t value) { return printf("%" PRIu64 "\n", value); }

int32_t ub_row(const unsigned char *name, uint64_t value)
{
    return printf("%s %" PRIu64 "\n", name, value);
}
