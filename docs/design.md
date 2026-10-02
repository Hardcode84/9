<!-- SPDX-License-Identifier: Apache-2.0 -->

# Crust core and compiler design

Crust keeps a small language core and exposes the compiler as libraries.
`crust main.crs` executes a compilation program. That program selects its
inputs, language rules, and backend through ordinary calls.

Compilation speed through backend handoff is the first requirement.
Explicit types, direct name lookup, and separate declaration facts keep
the core work bounded. Richer rules belong to selected stages. A program
that does not select those stages does not run their compiler passes or
receive their runtime machinery.

This guide describes the current implementation and its extension contracts.
The [Crust0 specification](crust0-spec.md) defines the seed language rules.
The [exploration archive](exploration/README.md) retains research, proposals,
and earlier experiments; their candidate syntax does not extend the seed.

## The language core

Crust0 is the bootstrap language used to write compiler libraries. Its core
provides enough data and control flow to implement readers, checkers, and
emitters:

| Core facility | Purpose |
| --- | --- |
| Fixed-width integers, `usize`, `isize`, and `bool` | Tags, offsets, arithmetic, and conditions |
| Nominal records and fixed arrays | Compiler nodes, tables, and explicit layout |
| Raw pointers and layout queries | Graphs, buffers, foreign data, and field addresses |
| Typed function values and foreign calls | Compiler operations, callbacks, and native services |
| Explicit declarations and signatures | Name binding and body checks without type inference |
| Variables, blocks, assignment, `if`, `while`, and returns | Ordinary algorithms |

`unit` is a function result with no stored value. Function parameters are
scalar; results are scalar or `unit`. Records and arrays can be constructed
and copied locally. Seed functions pass them through explicit pointers.
A richer frontend can define its own aggregate call convention.

Every parameter, result, local, constant, and field has an explicit type.
Calls require exact argument types. Integer literals carry a type suffix,
such as `1u32`. The parser recognizes syntax without declaration lookup.
There is no overload candidate search or implicit conversion search in the
seed checker.

All seed values are copyable. Copies do not allocate, call user code, or
transfer ownership. Arithmetic follows the specified wrapping and trap
rules. Operands, callees, and arguments evaluate from left to right. Raw
memory access requires valid, live, correctly sized storage; the seed does
not prove those preconditions.

Ownership, loans, RAII, `defer`, and `unsafe` policy belong to language
stages. So do overloads, module policy, and alternate syntax. The core has
no garbage collector, implicit cleanup, generics, exceptions, or universal
language IR. A frontend can represent richer types as ordinary data and
use a backend that understands them.

## Compilation is a source program

The root file runs from its first action. The launcher supplies
`run: *CrustRun`, an immutable source snapshot, compiler interfaces, and
ordinary host helpers. The default runner then repeats:

1. Capture the current reader, executor, and user state pointer.
2. Read one complete action and commit its end offset.
3. Check and execute that action with the default executor, or call the
   selected replacement executor.
4. Read the next action with the operations now stored in `run`.

A root action can load a stage, compile a target, or change how later bytes
are read. It cannot change syntax already read as part of that action.
Root compound statements end with a semicolon so this boundary is exact.

The following diagram shows a root that calls a compiler library. The target
pipeline runs only because the source makes that call.

```mermaid
flowchart TD
    Start[crust main.crs] --> Capture[Capture root bytes and install interfaces]
    Capture --> Read[Read one action with the selected reader]
    Read -->|action| Execute[Execute with the paired executor]
    Execute -->|continue| Read
    Read -->|EOF| Stop[Return root status]
    Execute -->|root return| Stop

    Execute -->|explicit compiler call| Input[Select target sources and bindings]
    Input --> Frontend[Selected reader and language checks]
    Frontend --> Checked[Checked operations and any retained stage plans]
    Checked -->|seed operations| ASM[Seed x86-64 backend]
    Checked -->|default or custom body emitter| C[Crust C backend]
    ASM --> Assembly[Text assembly]
    Assembly --> Assembler[GNU assembler]
    C --> CText[C text and symbol arguments]
    CText --> GCC[GCC compiles C]
    GCC --> Rename[objcopy assigns native symbols]
    Assembler --> Link[Native linker]
    Rename --> Link
    Link --> Output[Target executable or library]
```

