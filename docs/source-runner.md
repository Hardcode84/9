<!-- SPDX-License-Identifier: Apache-2.0 -->

# Source-order compilation

Date: 2026-10-01. This document defines the implemented root runner. The
[language specification](crust0-spec.md) defines the Crust0 value and execution
rules. The [design study](exploration/source-order-compilation.md) records the decision
and the required experiments.

Run a compilation program with:

```sh
crust main.crs
```

The root runs from its first action. It selects compiler stages, reads target
inputs, and requests output through ordinary calls. An action can also select
a different reader for the unread root bytes. There is no `meta` block,
required `build` function, or backend selector in the launcher.

## Build and example

The installed host profile is Linux x86-64 System V. Build the C99 seed with
a C99 compiler, Make, Python 3, and libffi development headers and library.
The optional C backend also requires GCC, GNU assembler, and GNU `objcopy`.

```sh
make all c-stage
build/crust examples/hello/main.crs
build/hello
make check check-c check-stage
```

The target prints `Hello, world!`. The
[example index](../examples/README.md) also covers compiler and target arguments,
multiple files, intrusive lists, reader replacement, and a custom assembly stage.

The [hello example](../examples/hello/main.crs) contains the complete build
description and target program in one file:

```crust
host_source(run, "../../api/crust0_stage.crs");
host_source(run, "../../stages/c/api.crs");
host_source(run, "../../stages/c/build.crs");
host_link(run, "../../build/crust-c-library.so");

var arguments: [*u8; 2] = make [*u8; 2] {
    "-o", host_path(run, "../../build/hello")
};
return c_build((*run).source, (*run).cursor, 2i32, &arguments[0usize]);

// The target program starts here.
extern fn puts(text: *u8) -> i32 = "puts";

fn main(argc: i32, argv: **u8) -> i32 {
    if puts("Hello, world!") < 0i32 { return 1i32; }
    return 0i32;
}
```

The source selects an ordinary shared library. A copy with another filename
works through the same interface. The [C backend](c-backend.md) is all Crust0.
Its output does not depend on the root evaluator or compiler libraries.

`c_build(source, begin, argc, argv)` is an ordinary Crust helper. It compiles the
range from `begin` through source EOF. The cursor already points past the root
return's semicolon, so the target starts there. A separate target file uses
`begin = 0`. The helper creates a target context, calls
`c_program`, reports its diagnostic, destroys the context, and returns its
status. The root can call individual reader, checker, and backend operations
instead. A different language can use its own tree and target representation.

Use the cursor in the final root action that transfers control to the target
compiler. An earlier saved cursor would include later root setup as target
input. The source descriptor retains the complete file, so diagnostics use
the original line numbers.

## Initial bindings and arguments

The launcher captures the root bytes once. It supplies `run: *CrustRun` as a
root variable. Its `argc` and `argv` fields contain only arguments after the
root path. `argv[argc]` is null. The root gives those arguments their meaning.
The launcher accepts `--help` and `--version` in place of a root operand.
Use a directory prefix for a root file with one of those names.

The installed declarations are `api/crust0.crs`, `api/crust0_host.crs`,
`api/crust0_eval.crs`, and `api/crust0_run.crs`. The installed helper source is
`stages/host.crs`. The build embeds these version-matched sources. Every
invocation reads and checks them. No saved checked tree or execution result
is reused. A root must not load those same declarations a second time.

These interfaces expose syntax, types, bindings, incremental checks,
evaluation calls, and the root cursor and operation fields. Include
`api/crust0_x64.crs` and load the external assembly stage to call its services.
The seed has no backend implementation. Include a library's consumer
declarations before calling that library.

The `host_` names are ordinary functions. Their prefix avoids conflicts with
common parameter names under the seed's rule against shadowing visible names.
`source`, `link`, and `meta` are ordinary identifiers.

## Initial action grammar

The initial reader accepts one declaration or root statement at a time.

