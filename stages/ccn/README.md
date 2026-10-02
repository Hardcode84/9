<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: a CCN checker written in Crust

A function with many decisions is difficult to inspect. A compilation program
can set a complexity limit and reject a function before it reaches the backend.
The limit is project policy. It does not need a core language rule.

This tutorial builds a cyclomatic complexity (CCN) checker with ordinary Crust
functions. It uses the existing parser and public syntax trees. The same counter
can inspect a source file or check a tree that another stage already holds.

Run the commands from the repository root.

## 1. Inspect a file

```sh
make all
build/crust examples/ccn/main.crs examples/ccn/program.crs
```

The result is:

```text
examples/ccn/program.crs:3:1: score: CCN=4
examples/ccn/program.crs:9:1: main: CCN=2
```

The [root program](../../examples/ccn/main.crs) loads the checker with
`host_source`. Its last action passes the root arguments to `ccn_program`.
The checker reads the named files as data. It does not execute their statements,
load their dependencies, resolve their names, or check their types.

The default limit is 15. Use `--CCN` to select a positive integer limit. Use
`-w` to report only functions above the limit:

```sh
build/crust examples/ccn/main.crs -w --CCN 3 examples/ccn/program.crs
```

This command returns status 1 and reports:

```text
examples/ccn/program.crs:3:1: score: CCN=4 (limit 3)
```

Options precede the paths. Use `--` before a path that starts with `-`.
Input paths are relative to the working directory. Each row contains the path,
line, byte column, function name, and CCN. Lines and columns start at 1.

| Exit status | Meaning |
| --- | --- |
| 0 | All functions are within the limit |
| 1 | At least one function is above the limit |
| 2 | An argument, input, allocation, or output error occurred |

The checker reports every defined function, including functions after a root
`return`. Root statements, external declarations, records, and constants do not
have a function CCN. An empty file succeeds without report rows. If a file has a
syntax error, no rows from that file are printed. Rows from earlier files can
already have been printed.

## 2. Define the count

The counter uses this rule for each function:

```text
CCN = 1 + number of if + number of while + number of && + number of ||
```

An `else if` contains another `if`. Plain `else`, `return`, `break`, `continue`,
and `trap` add zero. Bitwise operators, calls, comments, and string contents add
zero. Logical operators add one wherever they occur, including return values,
call arguments, array elements, record fields, and assignment operands.

The count describes the written syntax. It includes `while true`, constant
conditions, and unreachable branches. It does not fold constants or remove
dead code. A function with CCN equal to the limit passes.

## 3. Reuse the parser and syntax tree

[read.crs](read.crs) calls `crust_read_one` for each source action. This public
API returns a declaration or statement and the next byte offset. The checker
selects function declarations and passes them to `ccn_function`. There is no
second lexer or parser.

[count.crs](count.crs) walks the public `CrustStmt` and `CrustExpr` children.
It visits statement sequences, branch bodies, expression operands, arguments,
and initializer values. It does not follow symbol, type, or declaration links.
Those links are semantic facts, not children of the function body.

The walk uses an explicit stack. A long chain such as `a && b && c` can create
a deep tree even when the parser uses little recursion. The counter does not
put that tree depth on the host call stack. Its cost is linear in the visited
syntax. Scratch space grows with the maximum number of pending nodes.

Initialize one `CcnCounter` with `ccn_init`. Its context owns the stack storage.
Reuse the counter for subsequent functions. Each call resets the count and
reuses the allocated space. If allocation fails, `ccn_function` retains a
diagnostic and leaves the result argument unchanged.

`ccn_read` builds report rows in the same context. It publishes the rows only
after the complete input parses. It advances one position cursor to calculate
source locations; it does not scan the file again for each function.
[report.crs](report.crs) reuses a buffer and writes each report row in one call.

[program.crs](program.crs) owns the input file buffer. That buffer and its source
descriptor stay live through parsing, reporting, diagnostics, and context
destruction. The program then frees the buffer. A read or write failure returns
status 2 with a diagnostic.

## 4. Add the check to a compilation program

```sh
make c-stage
build/crust examples/ccn/build.crs
build/ccn-example
```

The executable returns status 0. Open [build.crs](../../examples/ccn/build.crs).
The root selects the module library, CCN counter, and C backend. Its steps are:

1. Read `program.crs` into a module.
2. Initialize a counter with that module's context.
3. Call `ccn_check_unit` with the parsed unit and a limit of 4.
4. Check types and export `main`.
5. Give the same checked module to the C backend.
6. Print any diagnostic and destroy the module.

