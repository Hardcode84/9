/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0.h"

#include <limits.h>

#if !defined(__linux__) || !defined(__x86_64__)
#error CRUST0 version 0.1 requires a Linux x86-64 host
#endif

typedef char
    CrustHostProfile[(CHAR_BIT == 8 && sizeof(void *) == 8 && sizeof(size_t) == 8 &&
                      sizeof(CrustTypeKind) == 4 && sizeof(short) == 2 && sizeof(int) == 4 &&
                      sizeof(long) == 8 && sizeof(bool) == 1 && sizeof(void (*)(void)) == 8)
                         ? 1
                         : -1];
