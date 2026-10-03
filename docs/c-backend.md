<!-- SPDX-License-Identifier: Apache-2.0 -->

# C backend stage

The second backend is an ordinary Crust0 library and driver in `stages/c/`.
It reads checked trees, makes C text, and invokes GCC. All type mapping,
expression lowering, names, number conversion, text buffers, and stage storage
are written in Crust0. No C function emits or formats backend output.

The driver calls the C99 reader and checker at the input boundary. It uses
native memory, file, and process operations as host services. These calls do
not select instructions or translate expressions. The seed interprets
the first C backend build. The C-stage executable has no `crust_x64_` symbols.

The backend also runs as an ordinary external library selected by a
[root compilation program](source-runner.md). The launcher has no
C-backend selector, path, or special native bridge. The source imports the
consumer declarations, links the library, and calls `c_program` or
`c_backend_build` through the normal Crust0 foreign interface.

## Build and use

The selected host and target are Linux x86-64, LP64, and the System V ABI.
GCC and GNU `objcopy` must be available through `PATH`.

```sh
make c-stage
build/crust-c -o build/list examples/intrusive/raw.crs --ldflag build/libcrust0_host.a
build/list
```

The program prints `intrusive: ok`. It removes and destroys separate nodes,
then reuses storage while the list remains live.

`make c-stage` first runs `stages/c/bootstrap.crs` through the backend-free
seed. This interprets C emission and invokes GCC to produce `build/crust-c-seed`. That program compiles the same Crust0 files through C and GCC
to produce `build/crust-c`. Both programs use the same C99 frontend library.
It also builds `build/crust-c-library.so` with the same compiler. That library
exports `c_program`, `c_backend_build`, and the public body-emission services.
It omits the standalone `main`.
Its build uses `-fno-semantic-interposition` with `-Bsymbolic`. Both options
keep internal calls bound to this library's definitions. The compiler option
also permits the same inlining as the standalone backend.
This is self-compilation of the backend and driver. The reader and checker
remain C99. The default `make` target builds the C driver to compile the
assembly stage. `make c-stage` also builds the C shared library.

Use `wc -l stages/c/*.crs` to count the stage, public interfaces, and root helper.
Tests and generated seed API declarations are separate.

| Option | Result |
|---|---|
| `--check` | Read and check source files |
| `--prepare` | Also make complete C and symbol text in memory |
| `--emit-c` | Write the generated C text |
| `--symbols PATH` | With `--emit-c`, write the symbol response file |
| `--object -o PATH` | Compile and write a native object |
| `-o PATH` | Compile, link, and write an executable |
| `--library` | Omit the hosted entry wrapper |
| `--entry NAME` | Select a defined `fn(i32, **u8) -> i32` entry |
| `--export NAME` | Give a defined function or constant its source name as a native name |
| `--cflag ARG` | Add one GCC compilation argument |
| `--ldflag ARG` | Add one GCC link argument |
| `--` | End option parsing |

Definitions have private linkage unless the caller supplies a native name.
Use `--export` to make a function or constant available to another object.
Private helpers and constants from separate builds do not share native names.
An earlier stage can also assign explicit names, such as overload ABI names;
the driver preserves them.

Supply source files in a fixed order. The driver assigns unit identities from
that order. Link arguments are explicit; the driver does not select runtime
libraries. Repeat `--cflag` and `--ldflag` for separate arguments. Each argument
is passed directly to a process. The driver does not use a shell.

For C output, an omitted `-o`, or `-o -`, selects standard output. Object and
executable modes require a regular output file path. A failed compilation or
link keeps the old output file. Temporary files use short names with 16 random
bytes from the host in the output directory. The output name does not affect
their length. Failure to obtain random bytes fails the output operation.
The driver checks process status and file operations and
removes temporary files.

C text and symbol text are separate output files. For new outputs, the driver
creates both temporary files with mode `0666` and the caller's umask. New object
files use the same mode. The linker adds execute permission for new executables,
subject to that umask. Replacements retain the destination's read, write, and
execute permission bits (`0777`). Set-user-ID, set-group-ID, and sticky bits are
not copied.
Temporary creation is exclusive and does not overwrite an occupied path.
Replacement temporaries retain the destination's group and other access
restrictions. The owner can read and write them during compilation. Temporary
C and symbol inputs use private mode `0600` with the caller's umask.
The driver finishes both temporary files before it publishes either regular
file. It publishes the symbol file first and the C file last. These two renames
are not one atomic transaction.
A text output path that names a device or symbolic link is opened as a stream;
a failed stream write can leave a prefix.
Paired outputs must resolve to separate paths and separate existing files.
The driver rejects a dangling symbolic link in this paired mode.

