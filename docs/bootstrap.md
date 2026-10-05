<!-- SPDX-License-Identifier: Apache-2.0 -->

# Crust0 bootstrap compiler

The repository contains a C99 implementation of the Crust0 version 0.1 syntax
and execution rules. `crust` executes source-order compilation programs and
contains no backend. `crust0` links the external Crust assembly stage to read,
check, and emit textual x86-64 assembly. GNU
assembler produces object code, and GCC links it. The
selected host and target profile is Linux x86-64 with the System V scalar ABI.

This implementation is the raw bootstrap language. It does not add ownership,
cleanup, imports, or macros. The direct-list example uses raw
memory preconditions. It is not evidence of a checked lifetime rule.
The [source runner](source-runner.md) executes ordinary Crust0 code that controls
target compilation and can change the reader for the unread root bytes.
The [native bootstrap tutorial](../stages/native/README.md) uses the same seed
with an explicitly loaded assembly stage to build a native executor. The
[cache tutorial](../examples/cached-backend/README.md) starts with only the
seed and sources and retains the resulting native library for later runs.

## Build and use

Install a C99 compiler, GCC, GNU Make, GNU binutils, Python 3, and the libffi
development headers and library. GCC and binutils compile, rename, and link
the generated backend code. Python 3 also runs tests and measurements.
The build downloads no dependencies. The standalone `build/crust0` executable
does not link libffi. Its source bootstrap uses the seed and libffi to build
the external assembly stage.

The build uses `CC` for C code and linking, and `AS` for generated assembly.
The default assembly command is `as --64`. Clang builds also use GNU assembler.
The LLVM integrated assembler rejects some exact external symbol names that
this target profile accepts.

The default build compiles `crust0_amalg.c` as one translation unit. This
generated file joins `src/core.c`, `src/read.c`, and `src/check.c`. Headers,
platform adapters, the runner, host functions, and command-line entry points
remain separate. A core-only program does not acquire runner or libffi
dependencies.

Use `make AMALGAMATION=0 BUILD=build/split` to compile the three core source
files separately. Both modes provide the same public C API. A mode change in
one build directory replaces the core archive and relinks its consumers.

Edit the source files, then run `make amalgamate`. The build and pre-commit
hook also regenerate the file. Do not edit or format the generated file
directly. Its `#line` directives retain source paths in compiler diagnostics.
Headers are not copied into the generated file; they remain build inputs.
`CRUST_STATIC` gives private cross-file helpers internal linkage in the
amalgamated build and external linkage in the split build. The allocator and
native ABI bridge helpers keep external linkage because their callers cross
translation-unit boundaries. `make check-amalgamation` checks generation and
the exported symbols in both modes.

```sh
make
build/crust0 -S -o build/intrusive.s examples/intrusive/raw.crs
gcc -no-pie build/intrusive.s build/libcrust0_host.a -o build/intrusive
build/intrusive
make check
```

The program prints `intrusive: ok`. It stores links inside heap nodes, recovers
the containing node through a nonzero field offset, and removes and frees one
node while another node remains linked. It then allocates and attaches a new
node. No node pool or pointer registry is required.

The command accepts an explicit source list. All those declarations share one
namespace. The driver assigns declaration identities from source order and
declaration order. This is a driver policy; the core does not discover files.

| Option | Endpoint or effect |
|---|---|
| `--check` | Read, collect, resolve, and check all bodies and constants |
| `--prepare` | Also assign link names, check native symbol agreement, and prepare frame and expression slots |
| `-S` | Also lower operations and emit complete assembly; this is the default |
| `--library` | Omit the native `main` entry wrapper |
| `--entry NAME` | Select a defined `fn(i32, **u8) -> i32`; the default name is `main` |
| `--export NAME` | Give a defined function or constant its source name as a native name; repeat for more declarations |
| `-o FILE` | Select the assembly output; the default is standard output |

`--check` does not require an entry point or a native definition for a foreign
function. The linker resolves native references when it makes an executable.
Use `--library` for preparation or emission of a library source.

