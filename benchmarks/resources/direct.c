#include "common.h"

static int run_query(sqlite3 *database, QueryContext *context)
{
    sqlite3_stmt *statement = NULL;
    int result = sqlite3_prepare_v2(database, "SELECT value FROM input ORDER BY seq", -1, &statement, NULL);
    if (result == SQLITE_OK && statement != NULL) {
        while ((result = sqlite3_step(statement)) == SQLITE_ROW) {
            int kind;
            const unsigned char *bytes = NULL;
            int size = 0;
            if (sqlite3_column_count(statement) < 1) {
                result = SQLITE_RANGE;
                break;
            }
            kind = sqlite3_column_type(statement, 0);
            if (kind != SQLITE_NULL) {
                bytes = sqlite3_column_blob(statement, 0);
                if (bytes == NULL && sqlite3_errcode(database) == SQLITE_NOMEM) {
                    result = SQLITE_NOMEM;
                    break;
                }
                size = sqlite3_column_bytes(statement, 0);
                if (size == 0 && sqlite3_errcode(database) == SQLITE_NOMEM) {
                    result = SQLITE_NOMEM;
                    break;
                }
            }
            result = write_value(kind, bytes, (size_t)size, context);
            if (result != SQLITE_OK)
                break;
        }
        if (result == SQLITE_DONE)
            result = SQLITE_OK;
    }
    if (statement != NULL) {
        context->finalized = sqlite3_finalize(statement);
        statement = NULL;
    }
    return result;
}
