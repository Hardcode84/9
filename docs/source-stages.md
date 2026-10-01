# Native host-stage experiment

Date: 2026-10-01. This document preserves the interface and measurements at
revision `9cff8f4`. That native host launcher has been removed. Use the
[source runner](source-runner.md) for the current command and contract.
The examples and commands below require the recorded revision. The
[Zig and Jai review](source-metastages.md) records the earlier design evidence.

The [source-order study](source-order-compilation.md) led to `rmd main.rmd`,
where root execution controls compilation and can select the next reader.
The replacement retains host/target separation, code and data lifetimes,
explicit native inputs, and the target-output boundary described here. Its
checked-tree evaluator removes native preparation of each root request.

The implementation proves the complete source-to-executable interface. Fresh
native host preparation does not pass the cold speed gate. The cost section
separates this preparation from target frontend work. Do not use the working
interface as evidence that the complete cold request has C-level speed.

## Source form

A source file can start with one `meta` block. Whitespace and line comments
can precede it. The block contains explicit bootstrap inputs, then ordinary
RMD0 declarations. The declarations define the host compilation program.
The bytes after the closing brace are input to that program.

```rmd
meta {
    source "../api/rmd0.rmd";
    source "../api/rmd0_stage.rmd";
    source "../stages/c/api.rmd";
    link "../build/rmd-c-library.so";

    fn build(request: *RmdBuild) -> i32 {
        return c_program(request);
    }
}

extern fn puts(text: *u8) -> i32 = "puts";

fn main(argc: i32, argv: **u8) -> i32 {
    puts("source stage: ok");
    return 0i32;
}
```

The historical executable example is `examples/meta.rmd` in that revision.
Build and run it there with:

```sh
make c-stage
build/rmd0 examples/meta.rmd -o build/meta-example
build/meta-example
make check-stage
```

Put the root source first on the command line. If it has a leading block,
the launcher passes every following argument to `build`. In this example,
`c_program` gives `-o` its meaning. The launcher does not interpret it.
A root path that starts with `-` must have a directory prefix such as `./`.

The bootstrap grammar is:

```text
HostPrefix = "meta" "{" { Input } { Declaration } "}" ;
Input      = ( "source" | "link" ) String ";" ;
```

`Declaration` is an RMD0 declaration. `source` and `link` are contextual input
words, not general keywords. An input path must have at least one byte and
must not contain a zero byte. All inputs precede declarations. A nested host
block is an error.

Each `source` input contains plain RMD0 declarations. Those declarations and
the inline declarations share the host namespace. An input cannot contain
another `meta` block. The list is an explicit, flat bootstrap closure.
It has no implicit imports, file discovery, package search, or recursive
bootstrap execution.

Each `link` input supplies native code to the host program. A shared library
must match the compiler's host profile and public API. An object or archive
must be suitable for a shared object. Missing files, invalid objects, and
unresolved native references are errors. The launcher has no list of backend
names, registered stage kinds, or special C-backend path.

Relative input paths start at the directory of the root source operand.
They do not start at a search path or the working directory of a later tool.
The launcher resolves these paths before it invokes native tools.

## Phase ownership

The launcher captures the root bytes once. The host reader stops at the
closing brace. It does not lex the next byte. Thus a selected reader can
accept a different target syntax, including bytes that are invalid RMD0.
There is no second file delimiter or required payload marker.

The host context owns only the inline declarations and explicit host source
inputs. It checks all these declarations before execution. The target context
starts empty. Host and target names are independent. Both can define `main`
or any other ordinary name. Host definitions do not become target definitions.

The entry receives this public request from `api/rmd0_stage.rmd`:

```rmd
record RmdBuild {
    context: *RmdContext;
    source: *RmdSource;
    target_begin: usize;
    argc: i32;
    argv: **u8;
}
```

| Field | Contract |
|---|---|
| `context` | Empty initialized target context; the launcher destroys it after the call |
| `source` | Read-only captured root descriptor and bytes; valid through context destruction |
| `target_begin` | Byte offset immediately after the host block's closing brace |
| `argc` | Number of arguments after the root source path; can be zero |
| `argv` | Read-only borrowed arguments, followed by a null pointer; no executable or root path entry |