Definitions are private unless `--export NAME` selects a native name. Separate
object files can use the same private function or constant names. The hosted
entry wrapper exports `main`; it can call a private entry function. The backend
API uses an empty `link_name` for an owned private definition. A null name is
an error. External references need a nonempty native name. A driver must keep
the selected names unchanged through emission.

For source-defined compilation, use `crust ROOT ARGUMENT...`. The root receives
the trailing arguments through `run`. Its actions select input files, stages,
and output. The launcher has no backend selector. It reads and executes one
complete action at a time and does not invoke an assembler or linker for it.

The driver publishes a regular output file through a temporary file and rename.
New regular files use mode `0666` with the caller's umask. Replacement files
retain the previous read, write, and execute permission bits (`0777`).
Set-user-ID, set-group-ID, and sticky bits are not copied. Temporary creation
is exclusive; an occupied temporary path is never overwritten.
Temporary names use 16 random bytes from the host in a short name in the
destination directory. They do not include the destination's file name.
Failure to obtain random bytes fails the output operation.
Replacement temporaries do not grant access beyond the destination's access
bits and the caller's umask.
Source or emission failure leaves the old regular file in place. A symbolic
link or a device is opened as a stream. A stream failure can leave a written
prefix and returns a failure status. Output to `-` uses standard output.

## Core and storage

The C implementation uses `-std=c99 -pedantic-errors` and treats warnings as
errors. Its host operations use the POSIX library; it does not use GNU C syntax.
The build checks the selected host representation. It rejects other hosts.

Count the current implementation with
`git ls-files src include runtime | xargs wc -l`. This includes comments, blank
lines, and private platform headers. Tests, examples, generated files, and external
libraries are separate. The prelude generator embeds the installed API and
host helper sources. The native bridge links libffi; ordinary target programs
do not need that library.

The Makefile selects the `linux_x64` profile and rejects other profile names.
`src/profile_linux_x64.c` checks the required host representation.
`src/driver_posix.c` publishes output files. `src/run_posix.c` captures root
paths and manages loaded native code. `src/eval_ffi_linux_x64.c` implements
native calls and callbacks. `runtime/host_posix.c` provides aligned allocation.
The build selects `src/linux_x64/eval_storage.h` for scalar memory access without
an extra call on each access. These private interfaces use portable C99 types.
Compiler policy and evaluation do not include OS or libffi headers.

Each compiler context owns an arena. Blocks start at 64 KiB and grow with
reserved storage up to 4 MiB. A request above that limit gets a larger block.
Allocation sizes and alignment calculations are checked. Context destruction
releases every block, including blocks retained after a failed stage. Callers
can supply an allocator with
the alignment guarantees of `malloc`, an allocation callback, and a release
callback. Both callbacks and their state must remain live until destruction.

The Linux allocator aligns blocks of at least 2 MiB to a huge-page boundary
and requests transparent huge pages for complete aligned regions. The kernel
can still use ordinary pages. A kernel without this advice uses ordinary
storage; other advice failures release the allocation and report failure.
Small blocks use ordinary allocation. Custom context allocators receive the
block requests directly. No process-wide allocator setting is changed.

Syntax, types, symbols, names, and temporary tables use that arena. The context
does not own source descriptors or source bytes. Keep them live while compiler
data or diagnostics can refer to them. `crust_alloc` and `crust_try_alloc` zero
compiler data. `crust_arena_alloc` returns uninitialized storage. None of these
rules causes zero initialization of a source-language `uninit` variable.

The reader uses ASCII tokens and recursive descent. It does not look up names.
The checker uses explicit types, interned names, hash tables, and nominal record
identities. It has no overload search, constraint solver, constant interpreter,
template instantiation, or incremental query engine.

