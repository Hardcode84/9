<!-- SPDX-License-Identifier: Apache-2.0 -->

# Source-order compilation programs

Date: 2026-10-01. Status: design study retained as the experiment record.
This study examined the [native host block](source-stages.md) at revision
`9cff8f4`. The [source runner](../source-runner.md) now implements its selected
contract: exact action boundaries, semicolon-ended root compounds, incremental
host checking, and checked-tree execution. The
[reader-transfer proof](../../benchmarks/source-order/proof.md) passed before
the complete evaluator was added. Statements below about the current compiler
and required changes describe that earlier revision.

## Decision

Use this command as the intended user interface:

```sh
crust main.crs
```

`main.crs` is the host compilation program. Its code selects language readers,
checks, backends, input files, and outputs. These operations use ordinary
libraries. The launcher does not select a backend or require a second build
script. Arguments after the root path are data for that program.

Retain both requested capabilities:

1. Execute root actions in source order. An action can change the reader for
   the remaining root bytes.
2. Let those actions select how other files are read and compiled.

These capabilities have different costs. The second needs ordinary calls on
explicit compiler values. The first also needs an exact boundary between
reading an action and executing it. Parsing the whole root before execution
would implement only the second capability.

The recommended model is a small source runner with replaceable reader and
execution functions. Compiler stages remain ordinary programs. Do not add a
grammar generator, automatic phase inference, or a global stage registry.
Source-order semantics do not require those facilities.

Root orchestration is a per-request setup path. Target tokenization, lookup,
and checking are hot paths. A dispatch at an action or file boundary is a
different cost from a dispatch for every token or syntax node.

## What a root program does

This example specifies call order only. It is pseudocode, not accepted Crust0
syntax. It does not propose type inference, methods, or new import keywords.

```text
compiler = host.load("compiler/crust")
c_backend = host.load("project/c_backend")

app = compiler.new_target()
compiler.use_backend(app, c_backend)
compiler.include(app, "src/list.crs")
compiler.include(app, "src/application.crs")
compiler.build(app, "build/application")
```

The load operation is library policy. The project can replace it. The C
backend has the same status as any other library. There is no launcher test
for its path, name, entry symbol, or output format. An LLVM adapter can use
the same host execution model.

The standard root helper resolves explicit relative file paths from the root
source directory. A module library can select another explicit base for its
inputs. Child process working directories must not change those resolved
inputs. This path policy belongs to the helper, not the seed reader.

The target is explicit. Reading its source creates target declarations; it
does not execute the application's functions. Host definitions and variables
do not enter the target namespace. A library that shares code between phases
must submit that code to each phase explicitly.

Changing `app`'s reader changes how a later include call reads its input.
Changing the root reader changes how the next root action is read. These are
separate values. Neither operation silently changes the other.

The user can also call the public stages directly, use another intermediate
representation, or replace the complete compilation procedure. The standard
target helper is a convenience library, not a required pipeline in the seed.
Module search, visibility, dependency discovery, and interface publication
remain library operations.

Reaching root EOF ends root execution. It does not create a target, choose an
output, start a default compilation, or run a target entry. Explicit calls
request those operations. A root that requests no output can finish normally.

## Evidence from other languages

### Python: file execution and interactive execution differ