`build` must be a defined `fn(*RmdBuild) -> i32`. The launcher checks the
request's direct field types and offsets before the native call. Use the
published declarations from the same compiler build. Foreign declarations
and public compiler data must satisfy their documented native layout and
ownership contracts; this check is not a verifier for arbitrary native code.

The entry chooses all target operations. For example, it can read a range,
construct syntax directly, check it, assign native names, and call a backend.
It can instead read another language and construct that language's own IR.
It can call ordinary module-management code to select more inputs.
It need not use the supplied target context if its language uses another
representation.

The standard `c_program` entry reads `[target_begin, source.size)` with
`rmd_read_range`. Locations retain the original root path and byte offsets.
It then processes explicit extra sources, checks the target, and calls the
C backend. A second `meta` block submitted to this reader is an error.
Another reader controls its own target grammar. The launcher does not claim
to validate target bytes that the selected program does not inspect.

## Host execution and lifetime

The launcher uses the seed assembly backend to compile the host declarations.
It assembles and links a private shared object, loads that object in the
compiler process, and calls its entry exactly once. Native host calls can
use the compiler's public functions and the explicitly linked libraries.
There is no child compiler process that must reconstruct the target context.

The launcher removes its temporary files before the entry executes. It keeps
the loaded module live until after target-context destruction. Allocator
callbacks in that module thus remain callable during destruction. Host source
copies and host compiler data remain live through host-context destruction.
The root descriptor, root bytes, and argument storage outlive both contexts.

The entry returns a process status from 0 through 255. A status outside that
range is an error. Host-tool failures retain their exit status. A compiler
diagnostic makes the request fail even if the entry returns zero. There is
no retry or fallback that repeats an entry's file or process effects.

The host profile is Linux x86-64 System V. The launcher uses `as` and `ld`
from `PATH`, and the native dynamic loader. The shared object uses read-only
relocation data, immediate symbol binding, and no text relocations. Constants
with native addresses use relocation data; plain integer constants remain
read-only data. The optional stage path has no cost in the target artifact.

Native host code has the process's file and process access. It is trusted
compilation code, like a native build program. Loading a stage is not a
sandbox boundary. No implicit compile-time expression evaluation or effect
replay is part of this interface.

## Ordinary backend library

The C backend publishes two functions in `stages/c/api.rmd`:

| Function | Input and result |
|---|---|
| `c_program` | A request with an empty context; reads and checks the selected RMD0 target, then emits the requested output |
| `c_backend_build` | An already checked context, optional hosted entry, and output options; emits C, an object, or an executable |

`c_backend_build` does not read sources, select a checker, or assign native
names. The caller owns its input and names. The backend owns and releases its
temporary storage during the call. It can be called again on the same checked
context. It reports errors in that context and does not print them.

The separate `main.rmd` supplies the standalone command-line entry. It is
omitted when building the library. `--export NAME` gives a defined function or
constant an explicit native name. Both the seed driver and the RMD driver
support this generic library operation.

The source-stage test copies the backend to an arbitrary name and path, then
selects that copy from source. It compiles and runs the actual intrusive-list
program. The target contains the list program and its requested host services;
it contains no compiler or stage library references.

## Dependency order and concurrency

The source model has two necessary ordering edges: host preparation precedes
host execution, and a consumer follows the stage that supplies its input.
An entry has ordinary statement order. There are no global compiler callbacks
that repeatedly reopen an earlier phase.

Independent sources can be read into separate contexts. Complete provider
facts can be bound into those contexts before independent body checks.
Independent target contexts and backend objects can run on separate workers.
The current launcher is sequential. A library can supply work scheduling;
the seed adds no scheduler or shared mutable cache.

## Cost gate

The target frontend endpoint is complete C and symbol output. It includes
reading, checking, lowering, and writing. Target GCC parsing, compilation,
and linking are excluded from these measurements. The tests still compile
and run targets to check correctness outside the timing boundary.

Report host preparation separately. A complete cold source-stage request
also includes reading and checking the host inputs, host assembly, native
linking, loading, and execution. This total must not be described as the
target frontend alone.

An explicit prepared library and a library rebuilt from changed source are
different configurations. Label each configuration. The current measurement
uses the prepared C backend and excludes its GCC construction cost. It is not
evidence that rebuilding a project-owned compiler extension is free.
The launcher has no persistent code cache or result cache. It prepares and
executes the inline entry on each request.

