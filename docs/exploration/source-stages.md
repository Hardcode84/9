<!-- SPDX-License-Identifier: Apache-2.0 -->

# Native host-stage experiment

Date: 2026-10-01. This document preserves the interface and measurements at
revision `9cff8f4`. That native host launcher has been removed. Use the
[source runner](../source-runner.md) for the current command and contract.
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

The old host-block measurement driver required the removed `rmd0` launcher,
its host-block syntax, and its original backend interface. It cannot measure
the current source-order compiler. Its source and reports remain in Git history.
Use the [current source-order tools](../../benchmarks/source-order/README.md)
for new measurements.

The historical experiment separated prepared target emission from the complete
request. The full request also assembled and linked an inline host entry.
Changing the source envelope could not remove that preparation work. Its
prepared result did not establish the cold speed gate.

Two lessons survive the removed interface. First, measure host preparation,
loading, execution, and target frontend work separately, then retain the complete
request total. Second, a successful foreign-call probe does not establish a
complete evaluator. A replacement must cover expressions, control flow, aligned
aggregate storage, scalar foreign signatures, native callbacks, reentrancy,
and code lifetime before its speed can justify a design change.

Compare prepared assembly emitters with
[bootstrap/compare.py](../../benchmarks/bootstrap/compare.py) and explicit
baseline and candidate binaries. Complete output must match before timing.
Keep raw reports and input captures in ignored storage.

Prepared-code reuse is a separate configuration. Its key must identify source
and native inputs, compiler interfaces, host profile, options, and external
observations. Reusing code must still run the compilation program's effects.
Reusing results requires the stronger
[effect contract](metacompilation.md#7-caching-without-changing-program-meaning).
