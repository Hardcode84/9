<!-- SPDX-License-Identifier: Apache-2.0 -->

# Resource-stage SQLite reader

This application uses owned database and statement values, automatic cleanup,
and synchronous borrowed callbacks. It matches the
[C baseline](../../../benchmarks/resources/README.md) on success and error paths.

Prepare the pinned SQLite sources and object with the commands in that baseline
document. Then run these commands from the repository root:

```sh
make all resource-stage
build/crust examples/resources/sqlite/main.crs
build/sqlite-resource .profile-cache/resources-baseline/normal.db
python3 examples/resources/sqlite/verify.py --sanitizers
```

`main.crs` loads the ordinary resource API and shared library. It selects the
target files and SQLite object. The runner has no resource-stage selector.
The root accepts compiler arguments after its path. For example, append
`--check` to check the target or `-o OUTPUT` to change the executable path.

The application accepts one database path. It opens the database read-only and
runs `SELECT value FROM input ORDER BY seq`. Result lines contain the original
SQL type and hexadecimal bytes. A successful run ends with `rows N`.
Errors use `error OPERATION FINALIZE CLOSE` and status 1. Invalid arguments use
status 2. The baseline document defines the output format in full.

The library uses these contracts:

- `db_acquire` returns an owned `Db`, including a handle from failed open.
- `db_close(mut Db)` empties the owner on success and retains it on failure.
- `with_statement` holds the database loan while its callback uses the statement.
- Finalization consumes the statement even when it reports an evaluation error.
- `with_blob` holds the statement loan while its callback uses the bytes.
- `Statement` and `Bytes` are noncopyable nominal types. Clients receive loans.
- `QueryContext` retains separate operation, finalization, and close results.

A null raw handle is an explicit library state. It is not a compiler drop flag.
An empty owner has no handle to release. A failed implicit cleanup terminates
with status 2. Checked close and finalization return their errors explicitly.

Unsafe functions require valid raw string input. Unsafe blocks contain handle
construction, raw fields, C calls, and byte access. These blocks still obey
ownership and loan rules. The C interface remains an audited library boundary.
It does not let the compiler prove SQLite's internal behavior.

The decimal formatter takes a raw address of an uninitialized 20-byte array
inside an unsafe block. A `u64` needs one to twenty decimal digits. Each loop
iteration writes one digit before it divides the value by ten. The formatter
passes only the written suffix to the synchronous output function. The array
stays alive through that call. Raw writes do not mark the array initialized for
safe source access.

This storage contract avoids mandatory initialization of unused bytes. The
[earlier code inspection](initialization-before.json) records two extra stores
that zeroed all 20 bytes. The current optimized executable has neither store.
The raw pointer path also needs no array bounds check; the digit-count argument
establishes the bound. This is an audited unsafe operation, not inferred
partial initialization.

[validation.json](validation.json) records 21 application process checks across
the compiler CLI, the source-order root, and an ASan/UBSan target. It also records
six rejected ownership violations and three decimal-format boundary checks.
The formatter tests zero, nine, ten, and the maximum `u64` against the actual C
baseline helper. The SQLite object uses its baseline build; only the resource
target is instrumented. Leak checks are disabled because LeakSanitizer fails
under the execution environment's ptrace monitor. Stack-use-after-return and
undefined-behavior checks remain enabled.

The rejected programs copy or move borrowed bytes, store a loan in a record,
step a borrowed statement, close a borrowed database, or change callback access
modes. The successful application tests NULL, empty values, embedded zero bytes,
UTF-8, integers, reals, empty tables, failed open, failed preparation, failed
step and finalization, failed output, and invalid arguments. Separate C contract
checks establish busy-close and allocation-failure behavior in the pinned SQLite
library.

These checks do not measure compilation or runtime speed. They do not establish
the separate direct-list observer contract.