The repeatable measurement is `benchmarks/source-stages/measure.py`. It gives
separate results for the prepared target frontend and the complete source-stage
request. The [one-worker speed gate](crust0-spec.md#14-conformance-and-performance-gates)
must identify which of these configurations it covers. Successful output
alone proves the phase and ownership boundary.

Run the current measurement from the repository root with an available CPU:

```sh
python3 benchmarks/source-stages/measure.py --cpu 4 --output build/source-stage-results.json
```

The command saves results and returns failure if the complete cold request
misses its gate. The [recorded run](../benchmarks/source-stages/results.json)
uses GCC 13.3, one logical CPU, 25 randomized paired rounds, fresh processes,
and a warm OS file cache. It performs no timed target GCC work. All stage
inputs and emitted C and symbol files have recorded hashes. The intrusive
target and C reference both run successfully before timing starts.

Median process times are in milliseconds:

| Input | Original C syntax check | Prepared RMD frontend through C output | Complete source-stage request |
|---|---:|---:|---:|
| 1,000 functions | 18.445 | 13.478 | 23.484 |
| 8,000 functions | 111.167 | 109.505 | 123.053 |
| Intrusive list | 6.907 | 1.778 | 11.274 |

The prepared frontend passes on these three inputs. Its largest ratio is
0.985 for 8,000 functions, with a paired 95% bootstrap interval from 0.982
to 0.992. The complete cold request fails on all three inputs. These are
different claims. The installed native backend library is an explicit input,
and the complete request prepares a new inline host entry each time.

The [first prepared-frontend run](../benchmarks/source-stages/results-before-name-buffer.json)
had an inconclusive upper bound of 1.003 on 8,000 functions. Name generation
allocated a temporary 256-byte arena buffer per declaration before copying
the retained name into the context. A 64-byte local buffer holds the fixed
prefix and two decimal 64-bit identities, including their terminator. This
removes about 2 MiB of temporary arena requests for 8,000 names. The retained
names still belong to the context. Reuse tests with stack-use-after-return
detection pass.

The [plain-source comparison](../benchmarks/source-stages/plain-baseline.json)
uses the compiler before this change and the current compiler on the same
three RMD0 inputs. Their complete assembly bytes match. All final paired
confidence intervals include one, so the run does not establish a timing
difference. A first probe identified an extra out-of-line trivia call per
token. The final reader inlines that helper and keeps primitive keywords
before the new keyword in its lookup table. The comparison is repeatable with
`benchmarks/source-stages/plain.py` and two prepared compiler executables.

The [native preparation profile](../benchmarks/source-stages/native-preparation.json)
uses 25 randomized paired rounds per configuration. The default GNU BFD route
spends a median 7.330 ms in the host linker and 1.535 ms in the assembler.
Host input, checks, planning, and assembly text take about 0.309 ms.
Loading the shared object takes about 0.082 ms. These are separate interval
medians; their sum is not a measured total median.

The same probe tests gold and three installed LLD configurations. The fastest
complete route, with gold, takes 6.874 ms against a 6.106 ms C control. Its
median paired ratio is 1.143, with a 95% interval from 1.130 to 1.168.
Changing the installed linker alone does not meet that gate. These probes
precede the final buffer and lexer changes. Their hashes identify their code.

A [bounded libffi probe](../benchmarks/source-stages/ffi-one-call.json) reads
and checks an entry of the form `return foreign(parameter);`, then executes
that call without native host compilation. It emits the same C and symbol
bytes and produces the intrusive-list output. Its complete process takes
2.046 ms against a 6.700 ms C control in 25 paired rounds. The ratio is 0.305,
with a 95% interval from 0.297 to 0.309.

That probe establishes a fast foreign-call boundary. It is not an RMD0
evaluator. A replacement executor must also implement ordinary expressions,
control flow, aligned aggregate storage, all scalar foreign signatures,
native callbacks into host functions, reentrancy, and code lifetime. The probe
rejects other entry bodies. Its narrow result does not justify limiting the
source language or adding a partial evaluator to the core. No libffi dependency
or interpreter was added to the implementation.

Prepared-code reuse is a separate option. A valid key must identify the host
prefix, its source and native inputs, compiler interface, host profile, and
options. Reusing code must still run `build` once for each request. Reusing a
result with file or process effects requires the stronger
[effect contract](metacompilation.md#7-caching-without-changing-program-meaning).
No cache is implemented in this change.
