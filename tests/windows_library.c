/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0_abi.h"

#include <stdbool.h>
#include <stdint.h>
#include <windows.h>

CRUST_ABI_EXPORT;

int8_t seed_i8(int8_t value);
uint8_t seed_u8(uint8_t value);
int16_t seed_i16(int16_t value);
uint16_t seed_u16(uint16_t value);
int32_t seed_i32(int32_t value);
uint32_t seed_u32(uint32_t value);
int64_t seed_i64(int64_t value);
uint64_t seed_u64(uint64_t value);
float seed_f32(float value);
bool seed_bool(bool value);
void *seed_pointer(void *value);
float seed_mixed(int8_t a, float b, uint64_t c, bool d, float e, int32_t f, uint8_t g, float h);
float seed_callback(float (*callback)(int8_t, float, uint64_t, bool, float, int32_t, uint8_t,
                                      float));
uint64_t seed_integer_callback(uint64_t (*callback)(uint64_t));
bool seed_bool_callback(bool (*callback)(bool));
void seed_write(uint32_t *pointer, uint32_t value);
int32_t seed_unwind(void);
int32_t seed_readonly(const char *path, int32_t enabled);

int8_t seed_i8(int8_t value) { return value; }
uint8_t seed_u8(uint8_t value) { return value; }
int16_t seed_i16(int16_t value) { return value; }
uint16_t seed_u16(uint16_t value) { return value; }
int32_t seed_i32(int32_t value) { return value; }
uint32_t seed_u32(uint32_t value) { return value; }
int64_t seed_i64(int64_t value) { return value; }
uint64_t seed_u64(uint64_t value) { return value; }
float seed_f32(float value) { return value; }
bool seed_bool(bool value) { return value; }
void *seed_pointer(void *value) { return value; }
float seed_mixed(int8_t a, float b, uint64_t c, bool d, float e, int32_t f, uint8_t g, float h)
{
    return (float)a + b + (float)c + (d ? 1.0f : 0.0f) + e + (float)f + (float)g + h;
}
float seed_callback(float (*callback)(int8_t, float, uint64_t, bool, float, int32_t, uint8_t,
                                      float))
{
    return callback(-8, 0.5f, 16, true, 1.25f, -32, 255, 2.5f);
}
uint64_t seed_integer_callback(uint64_t (*callback)(uint64_t)) { return callback(UINT64_MAX); }
bool seed_bool_callback(bool (*callback)(bool)) { return callback(true); }
void seed_write(uint32_t *pointer, uint32_t value) { *pointer = value; }

int32_t seed_readonly(const char *path, int32_t enabled)
{
    wchar_t wide[32768];
    DWORD attributes;
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, 32768) == 0)
        return 1;
    attributes = GetFileAttributesW(wide);
    if (attributes == INVALID_FILE_ATTRIBUTES)
        return 1;
    attributes =
        enabled ? attributes | FILE_ATTRIBUTE_READONLY : attributes & ~FILE_ATTRIBUTE_READONLY;
    return SetFileAttributesW(wide, attributes) ? 0 : 1;
}

int32_t seed_unwind(void)
{
    CONTEXT context;
    DWORD64 base = 0, frame = 0, previous;
    PVOID handler = NULL;
    PRUNTIME_FUNCTION entry;
    unsigned int index;
    RtlCaptureContext(&context);
    /* Unwind this C frame and then the generated caller with its large frame. */
    for (index = 0; index < 2; ++index) {
        entry = RtlLookupFunctionEntry(context.Rip, &base, NULL);
        if (entry == NULL)
            return 1;
        previous = context.Rsp;
        (void)RtlVirtualUnwind(UNW_FLAG_NHANDLER, base, context.Rip, entry, &context, &handler,
                               &frame, NULL);
        if (context.Rsp <= previous || context.Rip == 0)
            return 2;
    }
    return 0;
}
