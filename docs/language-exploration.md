# RMD: exploration of a small systems language

Date: 2026-09-30. Status: research and a proposed experiment.

Reading guide: [recommendation](#1-recommendation),
[language research](#3-lessons-from-existing-languages),
[Jai](#4-jai-public-evidence), [academic work](#5-academic-ideas),
[intrusive lists](#69-intrusive-lists-with-individual-destruction-and-reuse),
[syntax](#7-syntax-that-is-simple-to-parse-and-read),
[parallel stages](#8-compiler-stages-that-permit-parallel-work),
[acceptance gates](#10-production-witness-and-acceptance-gates).

## 1. Recommendation

Start with a small language of values, functions, records, tagged unions, and
explicit storage. Add move-only resources, automatic scope cleanup, and local
borrows. Use explicit module interfaces and function types. Make syntax independent
of name resolution. Permit independent files and function bodies to compile in
parallel.

**C-level front-end speed is the first acceptance condition.** A feature that fails
this condition does not enter the core, even if it has no runtime cost.

A required production witness is an intrusive doubly-linked list implemented in
ordinary safe user code. Nodes must support individual destruction and storage
reuse while the list remains live. An arena that only releases all nodes together
does not meet this requirement.

The first experiment should have these properties:

- A regular grammar with visible declarations, blocks, and statement ends.
- No textual headers, source macros, overload search, or user code execution during compilation.
- Complete function signatures. Local expressions can determine local variable types.
- One owner for each resource. Moves transfer ownership without user code.
- Automatic cleanup on normal scope exits, including explicit error returns.
- Lexical shared or exclusive borrows. Borrowed data cannot enter persistent storage.
- Explicit result values, allocation, C calls, and unsafe operations.
- No mandatory garbage collector, reference count, exception runtime, or scheduler.

The largest design risk is the borrow interface. A rule that forbids all borrowed
returns is small, but it forces many container APIs to use callbacks. Those callbacks
can add calls, obscure control flow, and make ordinary code harder to write.
Compare this strict rule with a narrow extension: a returned view names one input
as its source. Do not start with a general lifetime language.

Use opt-in checked pool keys for reclaimable intrusive links. They support
individual destruction and reuse without a heap-shape solver. Their generation
metadata and validity checks are an explicit selected cost. Ordinary owners and
borrows do not acquire that metadata. Section 6.9 specifies the contract and
compares the stronger static alternative.

This document proposes rules. It does not claim a soundness proof, a completed
language, or a measured speed result. The source research used three parallel
investigations: C/C++/D, Rust/Zig, and academic ownership models. The C/C++/D
investigation also covers public Jai material.

## 2. Requirements and evidence

Use this priority order:

1. Match or beat C before backend processing, including a single-worker build.
2. Keep syntax and semantics small enough to learn and implement.
3. Preserve direct control of storage, layout, allocation, and calls.
4. Prevent common resource and memory errors without a large proof system.
5. Expose independent work to the compiler. Parallelism must improve an already fast path.

The intrusive-list requirement includes writing the list algorithm itself.
Calling a compiler-provided list or a list implemented with unsafe code is not
sufficient evidence. The allocator and identity issuer are trusted primitives.
The splice and unlink algorithm must remain safe user code.

“Zero overhead” means comparison with C code that has the same behavior.
A checked array access has a possible branch. A resource must be released.
An optional value may need a tag. These costs do not disappear because a feature
has a useful name. List them and measure them.

Opt-in checked links are permitted to pay for generation checks and identity
metadata. Compare them with equivalent checked-key C to measure language overhead.
Also report their cost against raw-pointer C. Do not call that added safety free.

Code that does not use a feature must not acquire its runtime support.
For compilation, every language has some shared parser and type-system cost.
The narrower requirement is that an unused feature causes no extra expansion,
specialization, analysis, or runtime dependency.

The source notes below describe published mechanisms. The proposed rules and
performance gates are our design decisions. No cross-language speed ranking was
measured for this study.

## 3. Lessons from existing languages

### C

Keep direct data layout, ordinary functions, explicit allocation, and the target
C calling convention. C does not protect object lifetimes. Its rules also include
undefined signed overflow and restrictions on access through incompatible types.
Records can contain padding. A C-compatible record is therefore not a portable
file format. Use explicit encoding for external data.
[C23 working draft N3096, sections 6.2.4, 6.5, and 6.7.2.1](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n3096.pdf)

Keep a small compilation unit, but replace textual inclusion with module
interfaces. Clang documents the repeated preprocessing and parsing caused by
headers. Compiled interfaces can remove that repeated work. They still have a
loading cost proportional to the information needed.
[Clang modules](https://clang.llvm.org/docs/Modules.html)

C committee draft N3734 explores lexical `defer`, including reverse cleanup
order and evaluation of the return value before cleanup. It is a draft technical
specification, not a C23 feature. It shows a useful design direction without an
object hierarchy.
[C defer draft N3734](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n3734.pdf)

### C++

Keep deterministic destruction of completed local objects. It does not require
inheritance or heap allocation. Exception unwinding adds rules for partial
construction and destruction; the proposed language uses explicit error returns.
[C++ block declarations](https://eel.is/c++draft/stmt.dcl),
[C++ construction and exceptions](https://eel.is/c++draft/except.ctor)

Do not copy the implicit special-member rules. A declared destructor can prevent
an implicit move constructor, and a move expression can select a copy constructor.
Use one ownership transfer operation and an explicit function for cloning.
[C++ copy and move constructors](https://eel.is/c++draft/class.copy.ctor)

Drop behavior can also affect an ABI. The Itanium C++ ABI passes some classes
with non-trivial operations indirectly. A one-word resource wrapper is not
automatically equivalent to a one-word C argument. Test call and return code.
[Itanium C++ ABI](https://itanium-cxx-abi.github.io/cxx-abi/abi.html#non-trivial)

Template work can occur during overload resolution, type determination, and
constant evaluation. A function need not reach the final executable to cause
this work. Exclude these forms of implicit search from the first experiment.
[C++ template instantiation](https://eel.is/c++draft/temp.inst)

### D

BetterC retains modules, RAII, scope guards, slices, and bounds checks without
the D runtime. It excludes exceptions and garbage collection. It also retains
extensive metaprogramming, so it is evidence for runtime independence, not a
complete design for our compilation target.
[D BetterC](https://dlang.org/spec/betterc.html)

D places local destructors and scope guards in a shared reverse lexical order.
Its failure and success guards refer to exception exits. An explicit-result
language must define its own failure rule before it adds such guards.
[D scope guards](https://dlang.org/spec/statement.html#ScopeGuardStatement)

D's `scope` and `return scope` provide compact escape summaries.
They are not exclusive-ownership rules. Scope protection also does not
automatically extend through every level of pointer indirection.
These are useful models for a possible single-source borrowed return, not proof
that a short annotation solves all alias problems.
[D safe memory rules](https://dlang.org/spec/memory-safe-d.html#scope-return-params),
[D scope attribute](https://dlang.org/spec/attribute.html#scope)

D separates checked code from trusted wrappers and unrestricted operations.
Its `@nogc` excludes GC allocation, not all allocation. Its CTFE can execute
function bodies; an infinite compile-time loop can hang compilation.
Use a small unsafe boundary. Omit GC instead of adding a no-GC effect.
Do not execute ordinary functions during compilation.
[D functions](https://dlang.org/spec/function.html)

### Rust

Keep explicit ownership transfer, exclusive mutation, tagged results, and a
checked boundary around raw operations. Rust's borrow checker tracks moves and
initialization, generates region constraints, and checks loans on MIR. This is
compiler work, but it does not establish that borrowing dominates Rust build time.
[Rust borrow checking](https://rustc-dev-guide.rust-lang.org/borrow-check.html)

Conditional initialization and moves can require runtime drop flags. Rust can
remove them when the state is static. Partial field moves add finer cleanup
states. A language cannot promise no cleanup bookkeeping without specifying its
control-flow rules.
[Rust drop elaboration](https://rustc-dev-guide.rust-lang.org/mir/drop-elaboration.html)

Trait candidate search, nested obligations, macro expansion, and generic
specialization are separate costs. Exclude open trait search and generated
declarations from the core. Monomorphization remains in our pre-backend timing
budget even if a compiler calls it a backend phase.
[Rust trait resolution](https://rustc-dev-guide.rust-lang.org/traits/resolution.html),
[Rust macro expansion](https://rustc-dev-guide.rust-lang.org/macro-expansion.html),
[Rust monomorphization](https://rustc-dev-guide.rust-lang.org/backend/monomorph.html)

Ownership does not imply address stability. A bytewise move can break
self-references or intrusive links. Do not permit safe self-references in movable
records. Use stable owned storage when an address must remain fixed.
[Rust pinning](https://doc.rust-lang.org/std/pin/index.html)

### Zig

Keep explicit allocator use, scope cleanup, optional values, and error unions.
Zig leaves pointer and slice lifetime correctness to the programmer. Runtime
checks depend on the build mode and local settings. Those checks do not provide
static lifetime safety.

Zig's grammar targets constant lookahead and linear recursive-descent parsing.
This is a useful syntax goal. Its `comptime` and inferred error sets introduce
dependencies beyond parsing. Inferred errors can make a function generic and
conflict with recursion. Use explicit error types and bounded constant expressions.
[Zig language reference, development snapshot](https://ziglang.org/documentation/master/)

Zig 0.16 changed type resolution to address dependency cycles and repeated
analysis. Its release notes also separate LLVM input construction from object
emission. This supports a precise stage boundary, not a claim about C-speed builds.
[Zig 0.16 type resolution](https://ziglang.org/download/0.16.0/release-notes.html#Reworked-Type-Resolution)

### Jai

The Jai source review appears in section 4. Public demonstrations are useful
design evidence. They do not provide a reproducible baseline for this repository.

### Other useful comparisons

| Source | Useful concept | Decision |
|---|---|---|
| Go | Explicit dependencies and exported type information | Use interfaces that do not require imported function bodies. |
| Odin | Explicit memory policies and scope cleanup | Keep allocation visible. Do not require an allocator context in every function. |
| Hare | A small language with manual ownership conventions | Keep the small vocabulary. Add enforcement where the core promises it. |
| C3 | C-oriented code, defer, errors, and modules | Study the combinations. Exclude unrestricted compile-time work from the core. |

Go's design account explains how export data and acyclic package dependencies
reduce repeated source processing. It also describes syntax that does not require
type information for parsing. These are design precedents, not measurements of
our proposal.
[Go at Google](https://go.dev/talks/2012/splash.article)

Odin documents manual memory management and allocator support through its context.
Hare explicitly states that its ownership terms do not prevent double free or
use after free. C3's specification includes scope cleanup and compile-time control
flow. Convenient cleanup alone is not a lifetime guarantee.
[Odin overview](https://odin-lang.org/docs/overview/),
[Hare introduction](https://harelang.org/tutorials/introduction/),
[C3 specification](https://c3-lang.org/implementation-details/specification/)

## 4. Jai: public evidence

Jonathan Blow's 2025 keynote reports a clean build of about 300,000 lines in
2.3 seconds on his laptop. The build includes generated source. This is a
creator-reported demonstration, not a reproduced C comparison or an isolated
front-end measurement.

The talk identifies type checking as a major cost. Its compiler report counts
compile-time executions, polymorphism solves, reused instances, and new instances.
Reusing an instance still needs solver work. External metaprograms can run alongside
compilation. In-program compile-time values and generated definitions can block
progress. Keep stage reports and visible generated code. Exclude arbitrary
compile-time execution and declaration-changing plugins from the initial core.
[Blow, Jai Demo and Design Explanation, LambdaConf 2025](https://www.youtube.com/watch?v=IdpD5QIVOKQ)

The speech was inspected through a
[public transcript](https://youtubetotranscript.com/transcript?current_language_code=en&v=IdpD5QIVOKQ).
The video endpoint was rate-limited during this review. No Jai compiler was run.

Raphael Luba's public Uniform library uses explicit defer calls for resource
release. It also states that captured substrings refer to the original text.
The caller must keep that text alive or copy the captures. This is useful
evidence of direct storage control and of the lifetime contract that cleanup
syntax alone does not enforce.
[Uniform usage](https://github.com/rluba/uniform#usage)

Luba's Jaison parser uses type parameters, reflection, pointer casts, and member
offsets. One path uses a local flag and deferred conditional release when ownership
has not reached the result. Use this as a resource-transfer test: a proposed
ownership rule must preserve exactly one release without hiding extra runtime state.
The code shows library practice, not a normative language specification.
[Jaison typed parser](https://github.com/rluba/jaison/blob/master/typed.jai)

The public code also uses name-first declarations, including `name :: definition`.
This keeps declarations compact. RMD instead starts declarations with fixed
keywords so that readers and parsers see their role immediately. This is a design
choice, not evidence that Jai's parser is slow.

Do not treat a community feature list as the current Jai specification. The
reviewed evidence does not establish current parser complexity, speedup across
cores, or isolated front-end speed. Those claims need a public compiler version,
a fixed corpus, stage timings, and the same C baseline.

Keep Jai's focus on fast complete builds, visible data representation, and
compiler reports. Do not assume that its broad metaprogramming design satisfies
our stronger restriction on bounded front-end work.

## 5. Academic ideas

The useful distinction is between an ownership rule and a storage mechanism.
Affine values cannot be duplicated, but affinity alone does not specify when a
resource is released. Deterministic cleanup is a separate contract.

| Work | Published mechanism or result | Application to this design |
|---|---|---|
| Tov and Pucella, Practical Affine Types | Alms combines affine values with a formal type model and garbage collection. | Separate copying from transfer. Omit its broader qualifier polymorphism and subtyping. |
| Osvald and Rompf, Rust-Like Borrowing with 2nd-Class Values | Borrow scopes restrict values that cannot escape through returns, mutable storage, or first-class functions. The model does not implement ownership transfer. | Test lexical borrowed parameters. Do not claim that this paper proves our combined design sound. |
| Weiss and others, Oxide | A type-safety proof covers a Rust-like ownership model, reference provenance, and nonlexical lifetimes. | Use its safety obligations for review. Do not import its full reference analysis. |
| Tofte and Talpin, Region-Based Memory Management | Type-and-effect analysis infers stack-organized region allocation and release. | Use explicit arenas first. Region inference adds compiler work; regions can retain dead data until release. |
| Cyclone region system | Explicit interfaces support local analysis with region types, subtyping, and effects. Lifetime checks do not require reference counts or runtime region tags. | Keep separate interfaces. Bounds checks and allocator costs remain separate. |
| Cogent | Linear types support certified compilation to C without a required collector. The target programs have limited sharing. | Unique ownership can permit in-place update. Restricted sharing is a real cost. |

Primary papers:
[Practical Affine Types](https://users.cs.northwestern.edu/~jesse/pubs/alms/tovpucella-alms.pdf),
[Second-class borrowing](https://www.cs.purdue.edu/homes/rompf/papers/osvald-scala17.pdf),
[Oxide](https://arxiv.org/abs/1903.00982),
[Region-Based Memory Management](https://www.sciencedirect.com/science/article/pii/S0890540196926139),
[Cyclone regions](https://www.cs.cornell.edu/Projects/cyclone/papers/cyclone-regions.pdf),
[Cogent](https://arxiv.org/abs/1601.05520).

Hylo offers another direction: mutable value semantics, explicit copies, and
temporary projections. Its yield-based subscripts can suspend while a caller uses
a projection, then resume. This supports custom collection access, but adds control
flow and cleanup rules. Compare it with ordinary lexical views before adding it.
[Hylo introduction](https://hylo-lang.org/introduction/),
[Hylo yield statements](https://hylo-lang.org/docs/reference/specification/#yield-statements)

The Swift Ownership Manifesto distinguishes static and dynamic exclusivity.
Its discussion of global storage, reference properties, and closure captures
shows why local nonescape rules do not remove all hidden aliases. The small
core must restrict those aliases if it has no runtime exclusivity checks.
[Swift Ownership Manifesto](https://github.com/swiftlang/swift/blob/main/docs/OwnershipManifesto.md)

None of these results measures the combined proposal against the C compilation
target. A stack of borrow scopes and local owner states is a plausible checker
design. It still needs validation at joins, calls, returns, cleanup, and foreign
boundaries.

Intrusive structures require more than this local model.
GhostCell separates access permission from shared addresses. Its permission
operations have no runtime state, and its safe doubly-linked example has embedded
links. That example uses arena allocation and cannot reclaim individual nodes.
The permission brand and the storage lifetime are separate.
[GhostCell, sections 3.1 and 3.2](https://plv.mpi-sws.org/rustbelt/ghostcell/paper.pdf)

Walker and Morrisett's Alias Types support recursive structures and explicit
reclamation through named locations and store descriptions. Access permission
is separate from a pointer value. This is a real static alternative, not evidence
that reclamation always requires runtime metadata. Its recursive and existential
types still need a usability and compilation experiment for this project.
[Alias Types for Recursive Data Structures](https://www.cs.princeton.edu/~dpw/papers/alias-recursion-tr.pdf)

The `generational-arena` implementation demonstrates another route: a safe Rust
pool with generation-bearing indices. It forbids unsafe code in its implementation.
This supports the feasibility of a safe pool, not raw-pointer performance or all
the identity rules proposed here.
[Generational arena source](https://docs.rs/generational-arena/latest/src/generational_arena/lib.rs.html)

Static fractional ownership is another useful lead. The public
`ghost-collections` experiments combine GhostCell and StaticRc, but describe
extra pointer/write costs and experimental cursor mechanisms. Do not call this
a completed zero-overhead answer.
[Ghost collections](https://github.com/matthieu-m/ghost-collections)

## 6. Candidate semantics

### 6.1 Values, layout, and functions

Use fixed-width integers, a target-sized unsigned index, booleans, floating-point
values, fixed arrays, records, and tagged unions. Strings start as explicit byte
slices. Text decoding belongs in a library.

Ordinary functions have complete parameter and result types. Recursion is allowed.
No caller needs a callee body to find its type. Local inference follows the
initializer and declared operation types; it does not search for implementations.

A plain record is copyable only if every field is copyable and it has no resource
cleanup. A `resource struct` is move-only even if its representation is one integer.
A record with a resource field is also move-only. Cloning is an ordinary explicit
function and can return an allocation error.

Ownership-bearing raw fields are private to the resource module. Safe clients
cannot create a second file owner with `make File { fd: other.fd }`.
Claiming ownership from a raw handle requires an unsafe operation. A safe public
constructor must establish a unique valid resource and its release contract.

Define normal record field order and padding rules. Mark C records explicitly.
Do not add hidden vtables, reference counts, or ownership headers. Raw C pointers
are permitted, but dereference and construction of safe views require an unsafe
contract. Use a tagged optional type when absence is valid.

Use compiler-known `Option[T]` and `Result[T, E]` in the first experiment.
They describe tagged data, not arbitrary generic function bodies. Do not assume
tag removal or a special ABI until it is specified and tested.

### 6.2 Ownership and cleanup

Each resource has one cleanup obligation. Successful initialization creates it.
A move transfers it and makes the source unusable. Moves do not call user code.
Assignment evaluates the new value before it releases an old live value.

A safe `replace(place, value)` operation installs the new complete value and
returns the old owned value. It leaves the place initialized on every normal path.
Use it to extract an occupied pool slot without a partial move from an array.
This is a fixed ownership operation, not a generic function search.

A nominal resource can define one drop action. Drop cannot return a recoverable
error or unwind. A drop action cannot publish the object again. Resource fields
have a specified destruction order. For the first experiment, use reverse field
declaration order after the enclosing drop action.

A consuming API receives the cleanup obligation. It must either release the
resource, transfer it, or keep it owned on every normal return path. A foreign
release primitive discharges this obligation inside an audited unsafe wrapper.
It must not cause the same handle to be released again by automatic cleanup.
Define an unsafe consuming operation that ends the wrapper's obligation after
foreign release. Passing a copied raw handle to C alone does not end it.

Evaluate operands, call arguments, and initializer fields from left to right.
Each completed owning operand is a live temporary until the enclosing operation
succeeds. In `use(move a, acquire_b()?)`, failure of the second argument destroys
the temporary that received `a`. The callee has not received it.
Apply the same rule to record construction and defer registration. Do not run
the enclosing record's drop action before construction succeeds.

Use these control-flow rules for the small checker:

- A moved value cannot be read, borrowed, or dropped.
- No partial moves out of any record or array that contains resources.
- At every continuing control-flow join, each outer resource has the same ownership state
  on every incoming path.
- At a loop back edge, outer resources have their entry ownership state.
- At a loop exit, the condition-false path and every break path agree.
- A branch that returns does not join the continuing branch.
- Explicit initialization can restore a moved variable before a join.

Thus `if flag { consume(move file); }` is rejected if the other branch keeps
`file`. Use an explicit optional resource when the program needs that state.
The optional tag has a runtime representation. Do not hide it in a compiler flag.

Value matching consumes a whole tagged value and transfers its active payload
into the selected arm. That arm owns the payload. The original variable is moved
on every arm. Reinitialize it to `None` before an enclosing join if it remains
in use. This also defines how result propagation extracts a payload. It requires
no generic `take` function or partial record move.

Cleanup runs on fallthrough, return, break, continue, and explicit error
propagation. It follows one reverse registration order for locals and defers.
Evaluate a return value before cleanup, and transfer returned owners before
destroying the remaining locals.

Abort, process termination, and hardware failure do not promise cleanup.
Foreign unwinding or a nonlocal jump across a live resource scope is prohibited.

Fallible completion is an explicit operation. Examples include commit, flush,
and checked close. If release fails and the resource remains live, the error
result must retain ownership. If release consumes the resource despite an error,
the result must state that different contract. An implicit drop must not silently
discard a reportable failure. A resource whose drop can encounter such a failure
needs a defined fatal path; recoverable callers must use its checked operation.

### 6.3 A small defer

Start with `defer f(args);`, rather than an arbitrary captured block.

Evaluate the callee and arguments at registration. Store copied values in a local
cleanup slot. A moved argument transfers ownership into that slot. A borrowed
argument keeps its loan until the deferred call finishes. The target returns
`unit`; a fallible operation needs an explicit policy in an ordinary wrapper.
Registration completes only after all arguments succeed. Until then, completed
arguments are owned temporaries with the cleanup rule above. Invocation transfers
owned arguments to the callee; the cleanup slot must not destroy them again.

This prevents the meaning of `defer release(p);` from changing after reassignment
of `p`. It also makes the restrictions visible:

- Moving a resource into a defer makes it unavailable immediately.
- Deferring an exclusive borrow keeps that exclusive reservation until scope exit.
- A deferred borrow cannot outlive its owner.
- Automatic resource cleanup remains the normal way to keep a resource usable
  and release it at scope exit.

Do not permit an ordinary safe function to release an owner through a shared
borrow. `defer close(file)` must not become a second cleanup path for an
automatically managed owner.

Defer adds stored arguments and calls only where it appears. A defer inside a loop
belongs to that iteration's scope. No heap queue or function-wide accumulation is
required. Defer bodies, error-only defer, and cancellation are not part of this
first grammar.

### 6.4 Lexical borrows

Use two access modes:

| Mode | Permission | Owner restriction |
|---|---|---|
| `read T` | Read the value through shared views | No mutation, move, or destruction while views exist. |
| `mut T` | Read and write through one exclusive view | No independent access to the same owner. |

A named borrow has an explicit block. A temporary borrow lasts for the full call.
A reborrow reserves its parent until the inner block or call ends. The checker
tracks the whole root owner; it does not try to prove disjoint fields or indexes.
Check overlap across all call arguments. If one argument is exclusive, no other
argument can access the same root. Safe calls cannot bypass this rule through a
different parameter name.

A borrowed value is second-class: it can be a parameter or a local view, but
cannot enter a record, global, heap object, or escaping callback. This applies
through aggregate and pointer conversions too. Raw operations cannot turn a
borrow into a safe long-lived value.
An integer pool key is different: it is a copyable identity, not permission to
dereference memory. It can be stored in a record. Access requires a live pool
and validation, as described in section 6.9.

For the strict experiment, functions cannot return borrowed values. Built-in
array indexing and slicing are checked projections of a known owner. Custom
containers must return an owned value, return an index, or use a scoped callback.

This loses real expressiveness. Two disjoint mutable fields still conflict.
A view can keep an owner reserved longer than its last use. An ordinary
`buffer.data()` interface cannot return a slice. Measure these costs with the
production witness before accepting the rule.

The competing extension is:

~~~text
fn data(buf: read Buffer) -> read []u8 from buf;
~~~

The result names exactly one input origin. It remains second-class and cannot
outlive the caller's lexical loan of that input. A returned reborrow keeps its
parent reserved. A function that can return views from unrelated parameters
needs a different API; there is no inferred set of origins.

The origin must describe storage, not equal contents. Accept projections,
reborrows, and forwarding calls with that same declared origin. Reject local
copies, other parameters, and temporary owners that die at the call.
Retaining the result requires an active named lexical loan; a call-only loan
cannot extend itself implicitly. Keep the result's loan valid through callee
cleanup and reserve its parent until the caller's view scope ends.

For a raw buffer, reading a pointer field does not prove that storage belongs
to the buffer. An unsafe view constructor must assert its owner anchor, valid
extent, alignment, and initialized contents.

Fallible views need one more explicit rule in this competing experiment:

~~~text
fn blob(row: mut Row, column: usize)
    -> Result[Option[read []u8], SqlError] from row;
~~~

Permit borrowed payloads only in transient built-in optional/result wrappers.
The complete value is second-class and inherits the one origin. Reserve that
origin for the full lexical result scope, including empty and error variants.
This conservative rule avoids variant-dependent loan states. It does not permit
borrowed fields in ordinary records or persistent storage.

This is an experiment, not an accepted lifetime feature. Verify its return-source
rules and nested calls, then compare compile time and client code against the
strict version. Stored lifetime parameters and self-referential safe records do
not follow automatically.

### 6.5 Safety boundary and allocation

The checked subset must prevent use after move, duplicate resource release,
dangling local views, and conflicting access. It must also prevent uninitialized
reads, out-of-bounds access, and use of an unchecked union variant.

Unsafe code establishes contracts for raw storage, C handles, aliasing, and
callbacks. A safe wrapper must preserve these contracts for every safe caller.
Private raw fields do not prove ownership. A wrapper can still hide a borrowed
parent or allocator with a shorter lifetime.

Require explicit allocation functions. An allocator can be a library value;
it is not an implicit function parameter. The allocator's state must outlive
the allocation. The first buffer uses a process-lifetime allocator. Other valid
designs transfer allocator ownership or keep allocations inside an arena scope.
Do not return an independent owner containing a pointer to a short-lived allocator.

Arenas are optional library facilities. Arena reset invalidates every view.
Use a whole-arena exclusive operation to prevent reset during a loan. A raw
arena release does not run arbitrary element destructors. Support only trivial
elements, or explicitly pay for a destructor list and its traversal.

Shared reads are transitively read-only. The first core has no safe mutation
through a shared view. An unsafe wrapper cannot override this rule while a read
loan exists. Interior-mutable storage would need a compiler-visible type rule
before safe atomics or cells can use it.
Mutable global access, asynchronous foreign callbacks, and
raw thread launch are unsafe in this first experiment. A safe thread API needs
an ownership-transfer rule and a guarantee that borrowed workers finish before
scope exit. Compiler parallelism does not depend on a user-language thread API.

Bounds and narrowing checks stay active in optimized checked code. Signed and
unsigned arithmetic traps on overflow; provide explicit wrapping operations for
modular arithmetic. Division and shifts have defined invalid-input behavior.
Eliminate checks only when proven redundant. An explicit unsafe unchecked
operation has a precondition; optimization mode alone does not remove safety.

Validate bytes, files, network input, and foreign results at their public
boundaries. Do not add recoverable validation paths for impossible states
created by verified compiler stages. Resource exhaustion and malformed external
input remain real errors. Memory safety is not a proof of authentication,
protocol validity, or constant-time behavior.

### 6.6 Errors and initialization

Use a declared `Result[T, E]` and an explicit propagation operator. Propagation
is a branch plus the normal cleanup sequence. Discarding an error result is a
compile error unless the source explicitly handles it. No exception unwinding
or hidden error allocation is required.

All safe reads require initialization. Do not zero all storage implicitly.
A complete initializer can be explicit zero data when that is useful.

Use structured `if`, loops, and exhaustive `match` on tagged values.
There is no implicit fallthrough or jump into a scope. Labelled breaks can leave
an enclosing loop and run that scope's cleanup. General `goto` is excluded.

Fallible construction of resource arrays needs an initialized-element count and
cleanup of that prefix. Keep this cost in the builder that uses it. The initial
language slice only needs complete fixed-array initialization and concrete
buffer builders; a generic collection framework is not a prerequisite.

### 6.7 Generics and other omitted machinery

The first measured slice has no user-defined generics. Use concrete records,
byte buffers, and typed function pointers with explicit concrete context
parameters. A `void*` context needs an audited cast; it is not automatically safe.

This choice can cause repeated code. Do not hide that cost by declaring every
container compiler magic. If repetition prevents the production slice from
being useful, compare these explicit alternatives:

| Alternative | Compiler cost | Runtime or API cost |
|---|---|---|
| Concrete implementations | Compile the written code once | Repeated source and maintenance |
| Erased algorithms with explicit operation tables | No body specialization | Indirect calls and size/alignment/drop information |
| Checked-once generics with explicit instantiation | Check a template and lower each instance | Code growth; no required erased calls |
| Unrestricted specialization or compile-time execution | Work can grow with evaluation and instances | Too broad for the initial gate |

Even checked-once generics can require separate layout and lowering work per
instance. They do not provide free compilation. Test a bounded container use
before adopting one model.

Also omit inheritance, user-defined operators, implicit conversions, variadic
type machinery, dynamic reflection, implicit async state machines, and general
closures. Function pointers remain available. Reflection, code generation,
reference counting, and asynchronous runtimes need separate evidence before
they become core features.

### 6.8 Required counterexamples

The experiment must reject these programs or enforce the stated boundary.
Accepted examples alone do not test the ownership contract.

| Program shape | Required result |
|---|---|
| Borrow a buffer element, grow the buffer, then use the element | Reject growth while the root is borrowed. |
| Move a record while a field view exists | Reject the move, including through a different alias. |
| Call with both `mut owner` and `read owner` | Reject the overlapping arguments. |
| Consume a resource, then break from a possibly empty loop | Reject unequal resource states at the loop exit. |
| Move an argument, then fail while evaluating the next argument | Release the completed temporary exactly once. |
| Construct two resource wrappers from one raw handle | Require an unsafe ownership assertion; safe construction rejects it. |
| Put a borrowed view inside a returned ordinary record | Reject the escape through the record. |
| Return a view of a local copy under `from input` | Reject the false storage origin. |
| Retain a returned view from a call-only temporary owner | Reject the missing lexical owner. |
| Re-enter a mutable global from a callback | Require an unsafe boundary; no hidden shared alias is permitted. |
| Return storage tied to a local allocator | Reject the independent owner contract or keep it scoped. |
| Register a borrowed context for a later foreign callback | Require owned registration state and completion of all uses before release. |
| Reset an arena that contains live resource values | Run explicit destructors or reject those element types. |

### 6.9 Intrusive lists with individual destruction and reuse

The node contains its own `prev` and `next` fields. There is no separately
allocated list cell around each payload. The same object can contain a second
hook for another list. This follows the useful storage property of intrusive
containers.
[Boost intrusive and non-intrusive containers](https://www.boost.org/doc/libs/latest/doc/html/intrusive/intrusive_vs_nontrusive.html)

There are two different safety questions:

1. Who may read or mutate a node now?
2. Does a saved link still identify the same live node?

A unique token can answer the first question without answering the second.
After `saved = victim`, unlinking and destroying `victim` does not remove
`saved` or a copied link inside another live node. Reusing the address makes
the stale identity problem harder. Ending temporary borrows does not fix it.

| Candidate | Individual destruction and reuse | Representation and cost | Decision |
|---|---|---|---|
| Arena plus erased access token | No individual storage reuse in the simple model | Ordinary links; memory retained for all nodes | Does not satisfy the requirement |
| Static node permissions and recursive store types | Yes, when permissions prove access and release | Pointer-sized links are possible; stronger type checking and annotations | Not selected for the small core |
| Checked pool keys | Yes, with a new identity on reuse | Embedded keys, slot metadata, and lookup checks | Selected opt-in design |
| Permanent slot without generations | Destroys payload, but old keys can identify a new occupant | Smaller identity and an empty-slot test | Does not preserve node identity |
| Compiler-defined splice and auto-unlink primitives | Possible only under their restricted contracts | User cannot freely implement the pointer algorithm | Does not prove the requested language expressiveness |

Automatic unlinking also does not invalidate arbitrary saved cursors.
Boost's auto-unlink hook illustrates useful cleanup behavior and restrictions,
including its interaction with constant-time size tracking. It is not a general
proof that every pointer to a removed object is gone.
[Boost auto-unlink hooks](https://www.boost.org/doc/libs/latest/doc/html/intrusive/auto_unlink_hooks.html)

#### Concrete checked-key experiment

Use a concrete `TaskPool` library and a copyable `TaskKey`.
The list links are keys inside each task. This is an intrusive list implemented
with handles. It is not the same representation as a pair of C pointers.
No user-defined generics or special compiler list operations are needed.

~~~text
struct Task {
    ready_prev: TaskKey;
    ready_next: TaskKey;
    ready_list: u64;
    timer_prev: TaskKey;
    timer_next: TaskKey;
    timer_list: u64;
    payload: TaskData;
}

resource struct ReadyList {
    pool_id: u64;
    list_id: u64;
    head: TaskKey;
    tail: TaskKey;
}
~~~

An empty key denotes a list end. A stale key denotes an error. Never silently
treat a stale key as an empty link.

One concrete layout uses a 64-bit pool identity, a 32-bit slot index, and a
32-bit generation. Each key then needs 16 bytes on the selected ordinary ABI.
Reserve pool identity zero for the empty key. Two links need 32 bytes, compared
with 16 bytes for two pointers on a 64-bit target. Slots also need a generation,
an occupied/free/retired state, and allocator bookkeeping.
The selected nullable-link witness also has an explicit 64-bit list identity
per hook. Each hook therefore uses 40 bytes before any enclosing padding.
Two hooks use 80 bytes before payload and slot metadata. This membership cost
is part of the chosen container, not hidden language metadata.

Pool identities must not be reused while an old key can exist. A process-wide
monotonic allocator can provide them; exhaustion is an explicit failure.
Do not use an allocator address as identity. Generation counters never wrap:
retire an exhausted slot. The capacity and generation limits are part of this
particular layout, not undocumented safety assumptions.
Use one optional identity service with a safe issuance API. It must serialize
concurrent issuance and cannot reset its counter. Its cost occurs at pool creation;
programs without these pools need no service. Pool code uses this primitive as it
uses an allocation primitive. It does not contain privileged list operations.
Keys are identities within the creating process, not serialized cross-process IDs.

The pool is move-only, even when every payload is copyable. Its identity and slot
metadata are private. A move preserves its identity; a newly created pool receives
a fresh identity. Copying backing storage must not create another pool with the
same identity.

The pool owns initialized tagged slots and can reuse a vacant slot immediately.
A key lookup checks pool identity, index bounds, occupancy, and generation before
it exposes the payload. An old key fails after removal and after exact-slot
reuse. It also fails against a different pool with the same slot index.
Pool destruction releases the remaining payloads and storage. Old integer keys
can still exist, but lookup requires a live pool with the same unique identity.
Reusing the old pool's address does not make those keys valid.
Retain vacant and retired slot metadata while that pool identity remains live.
Shrinking and regrowing must not reset the generation at an old index.
The first pool therefore retains its slot capacity until destruction.

Keys identify a slot incarnation, not immutable payload contents. Assigning or
replacing contents through a valid mutable view changes the same live node.
Only pool removal ends that incarnation. Insertion into the vacant slot creates
the next one. Code that needs a new identity must use remove and insert.

A node view borrows the pool. A live view prevents destruction, reuse, pool growth,
or pool destruction that could invalidate it. End one mutable view before opening
another. Copying keys is safe because a key alone does not permit memory access.
Hold the pool borrow across both validation and payload access. A generation check
alone does not prevent concurrent reclamation. Foreign code must preserve this
same exclusivity contract.

Removal replaces the occupied slot with a vacant or retired state and takes
ownership of the old payload. It runs that payload's cleanup exactly once.
Advance the generation before the slot becomes reusable. At the counter limit,
retire the slot instead. Publish a free slot only after cleanup completes.
A safe reentrant destructor cannot acquire the already borrowed pool.
This is a static loan rule, not a runtime lock. Abort has the same cleanup rule
as other resources.

Use `replace`, checked arrays, tagged values, and ordinary functions to implement
a concrete pool. The list author can implement the pool and list with safe code.
A dynamic allocator remains an ordinary trusted storage primitive.
If stable payload addresses are required, use nonmoving slot blocks. Growing a
single relocatable array does not provide that property.

This meets individual object destruction and reuse. A pool can retain backing
capacity for reuse. It does not imply that every node's bytes return immediately
to the system allocator. Index keys need no access to freed payload memory for
validation. A direct pointer-plus-generation variant must instead keep its
validation metadata alive, or it will dereference freed storage to check safety.

The list algorithm remains ordinary sequential code:

~~~text
copy the victim's predecessor and successor keys;
check that all named nodes are live and the hook belongs to this list;
check the applicable head, tail, and reciprocal-link conditions;
set predecessor.next, or replace list.head;
set successor.prev, or replace list.tail;
clear the victim's membership in this hook;
~~~

This operation unlinks one hook and preserves the payload and all other hooks.
A separate destroy operation first validates every affected membership and
neighbor. It then removes all hooks, destroys the payload, and releases the slot.
It must not change the ready list before discovering an invalid timer membership.

~~~text
destroy_task(pool, ready, timer, task);
~~~

The first block gives algorithm steps, not proposed language keywords.
The second block calls an ordinary library helper with this complete validation
contract. Each access uses a safe pool operation. A scalar-field helper can return
copied keys. A scoped view can support payload access.
The single-source return experiment must also test
`lookup(pool, key) -> Result[mut Task, LookupError] from pool`.

Complete all recoverable validation before changing the links. Hold exclusive
pool access throughout the operation, and do not call user callbacks during the
edit. Internal link failures are invariant failures, not a request to skip nodes.
Do not add rollback allocations or hidden retries.

Membership is a container invariant, not a consequence of memory safety.
The witness uses a unique nonzero list identity per hook; zero means detached.
List identities do not repeat within a live pool. Check the header's pool identity
and the hook's list identity before unlinking. This detects wrong-list removal
even for an interior node with valid reciprocal links. A boolean cannot do that.
List-identity exhaustion also fails explicitly. Keep hook representation private
to the list module. Pool admission initializes detached hooks; it must not inherit
another task's copied membership.
List headers are move-only. Dropping a header does not destroy pool-owned tasks;
clear its memberships explicitly. Pool teardown still destroys every live task.

A circular-hook design is an alternative. A detached self-link can avoid a
separate linked flag, but it does not alone prove membership in a named list.
Changing that representation needs a separate layout and API comparison.

Traversal copies the next key before it destroys the current node. It ends the
current payload loan, removes the current node, then resolves the saved next key.
It must not return several mutable payload views at once. Cyclic or corrupt
topology can still cause wrong results or nontermination; a safe language does not
prove every list invariant.

#### Static-pointer alternative

If raw-pointer representation and no validity checks are required, the checked
pool does not pass that requirement. A different contract could use Alias Types:
a pointer names a location, while an affine permission authorizes access.
Deallocation consumes that permission. Recursive container descriptions explain
how the program regains access to the remaining nodes.

Require explicit local operations for opening a node's permissions, changing
links, closing the container invariant, and consuming the removed node.
Signatures must summarize these effects, so callers do not inspect callee bodies.
Do not add global lifetime inference, arbitrary theorem proving, or an assertion
that users merely promise to keep all links valid.

Its decisive test would be a readable user-written erase function that returns or
destroys one node while preserving the remaining list. Include external cursors
and two hooks in one payload. Count annotations, generated code, and front-end
work. A proof-oriented API that is harder to use than a small C implementation
fails the pragmatic requirement even if it is sound.

The exact additional contract is recovery of permissions for the surviving graph
after removing one allocation. An arena token and lexical loan stack cannot supply
that information. A small static rule has not been established by this research.
The selected checked-key design does not depend on solving this problem.
Do not add this type machinery while the accepted checked-link contract suffices.

## 7. Syntax that is simple to parse and read

Prefer keywords and visible boundaries over minimum character count.
The parser must not consult declarations to decide whether an expression is a
type. It must not backtrack over arbitrary token sequences.

Proposed surface rules:

- `fn`, `struct`, `enum`, `resource struct`, `let`, and `var` introduce declarations.
- Write names before types: `count: u32`.
- Use braces for blocks and semicolons for simple statements.
- Require `-> Type` on every function, including `-> unit`.
- Use fixed operator precedence and explicit casts with `as`.
- Use type arguments only in type positions in the first grammar.
- Use `make Type { field: value }` for record construction. This separates a
  constructor from an `if condition { ... }` block without type lookup.
- Do not add textual macros, user-defined syntax, or newline-dependent insertion.
- Use a small fixed token set. ASCII identifiers are sufficient for the first
  slice; UTF-8 remains available in comments and string data.

Illustrative syntax follows. These are design examples, not executable tests.

~~~text
module checksum;

fn sum(bytes: read []u8) -> u32 {
    var total: u32 = 0;
    for byte in bytes {
        total = total +% (byte as u32);
    }
    return total;
}

fn example() -> u32 {
    let bytes: [u8; 4] = [1, 2, 3, 4];
    borrow read bytes as view {
        return sum(view);
    }
}
~~~

Here `+%` means wrapping addition. The borrow ends as control leaves the block.
The return value is computed before scope cleanup.

A grammar fragment makes the parser constraints reviewable:

~~~text
function    := ["pub"] "fn" Name "(" Parameters ")" "->" Type Block
binding     := ("let" | "var") Name [":" Type] "=" Expression ";"
borrow      := "borrow" ("read" | "mut") Place "as" Name Block
defer       := "defer" Call ";"
block       := "{" Statement* "}"
~~~

Use recursive descent for declarations and statements, and precedence parsing
for expressions. A lexer can process each file independently. Keep comments,
strings, and delimiter matching in that file's parse task; splitting a token
stream at arbitrary byte offsets is not automatically safe.

Do not claim a formal LL(1) grammar from this fragment. The complete grammar
must pass ambiguity tests. Include function-pointer types, nested type arguments,
record literals in conditions, shifts, labels, and malformed input.
Measure tokens per second as well as total compile time.

The visual test is practical: write a parser, resource wrapper, and nested
cleanup path in the syntax. Prefer a few explicit words if punctuation makes
ownership or control flow hard to read.

## 8. Compiler stages that permit parallel work

The language must expose dependencies before expensive body work begins.
This is more useful than adding a thread pool to a type system with hidden
dependencies.

~~~mermaid
flowchart LR
    A["Read, lex, and parse each file"] --> B["Collect declarations per module"]
    B --> C["Resolve exported types, constants, and layouts"]
    C --> D["Publish immutable interfaces"]
    D --> E["Check independent function bodies"]
    E --> F["Lower ownership and cleanup per function"]
    F --> G["Construct complete backend input"]
    G --> H["Backend optimization and machine code"]
~~~

The graph shows dependencies, not global barriers. A ready module can advance
while another file is still being parsed. A function can start after its own
declarations and required imported interfaces are ready.
The build manifest fixes the source files in each module. Publish a module's
interface only after discovering declarations in all of those files. A later file
must not change an interface that workers already use.

| Stage | Independent work | Required coordination |
|---|---|---|
| Lex and parse | Files | Fixed source list and build configuration |
| Declare | Modules or deterministic file-table fragments | Duplicate-name checks and module imports |
| Resolve types and layouts | Independent type dependencies | Public constants and by-value record dependencies |
| Check bodies | Functions, including recursive functions with declared signatures | Read-only interfaces |
| Lower cleanup | Checked functions | No caller-body inspection |
| Build backend input | Independent modules or safe backend work units | Symbol and output assembly |

Use acyclic module imports for the first design. An invalid by-value type cycle
is an error. Pointer recursion does not require an infinite object layout.
Constants form a finite dependency graph and use literals, fixed arithmetic,
and type-layout queries. No loops, recursion, I/O, or arbitrary function calls
run during interface construction.

Public interfaces include type identity, visible fields and layout, function
signatures, ownership modes, drop properties, and required constants. A private
body edit must not change an interface. A private layout change can still affect
an exported by-value type; record that dependency instead of hiding it.

Use fixed target configuration for conditional declarations. Do not let function
execution discover imports or inject declarations while other workers check
bodies. External source generation is an explicit build step with declared
inputs; include its cost when reporting the complete build.

Keep parsed data and published interfaces immutable. Give workers local
allocation regions and mutable function state. Avoid a global lock for every
identifier or type lookup. Merge diagnostics in stable source order.

Rust's parallel query documentation explains why immutable results can be shared
and why dependent queries must wait. It also requires cycle handling.
Our smaller dependency graph is a proposal to reduce this coordination cost.
[Rust parallel compiler mechanisms](https://rustc-dev-guide.rust-lang.org/parallel-rustc.html)

Classify parsing, lookup, type checking, and lowering as compiler hot paths.
Cache files and source input are validation boundaries. Checked internal types
and plans are trusted data. Use values or `void` for infallible internal steps.
Do not add error-return branches for impossible producer states.

Parallel workers can increase memory traffic and total CPU time. A long function
or deep import chain limits available parallel work. Report these limits in
measurements. Do not promise linear speedup. Avoid concurrent mutation of one
LLVM context; use backend-supported independent work units at handoff.

## 9. Cost ledger

| Feature | Runtime cost when used | Pre-backend cost | Cost absent when unused |
|---|---|---|---|
| Plain value and function | Selected representation and calls | Parse, lookup, and local type checks | No ownership runtime |
| Resource cleanup | Release calls and possible cleanup branches | Ownership state and exit lowering | No cleanup state for scalar-only bodies |
| Lexical borrow | Pointer or slice representation | Root access and scope checks | No borrow analysis for bodies without loans |
| Slice | Pointer, length, and necessary bounds tests | Projection and element checks | No slice metadata on plain pointers |
| Optional or result | Tag/payload, branches, and ABI effects | Variant and propagation checks | No exception tables |
| Defer call | Captured values and call | Cleanup entry and exit lowering | No queue or general closure support |
| Scoped callback | Possible indirect call and context pointer | Function-type and non-escape checks | No callback machinery on direct calls |
| Arena | Arena state, allocation, and optional destructor traversal | Ordinary calls plus borrow constraints | No global arena or collector |
| Explicit erased interface | Function table and indirect calls | Ordinary concrete types | No mandatory vtable on records |
| Parallel compilation | No application cost | Scheduling, synchronization, and worker memory | One-worker execution remains available |
| Checked intrusive keys | Larger links, slot state, and validity tests | Ordinary concrete types and local loans | No metadata on ordinary owners or references |

“Absent” refers to feature-specific work, not the removal of basic parsing and
type checks. Compare cleanup control flow and layout before making a cost claim.
A backend can remove some branches or indirect calls, but the design must work
when it does not.

## 10. Production witness and acceptance gates

### 10.1 Establish one complete boundary

Use a small command-line SQLite reader. Open a database, prepare a query, iterate
rows, inspect a byte column, produce deterministic output, finalize the statement,
and close the database. Retain recoverable errors.

This is a proposed production-shaped witness against a real C library.
It is not evidence that a compiler or a wrapper has been implemented.

The hard boundary is:

~~~text
Connection -> scoped Statement -> scoped column view -> output operation
~~~

The caller must not close the connection while the statement is in use.
It must not step, reset, finalize, or convert a column while a view is in use.
SQLite documents that conversions can invalidate a returned pointer. A valid
row and column index are also required. Empty BLOBs can return a null pointer;
SQL NULL and allocation failure need distinct handling.
[SQLite column access](https://www.sqlite.org/c3ref/column_blob.html)

The strict borrow version uses concrete typed callbacks and concrete context
types. A scope helper owns the statement internally and lends access to the
callback. A nested helper lends the bytes. Neither callback can retain a loan.
The complete application must use the real library and produce the final output.

~~~text
fn with_statement(
    db: mut Database,
    sql: read []u8,
    context: mut QueryContext,
    body: fn(mut Statement, mut QueryContext) -> QueryResult
) -> StatementRun;

fn with_next_row(
    statement: mut Statement,
    context: mut QueryContext,
    body: fn(mut Row, mut QueryContext) -> QueryResult
) -> RowRun;

fn with_blob(
    row: mut Row,
    column: usize,
    output: mut OutputContext,
    body: fn(read []u8, mut OutputContext) -> QueryResult
) -> BlobRun;
~~~

These are application-specific signatures for the first witness. They do not
pretend to be a reusable generic SQLite library. `Statement` and `Row` are
private move-only types. Clients receive only borrows and cannot construct or
copy their raw representation.

The wrapper invokes these callbacks synchronously. This tests scoped API design.
A callback invoked by C also needs a foreign trampoline and an ABI test.
Neither case proves safety for a callback retained after the call.

Use a concrete result record with separate body and finalization outcomes.
A close result is either `Closed` or `StillOpen { database, error }`.
These represent the actual cleanup states without a general effect system.

A single-source returned view is the competing design for the inner byte access.
It can remove one callback layer. It does not solve a stored child resource's
dependency on its parent. A returned independent statement owner needs a separate
valid parent-lifetime contract.

Use exclusive statement access for any operation that can invalidate column
data, even if its name looks like a getter. Shared access must mean no invalidation.
Treat callback re-entry and access through another alias as violations of the
same ownership contract.

Do not simplify the foreign API to make the test pass:

- Test open failure with a handle that still needs cleanup.
- Test valid empty SQL and failed preparation without a statement.
- Check row state and the column index before calling the raw API.
- Distinguish an empty BLOB, SQL NULL, and allocation failure.
- Preserve both the body error and a cleanup error if both occur.
- Test cleanup after each failed acquisition and after early return.

An open error can still return a handle that needs release.
[SQLite open](https://www.sqlite.org/c3ref/open.html)
When column access requires an error-code check, perform it immediately.
Another SQLite operation can change that error state.

SQLite preparation can succeed without producing a statement for empty input.
Finalization destroys the statement and can return an evaluation error.
Close can return busy while leaving the connection alive. A consuming close
must not discard that live handle on failure.
[SQLite preparation](https://www.sqlite.org/c3ref/prepare.html),
[SQLite finalization](https://www.sqlite.org/c3ref/finalize.html),
[SQLite close](https://www.sqlite.org/c3ref/close.html)

SQLite can refuse close or defer destruction through its separate close API.
Do not claim that every live-statement close is a use-after-free. The static
design question is how to represent the parent dependency without hidden
reference counting, silent leaks, or discarded error status.

The baseline is direct C with the same query, output, checks, ownership contract,
and cleanup behavior. Also compare a C callback version to isolate callback cost.
Do not compare only with a C version that already pays for the proposed abstraction.

### 10.2 Intrusive list witness

Use one concrete task record with two embedded hooks. One hook belongs to a ready
list; the other belongs to a timer list. Use a preallocated pool for repeatable
allocation behavior. The application must write insertion, unlinking, and traversal
in the proposed safe language.

The test sequence must include all of these cases:

- Empty, singleton, first-node, last-node, and middle-node operations.
- Forward and reverse traversal, plus transfer between two lists.
- One payload present in two lists through separate hooks.
- Duplicate insertion and wrong-list removal under the selected membership contract.
- Wrong-list removal of an interior node with valid neighbors.
- Failure in the second hook's validation before a combined destruction changes either list.
- Removal from both lists, one payload destruction, and immediate reuse of the same slot.
- A saved cursor and a saved embedded link to the destroyed identity.
- Rejection of both saved identities after that slot receives a new payload.
- A key from a different pool with the same slot index and generation.
- Pool destruction and a new pool created at the old pool's address.
- Deletion of the current node during traversal.
- Deletion of a saved successor before the next access; report a stale key.
- Rejection of removal while a payload loan is active.
- Generation exhaustion: retire the slot and report exhausted capacity.
- Rebuilding the free list without resetting any vacant or retired generation.
- Rejection of pool shrink that would discard identity metadata needed for later reuse.
- Rejection of safe destructor re-entry while the pool has an exclusive loan.
- Exactly-once payload cleanup during erase, failed construction, and pool teardown.

Reach the real counter boundary by controlled allocator-state setup. Do not change
the production wrap rule to make tests faster. If a smaller test counter is used,
it must use the identical checked successor and retirement operation.

After the initial pool allocation, insertion and unlinking must allocate no wrapper
nodes. Destruction must make reusable storage available immediately, except for
an exhausted slot. Repeated insert/erase cycles with bounded live nodes must not
retain every destroyed payload. Report retained pool capacity separately.

Require no unsafe code in the user-written list or concrete fixed-capacity pool.
Require no per-node reference count or runtime borrow flag. A key is not a direct
reference; resolving it performs the declared checks. Node borrowing still uses
the local shared/exclusive rules.

The first ergonomic gate is that insertion and unlinking each fit within 40
nonblank lines, excluding shared storage helpers. Count helper lines separately.
No permission proof terms, per-node lifetime annotations, or compiler-recognized
list functions may be hidden in those helpers. This is a proposed review gate,
not a measured result. Include the complete pool, hooks, and client in the review.

Compare both equivalent checked-key C and a conventional C intrusive list.
Record link and node sizes, slot metadata, retained capacity, dependent loads,
validity branches, allocations, operation throughput, and compiler stage times.
Use a working set that fits in cache and another that exceeds it.
Matching checked-key C is the abstraction-cost gate. Raw-pointer C reports the
explicit cost of the selected safety policy.

### 10.3 Define the timing boundary

Record two measurements:

- **Check time:** process start, source and interface I/O, lexing, parsing,
  name resolution, type checking, and ownership checks.
- **Handoff time:** all check work plus cleanup lowering, all specialization,
  ABI lowering, and complete input construction for the selected backend.

Handoff time ends before backend optimization, instruction selection, register
allocation, and object emission. If LLVM IR is the handoff, building that IR is
included. Moving a pass into a file named “backend” does not exclude it.

Clang's `-fsyntax-only` stops after syntax and semantic checks. It is useful for
the check measurement, not the complete handoff measurement. LLVM-emission
timings need a documented pass boundary and separate serialization accounting.
[Clang stage selection](https://clang.llvm.org/docs/CommandGuide/clang.html)

Fix the reference before implementation. Use current release Clang and GCC for
check time, and a documented Clang frontend-only IR boundary for handoff.
Report a fast non-optimizing C compiler separately if it is available; its complete
build time is useful context, not an interchangeable frontend measurement.
Use the fastest eligible baseline for each declared test, not whichever is
easiest to beat.

In a cold run, include creation of required module interfaces when C pays for
the corresponding header declarations. Loading prebuilt interfaces is a separate
warm measurement. Process the same requested function bodies, including unused
bodies in the selected units. Lazy omission must not remove semantic checks
from one side of the comparison.

### 10.4 Test matrix and pass rule

| Test | Purpose |
|---|---|
| Small arithmetic and array modules | Prevent large-header savings from hiding a slow basic frontend |
| SQLite reader in C and the candidate | Test a real ownership boundary and final output |
| Intrusive lists with destruction and exact-slot reuse | Test safe user implementation and stale identities |
| Allocation-failure and early-return paths | Check resource release and error preservation |
| Wide and deep module graphs | Separate available parallelism from dependency depth |
| One large function with many branches and loans | Expose ownership-state and cleanup costs |
| Repeated concrete types and calls | Measure name lookup and type representation |
| Body, signature, and layout edits | Test invalidation at different dependency boundaries |
| Increasing files, declarations, and body sizes | Detect superlinear work and memory growth |
| Invalid source and illegal borrow cases | Check diagnostics, termination, and rejection |

Borrow-only rejection cases have no equivalent C rejection contract.
Give them correctness and termination budgets, not a candidate/C speed ratio.

Freeze equivalent-work sources and ordinary C sources with their real headers.
Do not use repeated empty functions or header duplication as the only workload.
Report tokens, declarations, functions, control-flow size, loaded interface
bytes, and emitted IR size. Lines per second alone are not comparable.

Record compiler revisions, build flags, target, CPU, memory, OS, worker count,
cache state, and all commands. Use optimized compiler binaries. Exclude compiler
build time. Measure fresh compiler processes with compiler caches empty, then
report cached and incremental runs separately. Distinguish filesystem cache
state from compiler cache state.

Use at least 20 paired timing samples after setup checks. Randomize run order.
Report medians, variation, total CPU time, and peak memory. For each frozen
workload and each comparable boundary, require a median candidate/C ratio at
most 1.00. Require the upper bound of its 95% confidence interval to be at most 1.00.
Otherwise, the speed requirement is not established. Collect more samples when
noise prevents a decision. Do not average away a failing workload.

Meet the single-worker gate first. Then run 2, 4, and 8 workers where hardware
permits. Report wall-time gain and CPU/memory cost. Require identical diagnostics
and equivalent program output across worker counts.

Check final generated code for wrapper call ABI, cleanup branches, hidden
allocations, reference counts, indirect calls, and retained metadata.
Compare runtime with equivalent checked C and record every remaining abstraction
cost. No feature passes on an assumption that LLVM will remove that cost.

For ordinary owners, the runtime gate permits no extra allocation, reference
count, runtime loan table, owner metadata, or required indirect call on a
direct-access path. A resource wrapper must have the C representation's size
and alignment. Reject an abstraction that adds those costs for the same operation.

Checked intrusive links are the explicit exception for identity metadata and
validity tests. They still must match equivalent checked-key C without extra
language machinery. Use the same runtime ratio and confidence rule for that
comparison. Report raw-pointer C separately; it is not the selected safety contract.

Also run repeated in-memory column processing with a checksum instead of output.
This prevents disk and terminal time from hiding callback cost. Require a median
runtime ratio at most 1.00 and the same confidence rule against equivalent checked C.
Match necessary validation and cleanup on both sides. If the strict callback API
fails, test the declared view-return alternative. Do not claim that callback cost
is free because it is small beside database I/O.

### 10.5 Decision sequence and stop conditions

1. Freeze both C witnesses, expected output, failure cases, and measurement boundary.
2. Specify and test the grammar independently of names and types.
3. Implement only the two complete witnesses: the SQLite ownership boundary and
   the intrusive lists with safe individual destruction and reuse.
4. Test forbidden programs as well as successful executions.
5. Measure one-worker check and handoff time. Stop feature expansion on failure.
6. Inspect runtime code and client readability. If scoped access makes either
   witness unsuitable, test only the single-source return extension.
7. Re-run all gates for that extension. Keep the smaller successful design.
8. Test parallel scheduling after the single-worker path passes.

Do not authorize a general compiler framework, trait system, or container
ecosystem from parser throughput or synthetic ownership tests.
The go/no-go evidence is both complete ownership boundaries, final output,
safe node reuse, measured compilation, and measured runtime cost.

## 11. Decision record

| Keep in the first experiment | Reason |
|---|---|
| Explicit signatures and semantic modules | Bound dependencies and expose independent work |
| Regular keyword-based syntax | Parse without name resolution |
| Move-only resources and lexical cleanup | Remove repeated manual release logic |
| Restricted shared and exclusive borrows | Check common lifetime and alias errors locally |
| Tagged data and explicit results | Make absence and failure visible |
| Explicit allocation and unsafe boundaries | Preserve storage control and name trust assumptions |
| Opt-in checked intrusive links | Permit safe user-written lists with individual destruction and reuse |

| Require a separate successful experiment | Concrete question |
|---|---|
| Single-source borrowed returns | Can ordinary view APIs stay simple without general lifetime solving? |
| User generics | Can useful containers avoid both specialization growth and unwanted indirect calls? |
| Safe thread and retained callback APIs | Can transfer and quiescence be proved without hidden lifetime escape? |
| Arbitrary deferred blocks | Can capture and cleanup stay clear without a general closure model? |

| Exclude from the initial core | Reason |
|---|---|
| General compile-time execution and generated declarations | Open-ended work and changing dependency graphs |
| Open overload or trait search | Resolution work not bounded by one explicit interface |
| Exceptions, mandatory GC, and automatic reference counting | Runtime policy is imposed on programs |
| Stored borrowed references and self-referential movable values | Require a larger lifetime or address-stability contract |
| Static graph and heap-shape proof machinery | Checked links satisfy the selected reclamation contract with a smaller core |
| Implicit allocation, cloning, and conversions | Hide cost and ownership changes |

The next artifact after this exploration is a frozen witness and a small
experimental specification. This study does not authorize implementation
expansion before those gates are met.
