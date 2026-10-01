#ifndef RMD0_HOST_H
#define RMD0_HOST_H

#include <stddef.h>
#include <stdint.h>

void *rmd0_host_alloc(size_t size, size_t alignment);
void rmd0_host_free(void *data);
void rmd0_host_move_bytes(void *dst, const void *src, size_t size);
int32_t rmd0_host_read_file(const char *path, unsigned char **data, size_t *size);
int32_t rmd0_host_write_file(const char *path, const unsigned char *data, size_t size);
int32_t rmd0_host_write_stream(uint32_t stream, const unsigned char *data, size_t size);

#endif