The CCN stage neither reads the file again nor changes its tree. Its call is
ordinary compilation code:

```crs
var counter: CcnCounter = uninit;
ccn_init(&counter, &(*target).context);
if !ccn_check_unit(&counter, (*target).context.units, CCN_LIMIT) { return 1i32; }
```

Change `CCN_LIMIT` in that example from 4 to 3 and run the root again. It rejects
`score` at `program.crs:3:1` with `function exceeds CCN limit`. It returns before
the backend call. It does not create or replace the output executable. Restore
the limit to 4 to accept the program.

For several units, call `ccn_check_unit` on each unit. To select a different
report or policy, call `ccn_function` and use its numeric result directly.
Neither use requires the command-line files.

The counter accepts finite function trees under the public seed AST contract.
A reader extension can call it on such a tree. If an extension uses another
representation, select an analysis for that representation or lower it to the
seed AST first. A count after lowering describes the lowered body, including
any decisions the extension inserts. The file command reads seed syntax only;
it rejects a custom grammar instead of executing reader changes from its input.

## 5. Build the checker as a native program

```sh
make ccn-stage
build/crust-ccn --CCN 15 stages/ccn/count.crs
build/crust-ccn -w --CCN 15 stages/ccn/*.crs
```

The first invocation lists each function. The second returns status 0 without
report rows. The native entry point uses the same checker as the root program.
The C backend builds it with GCC. Analysis itself does not invoke a backend.
The native tool links the existing run library for its source diagnostic
printer.

The repository's `crust-ccn` pre-commit hook runs this native checker with
`-w --CCN 15`. It checks every `.crs` file in `api/`, `stages/`, and `tests/`,
including the checker itself. It calls `make ccn-stage` before analysis so
changes to the compiler or checker rebuild the executable. A failed build,
invalid input, or function above the limit fails the hook.

```sh
pre-commit run crust-ccn --all-files
```

These directories contain implementation code and test helpers in seed syntax.
Tutorial inputs can select other grammars. Archived benchmark inputs must keep
their recorded bytes. The repository hook does not scan those two groups.
Use the file command or the AST interface to check a tutorial program.

## 6. Compare with Lizard

The comparison uses Lizard 1.21.6, which is also the version in the repository's
C complexity hook. Lizard starts a function at 1 and counts decision tokens.
Its default token set is `if`, `for`, `while`, `catch`, `case`, `?`, `&&`, and
`||`. Its warning filter uses a strict greater-than comparison. See its
[counter and warning filter](https://github.com/terryyin/lizard/blob/1.21.6/lizard.py)
and [default token set](https://github.com/terryyin/lizard/blob/1.21.6/lizard_languages/code_reader.py).

Crust's seed has no `for`, `catch`, `case`, or ternary expression. The rule in
this tutorial covers the shared syntax. Lizard's C/C++ reader also counts
`#if`, `#ifdef`, and `#elif`. Crust has no C preprocessor.

The tests compare 18 pairs of C and Crust functions. Fifteen counts agree.
Three C cases expose an undercount in Lizard 1.21.6: designated initializers,
an indexed assignment, and a field read from a compound literal. For example:

```c
int example(int a, int b) {
    int values[2] = {0, 0};
    values[a && b] = 0;
    return 0;
}
```

Lizard reports 1 for this function. The corresponding Crust function has CCN 2.
Lizard's [C++ rvalue-reference filter](https://github.com/terryyin/lizard/blob/1.21.6/lizard_languages/clike.py)
sees `&&`, then the later `=`, and subtracts a decision. It applies this filter
to C files too. The Crust AST identifies the logical operator without this
heuristic. The checker counts it. The tests retain these differences explicitly.

This tool reports per-function CCN. It does not implement Lizard's other metrics,
language readers, or suppression directives.

## 7. Check the implementation

The test requires Python 3 and `lizard==1.21.6` in its Python environment. Lizard
is a test oracle; it is not a dependency of either Crust checker command.

```sh
make check-ccn
```

The checks run the root and native commands. They compare counts and threshold
boundaries with Lizard, exercise every expression child shape, and verify that
input statements do not execute. They include long and wide expressions,
parser depth errors, invalid arguments, missing files, and failed output.
An allocation sweep fails each context allocation during parsing, counting,
and report construction, then checks cleanup and scratch reuse.

The compilation example is copied into a path with spaces and run from another
working directory. Its accepted executable runs. A rejected build must retain
the accepted output bytes. See [tests/ccn.py](../../tests/ccn.py) and
[tests/ccn_alloc.crs](../../tests/ccn_alloc.crs).
