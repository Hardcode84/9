/* SPDX-License-Identifier: Apache-2.0 */

#define main sqlite_reader_main
#include "callbacks.c"
#undef main

static int checksum(const Bytes *view, QueryContext *context)
{
    size_t index;
    uint64_t sum = context->rows;
    for (index = 0; index < view->size; ++index)
        sum += view->data[index];
    context->rows = sum;
    return SQLITE_OK;
}

static int repeat_columns(Statement *statement, QueryContext *context)
{
    uint64_t index;
    int result;
    if (statement->raw == NULL)
        return SQLITE_MISUSE;
    result = sqlite3_step(statement->raw);
    statement->at_row = result == SQLITE_ROW;
    if (result != SQLITE_ROW)
        return result;
    for (index = 0; index < 500000; ++index) {
        result = with_blob(statement, 0, context, checksum);
        if (result != SQLITE_OK)
            return result;
    }
    return SQLITE_OK;
}

int main(void)
{
    sqlite3 *database = NULL;
    QueryContext context = {0, SQLITE_OK, SQLITE_OK, SQLITE_OK};
    context.operation = sqlite3_open_v2(":memory:", &database, SQLITE_OPEN_READONLY, NULL);
    if (context.operation == SQLITE_OK)
        context.operation = with_statement(database, "SELECT x'000102030405060708090a0b0c0d0e0f'",
                                           &context, repeat_columns);
    if (database != NULL)
        context.closed = sqlite3_close(database);
    if (context.operation != SQLITE_OK || context.finalized != SQLITE_OK ||
        context.closed != SQLITE_OK) {
        write_errors(&context);
        if (context.closed != SQLITE_OK && sqlite3_close(database) != SQLITE_OK)
            _Exit(2);
        return 1;
    }
    if (context.rows != 60000000)
        return 2;
    return write_summary(&context);
}
