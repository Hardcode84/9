<!-- SPDX-License-Identifier: Apache-2.0 -->

# Source-defined metastages: Zig and Jai review

Date: 2026-10-01. Status: design review before implementation. The
[source runner](../source-runner.md) records the implemented syntax and ownership
rules. The [earlier native-stage experiment](source-stages.md) records its cold
execution cost. This review remains the research record; descriptions of
unimplemented code refer to that earlier state.

## Decision

Keep the stage override in the user program. Treat the C backend as an ordinary
external Crust library. The compiler must not recognize its name, path, symbols,
or implementation. Module management and other stages use the same rule.

Do not adopt the proposed `#crust-meta` and `#crust-payload` file envelope for
backend selection. A backend can consume the result of the normal reader.
It does not need a new file format or an opaque application region.

Use Jai as the closer reference for compiler control. Use Zig as a reference
for explicit compile-time execution within a fixed grammar. Neither gives
evidence that every compiler stage can be replaced by an ordinary application.
Crust must establish that stronger interface with its own implementation and tests.

The first design problem is the ownership of code and data in each phase.
Choose the source spelling after that contract is complete. A phase is an
execution step that prepares code or data for a later step.

## Zig: compile-time evaluation and build control are separate

Zig permits compile-time blocks, parameters, and expressions in normal source.
Its grammar includes a top-level `comptime` block. The development grammar
targets bounded token lookahead. Evaluation does not let a program replace
that grammar.
[Zig development grammar](https://ziglang.org/documentation/master/#Grammar)

Compile-time execution interprets ordinary Zig functions when their inputs
permit it. It rejects access to runtime values and calls to external functions.
Thus a normal `comptime` block cannot call the native Crust frontend or spawn
GCC. Compiler-provided operations, such as `@embedFile`, have their own rules.
They do not imply general host input/output access.
[Zig 0.16 language reference](https://ziglang.org/documentation/0.16.0/#comptime)

`build.zig` has a different role. It is a Zig program that constructs a graph
of build operations. Independent operations can run concurrently. They can
run host tools, generate files, configure modules, and compile targets.
Generated Zig source becomes an input to a later compilation. The build
system tracks dependencies between these operations and can cache results.
[Zig build system](https://ziglang.org/learn/build-system/)

Using one language for both programs does not make the build program an
inline part of the target source. Crust's requested source override must work
without a separate build file. Zig's build system is useful evidence for
explicit dependencies, but it does not supply that source model.

The current release also matters. Zig 0.16 deprecates `@cImport` in favor of
build-system C translation. It replaces `@Type` with separate type-creation
builtins, such as `@Struct` and `@Fn`. These operations construct types. They
do not expose an arbitrary target AST editor or a replaceable parser.
[Zig 0.16 changes](https://ziglang.org/download/0.16.0/release-notes.html#Language-Changes)

Do not equate lazy semantic analysis with lazy parsing. Compile-time selection
can avoid analysis of an unused branch. That branch must still satisfy the
source grammar. Deferring semantic work does not let an invalid token select
the reader that would give it meaning.
[Zig compile-time expressions](https://ziglang.org/documentation/0.16.0/#Compile-Time-Expressions)

The 0.16 release notes describe incremental frontend work and LLVM bitcode reuse.
Those notes identify parallel LLVM IR generation as work in progress. A parallel
build graph is not proof that all operations in one frontend run in parallel.
The current compiler source moved to Codeberg. This review could not read it
through the available web reader, so it makes no claim about the current
worker count for semantic analysis.
[Zig 0.16 compiler changes](https://ziglang.org/download/0.16.0/release-notes.html#Compiler)

The 0.17 development work further separates build execution. User `build.zig`
code compiles into a native configuration program. It writes a graph for a
separately compiled build executor. The executor is cached per compiler version;
configuration has separate reuse. Package-management code also moved from the
compiler to the build system. These changes support a small compiler with
ordinary external build components. The reported configuration speedup does
not measure a cold application frontend. These are development changes, not
0.16 release features.
[Kelley, May and June 2026 development reports](https://ziglang.org/devlog/2026/#build-system-reworked)

## Jai: ordinary source can control compilation

Public Jai programs use `#run` to execute code during compilation. A concrete
same-file example contains the runtime `main` and a later `#run` block that
imports compiler services and sets build options. A separate build file and
a meta/payload separator are not required for this use.
This is evidence from published program source; this review did not execute it.
[Jai X11 and wgpu program](https://gist.github.com/nosqd/5266ee4439d13b1db3f6bcb4032e3e75)

Jai also supports more extensive build metaprograms. The Jaibreak build source
creates workspaces, sets a backend and target, adds files and generated source,
and receives compiler messages. A workspace separates the state of a compiled
program. These calls are ordinary Jai code using the compiler interface.
Selecting a built-in backend through an option is evidence of backend
selection. It is not evidence of an API for an arbitrary replacement backend.
[Jaibreak build source, fixed revision](https://github.com/tsoding/jaibreak/blob/e7e206a66ae3140c5c588feb72591c2d641b0882/first.jai)

The Developer_Only example receives typed procedure data and submits modified
procedure bodies through `compiler_modify_procedure`. This establishes more
control than a constant evaluator. It does not establish which checks repeat
after each modification, or replacement of the full parser and checker.
[Developer_Only source](https://gist.github.com/alexover1/cbcb0fe1d735c96714c7c3426fdd02f6)

Another author's metaprogram receives `TYPECHECKED_ALL_WE_CAN` and inserts
generated source. Insertion causes another check round and another phase
message. Its guard prevents repeated insertion. A phase message is thus not
necessarily a single transition after which earlier work cannot resume.
[Marchetti's generation example](https://teiolass.gitlab.io/posts/metaprogramming_cards_1/)

In the 2025 creator demonstration, the compiler first loads a replaceable
default metaprogram. Compiler messages expose compilation progress and typed
code. The presentation distinguishes an external metaprogram that can overlap
compilation from inline values whose consumers must wait. It reports bytecode
generation cost as well as execution cost.

The reported complete build takes about 2.3 seconds for about 300,000 lines.
It is described as a clean build without incremental compilation. This is not
a C comparison or an isolated frontend measurement. It does not prove a
particular persistent cache design.
[Blow, compiler control at 09:22 and costs at 43:37](https://www.youtube.com/watch?v=IdpD5QIVOKQ&t=562s)

The video endpoint returned a rate-limit error during this review. The review
used the speaker's words in a public transcript, not its generated summaries.
Public source examples provide separate evidence for the API calls above.
[Transcript of the creator demonstration](https://youtubetotranscript.com/transcript?current_language_code=en&v=IdpD5QIVOKQ)

Neither the demonstration nor these examples establishes arbitrary reader
replacement. In particular, the bottom-of-file `#run` example does not prove
that it executes before earlier source is parsed. Source position alone is
not a phase-ordering contract.

A beta user's July 2026 experiments report that independent `#run` calls can
execute out of source order. The author also runs a graphics example's `main`
during compilation. These are first-hand observations, not a formal ordering
rule or a result reproduced here. The article's proposed interpreter design is
explicitly an estimate. Do not infer a required VM-only implementation from it.
[Jai experiments](https://pre-sence.com/archives/tour-of-jai/)

## What Crust should take from this evidence

| Concern | Crust decision |
|---|---|
| Source entry | Put compilation control in the user program. Use ordinary Crust functions and data. |
| Backend | Call an ordinary external library through its published interface. Give the C backend no compiler privilege. |
| Host execution | Permit the required native compiler, memory, file, and process calls. Zig-style constant evaluation alone is insufficient. |
| Phase membership | Identify the code and dependencies that run on the host. Keep them out of the target unless the target explicitly uses them. |
| Reader | Select it before it consumes the bytes that it controls. A backend-only override does not need reader replacement. |
| Parallel work | Publish required facts before dependent work starts. Let independent work proceed. |
| Optional reuse | Keep prepared code reuse separate from caching the effects or results of its execution. |

These are Crust design decisions. They are not additional claims about Jai or Zig.

### Minimum source model

Prefer one explicit entry for host compilation code in normal Crust source.
Its body calls normal library functions. The entry can select or replace
readers, module operations, checks, lowering, and emission through public APIs.
The source spelling of this entry is not selected by this review.

A top-level block can lower to an ordinary host function. A designated ordinary
function can also serve as the entry. Both choices need explicit phase
membership and preparation dependencies. A reserved function name alone does
not define those properties. Neither choice requires general compile-time
evaluation in every expression or calls into user code during type resolution.

The normal Crust reader can recognize the compilation entry and application
declarations under one fixed grammar. It need not perform type lookup while
parsing. Later stages separate host compilation code from target code.
Prepare and check only the selected host code and its declared dependencies
before executing that entry. Requiring the application to pass the default
checker first would prevent the entry from replacing that checker. A stage
cannot depend on its own unavailable output to prepare itself.

Changing the base grammar has an earlier dependency. A reader cannot define
how to recognize its own invocation in bytes that no available reader can
parse. An already available reader must identify the bootstrap code or an
explicit raw region. A prepared user program can also select a reader for
other input files. This is a dependency rule, not a reason to require a new
two-region format for every source file.

Complete reader replacement remains required. It must have a separate witness
with bytes that the default reader cannot accept. That witness must specify
the initial reader and when control passes to the replacement. It must not
silently fall back to Crust parsing.

### The concrete implementation boundary

The current seed has public compiler data and ordinary function values. It
can compile a host program that calls compiler libraries. It has no automatic
source-defined compilation entry yet. The standalone `crust-c` driver proves
the Crust backend algorithms; it does not complete source-defined selection.

Three current mechanisms need explicit treatment:

1. `crust_resolve` and `crust_check` traverse the owned declarations in a context.
   `crust_x64_prepare` and `c_emit` also traverse that context's definitions.
   Choosing another entry function does not restrict these traversals to the
   functions that it calls. Split phase ownership before these operations.
2. `c_driver_names` puts link-name strings in the C stage arena. Its current
   driver keeps this arena alive through context destruction. A reusable
   backend call must preserve that lifetime or receive names owned by its
   caller. It must not leave invalid pointers in a retained compiler context.
3. The seed emits assembly. A new host executable needs assembly and linking
   before execution. A child process cannot use the parent's AST pointers.
   Source re-reading, explicit serialization, or an in-process execution
   mechanism has a real cost and a different ownership contract.

These points are verified in `src/check.c`, `stages/asm/`,
`stages/c/emit.crs`, and `stages/c/driver.crs`. They are the work required by
the source model. New syntax alone would not fix them.

The generic `crust_read_range` API reads a selected byte range with locations in
the original source. It adds no framing or stage syntax. It permits a library
reader to retain correct diagnostics without copying the selected source text.
It does not establish phase separation or execute a metaprogram.

### Cost and acceptance gate

Keep this work bounded by a complete source-to-executable test. A user source
must select a copied external C backend, compile the intrusive-list program,
and produce its expected output. Change only the user source to change the
selected stage. The compiler must contain no backend-specific selection path.

The target artifact must contain no host compilation dependencies merely
because they appear in the same source program. Preserve diagnostics against
the actual captured input. Propagate stage and tool failures. Run the selected
compilation entry once per request; retries must not repeat its effects.

Measure the complete work before handing the application to its final backend.
Include project-stage preparation, native compilation needed for that stage,
execution, any repeated parsing, and all selected language checks and lowering.
Measure the plain-source path separately. Compare both with the paired GCC
baseline. Use the one-worker case as well as any parallel configuration.

The existing [C backend measurements](../c-backend.md#compilation-measurements)
use a prepared backend. They do not establish the cost of a new source-defined entry. Reusing
a prepared external library is valid, but label that configuration. Include
rebuilding a changed project stage in the cold configuration.

Cache prepared code only when its source, dependencies, compiler interface,
host profile, and options match. Caching that code does not permit omission of
its execution. Caching results with file or process effects needs the separate
[input and effect contract](metacompilation.md#7-caching-without-changing-program-meaning).

Do not add a general scheduler, VM, persistent cache, plugin registry, or file
envelope to make this first test possible by assumption. Prove the ownership
boundary and cold cost first. If the result misses the speed gate, identify
the measured cost before choosing another execution mechanism.