## Replace or compose the stage

The source files have these responsibilities:

| File | Responsibility |
|---|---|
| `model.crs` | Stage records |
| `base.crs` | Arena, text buffers, number conversion, and maps |
| `types.crs` | C types, layout checks, native bindings, and symbol text |
| `emit.crs` | Checked expressions and statements to C text |
| `driver.crs` | Reusable backend call, output files, and native processes |
| `program.crs` | Source input, frontend calls, names, options, and `c_program` |
| `main.crs` | Standalone command-line entry |
| `api.crs` | Consumer declarations for the two public calls and output options |
| `extension.crs` | Complete body callbacks and public emission services |
| `build.crs` | Optional root helper that owns one target context through the call |

An external consumer includes `api/crust0.crs`, `api/crust0_stage.crs`, and
`stages/c/api.crs`. It links the prepared stage library as an ordinary native
input. Do not also include `stages/c/api.crs` when compiling the implementation;
the implementation supplies those declarations itself.

`c_program` receives an empty initialized context and a captured source range.
It copies extra input descriptors, bytes, and native names into the context's
arena. They remain valid after the call. It leaves diagnostics in the context
for its owner to report. The root source remains borrowed through context
destruction.

`c_backend_build` receives checked input with caller-owned native names.
It accepts mode 0 for an executable, 1 for an object, or 2 for C text. Its
options record holds output and symbol paths and explicit compiler and linker
argument arrays. It releases its temporary arena before returning. The caller
can retain the context and call the backend again. The call returns zero,
a failed tool's exit status, or one for another failure.

A custom driver can compile `model.crs`, `base.crs`, `types.crs`, and `emit.crs`
with the public API declarations and its own entry.
Call `c_stage_init(stage, context)` on fresh storage. Keep that stage at one
address until `c_stage_destroy(stage)`. Call `c_emit(stage, entry)` once per
initialized stage. Supply a checked context with assigned native link names.
The entry must have the hosted signature, or be null for library output.

On success, write `stage.header`, then `stage.body`, as one C file. Each
`CBuffer` gives a byte pointer and a size. Write `stage.renames` as the native
symbol response file. `c_buffer_end` adds a zero terminator when a host service
needs a C string; it does not increase the logical byte count.

The input context, source bytes, declarations, and types are borrowed. Keep
them live during emission. Only declarations in `context.units` are defined
in the output. Supplied provider facts remain read-only. Type and symbol
identities do not depend on allocation addresses. Equal native names are
combined before C emission, and incompatible declarations are rejected.
Function signatures use the selected scalar ABI for this comparison. Data
pointer types have one native representation; `isize` matches `i64`, and
`usize` matches `u64`. Shared function-type graphs remain shared during
comparison and C type emission. Constants require exact seed type equality.

The C stage treats an empty `link_name` as a private definition. It emits C
`static` linkage and does not give that definition a native rename. Private
functions and constants have separate bindings, even when their empty names
match. They cannot capture a named external declaration. A null `link_name`
is still an error. An external declaration cannot use an empty name. Select
linkage before the first binding operation and keep it unchanged during
emission. This is a C-stage contract, not a seed language feature.

The stage owns a separate arena with 64 KiB blocks. Output and map growth use
that arena. Destruction releases all blocks, including blocks retained after
failure. Allocation and output-size overflow set a diagnostic. The first
stage error is retained. A caller must discard output from a failed stage.
Independent contexts and stage objects can run on separate workers. The
command-line driver is sequential and adds no scheduler to the core.

### Custom function bodies

Include `stages/c/model.crs` and `stages/c/extension.crs` to use
`c_backend_build_with_body` or `c_emit_with_body`. Supply a callback with type
`fn(*CStage, *CrustDecl, *u8) -> bool` and caller-owned data. The callback runs
after each defined function's signature. It emits that function's complete
body, including braces. Its declaration body can be null.

Types, layouts, signatures, parameter symbols, native names, and constant
initializers must be valid before emission. The callback owns body semantics.
The expression and statement helpers require checked nodes. Keep the context,
callback code, and caller data live through the synchronous build.

False or a new diagnostic stops the build. False without a diagnostic records
`C function body callback failed` at the declaration. The backend preserves
the first error and releases its temporary arena. A null callback selects the
ordinary checked-seed-body emitter. The ordinary emitter has no per-expression
callback cost.

