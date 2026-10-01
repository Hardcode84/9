#include "common.h"

typedef struct { sqlite3_stmt *raw; sqlite3 *database; int at_row; } Statement;
typedef struct { const unsigned char *data; size_t size; int kind; } Bytes;

static int output_bytes(const Bytes *view, QueryContext *context)
{
    return write_value(view->kind, view->data, view->size, context);
}

static int with_blob(Statement *statement, int column, QueryContext *context,
                     int (*body)(const Bytes *, QueryContext *))
{
    Bytes view = { NULL, 0, SQLITE_NULL };
    int size;
    if (statement->raw == NULL || !statement->at_row)
        return SQLITE_MISUSE;
    if (column < 0 || column >= sqlite3_column_count(statement->raw))
        return SQLITE_RANGE;
    view.kind = sqlite3_column_type(statement->raw, column);
    if (view.kind != SQLITE_NULL) {
        view.data = sqlite3_column_blob(statement->raw, column);
        if (view.data == NULL && sqlite3_errcode(statement->database) == SQLITE_NOMEM)
            return SQLITE_NOMEM;
        size = sqlite3_column_bytes(statement->raw, column);
        if (size == 0 && sqlite3_errcode(statement->database) == SQLITE_NOMEM)
            return SQLITE_NOMEM;
        view.size = (size_t)size;
    }
    return body(&view, context);
}

static int query_rows(Statement *statement, QueryContext *context)
{
    int result;
    for (;;) {
        result = sqlite3_step(statement->raw);
        statement->at_row = result == SQLITE_ROW;
        if (result == SQLITE_DONE)
            return SQLITE_OK;
        if (result != SQLITE_ROW)
            return result;
        result = with_blob(statement, 0, context, output_bytes);
        if (result != SQLITE_OK)
            return result;
    }
}

static int with_statement(sqlite3 *database, const char *sql, QueryContext *context,
                          int (*body)(Statement *, QueryContext *))
{
    Statement statement = { NULL, database, 0 };
    int result = sqlite3_prepare_v2(database, sql, -1, &statement.raw, NULL);
    if (result == SQLITE_OK && statement.raw != NULL)
        result = body(&statement, context);
    if (statement.raw != NULL) {
        context->finalized = sqlite3_finalize(statement.raw);
        statement.raw = NULL;
    }
    return result;
}

static int run_query(sqlite3 *database, QueryContext *context)
{
    return with_statement(database, "SELECT value FROM input ORDER BY seq", context, query_rows);
}
