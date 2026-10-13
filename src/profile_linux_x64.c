/* SPDX-License-Identifier: Apache-2.0 */

#define _GNU_SOURCE
#include "core_internal.h"

#include <errno.h>
#include <float.h>
#include <limits.h>
#include <locale.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

#if !defined(__linux__) || !defined(__x86_64__)
#error CRUST0 version 0.1 requires a Linux x86-64 host
#endif

typedef char
    CrustHostProfile[(CHAR_BIT == 8 && sizeof(float) == 4 && FLT_RADIX == 2 && FLT_MANT_DIG == 24 &&
                      FLT_MAX_EXP == 128 && sizeof(void *) == 8 && sizeof(size_t) == 8 &&
                      sizeof(CrustTypeKind) == 4 && sizeof(short) == 2 && sizeof(int) == 4 &&
                      sizeof(long) == 8 && sizeof(bool) == 1 && sizeof(void (*)(void)) == 8)
                         ? 1
                         : -1];

void *crust_profile_allocate(size_t size)
{
    const size_t huge_page = 2097152;
    void *allocation;
    if (size < huge_page)
        return malloc(size);
    if (posix_memalign(&allocation, huge_page, size) != 0)
        return NULL;
    /* For this aligned anonymous range, EINVAL means the kernel lacks THP support. */
    if (madvise(allocation, size - size % huge_page, MADV_HUGEPAGE) != 0 && errno != EINVAL) {
        free(allocation);
        return NULL;
    }
    return allocation;
}

bool crust_profile_f32(const char *text, uint32_t *bits)
{
    locale_t locale = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
    float value;
    if (locale == (locale_t)0)
        return false;
    value = strtof_l(text, NULL, locale);
    freelocale(locale);
    memcpy(bits, &value, sizeof(value));
    return true;
}