The [external body test](../tests/c_body.crs) uses null seed bodies, emits labels
and branches, runs the output, and checks three callback failure paths. It also
checks private function and constant linkage and rejects a private external
declaration. It links
the public interfaces against a copied ordinary backend library. The
[resource stage](../stages/resources/README.md) uses the same interface for its
shared cleanup blocks. No ownership operation occurs in this backend API.

## C execution rules

C output targets GCC. It is not a portable ISO C representation of Crust0 raw
memory. The handwritten bootstrap remains pedantic C99.

The default GCC arguments are `-std=c99 -pedantic-errors -O2 -g0
-fstack-clash-protection -Wno-overlength-strings`. The last option permits
string literals longer than the 4,095-byte minimum required by C99. Such
strings are valid Crust0 input.

The emitter captures operands in order. It captures the callee and each
argument before a C call. Logical operations use conditional blocks. Aggregate
values are copied before later stores, including overlapping assignment.
Record fields and array wrappers use checked sizes and offsets. Generated
C declarations check these layouts during GCC compilation.

Wrapping integer operations use unsigned arithmetic. Signed results retain
the same bits through `__builtin_memcpy`. Required division and shift traps
are explicit. The stage uses GCC's arithmetic right shift for signed values
on the selected target. It adds no allocation registry, generation counter,
reference count, or garbage collector to user programs.

Named scalar reads use direct C reads into separate temporaries. Raw loads
and stores use byte copies. Address arithmetic uses `uintptr_t`
and a tied input/output register in an empty `__asm__` expression. This gives
GCC an opaque pointer result. It supports a pointer to an embedded list link
and recovery of the containing allocation. A plain pointer/integer cast alone
would not establish this contract: GCC retains C object restrictions across
such casts. See the [GCC pointer conversion rules](https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/Arrays-and-pointers-implementation.html)
and [extended assembly interface](https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/Extended-Asm.html).

The empty assembly expression emits no instruction by itself. Register
constraints and lost optimizer facts can still affect surrounding code.
Required traps and aggregate copies also have costs. Native output must be
measured before a claim of runtime parity with handwritten C. Raw Crust0 memory
preconditions still apply; this backend adds no ownership checker.

## Native runtime contract