```text
RootAction = Declaration
           | ( Block | IfStatement | "while" Expr Block ) ";"
           | SimpleStatement ;
IfStatement = "if" Expr Block [ "else" ( Block | IfStatement ) ] ;
```

`SimpleStatement` has the ordinary statement grammar, excluding blocks,
`if`, and `while`. It already has a final semicolon. A root `return` requires
an `i32` value. `break` and `continue` require an enclosing loop. Function and
record declarations end at their final brace. For example:

```crust
var total: i32 = 0i32;
while total < 4i32 { total = total + 1i32; };
if total == 4i32 { return 0i32; } else { return 1i32; };
```

The final semicolon on a root compound statement makes its end explicit.
The reader consumes that delimiter but does not read the next token, comment,
or whitespace. A new reader owns all subsequent bytes. This rule requires
no symbol lookup or per-token extension dispatch.

A function body or block is one parsed action. A call inside that action
cannot change the grammar of its already parsed remainder. A library can
accept raw input through an explicit call when it needs a delayed region.

## Names and execution

Each action is checked against established host declarations and root locals.
It executes once before the next action is read. Root variables retain their
storage until the host context is destroyed. Locals inside a block have that
block's lexical scope. The ordinary no-shadowing rule applies.

A streamed function can refer to itself and earlier declarations. Its body
cannot refer to an unread declaration or capture a root local. Pass root
values, including `run`, as explicit arguments. `host_source` checks a complete
declaration unit; functions in that unit can refer to each other in either
source order. Target units retain the same forward-reference rule.

Streamed declarations use their source identity and starting byte offset plus
one as nominal identity. Whole-unit reads use declaration ordinals starting
at one. Callers that combine independently read ranges or these two identity
schemes must assign distinct identity spaces. Preserve an identity when the
same declaration is supplied to another context.

A root return ends execution immediately. Its status must be in 0 through
255. Unread bytes after that return are not parsed. EOF also ends execution;
the initial status is zero. EOF does not invoke a target compiler, call a
function named `main`, or publish queued work.
Ordinary actions retain explicit changes to the public completion state.
A root return supplies a new completion status. A reader that synchronously
enters the same runner can complete it; the outer loop retains that result.

Host and target namespaces are separate. A target context contains only the
declarations given to it. Host declarations do not become target definitions.

## Reader and executor replacement

`CrustRun` publishes these fields for root control:

| Field | Contract |
| --- | --- |
| `context`, `source` | Borrowed host context and immutable root snapshot |
| `cursor` | Byte offset of the next unread root region |
| `read` | `fn(*CrustRun, *u8, **u8) -> bool`; receives selected user state and produces an opaque action |
| `execute` | `fn(*CrustRun, *u8, *u8) -> bool`; receives the same user state and consumes that action |
| `user` | State pointer selected with the operations for the next action |
| `eval`, `scope` | Default host evaluator and persistent local bindings |
| `next_identity` | Identity used by the ordinary host-source helper |
| `argc`, `argv` | Borrowed root arguments |
| `returned`, `status` | Root completion and process result |
| `state` | Native resources owned by `crust_run_init` and `crust_run_destroy` |

The loop captures both operation pointers and `user` before calling the reader.
Both callbacks receive that captured user pointer as their second argument.
The returned action uses the captured executor. Changes to `read`, `execute`,
or `user` select operations and state for a subsequent action. Thus a reader
can install the next stage without changing its current executor's state.

A successful reader advances `cursor` and returns a non-null action. It can
instead return null at source EOF. Returning an action without progress,
moving outside the source, moving backwards, replacing the source, or claiming
EOF with unread bytes produces a diagnostic. Execution can consume additional
input, but cannot move before the end committed by the reader.

The default operations are `crust_run_read` and `crust_run_execute`. They ignore
the user argument. Their payload is a public `CrustAction`. A custom pair can
use any representation. Assign its functions to `run.read` and `run.execute`
with ordinary function values. There is no grammar registry or mandatory
intermediate representation. A custom
executor can call a different checker or evaluator.