Reader nesting and semantic traversal each have a limit of 256. Semantic
traversal counts syntax and type graph depth, not source indentation or
parentheses. A flat operator chain builds a nested expression tree and counts
toward this limit. A nested block and its `if` statement each count as one
level. By-value type chains also count.
An `else if` uses a conditional node without an extra wrapper block. Each
recursive arm consumes one reader level and one statement traversal level.
These limits produce diagnostics. They do not truncate the input or skip checks.
Pointer cycles stop at nominal
record identities and do not consume one stack frame per record in the cycle.
Type size must fit the Crust0 `isize` limit.

## Public stages

The public C declarations are in `include/crust0.h`, `include/crust0_x64.h`,
`include/crust0_host.h`, `include/crust0_stage.h`, `include/crust0_eval.h`, and
`include/crust0_run.h`.
The corresponding Crust0 declarations are in `api/`. Run `make api` after an API
change. The generator handles the selected header forms only and rejects a
form it cannot translate. It is not a C frontend. The test suite compares all
published record sizes, alignments, and field offsets with the C compiler.

The public data includes syntax nodes, type facts, declaration identities,
bindings, storage slots, native symbol roles, and backend operation functions.
There is no permanent binary ABI. Build a stage against the same package
version as its compiler libraries.

The API generator computes a SHA-256 digest from the public header tokens and
the Linux x86-64 LP64 profile identifier. The digest covers record fields,
enums, macros, and function signatures. Comments and whitespace do not change
it. `include/crust0_abi.h` and each generated Crust API file contain this digest.
`make` updates these files when a public header changes. `tools/api.py --check`
checks the generated declarations and digests.

