/* SPDX-License-Identifier: Apache-2.0 */

#include <errno.h>
#include <pthread.h>

int __real_pthread_create(pthread_t *thread, const pthread_attr_t *attributes,
                          void *(*entry)(void *), void *data);
int __wrap_pthread_create(pthread_t *thread, const pthread_attr_t *attributes,
                          void *(*entry)(void *), void *data);

int __wrap_pthread_create(pthread_t *thread, const pthread_attr_t *attributes,
                          void *(*entry)(void *), void *data)
{
    static unsigned calls;
    if (++calls == 3)
        return EAGAIN;
    return __real_pthread_create(thread, attributes, entry, data);
}