Keep callback code, its state, and action storage live through all consumers.
The default reader puts its actions in the host arena. A replacement owns its
payload contract. Changing the `eval` field does not transfer ownership of a
replacement evaluator to the default runner. Its creator must bind required
root values and destroy it after its final use.

The intended startup policy uses this boundary to leave seed interpretation
early. An ordinary root action prepares the selected backend through an
available compiler configuration, then installs the execution stage for
subsequent compilation code. The backend can compile its next generation
explicitly. Bootstrap policy stays in Crust code.

`host_link` only loads native code. It does not select a new root executor.
A complete bootstrap must also install the operations that execute later
code, with explicit state and code lifetimes. The action performing the
handoff finishes under its captured operations. Later actions use the new
selection without replaying the setup prefix. Native execution must preserve
the source-order boundaries; it cannot parse unread bytes across a pending
reader change. The [native stage](../stages/native/README.md) implements this
boundary with complete function actions. Its bootstrap uses the compiler
selected in `NativeSession.compile`. `NativeSession.libraries` supplies explicit
native dependencies. `native_start` retains that compiler selection. The
[cached example](../examples/cached-backend/README.md) starts with the seed
and sources, interprets assembly emission on a miss, and loads the published
library on a hit. It then compiles and calls the next
functions, preserves explicit state and callable identities, and builds the
target from the unread source tail. Its unit rules are ordinary library policy.

## Files and native inputs

The installed Crust helper library provides four operations:

| Function | Result |
| --- | --- |
| `host_path(run, path)` | Root-relative absolute path copied into the host arena |
| `host_input(run, path, identity)` | Captured source descriptor, path, and bytes in that arena |
| `host_source(run, path)` | Read and check one complete host declaration unit |
| `host_link(run, path)` | Load one exact shared-library path for host calls |

Relative paths start at the directory of the root operand. They do not change
after a host working-directory change. The root operand's directory is used
even when the operand is a symbolic link. A loaded source does not change the
base directory. All retained paths and source bytes are copies.

The helpers implement one flat host namespace. There is no implicit file
search, deduplication, import graph, package resolver, or source execution in
`host_source`. Loading the same definitions twice is an error. A module library
can use public reads, bindings, and contexts to implement another policy.
The [module tutorial](../stages/modules/README.md) does this with separate
contexts, explicit exports, and consumer aliases.

Native libraries use immediate symbol binding and local loader visibility.
They remain loaded through runner destruction. The default resolver searches
the process and explicitly loaded libraries. At first resolution, different
addresses for the same native name are an error. The resolved address then
stays fixed for the evaluator's lifetime, including after a later library load.
An unresolved requested name is an error.
Extern declarations can precede `host_link`: symbol lookup occurs when the
function value is needed. Native declarations with one link name must have
compatible scalar ABI types, including when they are not called.

Only shared libraries are input to `host_link`. The direct `crust_run_link` API
requires a path containing `/`; it does not search for a bare library name.
Preparing an object, archive,
or changed native library is an explicit build operation in source. The
launcher does not invoke a hidden compiler or linker to prepare root actions.

## Execution and lifetime

The checked-tree evaluator implements the Crust0 expressions and statements,
including wrapping integer arithmetic, required traps, aggregate copies,
function values, recursion, and native callbacks. It uses arena storage for
prepared calls and reusable activation frames. A loop does not allocate a new
frame for each iteration. Active recursive or reentrant calls have separate
frames.

The evaluator permits 8192 active calls and syntax visits combined by default.
Expression, place, statement, and function visits share this depth budget.
The budget includes direct calls, function-pointer calls, and native callback
reentry. A deeply nested expression consumes budget in each recursive call.
Exhaustion records a source diagnostic and returns failure. A failure during
a native callback terminates the process as described below. Completed visits
release their budget. Repeated calls and loop iterations do not consume a
cumulative allowance. This limit applies to host interpretation; emitted
target code has no evaluator depth counter.

