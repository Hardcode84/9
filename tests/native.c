/* SPDX-License-Identifier: Apache-2.0 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

int8_t native_i8(int8_t value);
uint8_t native_u8(uint8_t value);
int16_t native_i16(int16_t value);
uint16_t native_u16(uint16_t value);
int32_t native_i32(int32_t value);
uint32_t native_u32(uint32_t value);
int64_t native_i64(int64_t value);
uint64_t native_u64(uint64_t value);
bool native_bool(bool value);
void *native_pointer(void *value);
int64_t native_stack(int8_t a, uint8_t b, int16_t c, uint16_t d, int32_t e, uint32_t f, int64_t g,
                     uint64_t h, bool i, int8_t j, uint16_t k, void *p);
int32_t native_callback(int32_t (*function)(int8_t, uint8_t, int16_t, uint16_t, int32_t, uint32_t,
                                            int64_t, uint64_t));
int32_t (*native_function(void))(int32_t);

int8_t native_i8(int8_t value) { return value; }
uint8_t native_u8(uint8_t value) { return value; }
int16_t native_i16(int16_t value) { return value; }
uint16_t native_u16(uint16_t value) { return value; }
int32_t native_i32(int32_t value) { return value; }
uint32_t native_u32(uint32_t value) { return value; }
int64_t native_i64(int64_t value) { return value; }
uint64_t native_u64(uint64_t value) { return value; }
bool native_bool(bool value) { return !value; }
void *native_pointer(void *value) { return value; }

int64_t native_stack(int8_t a, uint8_t b, int16_t c, uint16_t d, int32_t e, uint32_t f, int64_t g,
                     uint64_t h, bool i, int8_t j, uint16_t k, void *p)
{
    if (a != -128 || b != 255 || c != -32768 || d != 65535 || e != INT32_MIN || f != UINT32_MAX ||
        g != INT64_MIN || h != UINT64_MAX || !i || j != -1 || k != 65000 || p == NULL)
        return 0;
    return 42;
}

int32_t native_callback(int32_t (*function)(int8_t, uint8_t, int16_t, uint16_t, int32_t, uint32_t,
                                            int64_t, uint64_t))
{
    return function(-128, 255, -32768, 65535, INT32_MIN, UINT32_MAX, INT64_MIN, UINT64_MAX);
}

static int32_t native_increment(int32_t value) { return value + 1; }

int32_t (*native_function(void))(int32_t) { return native_increment; }
