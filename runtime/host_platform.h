/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST_HOST_PLATFORM_H
#define CRUST_HOST_PLATFORM_H

#include <stddef.h>
#include <stdio.h>

/* Resize a host file buffer, preserving its bytes. Failure keeps the old buffer. */
void *crust_host_resize(void *data, size_t size);
/* Open a host path in binary read or write mode. */
FILE *crust_host_open(const char *path, const char *mode);
/* Write exact bytes to a stream, reporting a partial write as failure. */
int crust_host_write_bytes(FILE *file, const unsigned char *data, size_t size);

#endif