The backend branches are alternatives chosen by the compilation program.
Successful compiler calls return to the root. The resulting target program
runs separately. A root can also interpret actions directly, emit source,
or produce only an object file. The resource stage's exit plans require its
C body emitter; the seed assembly emitter does not consume those plans.

### One file can contain both programs

The [Hello World source](../examples/hello/main.crs) loads the C stage API
and shared library, prepares an output argument array, and ends with:

```crust
return c_build((*run).source, (*run).cursor, 2i32, &arguments[0usize]);
```

The cursor is already after this return statement's semicolon. `c_build`
compiles the remaining declarations in a separate target context. Target
diagnostics retain positions in the complete file. Root declarations do
not become target declarations, and the runner does not implicitly invoke
a target function named `main` at EOF.

Root declarations can use earlier declarations and themselves. A function
cannot capture root locals or refer to an unread root declaration. A whole
unit loaded through `host_source` can use forward references and mutual
recursion within that unit. Target declaration units have that same rule.

### Metacompilation uses ordinary execution

A metastage is a function or program that does compiler work. It uses the
same records, pointers, loops, and calls as other Crust code. The runner
executes checked host trees. Prepared libraries run as native code through
the normal foreign interface. Libffi supplies the evaluator's native call
and callback boundary.

Host interpretation has a configurable budget of 8192 active calls and
syntax visits by default. This permits the interpreted reader's full syntax
depth on the tested 8 MiB stack. It also bounds runaway recursion. The budget
counts more than one visit per function call. Embedders must provide enough
stack for their budget and native callees. See the
[execution contract](source-runner.md#execution-and-lifetime).

`host_source` checks a host declaration unit. `host_link` loads an explicit
shared-library path. It does not compile changed library source. Stage code
must already be available before a call uses it; preparing that code is an
explicit build dependency. A root can also define and execute stage functions
directly, as the [reader switch](../examples/reader-switch/README.md) does.

There is no required `meta` block, separate build script, or backend-specific
launcher option. Arguments after the root path are data for the root to
interpret. Earlier effects remain if a later action fails. EOF performs no
implicit build, task join, or publication of pending output.

## Compiler stages and their data

The frontend API is in [include/crust0.h](../include/crust0.h) and the
matching [Crust declarations](../api/crust0.crs). Assembly operations use
[include/crust0_x64.h](../include/crust0_x64.h) and
[api/crust0_x64.crs](../api/crust0_x64.crs):

| Boundary | Input and result | Public operation |
| --- | --- | --- |
| Read | Source bytes to syntax with original locations | `crust_read`, `crust_read_range` |
| Bind providers | A visible name and complete external declaration facts | `crust_bind` |
| Collect | Owned declarations to the top-level name table | `crust_collect` |
| Resolve | Names and type syntax to signatures, layouts, and type facts | `crust_resolve` |
| Check | Resolved declarations and a body to checked operations | `crust_check_body`, `crust_check` |
| Prepare assembly | Checked input and native names to storage and expression plans | `crust_x64_prepare` |
| Emit assembly | A prepared plan to complete assembly text | `crust_x64_emit_program` |

Whole-unit compilation collects declarations before checking bodies. Root
execution uses `crust_read_one`, the incremental unit operations, and
`crust_check_root`. It checks each new action against facts already available.
It does not rescan all earlier actions after every declaration.

These boundaries are callable operations, not a required pass manager or
serialized intermediate files. A stage can construct valid input directly
and skip the producer it replaces. Public syntax, type, declaration, and
backend records expose the required data. Package versions define their
layouts; there is no permanent binary ABI between arbitrary compiler versions.

Syntax expressions and statements are trees of distinct occurrences.
Complete declaration and type facts can be shared under their lifetime
contract. A backend can trust checked facts. A replacement producer must
establish those facts before it calls the consumer.

### Module management belongs to the caller

The seed accepts selected sources and explicit bindings. It does not search
for imports, choose visibility, resolve packages, or assign a module-based
mangling scheme. The supplied host helpers use a flat namespace. Loading
the same definitions twice is an error.

A module stage can collect interfaces, select visible names, assign stable
declaration identities and native names, and bind those facts into consumer
contexts. `crust_bind` borrows complete provider facts; it does not add the
provider's definitions to the consumer's output units. Providers must stay
live and unchanged until their consumers finish.

The [multiple-file example](../examples/multiple-files/README.md) selects
sources explicitly. The [separate-object example](../examples/overload/separate/README.md)
uses a shared source interface and stable overload names across two builds.
Neither requires a package resolver in the seed.

## Extension points

Replacement can be small or complete. Use the interface that matches the
data your stage needs to change.

| Extension | Interface | Working example |
| --- | --- | --- |
| Replace unread root syntax and action execution | `CrustRun.read`, `execute`, and `user`; the action is an opaque pointer | [Reader switch](../examples/reader-switch/README.md) |
| Extend the Crust declaration grammar | `CrustReaderHooks` for declarations, statements, prefixes, and types | [Reader library](../stages/reader/README.md) |
| Construct or transform seed input | Public nodes, bindings, identities, and checking operations | [Custom reader](../examples/custom-stage/README.md) |
| Add source name and type rules | An ordinary pass before the next checker | [Overload stage](../stages/overload/README.md) |
| Add ownership and cleanup rules | Source checker, separate lowered types, and retained exit plans | [Resource stage](../stages/resources/README.md) |
| Change one assembly operation | `CrustX64Ops.expression`, `place`, or `statement` | [Custom assembly operation](../examples/custom-stage/README.md) |
| Supply complete C function bodies | `c_emit_with_body` or `c_backend_build_with_body` | [Resource body emitter](../stages/resources/emit.crs) |
| Replace the backend | A library that consumes its chosen representation and produces output | [C backend](../stages/c/README.md) |
| Classify source for display | User services append source spans; consumers render HTML or editor tokens | [Highlighting tutorial](../stages/highlight/README.md) |

The Crust reader library is separate from the seed reader. Its four hooks
extend target syntax without adding keywords to the C99 parser. Replacing
the root reader and executor can replace the entire grammar of unread root
bytes. Install both operations in one action, and keep their code, action
data, and user state live through execution. The callbacks receive the captured
user pointer as an explicit argument. A change to `run.user` selects state for
the next action. The captured operations and state finish the current action.

Check a source rule before lowering discards the facts that express it.
For example, overload selection must distinguish `read T` from `mut T`
before both become pointers. The resource checker must retain cleanup plans
through emission. Its checked operation trees alone omit cleanup that the
body emitter obtains from those plans.

A user frontend can instead keep its own syntax, type system, checker, and
IR. Seed types do not have to represent every target type. Reusing a seed
consumer still requires its input contract; using another consumer requires
that consumer's contract.

## Built-in assembly and a custom backend

The assembly backend gives the bootstrap compiler a direct native output
path. The C backend demonstrates a complete backend implemented as an
ordinary Crust library.

| Property | Seed assembly backend | Crust C backend |
| --- | --- | --- |
| Implementation | [src/x64.c](../src/x64.c), compiled as pedantic C99 | [stages/c/](../stages/c/README.md), written in Crust |
| Input | Checked seed operations with native names | Checked declarations and default bodies, or a custom complete-body callback |
| Output | Text x86-64 assembly | C text and a symbol response file |
| Native toolchain | GNU assembler and linker | GCC, `objcopy`, and linker |
| Code optimization | Direct emission without an optimization pipeline | GCC optimizes the generated C |
| Customization | Public preparation data and expression, place, and statement operations | Public buffers, types, emission helpers, and complete body callback |
| Command wrapper | `build/crust0` | `build/crust-c` |

Both current backends select Linux x86-64 and the System V scalar ABI for
seed functions. The C output uses GCC-specific operations to preserve seed
arithmetic, evaluation order, and raw address behavior. It is not a portable
C target for arbitrary machines. A different target needs explicit layout
and ABI rules; the host's `sizeof` is not a target description.

The `crust` executable includes the assembly services, but the root chooses
whether to call them. Built-in availability does not select a target backend.
The C stage uses C99 frontend services and native allocation, file, and
process calls. Its lowering and C text construction remain Crust code.

For its first build, `make c-stage` uses `crust0` to compile the C backend
to assembly. That executable then compiles the same backend through C and
GCC. The result also builds the shared library loaded by source roots.
This bootstraps the backend and driver. `make check-c` builds one more
generation, compares emitted C and symbol response files across all three,
and runs a direct-list program built by the final generation. These builds
use no cache. The seed reader, checker, evaluator, runner, and assembly
backend remain C99 by design. The C backend calls the C99 frontend. The
separate Crust reader library is available to stages that select it.

An LLVM adapter belongs at the same library boundary. There is no LLVM
adapter in the current tree. Such an adapter must implement target layout
and ABI mapping, operation lowering, IR construction, pass options, and
emission. It must preserve source trap and alias rules. Exposing that adapter
does not by itself expose LLVM's internal algorithms.

## Lifetimes, parallel work, and cost

Contexts own arenas for compiler nodes, names, tables, and plans. Source
descriptors and bytes remain live through their consumers. A supplied
binding borrows its provider facts. Native callbacks and loaded library
code remain live until all uses finish. The default runner destroys its
evaluator before unloading libraries. The launcher then releases its host
context.

One mutable context and each syntax body have one writer. Independent
contexts can read sources, check bodies, and emit output in parallel while
sharing complete, immutable provider facts. Stable identities and diagnostic
order must not depend on worker completion order. The current drivers are
serial; the public interfaces permit a library to schedule independent work.

The root cursor has a serial dependency because an action can select the
next reader. A host evaluator also requires exclusive access from one
thread, though it permits synchronous callback reentry. These constraints
do not require independent target compilations to share that evaluator or
mutable context.

No persistent root-result cache is implemented. Root effects run on each
invocation. A cache would need captured input bytes, stage code, provider
facts, target settings, options, and external inputs, including failed file
lookups. It also needs an explicit contract for effects. It must not replay
an output effect silently or hide native stage preparation from a cold-build
measurement.

Keep frontend checks, stage execution, emission, and target toolchain time
separate. Assembly `--prepare` builds storage plans but leaves instruction
selection to emission. C `--prepare` constructs complete C and symbol text
in memory. These endpoints are different. Exclude target GCC compilation
and linking from the current frontend measurements. Passing a functional
test does not establish the project's C-speed requirement.

Safety claims also follow the selected stages. Raw seed pointers do not
justify ownership guarantees or exclusive-access metadata. The resource
stage checks local owners and loans. Persistent intrusive links require an
additional observer-validity contract across unlink, destruction, and
storage reuse; the current resource types do not express that relation.
Native host execution is trusted process code, with no sandbox guarantee.

## Read next

- [Tutorials and examples](../examples/README.md): run the stages and inspect output.
- [Language specification](crust0-spec.md): syntax, values, memory, and construction contracts.
- [Runner contract](source-runner.md): action boundaries, native calls, errors, and teardown.
- [Bootstrap guide](bootstrap.md): build commands, assembly interfaces, and validation.
- [C backend reference](c-backend.md): emission, symbol mapping, and custom bodies.
- [Exploration archive](exploration/README.md): research and recorded design decisions.
