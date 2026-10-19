/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST_WINDOWS_IO_H
#define CRUST_WINDOWS_IO_H

#include <stdio.h>
#include <wchar.h>

/* Return malloc-owned converted text, or null for invalid input or allocation failure. */
wchar_t *crust_windows_wide(const char *text);
char *crust_windows_utf8(const wchar_t *text);
/* Open a UTF-8 path. The caller owns the returned stream. */
FILE *crust_windows_open(const char *path, const char *mode);

#endif
