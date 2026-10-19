/* SPDX-License-Identifier: Apache-2.0 */

#include "eval_lookup.h"
#include <string.h>
#include <windows.h>

void *eval_test_lookup(const char *name)
{
    FARPROC symbol = GetProcAddress(GetModuleHandleW(NULL), name);
    void *address = NULL;
    if (symbol != NULL)
        memcpy(&address, &symbol, sizeof(address));
    return address;
}