`CrustEvalOptions.max_depth` selects a different budget. Zero selects the
default. The caller must supply enough thread stack for the selected budget
and native callees. The launcher uses the calling thread's stack. On Linux
x64, the default passes the reader's full syntax-depth boundary and runaway
direct, indirect, and native-callback recursion checks with an 8 MiB stack,
including GCC and Clang sanitizer builds. The optimized interpreted reader
needs between 1 and 1.5 MiB for 126 nested parentheses. A simple recursive
function consumes several visits per call; 8192 visits do not mean 8192
function calls. For example, a function with `if n == 0u64 { return 0u64; }`
and `return down(n - 1u64);` accepts `down(2046u64)` and rejects
`down(2047u64)`. Small-stack embedders must select a lower budget or supply a
larger stack.

Libffi supplies the scalar native-call and callback boundary. A function
pointer passed to native code retains one callable identity. Native callbacks
can synchronously enter the evaluator again. One evaluator requires exclusive
access from one thread. A library must serialize calls or use independent
evaluators for concurrent work. The native bridge follows the
[libffi call contract](https://github.com/libffi/libffi/blob/v3.4.6/doc/libffi.texi).

The host context owns checked syntax, evaluator plans, root slots, and input
snapshots. Destroy target contexts while their source descriptors, provider
facts, allocator state, and callback code remain live. Complete all native
uses of interpreted function pointers before destroying their evaluator.
The default runner destroys its evaluator before unloading native libraries,
then the launcher destroys the host context and releases root bytes.
Unregister callbacks before teardown if a library finalizer can call them.

Raw pointers still require the seed's memory preconditions. Calling a native
library is a trusted process operation. This execution mechanism does not
provide memory safety or a sandbox. The target pays no evaluator or libffi
cost unless target code explicitly requests such services.

## Errors and effects

Read, check, allocation, input/output, and loader failures retain diagnostics.
An operation that returns false without a diagnostic causes a runner error.
A retained host diagnostic stops the root even if a statement ignored its
boolean result. Source diagnostics preserve the captured path and byte offset.

An evaluator failure during a native-to-interpreted callback cannot return
an invented value through an arbitrary scalar ABI. It reports the failure,
flushes output, and terminates the process. Required arithmetic traps also
terminate abnormally. A callback that deliberately returns false through its
declared boolean result remains an ordinary successful function execution.

Earlier effects remain after a later parse or execution error. No action is
retried or replayed. A library that requires publication after successful root
EOF must implement that finalization contract. Default EOF supplies no
transaction and does not complete a library's pending tasks.

## Parallel work, reuse, and measurements

The root cursor is serial: an action can determine how to read the next bytes.
Independent target work can use separate mutable contexts and stable shared
facts. Submitted jobs must retain their source, selected stages, state, and
native code until completion. A library can schedule those jobs and join them
before releasing their inputs. The seed adds no task scheduler.

The optional [artifact cache](../stages/cache/README.md) stores complete files
from a user build function. It hashes captured bytes and validates each reused
artifact. Callers declare all build inputs, including code, ABI, options, tools,
and external data. They supply captured bytes to the producer. Missing required
inputs fail before lookup. A producer with optional lookups must include their
presence or absence in its inputs. Root effects execute on every invocation;
contexts, pointers, and prepared roots are not cached. See the
[cache tutorial](../examples/cached-backend/README.md) for source bootstrap,
publication, loading, and execution through the same source program.

The [reader-transfer proof](../benchmarks/source-order/proof.md) established
the first ownership and output boundary before this implementation. The
production suite is `tests/source_order.py`. Its target GCC runs check actual
executables outside the measurement interval. The full timing command is
`benchmarks/source-order/measure.py`.

Measure from process start through root capture, installed interface checks,
root checking and execution, loading, target frontend work, complete C and
symbol output, and cleanup. Exclude final target GCC compilation and linking.
Report prepared native inputs explicitly. Preparation of a changed native
stage is a separate measured configuration; it is not free project setup.

The [measurement guide](../benchmarks/source-order/README.md) explains paired
rounds, output controls, and separate preparation costs. Store raw samples,
commands, tool versions, hashes, and confidence intervals in ignored reports.
A historical prepared-stage result cannot establish current checkout speed or
the full specification performance gate. The complete gate remains
unestablished; these benchmark tools cover only part of its required matrix.

### Compiled-backend application gate

[gate.py](../benchmarks/source-order/gate.py) starts a fresh root with a
compiled native backend. It measures semantic checking separately from complete
C and native-symbol output. The generated program must match the C reference
when compiled and executed outside the timed interval.

Compare checks with the fastest measured GCC or Clang syntax check. Compare
handoff with Clang frontend IR emission with LLVM passes disabled. Both
handoff measurements include text serialization. The test verifies that
Clang emits every requested function body.

Backend interpretation, construction, and automatic cache validation are
separate measurements. Loading the selected compiled library remains in the
application endpoint. If a project changes a source stage, include that stage's
preparation in a separate configuration. Final target GCC compilation and
linking remain outside all frontend endpoints.

```sh
python3 benchmarks/source-order/gate.py --build build --cpu 0 --rounds 20 \
  --output build/benchmarks/source-gate.json
```

Select an allowed CPU. Exit status 2 means the speed gate failed. The optional
`--perf` argument selects a Linux perf executable for a separate profile after
the timing rounds. Flat sample attribution is not elapsed time per stage.

### Native continuation measurement

[native/measure.py](../benchmarks/native/measure.py) separates stage preparation,
continuation compilation, native target frontend work, C emission, and the final
target toolchain. It also records the complete cold endpoint. Its assembly
library is a prepared input. The main application gate uses
[`source-order/gate.py`](../benchmarks/source-order/gate.py) with a compiled
C backend. Bootstrap and automatic cache validation are separate measurements.
The source-only cache harness measures a different
bootstrap boundary, as described in the [cache measurements](../benchmarks/backend-cache/README.md).

```sh
python3 benchmarks/native/measure.py --cpu 0 --rounds 20 \
  --output build/benchmarks/native.json
```

Use a fresh process and an empty stage-result cache for each cold sample.
State whether filesystem caches are warm. Check output bytes and the final
list executable before interpreting a timing result. Separate phase medians
need not sum to the median of the complete request.

Compare source bootstrap with prepared backend execution. Record extra backend
generations and cache preparation in that configuration. Improvement over
interpretation does not establish the compiled-backend application gate.

### Compare cold native builds

[The comparison tool](../benchmarks/native/cold.py) measures a frozen checkout
and the current build against GCC and Clang. It uses randomized paired rounds,
fresh processes, empty stage result caches, and warm OS file caches. Stage
bootstrap and continuation compilation remain inside this separate bootstrap
endpoint. The default constructs the assembly stage from source. Use
`--backend prepared` to load the identified assembly library instead. Final
target GCC compilation and linking stay outside both configurations.

Create a frozen baseline before an optimization. Both builds must use the same
C compiler and build flags. Run from the repository root and select a CPU
allowed by the host. Use a new output path for each run.

```sh
mkdir -p build/native-before
git archive HEAD | tar -x -C build/native-before
make -C build/native-before all c-stage
# Make the source change, then build and compare it.
make all c-stage
python3 benchmarks/native/cold.py --before build/native-before --cpu 0 --rounds 20 --output build/native-cold.json
```

The report contains raw samples, phase times, paired confidence intervals,
commands, and source, tool, header, and artifact hashes. Every timed output
must retain the same C and symbol bytes. The list program must also compile
and run with the same output as its C equivalent. Sources and tools must stay
unchanged during the measurement.

Exit status 2 means a bootstrap configuration exceeds its C comparison.
This result does not block the main compiled-backend application gate. That
gate must pass with one worker before parallel scheduler expansion. These
inputs do not cover the full matrix in specification section 14. The optional
`--perf` argument selects a
native Linux perf executable for a separate symbol profile. This profile uses
a prepared assembly-built C driver; it does not measure cold stage preparation.
Keep generated reports and profiles in the ignored build directory.
