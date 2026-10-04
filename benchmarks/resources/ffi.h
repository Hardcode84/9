/* SPDX-License-Identifier: Apache-2.0 */

struct sqlite3;
struct sqlite3_stmt;

extern int sqlite3_open_v2(const char *, struct sqlite3 **, int, const char *);
extern int sqlite3_close(struct sqlite3 *);
extern int sqlite3_prepare_v2(struct sqlite3 *, const char *, int, struct sqlite3_stmt **,
                              const char **);
extern int sqlite3_step(struct sqlite3_stmt *);
extern int sqlite3_finalize(struct sqlite3_stmt *);
extern int sqlite3_column_count(struct sqlite3_stmt *);
extern int sqlite3_column_type(struct sqlite3_stmt *, int);
extern const void *sqlite3_column_blob(struct sqlite3_stmt *, int);
extern int sqlite3_column_bytes(struct sqlite3_stmt *, int);
extern int sqlite3_errcode(struct sqlite3 *);
extern long write(int, const void *, unsigned long);
extern void _Exit(int);

#define SQLITE_OK 0
#define SQLITE_NOMEM 7
#define SQLITE_IOERR 10
#define SQLITE_MISUSE 21
#define SQLITE_RANGE 25
#define SQLITE_ROW 100
#define SQLITE_DONE 101
#define SQLITE_OPEN_READONLY 0x00000001
#define SQLITE_INTEGER 1
#define SQLITE_TEXT 3
#define SQLITE_BLOB 4
#define SQLITE_NULL 5
