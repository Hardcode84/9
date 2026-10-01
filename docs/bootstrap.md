# Crust0 bootstrap compiler

The linked measurements retain the source names and hashes from the recorded
runs.

The repository contains a C99 implementation of the Crust0 version 0.1 syntax
and execution rules. `crust0` reads Crust0, checks the program, and emits textual
x86-64 assembly. `crust` executes source-order compilation programs. GNU
assembler produces object code, and GCC links it. The
selected host and target profile is Linux x86-64 with the System V scalar ABI.

This implementation is the raw bootstrap language. It does not add ownership,
cleanup, imports, or macros. The direct-list example uses raw
memory preconditions. It is not evidence of a checked lifetime rule.
The [source runner](source-runner.md) executes ordinary Crust0 code that controls
target compilation and can change the reader for the unread root bytes.

## Build and use

A C99 compiler, the system C library, Make, Python 3, and libffi development
headers and library build the default tools. GNU assembler and the system
linker build the native examples. Python 3 also runs tests and measurements.
The build downloads no dependencies. The standalone `build/crust0` target does
not need libffi.

The build uses `CC` for C code and linking, and `AS` for generated assembly.
The default assembly command is `as --64`. Clang builds also use GNU assembler.
The LLVM integrated assembler rejects some exact external symbol names that
this target profile accepts.

