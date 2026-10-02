/* SPDX-License-Identifier: Apache-2.0 */

#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>

int getentropy(void *buffer, size_t length)
{
    const char *mode = getenv("CRUST_TEST_ENTROPY");
    if (mode == NULL || strcmp(mode, "collision") != 0) {
        errno = EIO;
        return -1;
    }
    memset(buffer, 0, length);
    return 0;
}
