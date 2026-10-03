/* SPDX-License-Identifier: Apache-2.0 */

#include <stdio.h>
#include <stdlib.h>

void *__real_Z3_mk_config(void);
void *__wrap_Z3_mk_config(void);

void *__wrap_Z3_mk_config(void)
{
    if (getenv("CRUST_TEST_NO_SOLVER") != NULL) {
        fputs("import called the proof solver\n", stderr);
        abort();
    }
    return __real_Z3_mk_config();
}
