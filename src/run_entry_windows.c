/* SPDX-License-Identifier: Apache-2.0 */

#include "../runtime/windows_io.h"
#include "run_platform.h"

#include <stdio.h>
#include <stdlib.h>

int wmain(int argc, wchar_t **wide);

int wmain(int argc, wchar_t **wide)
{
    char **arguments = calloc((size_t)argc + 1, sizeof(*arguments));
    int index;
    int status = 1;
    if (arguments == NULL)
        return 1;
    for (index = 0; index < argc; ++index) {
        arguments[index] = crust_windows_utf8(wide[index]);
        if (arguments[index] == NULL) {
            fputs("crust: cannot convert command line to UTF-8\n", stderr);
            break;
        }
    }
    if (index == argc)
        status = crust_run_main(argc, arguments);
    for (index = 0; index < argc; ++index)
        free(arguments[index]);
    free(arguments);
    return status;
}