```sh
make
build/crust0 -S -o build/intrusive.s examples/intrusive/program.crs
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

For source-defined compilation, use `crust ROOT ARGUMENT...`. The root receives
the trailing arguments through `run`. Its actions select input files, stages,
and output. The launcher has no backend selector. It reads and executes one
complete action at a time and does not invoke an assembler or linker for it.

The driver publishes a regular output file through a temporary file and rename.
Source or emission failure leaves the old regular file in place. A symbolic
link or a device is opened as a stream. A stream failure can leave a written
prefix and returns a failure status. Output to `-` uses standard output.

## Core and storage

The C implementation uses `-std=c99 -pedantic-errors` and treats warnings as
errors. Its host operations use the POSIX library; it does not use GNU C syntax.
The build checks the selected host representation. It rejects other hosts.

The implementation has 6,621 physical C and header lines, including comments
and blank lines. The reader, checker, storage code, and core header use 3,165
lines. The assembly backend and its header use 1,446 lines. The evaluator and
its header use 1,096 lines. The root runner and its header use 446 lines. The
standalone driver and host interfaces use 468 lines.
Use `wc -l src/*.c include/*.h runtime/*.c` to repeat the count.

Tests, examples, and generated files are separate. The installed Crust host
helpers use 72 lines. The 31-line prelude generator makes a 474-line C byte
table from installed API and helper sources. The native bridge links the
external libffi library; the tested version is 3.4.6. Its implementation is
not included in the 6,621-line count. No libffi dependency enters ordinary
target programs.

Each compiler context owns an arena. Arena blocks are normally 64 KiB. A larger
request receives a separate larger block. Allocation sizes and alignment
calculations are checked. Context destruction releases every block, including
blocks retained after a failed stage. Callers can supply an allocator with
the alignment guarantees of `malloc`, an allocation callback, and a release
callback. Both callbacks and their state must remain live until destruction.

Syntax, types, symbols, names, and temporary tables use that arena. The context
does not own source descriptors or source bytes. Keep them live while compiler
data or diagnostics can refer to them. `crust_alloc` and `crust_try_alloc` zero
compiler data. `crust_arena_alloc` returns uninitialized storage. None of these
rules causes zero initialization of a source-language `uninit` variable.

The reader uses ASCII tokens and recursive descent. It does not look up names.
The checker uses explicit types, interned names, hash tables, and nominal record
identities. It has no overload search, constraint solver, constant interpreter,
template instantiation, or incremental query engine.

Reader nesting and semantic traversal each have a limit of 256. The semantic
limit also covers long expression trees and by-value type chains. These limits
produce diagnostics. They do not truncate the input or skip checks. Pointer
cycles stop at nominal record identities and do not consume one stack frame
per record in the cycle. Type size must fit the Crust0 `isize` limit.

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
identities are pairs of driver-assigned unit and declaration integers.

Resolved type queries consume complete type facts. They do not validate
arbitrary C object graphs. A checked expression records its type and its place
and write permissions. Backend preparation adds aggregate value slots, scratch
slots, and argument slots where required. A scalar emitter leaves its result
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
gcc -no-pie build/stage.s build/libcrust0.a build/libcrust0_host.a -o build/stage
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
driver in Crust0 and compiles itself through its own output. The reader and
checker remain C99. Full compiler self-compilation requires their translation
to Crust0 and a second complete build with the resulting executable.
The C frontend experiment requires a separate C reader, C semantic rules, and
an ABI adapter for C operations absent from Crust0. Neither case is established
by this small replacement-stage witness.

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

## Native output and cost

The backend emits unoptimized assembly. It uses stack slots where operand
evaluation and aggregate value copies require storage. GNU assembler produces
object code, and GCC links it. This path has no C optimization step. Runtime
parity with optimized C has not been measured. The optional C backend stage
constructs GCC input and uses GCC optimization. Its measurements are separate
from this assembly seed.

There is no runtime pointer metadata, allocation registry, garbage collector,
reference count, or implicit cleanup. Required division and shift traps remain
explicit. Raw pointer access has the preconditions in the specification and
does not receive automatic lifetime or bounds checks. Large stack reservations
probe each page so that they cannot skip a stack guard.

## Validation and measurements

Run `make check` for reader, checker, allocator, host, parallel, evaluator, and backend API
tests. It also compiles and executes integer, native ABI, aggregate, list, and
replacement-stage programs. The integer expectations use Python mathematical
integers. Trap tests require abnormal process termination. Allocation tests
fail every arena allocation point in a complete compilation and check release.

The C suites pass 21,904 checks under GCC AddressSanitizer and
UndefinedBehaviorSanitizer. The assembly integration suite passes 398 process
checks. The C backend passes 348. The integration cases include
10,220 integer comparisons, 65 required traps, 260 public API layout comparisons,
and 20 native file-status layout comparisons. The allocation sweep covers
19 failure points. The parallel
test checks six consumers in serial order and two concurrent orders, with
shared provider facts unchanged. Both complete specification examples run.
The source-order suite adds 154 process checks. Its root evaluator, source
snapshots, native callbacks, reader replacement, phase isolation, backend
reuse, paths, and failure cases pass with the C core and Crust C backend under
GCC AddressSanitizer and UndefinedBehaviorSanitizer. Stack-use-after-return
detection is enabled. The evaluator suite also passes 10,829 checks under
Clang 20 AddressSanitizer and UndefinedBehaviorSanitizer.
The [runner validation record](../benchmarks/source-order/validation.json)
contains the GCC commands, source hashes, and complete sanitizer logs from
revision `b1a6196`, before the example directories were added. That run passes
141 root and 348 C-backend process checks, including buffer overlap and growth
with a one-byte append. The 13 added example checks run unchanged source files
from a copied layout. They cover inline targets, arguments, multiple files,
reader replacement, original error locations, and output failure.
The updated target and example groups also pass 13 process checks each with
the instrumented GCC build and stack-use-after-return detection enabled.

Use these commands for a second strict compiler and address/undefined-behavior
instrumentation:

```sh
make CC=clang-20 BUILD=build/clang check
ASAN_OPTIONS=detect_leaks=0:detect_stack_use_after_return=1:abort_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1 make CC=gcc BUILD=build/sanitize \
  CFLAGS='-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer' \
  LDFLAGS='-fsanitize=address,undefined' all c-stage check-stage
```

LeakSanitizer cannot run under the tracing environment used for these runs.
The allocation-failure tests separately count live arena blocks. This is not
a general replacement for leak detection. The parallel witness also runs under
ThreadSanitizer. The
[final thread check](../benchmarks/bootstrap/results/parallel-2026-10-01.md)
records the exact command, source hashes, and 75 passing checks with no report.

The [source-runner results](source-runner.md#parallel-work-reuse-and-measurements)
include root capture and execution through complete C and symbol output.
All three inputs pass the C-speed gate. Final target GCC compilation and
linking are excluded. The backend shared library is an explicit prepared
input. The report records its separate rebuild cost.

The assembly measurements below precede the source-order runner. Their source
hashes identify that implementation. The
[plain-seed comparison](../benchmarks/source-order/plain-results.json)
compares the old and current seed separately.

`benchmarks/bootstrap/measure.py` records fresh-process, single-worker timings
for the list witness and generated scaling cases. It retains the source and
binary hashes, commands, raw paired samples, and confidence intervals. Check,
frame preparation, and complete assembly are distinct endpoints. The installed
stage libraries and warm operating-system file cache are stated conditions.
Results do not establish cold stage preparation cost, checked-Crust cost, time to
compile Linux, GCC, LLVM, or SQLite sources, or self-hosted C frontend cost.

The [final measurement](../benchmarks/bootstrap/results/frontend-2026-10-01.json)
uses 25 paired rounds for each endpoint and workload, for 375 timed processes.
The machine is an AMD Ryzen Threadripper PRO 7995WX. All compiler processes use
one logical CPU. GCC 13.3 and Clang 20.1.8 provide the C comparisons. GCC has the
lower median on each workload. Frequency is not fixed and the CPU is not
reserved. The isolated single-worker build of the C99 compiler and its two
libraries took 0.706 seconds; this build is outside the compilation samples.

| Workload | GCC syntax (ms) | Crust check (ms) | Crust prepare (ms) | Crust assembly (ms) | Assembly / fastest C, with 95% interval |
|---|---:|---:|---:|---:|---|
| Intrusive list | 7.334 | 1.759 | 1.769 | 1.823 | 0.248 [0.245, 0.255] |
| 1,000 generated functions | 18.772 | 8.628 | 10.679 | 12.695 | 0.676 [0.662, 0.692] |
| 8,000 generated functions | 115.064 | 60.909 | 82.715 | 110.588 | 0.961 [0.955, 0.968] |

Each generated function reads record fields, does integer arithmetic, branches,
and writes a field. The C and Crust cases have equivalent operations. Each timed
invocation starts a new process. Assembly goes to the null device. Assembly and
linking of the result are outside the samples. The script checks complete
assembly function counts and executes the list witness in both languages.

The gate requires the upper 95% interval bound to be at most 1 against the
faster C compiler. All three Crust endpoints pass on each workload. The intervals
use 10,000 resamples of complete paired rounds. Each resample selects the
faster C median again. These are separate comparison intervals; they do not
provide simultaneous coverage for all nine comparisons.

The [first baseline](../benchmarks/bootstrap/results/frontend-2026-10-01-baseline.json)
failed the full-assembly gate at 1,000 and 8,000 functions. At 8,000 functions,
it took 185.491 ms. The
[cycle profiles](../benchmarks/bootstrap/results/x64-profile-2026-10-01.json)
identified general `printf` formatting as a large cost: its libc symbols
accounted for 49.31% of sampled user cycles in the baseline recording. This
share was 0.58% in the last diagnostic candidate recording. These percentages
are flat cycle attribution, not stage wall times. That candidate predates the
final invariant and callback repairs; the final timing uses the repaired source.

The changes remove unused scalar value slots, retain aggregate copies where
required, use direct frame loads and stores, and use a small private text
formatter. Public formatted output retains normal C formatting behavior. The
[baseline patch](../benchmarks/bootstrap/results/baseline.patch) reconstructs
the failed compiler from the final source. The
[reconstruction record](../benchmarks/bootstrap/results/baseline-reconstruction.json)
checks its source and executable hashes. Apply the patch in a separate clean
copy with `git apply --unidiff-zero benchmarks/bootstrap/results/baseline.patch`.
It changes final compiler sources back to the failed baseline.

Use a new output path to repeat the measurement:

```sh
python3 benchmarks/bootstrap/measure.py --cpu 4 --output build/frontend-repeat.json
```