The supplied C and assembly drivers export each `CRUST_ABI_` constant from
their input in `--library` mode. The native stage does the same. This prefix is
reserved for API metadata. The root loader requires the base marker and checks
all additional API markers in each library against its own digest. A mismatch
or missing base marker stops the load and reports the library path. The check runs once per
load. It adds no check to native calls. See the
[native input contract](source-runner.md#files-and-native-inputs) for C libraries
and custom emitters.

| Operation | Input and result |
|---|---|
| `crust_read` | Source bytes to an owned syntax unit |
| `crust_read_range` | A byte range to an owned unit, with locations in the original source |
| `crust_read_one` | One unlinked root declaration or statement and its exact byte end |
| `crust_bind` | A selected name and complete external declaration facts to a borrowed binding |
| `crust_collect` | Owned syntax units to the top-level namespace |
| `crust_resolve` | Collected declarations and bindings to types, layouts, and signatures |
| `crust_check_body` | A resolved owned function to its checked body |
| `crust_check` | All owned functions and constants to checked input |
| `crust_collect_unit`, `crust_resolve_unit`, `crust_check_unit` | Check one owned unit without rescanning earlier units |
| `crust_check_root` | One root statement and persistent local bindings to checked input |
| `crust_eval_*` | Checked host operations, values, and native callbacks |
| `crust_run_*` | Source-order loop, replaceable reader/executor, and native input lifetime |
| `crust_x64_prepare` | Checked input with link names to a public frame and expression plan |
| `crust_x64_emit_program` | That plan to assembly |

`crust_read_range` accepts `[begin, end)` within the source. Empty ranges are
valid. It does not read excluded bytes, change the source descriptor, or copy
the source text. Keep the full descriptor and bytes live until context
destruction. Declaration ordinals start at one in each returned unit.
Callers that combine distinct ranges must assign distinct declaration
identities, as for other independently constructed units. This API adds no
stage syntax or automatic compile-time execution. `crust_read_one` instead uses
the declaration's starting byte offset plus one. Callers must not mix these
ordinal spaces under one source identity. It does not link its result into
the context or read beyond its action delimiter. The runner controls checking
and execution; the reader does neither.

`libcrust0_run.a` contains the evaluator and root loop. A native consumer links
it with `libcrust0.a`, libffi, and the system dynamic-loader interface. The
installed executable also links `libcrust0_host.a` and exports its public native
symbols. The separate `crust0` path does not link the evaluator.

`libcrust_asm.a` and `crust-asm-library.so` contain the assembly stage. Its
`crust_x64_*` functions are not in the seed or core archive. The C header
describes the external stage ABI; its generated Crust model shares that layout.

The frame plan retains checked operations. Instruction selection, required
trap sequences, and final assembly remain in the emitter. Thus `--prepare`
alone is not a measurement of all lowering work. Measurement through complete
assembly includes that work.

A caller can create syntax directly, edit checked operations under their
preconditions, construct a frame plan, or replace expression, place, and
statement emission. It need not invoke the producer it replaces. A replacement
reader must supply valid syntax data. The checker still checks source-language
rules. A replacement that supplies checked types or a backend plan must satisfy
that consumer's published invariants. There is no second defensive validation
of every internal node.

Zero-initialize newly constructed nodes. Set the fields required by their kind.
`CrustTypeSyntax`, `CrustExpr`, and `CrustStmt` store kinds as `uint32_t`.
The exclusive seed range ends are `CRUST_T_END`, `CRUST_E_END`, and
`CRUST_S_END`. Reserve extension ranges with `crust_allocate_kinds(ctx, count)`.
It returns the first kind, or zero with a retained diagnostic. Count must be
positive. Ranges are disjoint in one context and remain reserved until its
destruction. This operation uses a context counter and allocates no storage.
Lower extension nodes before seed checking. The seed checker reports unlowered
type, expression, and statement kinds. When copying extended syntax between
contexts, remap its kinds to ranges reserved in the destination context.

Expression and statement nodes form trees of occurrences. Each occurrence has
its own node. Do not share these nodes between parents or function bodies.
Declarations and complete type facts can be shared under the rules below.
Names in owned syntax must be interned in the destination context. A function
declaration stores its result syntax in `syntax_type`; each parameter stores
its own type syntax. A function type stores its result in `base`. A call stores
its callee in `left`. A record initializer stores fields in written order in
`inits`. Array initializers and calls use `args`. A block stores its statement
list in `body`. Lists end with a null `next`. String `byte_count` includes the
additional final zero byte.

The declarations in `context.units` are local definitions. A supplied binding
does not add its provider to that list. Providers retain ownership of their
facts. The binding operation validates incomplete or conflicting facts at
that boundary. It does not change provider declarations. Equal nominal record
identities are pairs of driver-assigned unit and declaration integers. A failed
binding publishes neither a name binding nor provider identities, including
when destination table allocation fails.

Resolved type queries consume complete type facts. They do not validate
arbitrary C object graphs. `crust_try_type_equal` takes a scratch context and
writes exact equality to its result pointer. Allocation failure returns false,
retains a diagnostic, and leaves the result unchanged. Repeated comparisons
reuse context storage without retaining results across calls. The C-only
`crust_type_equal` helper requires an active failure frame.

A checked expression records its type and its place and write permissions.
Backend preparation adds aggregate value slots, scratch slots, and argument
slots where required. A scalar emitter leaves its result
in RAX with the type's signed or unsigned extension. An aggregate emitter
leaves an address to its complete value copy. A place emitter leaves an address
without reading the stored value. The frame size has 16-byte alignment.

The default path calls C operations directly. A custom operation table is
optional. Null operations select the default operation. A callback returns
false on failure and records a diagnostic. Crust0 callbacks use the `try` entry
points and `crust_x64_write`. These functions contain C error exits inside their
own C frames and return normally to Crust0. They do not jump across Crust0 frames.

The place operation computes an address for a stored name, dereference, field,
index, or group that denotes a place. Default reads of stored values use this
operation when a place callback is installed. A group delegates value
evaluation to its child expression. It does not add a memory read, so it does
not request a place during value evaluation. Field and index reads can request
an address inside an aggregate temporary. Such a temporary is not a writable
source-language place. Variable initialization and parameter stores belong to
statement and function emission; they do not invoke the expression-place hook.

Native C construction helpers can use `crust_run_stage` with a C callback that
permits a nonlocal exit. The raw helpers require that failure frame. They are
not published as Crust0 foreign calls. Crust0 has no variable arguments or aggregate
call ABI; text output and output-pointer wrappers provide those operations
without either language feature. A caller releases resources it owns after
each reported failure. Failed work is not a published interface.

## A compiled replacement stage

`examples/custom-stage/stage.crs` is an ordinary Crust0 program. Its reader accepts a decimal
exit status, such as `42`, instead of Crust0 syntax. It creates a function through
the public syntax records, invokes the checker, and emits a library. It also
replaces integer addition by zero with a direct value transfer through the
public backend API. The remaining operations use the standard emitter.

```sh
build/crust0 -o build/stage.s api/crust0.crs api/crust0_host.crs api/crust0_x64.crs examples/custom-stage/stage.crs
gcc -no-pie build/stage.s build/libcrust_asm.a build/libcrust0.a build/libcrust0_host.a -o build/stage
build/stage examples/custom-stage/answer.txt build/answer.s
gcc -no-pie build/answer.s examples/custom-stage/answer_main.c -o build/answer
build/answer
```

The final program exits with status 42. The custom reader never calls the seed
reader. The example needs no plugin loader, evaluator, JIT, or compiler server.
The test also uses a native caller that checks the result and all callee-saved
registers. This checks the replacement stage's native calling contract.

This is stage execution through Crust0. The seed compiler remains C99. The
[C backend stage](c-backend.md) separately implements a complete backend and
driver in Crust0 and compiles itself through its own output. The seed reader,
checker, evaluator, and runner remain C99. `make c-stage` interprets the C
stage through `stages/c/bootstrap.crs`, then compiles its next generation.
The assembly stage is also Crust source. `make check-asm` checks its successive
generations. `make check-cache` checks source-only bootstrap and artifact reuse.
`make check-c` builds the next generation, compares generated C and native
symbol response files across all three generations, and uses the final
generation to build and run the direct-list program. No cache is used.
These checks establish the stage self-compilation gate.

## Parallel use

Each mutable context and syntax body has one writer. Different workers can
read sources, check bodies, or prepare and emit code in separate contexts.
They can share complete, read-only declaration facts. Providers and their
source data must remain live until all consumers finish. Contexts do not use
mutable global compiler state. A driver chooses stable identities and orders
diagnostics before it schedules work.

`tests/parallel_test.c` implements a small module policy outside the core. It
selects provider facts, supplies public names, omits private names, and chooses
native link identities. Six consumers run serially and in two concurrent
orders. Their assembly and diagnostics must match. The test also checks that
provider facts do not change. The default command-line driver stays sequential;
it does not impose a scheduler or a module resolver on other drivers.

The [module tutorial](../stages/modules/README.md) implements source selection,
visibility, and native exports in Crust. Its root selects a provider before
its consumer, then destroys contexts in reverse dependency order. This
library uses the same public binding boundary as the parallel C test.

## Native output and cost

The backend emits unoptimized assembly. It uses stack slots where operand
evaluation and aggregate value copies require storage. GNU assembler produces
object code, and GCC links it. This path has no C optimization step. Runtime
parity with optimized C has not been measured. The optional C backend stage
constructs GCC input and uses GCC optimization. Its measurements are separate
from this assembly stage.

There is no runtime pointer metadata, allocation registry, garbage collector,
reference count, or implicit cleanup. Required division and shift traps remain
explicit. Raw pointer access has the preconditions in the specification and
does not receive automatic lifetime or bounds checks. Large stack reservations
probe each page so that they cannot skip a stack guard.

## Development checks

Install the commit checks once per checkout:

```sh
python3 -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

The hooks check text and configuration files, format C and Python, lint Python,
and check the generated Crust APIs and Apache 2.0 SPDX headers. Source,
configuration, and documentation files start with one
`SPDX-License-Identifier: Apache-2.0` comment, after any shebang. Update the
generator for a generated file. The header check excludes `benchmarks/` to
preserve archived bytes. JSON files and raw test inputs use the repository
[license](../LICENSE) without an inserted comment.

Lizard limits functions in `src/`,
`include/`, and `runtime/` to CCN 15. Recorded benchmark inputs and reports are
excluded from formatters because their hashes identify the measured bytes.

## Validation and measurements

Run `make check` for reader, checker, allocator, host, parallel, evaluator, and backend API
tests. It also compiles and executes integer, native ABI, aggregate, list, and
replacement-stage programs. The integer expectations use Python mathematical
integers. Trap tests require abnormal process termination. Allocation tests
fail every arena allocation point in a complete compilation and check release.

The parallel test compares serial and concurrent consumers while shared
provider facts remain unchanged. The source-order suite checks interpreted
root actions, source snapshots, native callbacks, reader replacement, phase
isolation, backend reuse, paths, and failure cases. Run the test commands to
get counts for the current checkout.

The example checks run unchanged source files from a copied layout. They
cover inline targets, arguments, multiple files, reader replacement, original
error locations, and output failure.

Use these commands for a second strict compiler and address/undefined-behavior
instrumentation:

```sh
make CC=clang BUILD=build/clang check
ASAN_OPTIONS=detect_leaks=1:detect_stack_use_after_return=1:abort_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1 make CC=gcc BUILD=build/sanitize \
  CFLAGS='-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer' \
  LDFLAGS='-fsanitize=address,undefined' all c-stage check-stage
```

This configuration enables leak scanning. Allocation tests also count live
arena blocks. Retain commands and logs for each sanitizer run in ignored storage.

The [source-runner measurement contract](source-runner.md#parallel-work-reuse-and-measurements)
includes root capture and execution through complete C and symbol output.
The application gate uses a compiled backend and includes loading it. Measure
source bootstrap and automatic cache validation separately. A changed project
stage needs a configuration that includes its preparation cost. Exclude final
target GCC compilation and linking from frontend measurements.

`benchmarks/bootstrap/measure.py` measures fresh-process checking, frame
preparation, and complete assembly as separate endpoints. It uses the list
witness and generated scaling inputs. It records commands, source and binary
hashes, raw paired samples, and confidence intervals. Installed stages and warm
filesystem caches are explicit conditions. The script checks emitted function
counts and executes the list witness outside the timed intervals.

```sh
python3 benchmarks/bootstrap/measure.py --cpu 0 \
  --output build/benchmarks/frontend.json
```

Select an allowed CPU and a new output path. Compare equivalent source operations
against the faster eligible C compiler at the same boundary. This harness covers
the raw list program and generated function scaling. The
[benchmark guide](../benchmarks/README.md) lists the resource, ownership, and
parallel workloads and defines comparison rules. Keep reports under `build/`.

## Expression storage measurement

Order expression fields by decreasing size and keep the generated stage API in
agreement with the C header. Measure layout changes with separately built
baseline and candidate compilers using the same flags. Each build directory
must contain `crust0` and `crust-c`.

```sh
python3 benchmarks/bootstrap/storage.py --before build/before --after build/after \
  --work build/storage-inputs --cpu 0 --output build/storage-repeat.json
```

The report separates checking, assembly, and C preparation. It records elapsed
time, peak resident memory, page faults, commands, and input and tool hashes.
Target assembly, C compilation, and linking are excluded. Reduced memory use
does not by itself establish a speed improvement or the full C-speed gate.

## Arena page-fault measurement

Use the same storage comparison to test allocator changes. Measure page faults,
peak resident memory, and elapsed time together. Huge pages can reduce faults
while retaining more unused memory. Keep builds, inputs, and options identical
when testing page-policy effects.

For a control with transparent huge pages disabled, compile
[thp_off.c](../benchmarks/bootstrap/thp_off.c) and pass it with `--prefix`.
It disables THP for the child process, verifies the setting, and executes the
compiler. It does not change the system setting.

```sh
cc -std=c99 -pedantic-errors -O2 benchmarks/bootstrap/thp_off.c -o build/thp-off
python3 benchmarks/bootstrap/storage.py --before build/before --after build/after \
  --work build/arena-inputs --prefix build/thp-off --cpu 0 \
  --output build/arena-disabled-repeat.json
```