CPython parses and compiles a normal source file before it executes the first
statement. A syntax error near EOF therefore prevents an earlier statement's
effects. Interactive execution instead accepts and runs one complete input
unit at a time. A block can span several input lines.
[CPython 3.12.11 execution source](https://github.com/python/cpython/blob/v3.12.11/Python/pythonrun.c)

Python's import protocol lets an executed program install a loader for a later
import. That loader can read a different syntax. It cannot repair invalid
syntax in the file that Python has already tried to parse. Python therefore
provides a useful model for the external-file case, but normal Python file
execution does not supply the requested root-reader behavior.
[Python import protocol](https://peps.python.org/pep-0451/)

The [repeatable witness](../../benchmarks/source-order/python_boundaries.py)
tests these Python execution boundaries:

| Input | Observed effect |
|---|---|
| File with an early write and a later syntax error | No write |
| File with a syntax error in an unused function | No earlier write |
| File with an early write and a later runtime error | Write remains |
| One `exec` string with a later syntax error | No earlier effect |
| Two interactive units; the second has a syntax error | First effect remains |
| Incomplete interactive compound statement | No body execution |
| Completed interactive compound statement | Body executes once |
| Installed loader reads a later external custom input | Loader produces 42 |
| Installer file itself ends with custom syntax | No installer execution |

These are semantic checks. They are not compiler speed measurements.
Run them with:

```sh
python3 benchmarks/source-order/python_boundaries.py
```

### Forth and Common Lisp: process a prefix before reading more

Forth's text interpreter looks up a word and performs its interpretation or
compilation behavior before continuing. Words can consume input. The standard
also exposes the input position through `>IN`. This is a direct precedent for
code that changes how subsequent input is processed. It does not require Crust
to adopt stack syntax or Forth's error rules.
[Forth standard, sections 3.3.3.5 and 3.4](https://forth-standard.org/standard/usage)

Common Lisp's file compiler processes each top-level form before it reads the
next one. Compile-time effects can therefore change the reader for later
forms. This does not mean that every top-level function call executes during
compilation: the language has rules such as `eval-when` for that distinction.
Crust can avoid that choice in the root by assigning the entire root to the host
phase and submitting target inputs explicitly.
[Common Lisp top-level processing](https://www.lispworks.com/documentation/HyperSpec/Body/03_bca.htm)

### Racket and research: keep input and phase boundaries explicit

Racket distinguishes reading input from expanding syntax. A module reader can
accept a different character syntax. Syntax expansion alone does not provide
that operation. The useful Crust boundary is a callable reader over bytes, with
an explicit result and source location.
[Racket reader protocol](https://docs.racket-lang.org/guide/hash-lang_reader.html)

Flatt's work on composable macros explains failures caused by mixing values
from different phases or compilation instances. It uses explicit dependencies
and separate phase state. The Crust consequence is to keep host execution state
separate from target facts, and to identify the inputs of a prepared stage.
A process-global collection of whichever extensions happened to run first
does not establish those dependencies.
[Flatt, ICFP 2002](https://www-old.cs.utah.edu/plt/publications/macromod.pdf)

SugarJ reads and transforms one top-level entry, then changes its grammar for
later entries. Its implementation restricts grammar changes to top-level
boundaries. This is close to the requested order. Its reported compilation
cost is seconds with cached language preparation, and longer when syntax
rules change. Its SDF parser has cubic worst-case cost. This establishes a
working extension model, but supplies no evidence for C-level speed. Crust can
use the boundary rule with prepared reader functions, without adopting its
grammar construction machinery.
[Erdweg et al., SugarJ, sections 4.1–4.3](https://www.informatik.uni-marburg.de/~seba/publications/sugarj.pdf)

### Zig and Jai: useful control, different ordering contracts

Zig's `comptime` executes code within a fixed grammar. Its build program
configures target modules and build operations through ordinary calls. The
latter is the closer model for root-controlled external inputs.
[Zig language reference](https://ziglang.org/documentation/0.16.0/),
[Zig build guide](https://ziglang.org/learn/build-system/)

Public Jai source creates workspaces, sets options, and adds source from
functions called by `#run`. This demonstrates program-controlled compilation.
It does not establish that an earlier root statement can replace the reader
for the next unread root bytes. Source position alone is not such a contract.
[Jaibreak build source at a fixed revision](https://github.com/tsoding/jaibreak/blob/e7e206a66ae3140c5c588feb72591c2d641b0882/first.jai)

The [earlier comparison](source-metastages.md) gives the wider Zig and Jai
evidence. The present proposal changes Crust's source execution contract; it
does not claim that Jai or Zig already implements it.

## The minimum execution contract

### Startup and the seed

An initial reader and an execution mechanism must exist before the first
action can run. An extension cannot define the syntax needed to load itself
unless an earlier reader already accepts that syntax.

The installed compiler supplies one initial runner and its explicit bindings.
The first bootstrap can implement this runner in C99. A prepared Crust library
can supply a later runner. The seed needs an entry interface and host services;
it does not need a package search algorithm or backend registry. The installed
prelude can provide ordinary loading and compiler helper functions. Its code
and preparation are part of the installed compiler, not undisclosed project
setup.

Replacing the runner, parser, checker, module policy, or backend means calling
already available code. The new stage can prepare the next stage. Each such
step must have executable dependencies before it starts. Arbitrary cyclic
bootstrap dependencies have no first executable step and must be rejected.

### One source cursor, one complete action

The runner owns immutable captured source bytes and a cursor at the first
unread byte. A read operation returns one complete host action and its exact
end offset. A selected execution function executes that action once.

```text
capture root bytes
repeat:
    result = current_reader(source, cursor, host_environment)
    if result is EOF: finish root execution
    action = result.action
    check and prepare action using already available facts
    cursor = result.end
    execute action once
    use the reader selected by that execution for the next read
```

This describes semantics, not an extra virtual machine instruction set.
Reader and execution operations are replaceable ordinary functions. Their
shared action representation belongs to that runner. Target compiler stages
do not have to use it.

Each returned action retains its matching preparation and execution operations
until completion. Replacing the runner selects operations for later actions;
it must not pair an already produced action with a different executor.

Commit the consumed action's end before execution. An explicit input operation
then sees the remaining region. If that operation consumes more input, the
runner preserves its new cursor. Only the current reader or executing input
operation owns this cursor; a background job cannot change it.

The current reader owns the full current action, including its delimiter.
The next reader owns all bytes after it, including comments and whitespace.
The old reader must not report lexical errors in that next region or retain
tokens that determine its meaning. Capturing the file bytes in advance is
permitted. Interpreting the tail in advance under the old grammar is not.

A successful non-EOF read must advance the cursor within the input range.
EOF must account for the remaining bytes under the active reader's rules.
A reader failure stops that source. The runner must not retry with a default
reader, ignore an unconsumed suffix, or replay an earlier action.

### Action boundaries and fast parsing

Keep the initial grammar explicit and independent of type lookup. Calls
already end with `;`; records and function declarations have closing braces.
A reader change made by a call takes effect after the complete call action.
No per-token callback or runtime grammar generation is needed.

Compound statements need care. In `if condition { ... } else { ... }`, the
first closing brace is not the action end. The old reader must determine
whether the action includes `else` before executing it. A complete root grammar
must give such actions an unambiguous end. Requiring a final `;` for a root
compound action is one small candidate. This investigation does not select
that spelling. The first boundary experiment uses a semicolon-ended call.

A function body or block is read as part of its containing action. A call
inside it cannot change the syntax of bytes that have already been parsed.
For example, installing a reader in the first statement of an ordinary block
does not permit new syntax in the second statement of that same block.
Such behavior requires an explicit operation that passes raw input to a
reader, or a reader-defined delayed region. Do not add it implicitly.

An extension can replace the full reader. It need not fit into a table of
operators or a universal grammar. A library that combines several grammars
owns their composition rules and their cost. The standard reader must retain
its direct parsing path when no such library is used.

### Names and execution order

The host environment persists between actions. A root variable stores a host
value in that environment. A function declaration defines host code; it does
not run that function's body. Functions receive root-local variable values
through explicit parameters. This proposal does not add implicit closures
over those variables. Available constant and function bindings retain their
ordinary use within function bodies.

An executed action can call only code already available to it. A later
definition in an unread tail cannot supply an earlier call. Searching that
tail would assume the grammar that earlier execution can still replace.
Earlier signatures alone also cannot make an unavailable body executable.

Self-recursion can use the current function's signature. Mutually recursive
host definitions can be prepared together by an explicit library load or
closed compilation unit. They are then available before their first call.
The implementation must not defer arbitrary effects to make an invalid
forward call appear to work.

Target source has a separate rule. A target unit can collect all declarations
before it resolves types and checks bodies. It retains ordinary forward
references and mutual recursion. The source runner does not impose root
execution order on inert target declarations.

### State ownership, errors, and publication

Keep source descriptors, bytes, provider facts, host values, and stage code
alive for every operation that borrows them. Arena allocation fits this
contract. A session can own prepared modules until all work is complete;
per-node reference counting is not required.

A callback from native code into an interpreted host function also needs a
callable native entry and live evaluator state. Its lifetime can exceed the
call that first registered it. A native function pointer alone does not
implement this case.

Source text and externally supplied interfaces are validation boundaries.
Once a producer has established an internal representation's invariants,
internal consumers use that contract. Do not repeat full validation at each
stage call. Native stage code remains trusted process code. The seed's raw
memory rules do not become memory-safe merely because execution occurs on
the host. A checked language profile must still enforce its safety contract.

A later parse or execution error stops dependent work and reports its source
location. Earlier file writes and process effects remain. A helper that offers
atomic file publication must complete the requested build before it publishes
the artifact. A direct stream write can leave a partial prefix on failure.
A later root error cannot undo an already published artifact. Even an apparently
final publication call can precede an invalid trailing byte. Publication after
successful root EOF would require an explicit finalization operation after
that EOF is established. The minimum runner supplies no whole-root transaction.

## Parallel work and caching

The root cursor has a real serial dependency: an arbitrary action can decide
the next grammar. No scheduler can safely parse that dependent tail first
without an additional contract. Independent target work has no such edge.

A submitted target job captures its source snapshot, selected stages, and
required facts. Those inputs must stay fixed until the job completes. Copying
a table of pointers is insufficient if later root code mutates their state.
Use owned state or immutable shared state. A later change selects a new
configuration for later work. It does not modify facts already published to
another worker.

File reads, parsing, and preparation can run independently when their inputs
are ready. Checking can use complete interfaces from provider units. Lowering
and emission can run after their own required facts are ready. A language
that needs whole-program facts must establish those facts before dependent
operations. Use separate mutable contexts; do not let workers mutate one
context concurrently. Shared stage functions must support concurrent calls
or synchronize access to their shared mutable state.

The initial runner can execute all work synchronously. A library can add
parallel submission with explicit result and effect dependencies. It cannot
replace `build(path); inspect(path)` with a queued build followed by an early
inspection. Joining at shutdown does not repair that change in behavior.
The library must also join all work before destroying borrowed session state,
source storage, or stage code. An unjoined task is a lifecycle error, not
permission to detach it at EOF.

Start with no execution-result cache. Run root effects once per invocation.
Prepared code reuse is a different operation: it can avoid preparing unchanged
host code while still executing that code for the new request.

Reusing parsed or checked results requires the source bytes, reader and stage
code, configuration, bindings, target profile, and all consulted external
inputs. Changed prefix effects can invalidate an unchanged tail. Function
addresses are not stable cache identities. Module lookup can depend on absent
files and directory contents, not only files that were found.

Unrestricted native file and process calls do not automatically disclose a
complete dependency set. Result caching requires declared or observed inputs
and a specified effect policy. Do not infer that policy from a source hash.
The [metacompilation study](metacompilation.md#7-caching-without-changing-program-meaning)
defines the wider dependency and effect requirements.

## Concrete changes required in the current compiler

These findings were checked against commit `9cff8f4`.

| Current mechanism | Required change for this proposal |
|---|---|
| `take` in `src/read.c` always calls `next_token` | Permit consumption of the final token without lexing the next action. |
| `read_block` and record parsing lex beyond `}` | Return an exact action boundary. A loop around the current declaration reader is insufficient. |
| `read_meta` has one exact transfer after its final `}` | Generalize the boundary contract; the existing special case does not execute arbitrary root actions. |
| `crust_read_range` parses a complete fixed range | Add a reader operation that returns the next offset, or supply an external reader with that contract. |
| Each parsed range starts declaration ordinals at 1 | Distinguish the ordinal spaces of disjoint ranges. Preserve the identity of the same declaration when it is used in another context. |
| `crust_collect` and `crust_resolve` revisit all owned declarations | Check closed target batches once. Do not append and rescan the complete context after every root action. |
| The root grammar accepts declarations only | Add host action reading and persistent host value storage in the runner. |
| The launcher prepares one native host module before calling `build` | Supply execution before reading later actions. Repeating native preparation per action fails the cost objective. |
| Target contexts are destroyed before host code unloads | Preserve this lifetime for all callbacks and queued work. |

Repeated prefix scans cost `1 + 2 + ... + n` declaration visits for `n` forms.
Separate action contexts can avoid that scan, but copying all earlier bindings
into each context would recreate the same problem. An action needs its used
bindings, or an environment that supports direct lookup of established facts.
Neither operation is provided by repeatedly calling the current whole-context
checker.

Disjoint ranges can share the full diagnostic bytes and path while using
distinct ordinal spaces. Giving a fresh identity to every job is incorrect:
the same record declaration must retain its nominal type identity across
contexts and imported interfaces.

The current API supports independent target contexts and supplied bindings.
It does not provide a general incremental host checker or a Crust evaluator.
Those are concrete implementation requirements, not consequences of deleting
the `meta` braces.

## Execution cost and implementation choices

The earlier native host-block experiment separated prepared target work from
a request that assembled and linked its host entry. Removing a source envelope
cannot remove that preparation cost. The
[historical study](source-stages.md#cost-gate) describes the boundaries; use the
[current harnesses](../../benchmarks/source-order/README.md) for new reports.

| Execution choice | Cost and consequence |
|---|---|
| Assemble and link each root action | Repeats the measured preparation cost. Reject this route. |
| Prepare the whole root once | Reuses the current native path, but cannot meet same-file reader replacement. It is a narrower alternative only. |
| Execute checked syntax and call prepared native libraries | Avoids native preparation for small root actions. Requires complete value, call, callback, and error semantics. |
| Add bytecode or a JIT | Adds preparation work and implementation size. Measure a need before choosing it. |
| Reuse prepared native code | Can reduce unchanged-code cost. It does not establish cold behavior when project code changes. |

Use execution of checked syntax as the first candidate to investigate. Keep
large compiler stages as ordinary prepared native libraries when measuring
that configuration. Do not move target tokenization, checking, or per-node
emission into an interpreter merely to execute a short root program.

The earlier foreign-call probe executed one checked foreign call. It did not
implement root statements, user function bodies, reader replacement, or general
callbacks. Such a probe can test the call boundary; it cannot establish the
complete runner's speed or semantics.

A complete execution candidate must implement the applicable Crust0 expression
and statement rules, scalar and pointer ABI mapping, aligned local storage,
function values, recursion, and native callbacks into host functions. It must
also define reentrant calls and error propagation. A call-only configuration
language cannot be presented as ordinary Crust execution.

The current seed is about 5,400 C and header lines. This investigation adds no
evaluator and establishes no new line-count result. The user asked whether
the core can fit in 10,000 or 20,000 lines. Measure the added executor against
both sizes. Count the whole seed, native-call adapters, and platform support.
Report external runtime dependencies separately; excluding their source does
not remove their cost.

## Bounded experiment and stop conditions

The first experiment must prove reader transfer and real target output.
Do not build a general interpreter first. Use explicit prepared host libraries
and a small experimental executor. Reject unsupported action forms.

The witness root performs setup, selects the ordinary Crust C backend, includes
the real intrusive-list input, switches its own reader, and requests output.
All compilation choices occur in the root. The harness receives the root path
and has no backend-specific branch.

Immediately after the reader-switch call's semicolon, put a byte rejected by
the initial grammar. The selected Crust reader must consume a small custom form
that creates a target helper with observable behavior. The intrusive target
must call that helper, including a forward call to an ordinary target function.
Skipping an invalid marker without changing target meaning is insufficient.

The experiment must establish these results:

1. The old reader does not diagnose the new reader's first byte. The new reader
   receives the exact offset and original source locations.
2. Setup and selection execute once. A selection failure stops before the new
   reader runs. A later malformed custom form produces the correct diagnostic.
3. The produced intrusive executable runs insertion, unlink, individual
   destruction, storage reuse, and traversal. Its output verifies the custom
   helper. This is a raw bootstrap witness, not a checked ownership proof.
4. Host and target names remain separate. A copied and renamed backend library
   works through the same interface. The target has no compiler dependency.
5. A retained target operation runs after the reader call returns. Source,
   facts, callback code, and allocator state remain valid through context
   destruction. Check that lifetime with sanitizers before measuring time.
6. No assembler or linker runs between actions. Unimplemented host operations
   fail explicitly. No retry, fallback reader, or silent tail discard occurs.

Then run 25 randomized paired rounds in fresh processes on one fixed CPU.
Include root capture, host input checking and preparation, library loading,
action execution, target reading and checks, and complete C and symbol output.
Exclude final target GCC compilation and linking. Record installed libraries,
prepared project libraries, and changed project-stage preparation separately.
No prepared input can be reported as cold source preparation.

Use the intrusive case first, then the existing 1,000- and 8,000-function
workloads. Require the upper paired 95% ratio bound against matched original-C
GCC syntax to be at most 1 on each. Include a root with no reader change and
the ordinary target path as controls. Reject repeated whole-prefix scans.

Stop after this boundary and ownership experiment. A pass supports a separate
decision about a complete executor; it does not prove one. A failure requires
an attributed cost before additional machinery is selected. Do not expand to
a VM, persistent cache, scheduler, or production syntax on the strength of a
call-only result.

After that decision, a complete executor must pass the language conformance
tests through host execution, including callbacks and failure paths. Changed
project-stage code must receive its own cold timing result. Those results are
required before replacing the current implementation with this source model.

## Contract comparison

| Property | Current host block | Proposed source runner |
|---|---|---|
| User command | Root first, then stage arguments | `crust main.crs`, then root arguments |
| Host selection | Leading `meta` block and named entry | Root execution starts with the first action |
| Host dependency loading | Flat prefix input list | Ordinary executed library calls |
| Target input | Remaining root range or explicit other files | Explicit target submission; other files are the simple case |
| Reader changes | One initial transfer | Transfer after each complete root action |
| Host forward references | Complete host unit is checked first | Available earlier code, or explicit prepared batch |
| Target forward references | Complete target unit | Retained within complete target units |
| Stage status | Ordinary external code | Retained |
| Ownership and module policy | Library responsibilities | Retained |
| Target runtime cost | No implicit host runtime | Retained |
| Cold C-speed evidence | Current full host path fails | Requires the experiment and complete executor measurements |

Keep the implemented specification until a replacement satisfies these gates.
The simpler user interface is useful. The technical claim must be an explicit
execution contract with measured cost, not a new name for the current loader.