Generated C can require native runtime functions even when the Crust source
has no foreign calls. GCC can lower aggregate copies to `memcpy`, and can
introduce `memmove`, `memset`, or `memcmp`. These names must have their C
runtime meanings and ABI. This requirement remains with `-ffreestanding`;
that option does not remove GCC's memory support calls.
[GCC runtime requirements](https://gcc.gnu.org/onlinedocs/gcc/Standards.html)

For example, an exported no-op `memcpy` can leave a large record assignment
unchanged. The generated object calls that definition. Symbol renaming cannot
isolate it from other native calls to the same name. A program can supply its
own correct runtime implementation; the stage does not prohibit these exports
or prove their implementations. A private Crust function named `memcpy` does
not replace the native symbol unless the driver exports it under that name.

GCC configuration and extra `--cflag` arguments can add further dependencies.
The tested Ubuntu GCC 13.3.0 configuration enables
`-fstack-protector-strong`, `-fstack-clash-protection`, and
`-fcf-protection=full`. Stack protection can call `__stack_chk_fail`, which must
terminate on guard failure. Control-flow protection can emit `endbr64`.
The driver explicitly requests stack-clash protection and retains the other
toolchain defaults. Sanitizer or profiling flags can add their own runtime
calls. These costs belong to the selected GCC configuration.
[GCC instrumentation options](https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/Instrumentation-Options.html)

Check the selected compiler and emitted object when supplying a runtime:

```sh
gcc -Q -O2 --help=common
nm -u build/program.o
```

`tests/run.py` checks a 16 KiB record copy with hosted and freestanding GCC
options. Both objects call `memcpy` and, with stack protection requested, refer
to `__stack_chk_fail`. A Crust-defined `memcpy` supplies the copy in the test;
the C caller checks every array element and confirms that the runtime was called.

## Exact native names

C identifiers are generated names. Source identifiers can be C keywords.
Native names can contain any nonzero ASCII byte. A native name can also be
the same as one of GCC's private labels. The emitter therefore does not put
native names into GCC assembly-name declarations.

GCC first makes an object with generated symbols. GNU `objcopy` then assigns
the exact native names. The response file contains quoted arguments, with
literal newline bytes inside a quoted argument when a name contains a
newline. It is not a line-based `--redefine-syms` file. Function aliases with
the same native name share one C declaration, so GCC sees their identity
before optimization.

Use both artifacts when compiling dumped C by hand:

```sh
build/crust-c --emit-c -o build/list.c --symbols build/list.rsp examples/intrusive/raw.crs
gcc -std=c99 -pedantic-errors -O2 -fstack-clash-protection -Wno-overlength-strings -c build/list.c -o build/list.raw.o
objcopy @build/list.rsp build/list.raw.o build/list.o
gcc -no-pie build/list.o build/libcrust0_host.a -o build/list
```

The normal object and executable modes perform these operations directly.
This path requires native object files. If a GCC option requests LTO output,
`objcopy` rejects that object and the driver reports failure.

## Validation

```sh
make check
make check-c
make check-stage
python3 tests/run.py --backend c --compiler build/crust-c --work-dir build/tests-c-ubsan --cflags='-O3 -fsanitize=undefined -fno-sanitize-recover=all' --ldflags='-fsanitize=undefined'
```

The common suite checks integer results, required traps, native calls,
callbacks, layout, aggregate copies, and direct intrusive lists. Separate
native functions supply values that GCC cannot replace with constants.
Those cases check wrapping arithmetic and stores through pointers with
different element types under optimization.

The C suite compares complete C and symbol output from the seed-built and
self-compiled drivers. It builds the next driver generation, compares its
output, and uses it to compile and run the intrusive-list program. It also
checks native names, allocation-size failures, output failures, and the
absence of C backend helper calls.

The common suites check integer results, required traps, public API layouts,
and native file-status layouts. Run `make check` and `make check-c` for current
results and counts.
The source-order suite checks interpreted root actions and the loaded backend.
The [bootstrap guide](bootstrap.md#validation-and-measurements) describes its
checks and recorded AddressSanitizer and UndefinedBehaviorSanitizer results.
The exact generated backend C passes Clang 20 with strict C99 syntax checks;
the layout probes use named structures in `offsetof`.

The earlier prepared-driver run passed all 348 C-backend process checks at
`-O3` with AddressSanitizer and UndefinedBehaviorSanitizer. That run preceded
the source-stage split. Repeat that instrumented stage build with:

```sh
build/crust-c -o build/crust-c-sanitize \
  --cflag -O3 --cflag -fsanitize=address,undefined \
  --cflag -fno-sanitize-recover=all --cflag -fno-omit-frame-pointer \
  --ldflag -fsanitize=address,undefined \
  --ldflag build/libcrust0.a --ldflag build/libcrust0_host.a \
  api/crust0.crs api/crust0_host.crs api/crust0_stage.crs \
  stages/c/model.crs stages/c/base.crs stages/c/types.crs stages/c/emit.crs \
  stages/c/driver.crs stages/c/program.crs stages/c/main.crs
ASAN_OPTIONS=detect_leaks=0 python3 tests/run.py --backend c \
  --compiler build/crust-c-sanitize --work-dir build/tests-c-sanitize \
  --cflags='-O3 -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer' \
  --ldflags='-fsanitize=address,undefined'
```

Leak detection is disabled because LeakSanitizer needs process inspection
that this sandbox does not permit. The allocation-failure test enables
`allocator_may_return_null` for that child only. It sends a valid large request
through the host allocator and checks the resulting stage error and cleanup.

## Compilation measurements

The [measurement script](../benchmarks/c-stage/measure.py) builds isolated
compiler executables and records their source and binary hashes. It measures
semantic checks, complete C and symbol buffers in memory, and complete output
as separate endpoints. All include the work needed to reach that endpoint.
Target GCC compilation, symbol renaming, and linking are separate costs.

Run from the repository root with an allowed CPU and a new report path:

```sh
python3 benchmarks/c-stage/measure.py --cpu 0 \
  --output build/benchmarks/c-stage/results.json
```

The harness uses equivalent generated functions and the direct-list witness.
Correctness checks compile and run the output outside the timing samples. Keep
raw samples, commands, source and tool hashes, and confidence intervals in the
ignored report. A result applies to its recorded builds, inputs, and host.

Stage construction is also separate. Include all required construction when
measuring a cold source-defined compilation request. The
[source runner](source-runner.md#parallel-work-reuse-and-measurements) defines
that boundary. A prepared backend result does not establish the full cold gate.
The [source-order measurement guide](../benchmarks/source-order/README.md)
describes library inlining and text-append controls. Preserve capacity, overlap,
raw-access, and aggregate-copy contracts when testing emitter changes.
