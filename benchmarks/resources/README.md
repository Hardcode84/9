# SQLite resource baseline

These files define the behavior of the first resource-stage application.
The frozen baseline report contains no speed samples. See
[RESULTS.md](RESULTS.md) for the separate frontend and cleanup measurements.

The reader accepts one database path. It opens that database read-only and runs
`SELECT value FROM input ORDER BY seq`. The `input` table must contain `seq` and
`value` columns. Each result line contains its original SQL type and the bytes
returned by the BLOB interface. The type markers are `N`, `B`, `T`, `I`, and `R`
for NULL, BLOB, text, integer, and real values. Non-NULL bytes use lowercase hex.
A successful run ends with `rows N`.

Errors use `error OPERATION FINALIZE CLOSE` on standard error and exit status 1.
The three fields retain separate error codes. Invalid command arguments use
status 2. A failed implicit cleanup uses status 2 and a fatal diagnostic.

`direct.c` uses direct SQLite calls. `callbacks.c` adds the same synchronous
statement and byte-view callbacks as the resource source. Both use the same
output code and the same pinned SQLite object. This permits a later comparison
with direct C as well as with C that already has the callback interface.

Run from the repository root:

```sh
mkdir -p .profile-cache/sources
curl -fL https://sqlite.org/2025/sqlite-amalgamation-3500400.zip -o .profile-cache/sqlite.download
printf '%s  %s\n' 1d3049dd0f830a025a53105fc79fd2ab9431aea99e137809d064d8ee8356b032 .profile-cache/sqlite.download | sha256sum -c -
unzip -jo .profile-cache/sqlite.download 'sqlite-amalgamation-3500400/sqlite3.[ch]' -d .profile-cache/sources
python3 benchmarks/resources/verify.py
```

The verifier also checks the extracted source hashes. If those files are already
present from the compiler study, run only the last command. The verifier builds
SQLite 3.50.4, builds both C applications with strict C99 flags, and checks:

- NULL, empty BLOB, empty text, embedded zero bytes, UTF-8, integers, and reals.
- An empty table, failed open, failed preparation, and failed evaluation.
- Separate evaluation and finalization errors.
- Failed output and invalid command arguments.
- An open failure that still returns a handle requiring close.
- Successful empty SQL, invalid SQL, and finalization after evaluation failure.
- A busy close that preserves the connection, followed by finalization and retry.
- A real allocation failure during BLOB expansion, followed by failed finalization
  that still destroys the statement.

The allocation fixture uses `SELECT zeroblob(4096 + random()%1)`. The remainder
is zero, so the result size is fixed. The call to `random` prevents SQLite from
expanding a constant BLOB before the test installs its heap limit. The fixture
sets the hard heap limit after stepping, reads the BLOB, captures the error code
immediately, and restores both heap limits. It requires `SQLITE_NOMEM`; an access
that succeeds does not pass the test.

[baseline.json](baseline.json) records 14 application process checks and 30
SQLite contract checks. It includes commands and input/output hashes. These
are C baseline results. The resource application now matches all seven
application cases through both entry paths; its separate
[validation report](../../examples/resources/sqlite/validation.json) records
the results and ownership rejection checks.

SQLite defines the relevant contracts in its documentation for
[open](https://www.sqlite.org/c3ref/open.html),
[column access](https://www.sqlite.org/c3ref/column_blob.html),
[finalization](https://www.sqlite.org/c3ref/finalize.html),
[close](https://www.sqlite.org/c3ref/close.html), and
[heap limits](https://www.sqlite.org/c3ref/hard_heap_limit64.html).
