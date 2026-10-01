#include <stdio.h>
#include "sqlite3.h"

static unsigned checks;

#define CHECK(condition) do { \
    ++checks; \
    if (!(condition)) { \
        fprintf(stderr, "SQLite contract failed at line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

static int failed_open(const char *path)
{
    sqlite3 *database = NULL;
    int result = sqlite3_open_v2(path, &database, SQLITE_OPEN_READONLY, NULL);
    CHECK(result == SQLITE_CANTOPEN);
    CHECK(database != NULL);
    CHECK(sqlite3_close(database) == SQLITE_OK);
    return 0;
}

static int prepare_and_finalize(void)
{
    sqlite3 *database = NULL;
    sqlite3_stmt *statement = NULL;
    CHECK(sqlite3_open(":memory:", &database) == SQLITE_OK);
    CHECK(sqlite3_prepare_v2(database, " -- only a comment\n", -1, &statement, NULL) == SQLITE_OK);
    CHECK(statement == NULL);
    CHECK(sqlite3_prepare_v2(database, "invalid sql", -1, &statement, NULL) == SQLITE_ERROR);
    CHECK(statement == NULL);
    CHECK(sqlite3_prepare_v2(database, "SELECT abs(-9223372036854775808)", -1, &statement, NULL) == SQLITE_OK);
    CHECK(statement != NULL);
    CHECK(sqlite3_step(statement) == SQLITE_ERROR);
    CHECK(sqlite3_finalize(statement) == SQLITE_ERROR);
    statement = NULL;
    CHECK(sqlite3_next_stmt(database, NULL) == NULL);
    CHECK(sqlite3_close(database) == SQLITE_OK);
    return 0;
}

static int retained_close(void)
{
    sqlite3 *database = NULL;
    sqlite3_stmt *statement = NULL;
    CHECK(sqlite3_open(":memory:", &database) == SQLITE_OK);
    CHECK(sqlite3_prepare_v2(database, "SELECT 1", -1, &statement, NULL) == SQLITE_OK);
    CHECK(sqlite3_close(database) == SQLITE_BUSY);
    CHECK(sqlite3_step(statement) == SQLITE_ROW);
    CHECK(sqlite3_column_int(statement, 0) == 1);
    CHECK(sqlite3_finalize(statement) == SQLITE_OK);
    statement = NULL;
    CHECK(sqlite3_close(database) == SQLITE_OK);
    return 0;
}

static int column_allocation_failure(void)
{
    sqlite3 *database = NULL;
    sqlite3_stmt *statement = NULL;
    sqlite3_int64 old_soft;
    sqlite3_int64 old_hard;
    const void *bytes;
    int error;
    CHECK(sqlite3_open(":memory:", &database) == SQLITE_OK);
    CHECK(sqlite3_prepare_v2(database, "SELECT zeroblob(4096 + random()%1)", -1, &statement, NULL) == SQLITE_OK);
    CHECK(sqlite3_step(statement) == SQLITE_ROW);
    CHECK(sqlite3_column_type(statement, 0) == SQLITE_BLOB);
    old_soft = sqlite3_soft_heap_limit64(-1);
    old_hard = sqlite3_hard_heap_limit64(1);
    bytes = sqlite3_column_blob(statement, 0);
    error = sqlite3_errcode(database);
    (void)sqlite3_hard_heap_limit64(old_hard);
    (void)sqlite3_soft_heap_limit64(old_soft);
    CHECK(old_soft >= 0 && old_hard >= 0);
    CHECK(bytes == NULL);
    CHECK(error == SQLITE_NOMEM);
    CHECK(sqlite3_finalize(statement) == SQLITE_NOMEM);
    statement = NULL;
    CHECK(sqlite3_close(database) == SQLITE_OK);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 2)
        return 2;
    if (failed_open(argv[1]) != 0 || prepare_and_finalize() != 0 ||
        retained_close() != 0 || column_allocation_failure() != 0)
        return 1;
    if (printf("SQLite contracts: %u checks passed\n", checks) < 0 || fflush(stdout) != 0)
        return 1;
    return 0;
}
