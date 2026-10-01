# Public compiler stages and a C compiler witness

Date: 2026-10-01. Status: proposed interfaces and a bounded experiment.

This document extends the [metacompilation study](metacompilation.md).
It defines how much of the compiler a user can replace. It adds no compiler
implementation or timing result.

The [Crust0 specification](crust0-spec.md) defines the concrete bootstrap language
and takes precedence over seed proposals in this study. Its core has explicit
declaration bindings; module management belongs to a metastage.

Reading guide: [interface](#1-extension-boundary),
[ownership and unsafe](#ownership-and-unsafe-are-language-stages),
[syntax](#2-replace-the-base-syntax),
[LLVM](#3-the-backend-adapter-is-a-metastage),
[C benchmark](#4-c-compiler-witness), [measurement](#5-cost-and-parallelism),
[acceptance](#6-decision-gates).

## 1. Extension boundary

Expose the complete compiler as libraries. The standard Crust driver is one
program that uses these libraries. A user can replace the base syntax,
language rules, intermediate representations, scheduling, and backend adapter.
The user program contains the code that selects its custom stages. These
stages are ordinary functions, defined in the user source or supplied by
external libraries. The C backend is one such library. A separate build file
is not required. The interface is ordinary compiler code with explicit inputs
and outputs.
It does not require a universal grammar engine or a plugin registry.

| Component | User control | Required contract |
|---|---|---|
| Reader | Replace tokenization, grammar, operators, and whitespace rules | Source locations and declared parsing dependencies |
| Frontend | Replace binding, types, conversions, lifetime rules, and lowering | State which language rules the result satisfies |
| Module library | Replace source discovery, imports, visibility, interfaces, and dependency policy | Supply consistent declaration bindings before dependent checks |
| Intermediate representation, or IR | Construct, inspect, edit, or replace it | Publish its meaning and the preconditions of each consumer |
| Driver | Add, remove, combine, or reorder stages | Supply each stage's inputs before execution |
| Backend adapter | Replace target queries, ABI lowering, IR construction, passes, and emission | Preserve source meaning and satisfy the chosen backend contract |
| Build services | Select scheduling, caching, linking, and artifact output | Track the inputs that affect each result |

Use two entry routes. A syntax extension can produce standard Crust code or IR,
which the normal Crust checkers accept or reject. A complete language frontend
can supply its own checker and lower to public low-level operations. It need not use the
Crust syntax tree or ownership checker. A frontend can also use its own IR and
provide the conversion to its selected backend.

Shared low-level operations need explicit meanings for storage, arithmetic,
control flow, calls, and memory access. They must not attach Crust ownership or
non-aliasing assumptions to arbitrary foreign-language pointers. A changed
checker or lowering stage is part of that compiler's trusted implementation.
Each compiler configuration claims only the guarantees that it establishes.

The library source and APIs remain public. Access must include constructors
and operations needed to replace a stage, not only observation callbacks.
Version the interfaces with the compiler. A stable binary plugin ABI is not
required for this experiment.

### Ownership and unsafe are language stages

The [resource stage proposal](resource-metastage.md) applies this boundary to
the current runner, checker, and backend APIs. It specifies cleanup slots,
retained ownership facts, and the first implementation experiment.

Keep three layers distinct:

| Layer | Contents |
|---|---|
| Bootstrap seed | Primitive values, storage, calls, control flow, and basic type and layout operations sufficient to build compiler libraries |
| Standard Crust language libraries | Reader, module management, binding and type rules, ownership and borrowing, address stability, unsafe policy, and cleanup lowering |
| Backend libraries | Target description, ABI operations, backend IR construction, optimization, and emission |

The seed does not contain a special ownership algorithm. It admits low-level
memory operations with explicit primitive semantics. This alone does not
establish temporal memory safety. The standard language's compiled checker
establishes its declared lifetime rules before lowering to those operations.
A small seed does not imply a small trusted implementation: the checkers and
the transformations that preserve their results remain part of that trust.

Put all complex ownership policy in metastages. This includes moves, loans,
escape rules, persistent aliases, address stability, partial initialization,
and the checks required for cleanup. Keep the representation they need in
ordinary library types. A low-level pointer IR cannot by itself recover which
source operation was a borrow, a move, or a resource acquisition.

The standard sequence can be:

~~~text
Crust reader and type rules
    -> typed resource IR with moves, borrows, scopes, and unsafe regions
    -> ownership and lifetime checker
    -> checked resource IR
    -> cleanup lowering for each supported exit
    -> low-level IR
    -> backend adapter
~~~

These are replaceable library stages. They can share a representation or fuse
work when their contracts permit it. Full copies between each step are not
required. Any edit after checking must preserve the checked facts or trigger
the affected check again.

The spelling and parsing of `unsafe` belong to the selected reader. Its
meaning belongs to the selected language checker. In standard Crust, it can
mark a region or function that permits specified unchecked operations.
An unsafe region's implementation must establish the operation's preconditions.
An unsafe function's signature declares obligations for its callers. A safe
wrapper must establish the internal preconditions before exposing a safe call.
The marker does not silently remove ordinary type checks or scheduled cleanup.
Preserve authorization through expansion. Generator-authored operations retain
their definition-site contract. Inserted caller code retains its caller context;
it does not obtain the generator's unsafe permissions merely through insertion.

The seed and a C reader need no `unsafe` keyword. C uses its own pointer rules.
A custom language can choose another syntax or another policy. The standard
Crust driver selects its safety stages by default. Removing them changes the
language guarantee; it is not a speed result for standard checked Crust.

Compile the ownership library with an earlier available seed or Crust compiler.
Then execute that library to check later Crust programs. Do not require it to
check its own unfinished implementation during construction. Later self-builds
can check the library under the resulting standard language rules.

Measure the checker's work within the frontend budget. Prepared native code
avoids repeated stage construction; it does not remove analysis cost. Plain
functions need not run complex loan analysis when their operations and called
interfaces create no such obligations. C mode does not run the Crust checker.

This placement does not solve the direct-list lifetime problem. The standard
ownership library still needs a precise contract for individual destruction,
retained aliases, and exact-address reuse. User-written intrusive-list code
must satisfy that contract without a mandatory pool or a hidden unchecked
implementation. Metacompilation is the implementation mechanism for the rules,
not evidence that the rules meet the requirement.

## 2. Replace the base syntax

Complete syntax replacement is permitted. A C frontend can own a file from
its first byte. A Lisp reader, a Forth reader, or a different Crust grammar can
do the same. Racket provides a useful precedent: a language can replace both
the reader and expansion rules. This is evidence for the interface model,
not for C-level compilation speed.
[Racket language construction](https://docs.racket-lang.org/guide/languages.html)

Select the language package before parsing its source. Compilation code in the
user program maps input units to prepared readers. An already available reader
must recognize that compilation code. A directive that selects a reader for
a following region would also need an already known grammar. The
[Zig and Jai review](source-metastages.md) rejects a mandatory two-region
envelope for ordinary backend selection. The exact source spelling is not
selected by this experiment.

Compile each reader with an earlier available compiler configuration. Once
prepared, the reader can process many files. It does not need to compile its
own definition each time it sees an input file.

The default Crust reader keeps its regular, name-independent grammar. A custom
reader can add operators, use indentation, combine grammar fragments, or
change parsing rules in source order. Its implementation must define conflict
resolution and dependencies. Worker completion order must not decide grammar
meaning. Changes in source order introduce real ordering constraints.

C demonstrates why the whole frontend must be replaceable. In `T * x;`, the
meaning depends on whether `T` names a type or a value in that scope. Clang's
lexer returns both as identifiers; scope information is needed later.
Thus the public API must permit parsing and name resolution to cooperate.
It must not require every language to finish a name-independent parse first.
[Clang tokens and annotation tokens](https://clang.llvm.org/docs/InternalsManual.html#annotation-tokens)

Stage boundaries describe data dependencies. They do not require separate
passes, copied syntax trees, or a complete token array between each function.
Configure the reader once per unit. Do not require a dynamic callback for
each token merely to expose the parser.

## 3. The backend adapter is a metastage

A backend metastage is ordinary compiler code that runs during a build. It
can lower an IR to LLVM, select passes, and request machine code. It can also
use another backend. Compile standard adapters when the compiler distribution
is built. A metastage does not imply an interpreter, JIT, or generated runtime
service in the target program.

Expose both the lowering into the backend and the backend invocation. The
following code illustrates the call structure; it is not an adopted API:

~~~text
target = llvm_adapter.describe_target(target_options)
unit   = c_frontend.parse_and_check(sources, c_options, target)
core   = c_frontend.lower(unit, target)
abi_ir = c_abi.lower(core, target)
module = llvm_adapter.construct_ir(abi_ir, target)
record_handoff()
object = llvm_adapter.optimize_and_emit(module, target, backend_options)
image  = linker.link(objects + object, link_options)
~~~

Every component in this sequence is replaceable. A driver can combine stages
or use a different representation between them. It can inspect and change
LLVM IR before emission. It can stop at IR, emit an object, or select another
output path. There is no mandatory text serialization and reparsing between
stages. The public driver also controls linking and any selected link-time
optimization.

Target information is needed before the final emission call. Type layout,
`sizeof`, alignment, pointer width, and foreign calls can affect frontend
decisions. Use one consistent target description throughout the pipeline.
For cross-compilation, compile-time code runs on the host but queries the
declared target layout. Host layout is not an implicit substitute.

LLVM requires a module's data layout to agree with the target code generator.
Its target interface supplies target-machine and data-layout facilities.
These do not perform all C ABI classification for a frontend. Clang has a
separate ABI layer for function arguments and returns. The C frontend and
adapter must preserve that distinction.
[LLVM data layout](https://llvm.org/docs/LangRef.html#data-layout),
[LLVM object emission tutorial](https://llvm.org/docs/tutorial/MyFirstLanguageFrontend/LangImpl08.html),
[Clang 21.1.0 ABI interface](https://github.com/llvm/llvm-project/blob/llvmorg-21.1.0/clang/lib/CodeGen/ABIInfo.h)

Preserve the source ABI type information until classification is complete.
For example, do not discard aggregate argument structure and later try to
recover its calling convention from independent scalar operations. Record
layout and a default LLVM calling convention do not supply this information.

Backend freedom has a concrete correctness obligation. The adapter must
preserve overflow behavior, alignment, calling conventions, volatile access,
atomic ordering, and valid alias assumptions. LLVM attributes and instruction
flags can make stronger claims than the source permits. A structurally valid
LLVM module is not proof that those claims are correct.
[LLVM language reference](https://llvm.org/docs/LangRef.html)

Use LLVM's verifier in adapter validation and development checks. Validate
external IR and cache files at their input boundary. Trusted internal stages
use their documented contracts; do not add repeated file validation to every
IR access. An invalid module from a trusted stage is a compiler defect.
State the verifier configuration in each timing result.

Public IR editing also needs a handle-lifetime contract. An erase or replacement
can invalidate a reference while its LLVM context remains alive. A raw binding
must expose these validity requirements. A safe binding must control retained
access across such edits or provide explicit tracking with measured costs.
Context ownership alone does not establish instruction lifetime.
[LLVM 21.1.0 value handles](https://github.com/llvm/llvm-project/blob/llvmorg-21.1.0/llvm/include/llvm/IR/ValueHandle.h)

The public adapter can use LLVM bindings and a versioned native bridge where
needed. It can expose LLVM pass construction and analysis invalidation.
This does not make every LLVM internal algorithm replaceable through one
callback. Changes that lack an LLVM extension API require a modified LLVM
library or a different backend implementation. Publish this dependency.
[LLVM pass construction and extension points](https://llvm.org/docs/NewPassManager.html)

The default route can use direct calls and in-memory IR. Selecting a backend
must not force unused adapters to initialize or create backend-specific IR.
Measure binding calls, copies, pass setup, and module merges when they occur.
Do not introduce a second general IR solely to make this interface look uniform.

## 4. C compiler witness

Build a C frontend and driver in Crust through the public compiler libraries.
Call the resulting compiler `crust-cc`. It must process unchanged C source and
headers, establish the selected C semantics, and use the public backend adapter.
The primary path must implement its own preprocessing, parsing, and checking.
A call to Clang or a host preprocessor is a separately named comparison.

The construction is:

~~~text
installed Crust compiler + C frontend and driver written in Crust
    -> crust-cc
    -> unchanged C source
    -> C checks and lowering
    -> public LLVM adapter
    -> object, executable, and program result
~~~

This tests compiler construction through libraries. Crust self-hosting is the
separate act of compiling the Crust compiler's own Crust source. A C bootstrap
chain can extend this witness without adding a Crust-to-C translation backend.

C support needs more than its grammar. It needs preprocessing and includes,
scopes, conversions, initializers, linkage, object lifetimes, qualifiers,
aggregate layout, and the selected target ABI. These obligations are present
even when the compiler implementation uses safe Crust code. They do not require
adding Crust destructors or ownership checks to ordinary C programs.
[C11 committee draft N1570, clauses 5.1.1.2, 6.2, 6.3, 6.5, 6.7, and 6.10](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf)

### Freeze the inputs

Use Linux x86-64, LP64, and a pinned System V ABI as the first target.
Freeze a named GNU C11 workload profile. Its claim covers the features in
the frozen inputs and tests; it does not establish all-C or kernel support.

| Witness | Pin and purpose |
|---|---|
| SQLite reader in C | The C baseline of the [SQLite ownership witness](language-exploration.md#101-establish-one-complete-boundary); reaches real foreign calls and deterministic output |
| SQLite implementation | Version 3.50.4, `sqlite-amalgamation-3500400.zip`; large single translation unit, using the existing GNU C11 profile |
| C compiler | chibicc commit `90d1f7f199cc55b13c7fdb5839d1409806633fdb`; multiple translation units, compiler construction, and its tests |
| Small nonempty C units | Typedef shadowing, macro state, calls, and layout; prevent large-source savings from hiding startup and interface costs |

The [existing profile harness](../benchmarks/frontend/profile.py) records the
SQLite archive URL and SHA-256. Retain its default SQLite feature macros.
Archive the pinned chibicc source as well. Its author rewrites repository
history, so a branch name is not a sufficient source identity.
[Pinned chibicc source and scope](https://github.com/rui314/chibicc/blob/90d1f7f199cc55b13c7fdb5839d1409806633fdb/README.md)

Before implementation, archive the sysroot and record header hashes, include
search order, predefined macros, dialect options, ABI revision, and target
options. Record assembler, linker, runtime libraries, and the exact test
selection. Inventory the preprocessor output and required extensions for each
reference compiler. Compiler-specific branches can produce different inputs.
Do not assume that the same file name means identical preprocessing work.

The current profile records do not archive the full header closure. The next
preparation step is to capture that closure and its feature manifest. Do not
claim a supported C profile until those inputs are fixed. An unsupported
feature must produce a diagnostic. Do not change the dialect or disable a
production feature to make a frozen witness pass.

Before implementation, require reference-built chibicc to complete the proposed
bootstrap chain and selected tests on those headers. Its include paths depend
on fixed system directories and its executable location. Freeze and verify
the header placement for every stage. Moving B2 must not change its header
inputs. If this preparation fails, identify the incompatible header or compiler
rule and establish a working reference profile before freezing the benchmark.
[Pinned chibicc include setup](https://github.com/rui314/chibicc/blob/90d1f7f199cc55b13c7fdb5839d1409806633fdb/main.c#L53)

### Require executable results

Start with the C SQLite reader linked to a reference-built SQLite library.
Then compile the frozen SQLite implementation with `crust-cc` and run the same
reader. Add a fixed selection from SQLite's public tests and record every
selected test. SQLite's complete internal test program is not all public;
TH3 is proprietary.
[SQLite test harnesses](https://sqlite.org/testing.html#test_harnesses)

Compile chibicc with `crust-cc` to produce B1. Use B1 to compile the same chibicc
source to B2, then use B2 to produce B3. Run the selected compiler tests for
each result. Freeze source paths, options, headers, assembler, and linker.
Require deterministic B2/B3 output equality. B1 and B2 have different code
generators, so byte equality between them is not the gate.

Upstream chibicc supplies stage2 tests, but no stage3 comparison target at
this pin. Its test harness uses a host-compiled helper and host linking.
Record this mixed-compiler boundary. The B3 step is an added experiment.
Self-reproduction tests consistency; it does not prove C conformance.
[Pinned chibicc build and tests](https://github.com/rui314/chibicc/blob/90d1f7f199cc55b13c7fdb5839d1409806633fdb/Makefile)

Also link candidate-generated functions with Clang- and GCC-generated callers
and callees in both directions. Cover the selected scalar, floating, aggregate,
variadic, callback, and layout rules. Inspect required memory operations in
the generated code. Syntax-only success cannot establish these contracts.

## 5. Cost and parallelism

Classify parsing, checking, lowering, and adapter calls as compiler hot paths.
Compiler construction is a build-time path. Stage preparation is part of the
application request whenever that request must perform it.

Keep the existing [check and handoff boundaries](language-exploration.md#103-define-the-timing-boundary).
Check time includes preprocessing and semantic work. Handoff time also
includes all required lowering, target setup used by the frontend, ABI work,
and complete LLVM IR construction. It stops before backend optimization,
instruction selection, register allocation, and object emission.
Record this boundary inside the adapter. A package called `backend` cannot
move required pre-handoff work outside the measurement.
Complete all promised module construction before recording handoff. Deferred
IR construction still belongs to that work. When comparing serialized output,
record serialization and decoding separately on both sides.

| Configuration | Timed work | Interpretation |
|---|---|---|
| Installed `crust-cc`, cold C build | Fresh process, component loading, empty compilation-result caches, complete C check or handoff | Primary comparison with installed Clang and GCC |
| Installed Crust, project stages supplied as source | All required stage preparation and the complete C build through the selected endpoint | On-demand compiler extension cost |
| Prepared project stages, cold C build | Loading and execution of supplied stage artifacts; empty application-result caches; complete C check or handoff | Prepared-stage result, with the artifact starting state recorded |
| Full compiler construction | Declared seed, compiler libraries, C frontend, adapters, and requested C build | Construction benchmark with an explicit starting state |
| Warm application | Actual cache validation, loading, and remaining work | Application-result reuse, with stage preparation state recorded separately |

If a project stage needs native compilation and linking before it can execute,
count that work in its request. This applies to the C frontend and to a custom
LLVM adapter. The excluded backend work is the final target program's backend
processing, not native code generation required to reach its frontend endpoint.

Record exactly which artifacts exist before each run. Building an installed
compiler is outside ordinary application timing on both sides. Preparing a
project-specific stage belongs inside the source-supplied configuration.
A prepared stage can process a cold application, but that result must name
the supplied artifact. It cannot establish on-demand preparation speed.
State filesystem cache state separately from compilation-result cache state.

Measure the same C frontend in a fixed direct-call driver and through the
public user driver. Keep operations, checks, representations, allocations,
and backend choices equal. If the public interface already consists of direct
calls, both drivers may have the same call sequence. Do not add dispatch solely
to manufacture a comparison. Report absolute time and the driver/direct ratio.
This isolates interface cost; it does not prove that either frontend is fast.

C macro definitions and includes have source-order effects. Included text can
even be part of a declaration or statement. Start with independent translation
units as the C parallel unit. Do not schedule arbitrary headers as independent
syntax modules. Immutable file bytes can still be shared.
[GCC macro state](https://gcc.gnu.org/onlinedocs/cpp/Undefining-and-Redefining-Macros.html),
[GCC include operation](https://gcc.gnu.org/onlinedocs/cpp/Include-Operation.html)

For LLVM work, use independent contexts and owned modules, or serialize access
to a shared context. LLVM documents concurrent work through separate contexts.
Public stage access does not permit concurrent mutation of shared LLVM state.
Choose module partitioning from the workload. Count extra IR copies, contexts,
and merges; a lock or separate context is not free parallelism.
[LLVM threads and contexts](https://llvm.org/docs/ProgrammersManual.html#threads-and-llvm)

Pass the single-worker gate first. Then compare 2, 4, and 8 workers with equal
worker budgets for both compilers. Permit parallel baseline compiler jobs on
the chibicc units. SQLite's single amalgamation tests large-unit latency; it
does not by itself establish parallel parsing speed.

Cache identity must include language selection, parser and checker code,
driver order, target and ABI rules, adapter and LLVM versions, and all observed
source, header, macro, and search inputs. Add pass options to the products
they affect. A header path alone is not a valid preprocessing cache key.
Keep [absence dependencies and direct IR edits](metacompilation.md#7-caching-without-changing-program-meaning)
in the invalidation tests. Backend replacement must invalidate affected output
even when source bytes are unchanged.

## 6. Decision gates

1. Freeze the C inputs, feature manifest, target, expected results, and timing
   endpoints. Keep Crust's safe SQLite and direct-list requirements separate.
2. Produce the C SQLite reader through public frontend and backend calls.
   Reach its final output before expanding the C feature set. Do this without
   seed changes, private compiler hooks, or host frontend delegation.
3. Replace one real LLVM lowering operation through the public adapter API.
   Test its output and ABI. A callback that only delegates to a hidden producer
   does not establish replacement access.
4. Compile the full frozen SQLite and chibicc inputs. Run the selected tests,
   ABI tests, and B1/B2/B3 chain. Diagnose unsupported inputs explicitly.
5. Compare check time with current release Clang and GCC. Compare handoff at
   the documented Clang frontend-to-LLVM boundary. Freeze compiler revisions
   and use the fastest eligible reference at each boundary.
6. Use at least 20 randomized paired samples per comparable workload. Apply
   the [existing median and confidence rule](language-exploration.md#104-test-matrix-and-pass-rule):
   candidate/C median at most 1.00, with the upper 95% confidence bound at most
   1.00. More samples can resolve noise. A warm win cannot waive a cold failure.
7. Compare direct and public drivers, then equal worker budgets. Require the
   same candidate diagnostics and equivalent program results. Measure CPU
   time, peak memory, and IR size as well as elapsed time.
8. Change language selection, helpers, headers, macros, target, adapter,
   checker rules, and pass configuration. Cached and cache-disabled results
   must agree. Run with no LLVM adapter selected and check for unwanted work.

Do not average away a failed workload or assign an arbitrary interface-cost
allowance. Identify the failing operation and repeat the same witness after
changing its contract. No result here proves Crust ownership-checking speed,
safe intrusive-list reclamation, or complete Linux/GCC/LLVM source coverage.
Those claims retain their own required witnesses.
