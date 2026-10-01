#ifndef RESOURCE_SQLITE_COMMON_H
#define RESOURCE_SQLITE_COMMON_H

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include "sqlite3.h"

typedef struct {
    uint64_t rows;
    int operation;
    int finalized;
    int closed;
} QueryContext;

static int run_query(sqlite3 *database, QueryContext *context);

static inline int write_bytes(int stream, const unsigned char *bytes, size_t size)
{
    size_t offset = 0;
    while (offset < size) {
        ssize_t count = write(stream, bytes + offset, size - offset);
        if (count <= 0)
            return SQLITE_IOERR;
        offset += (size_t)count;
    }
    return SQLITE_OK;
}

static inline int write_number(int stream, uint64_t value)
{
    unsigned char bytes[20];
    size_t begin = sizeof(bytes);
    do {
        bytes[--begin] = (unsigned char)('0' + value % 10);
        value /= 10;
    } while (value != 0);
    return write_bytes(stream, bytes + begin, sizeof(bytes) - begin);
}

static inline int write_value(int kind, const unsigned char *bytes,
                              size_t size, QueryContext *context)
{
    static const unsigned char hex[] = "0123456789abcdef";
    unsigned char marker = kind == SQLITE_NULL ? 'N' :
        kind == SQLITE_BLOB ? 'B' : kind == SQLITE_TEXT ? 'T' :
        kind == SQLITE_INTEGER ? 'I' : 'R';
    size_t index;
    int result = write_bytes(1, &marker, 1);
    if (result == SQLITE_OK && kind != SQLITE_NULL)
        result = write_bytes(1, (const unsigned char *)" ", 1);
    for (index = 0; result == SQLITE_OK && index < size; ++index) {
        unsigned char pair[2];
        pair[0] = hex[bytes[index] >> 4];
        pair[1] = hex[bytes[index] & 15];
        result = write_bytes(1, pair, sizeof(pair));
    }
    if (result == SQLITE_OK)
        result = write_bytes(1, (const unsigned char *)"\n", 1);
    if (result == SQLITE_OK)
        ++context->rows;
    return result;
}

static inline int write_summary(QueryContext *context)
{
    int result = write_bytes(1, (const unsigned char *)"rows ", 5);
    if (result == SQLITE_OK)
        result = write_number(1, context->rows);
    if (result == SQLITE_OK)
        result = write_bytes(1, (const unsigned char *)"\n", 1);
    return result;
}

static inline int write_errors(const QueryContext *context)
{
    int result = write_bytes(2, (const unsigned char *)"error ", 6);
    if (result == SQLITE_OK)
        result = write_number(2, (uint64_t)context->operation);
    if (result == SQLITE_OK)
        result = write_bytes(2, (const unsigned char *)" ", 1);
    if (result == SQLITE_OK)
        result = write_number(2, (uint64_t)context->finalized);
    if (result == SQLITE_OK)
        result = write_bytes(2, (const unsigned char *)" ", 1);
    if (result == SQLITE_OK)
        result = write_number(2, (uint64_t)context->closed);
    if (result == SQLITE_OK)
        result = write_bytes(2, (const unsigned char *)"\n", 1);
    return result;
}

int main(int argc, char **argv)
{
    sqlite3 *database = NULL;
    QueryContext context = { 0, SQLITE_OK, SQLITE_OK, SQLITE_OK };
    int result;
    if (argc != 2) {
        (void)write_bytes(2, (const unsigned char *)"usage: sqlite-reader DATABASE\n", 30);
        return 2;
    }
    context.operation = sqlite3_open_v2(argv[1], &database, SQLITE_OPEN_READONLY, NULL);
    if (context.operation == SQLITE_OK)
        context.operation = run_query(database, &context);
    if (database != NULL) {
        context.closed = sqlite3_close(database);
        if (context.closed == SQLITE_OK)
            database = NULL;
    }
    if (context.operation == SQLITE_OK && context.finalized == SQLITE_OK && context.closed == SQLITE_OK)
        context.operation = write_summary(&context);
    result = context.operation != SQLITE_OK || context.finalized != SQLITE_OK || context.closed != SQLITE_OK;
    if (result != 0 && write_errors(&context) != SQLITE_OK)
        result = 1;
    if (database != NULL) {
        int cleanup = sqlite3_close(database);
        if (cleanup != SQLITE_OK) {
            (void)write_bytes(2, (const unsigned char *)"fatal close\n", 12);
            _Exit(2);
        }
    }
    return result;
}

#endif
