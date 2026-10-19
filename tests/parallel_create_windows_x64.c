/* SPDX-License-Identifier: Apache-2.0 */

#include <stdint.h>

uintptr_t __real__beginthreadex(void *security, unsigned stack, unsigned (*entry)(void *),
                                void *data, unsigned flags, unsigned *id);
uintptr_t __wrap__beginthreadex(void *security, unsigned stack, unsigned (*entry)(void *),
                                void *data, unsigned flags, unsigned *id);

uintptr_t __wrap__beginthreadex(void *security, unsigned stack, unsigned (*entry)(void *),
                                void *data, unsigned flags, unsigned *id)
{
    static unsigned calls;
    if (++calls == 3)
        return 0;
    return __real__beginthreadex(security, stack, entry, data, flags, id);
}
