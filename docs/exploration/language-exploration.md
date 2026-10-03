<!-- SPDX-License-Identifier: Apache-2.0 -->

# Crust: exploration of a small systems language

Date: 2026-09-30. Updated: 2026-10-03. Status: research and executable experiments.

The [Crust0 specification](../crust0-spec.md) now defines the bootstrap language.
The richer syntax and checked rules below remain research candidates, not seed
features. Module management is a library stage under that specification.

Reading guide: [recommendation](#1-recommendation),
[language research](#3-lessons-from-existing-languages),
[Jai](#4-jai-public-evidence), [academic work](#5-academic-ideas),
[intrusive lists](#69-intrusive-lists-with-individual-destruction-and-reuse),
[syntax](#7-syntax-that-is-simple-to-parse-and-read),
[parallel stages](#8-compiler-stages-that-permit-parallel-work),
[metacompilation](metacompilation.md),
[acceptance gates](#10-production-witness-and-acceptance-gates).

The [compiler profiles](compiler-profiles.md) contain measured C, C++, and Rust
check costs. They are evidence about existing compilers, not a Crust speed result.
The [systems source study](systems-capabilities.md) records concrete Linux, GCC,
LLVM, and Coho requirements. It explains the direct-link representation target.
The [metacompilation study](metacompilation.md) examines a small core with
language features implemented as libraries, full access to compiler stages,
and explicit cache and stage dependencies.
The [compiler extension experiment](compiler-extension-experiment.md) defines
complete language replacement, backend metastages, and a C frontend benchmark.
The [resource stage proposal](resource-metastage.md) maps the ownership, RAII,
and defer rules to the current compiler APIs. It adds a proposed rule for the
cleanup position of a local that is initialized again.

## 1. Recommendation

Start with the [minimal seed](../crust0-spec.md) and public compiler libraries.
For the separate checked-language experiment, evaluate tagged unions,
move-only resources, automatic scope cleanup, and local borrows. Use explicit
interfaces and function types. Keep module policy in a library. Make the default
syntax independent of name resolution. Permit independent files and function
bodies to compile in parallel.

Expose the compiler core, representations, checkers, and stages as public
libraries. Implement the standard compiler pipeline through those same
interfaces. Users can replace the driver and its stages. A custom pipeline
must state the semantic guarantees of its selected checks.
This includes the lexer, complete grammar, language rules, and backend adapter.
Select a language before parsing its input. The default Crust grammar and checks
remain one compiler configuration, implemented through the public interfaces.

Keep the bootstrap seed smaller than the standard language. Implement ownership,
borrowing, address stability, cleanup, and the meaning of `unsafe` in compiled
standard language stages. The seed has no hidden ownership solver. The
[ownership stage contract](compiler-extension-experiment.md#ownership-and-unsafe-are-language-stages)
preserves resource operations until checking and cleanup lowering are complete.
The semantics below describe the standard checked Crust configuration.

**Keep the basic path fast; make stronger checks selectable.** The root program
can choose capabilities with different compilation costs. C-level speed remains
the basic profile's target, not a veto on an explicitly selected proof stage.
Ownership proof state must still have no runtime representation.

A required production witness is an intrusive doubly-linked list implemented in
ordinary safe user code. Nodes must support individual destruction and storage
reuse while the list remains live. An arena that only releases all nodes together
does not meet this requirement.

The first experiment should have these properties:

- A regular grammar with visible declarations, blocks, and statement ends.
- No textual headers or open overload search.
- A baseline run without expansion work, followed by the bounded metacompilation experiment.
- Complete function signatures. Local expressions can determine local variable types.
- One owner for each resource. Moves transfer ownership without user code.
- Automatic cleanup on normal scope exits, including explicit error returns.
- Lexical shared or exclusive borrows for local views.
- Direct embedded links with a separate persistent-pointer lifetime contract.
- Explicit result values, allocation, C calls, and unsafe operations.
- No mandatory garbage collector, reference count, exception runtime, or scheduler.

Use direct C/C++-style intrusive links as the primary representation. Keep
membership separate from ownership. Add automatic unlinking, explicit address
stability, and clear destruction rules. Do not require a pool, arena, generation
table, or per-node list identity to use a list. Section 6.9 defines this target.

The main open contract is safe access through persistent aliases after individual
destruction. Automatic unlinking alone does not solve it. The earlier combination
of forbidden stored borrows and unsafe raw dereferences forced a pool workaround.
That combination is not a complete language design for this target. Establish a
static contract that erases to ordinary pointers. Runtime observer metadata is
excluded from this experiment.

The local borrow interface also needs a test. A ban on borrowed returns forces
callbacks, which can add calls and obscure control flow. Compare it with a narrow
extension in which a returned view names one input as its source. Neither version
by itself establishes the lifetime of stored graph links.

This document proposes rules. It does not claim a soundness proof, a completed
language, or a measured Crust speed result. The source research used three parallel
investigations: C/C++/D, Rust/Zig, and academic ownership models. The C/C++/D
investigation also covers public Jai material.

## 2. Requirements and evidence

Use this priority order:

1. Keep the basic path near C and measure optional checking costs separately.
2. Keep the core small; expose stronger rules through user-selected stages.
3. Preserve direct control of storage, layout, allocation, and calls.
4. Check common resource and memory errors locally; select stronger proofs when needed.
5. Expose independent work to the compiler. Parallelism must improve an already fast path.

The intrusive-list requirement includes writing the list algorithm itself.
Calling a compiler-provided list or a list implemented with unsafe code is not
sufficient evidence. Allocation and primitive memory access need explicit trust
contracts. The splice and unlink algorithm must remain safe user code.
Linux, GCC, LLVM, and the Coho list define the required capability level.
Their storage and mutation patterns must not be rejected just to simplify a
local-borrow experiment.

“Zero overhead” means comparison with C code that has the same behavior.
A checked array access has a possible branch. A resource must be released.
An optional value may need a tag. These costs do not disappear because a feature
has a useful name. List them and measure them.

The revised ownership requirement excludes runtime pointer-validity checks,
pointer tags, reference counts, generation tables, and hidden cleanup flags.
Null checks before release and debug-only bounds checks are permitted. Required
unlink writes and destructor calls are program behavior, not proof bookkeeping.
Compare the representation and operations with direct C/C++ before optimization.

Debug-only bounds checks do not establish release-build spatial safety. A static
ownership proof can prevent use after destruction while an unchecked array index
still corrupts memory. Claim complete memory safety only when range proofs,
enforced checks, or checked calling contracts also establish valid accesses.
The current resource stage emits array-bounds and indirect-call null guards;
this research does not change those implementation rules.

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
Do not execute ordinary functions implicitly during type or interface resolution.
Explicit prepared stages can execute ordinary functions before dependent checks.
[D functions](https://dlang.org/spec/function.html)

D also provides useful evidence about compiler phase separation. Walter Bright
described the design intent and the incomplete parallel implementation at
different dates. See the [historical sources](#81-d-design-for-parallel-compilation).

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
specialization are separate costs. Exclude open trait search from the first
experiment. Test generated declarations through explicit stages in the
metacompilation experiment. Monomorphization remains in our pre-backend timing
budget even if a compiler calls it a backend phase.
[Rust trait resolution](https://rustc-dev-guide.rust-lang.org/traits/resolution.html),
[Rust macro expansion](https://rustc-dev-guide.rust-lang.org/macro-expansion.html),
[Rust monomorphization](https://rustc-dev-guide.rust-lang.org/backend/monomorph.html)

Ownership does not imply address stability. A bytewise move can break
self-references or intrusive links. Do not permit safe self-references in movable
records. Use stable owned storage when an address must remain fixed.
[Rust pinning](https://doc.rust-lang.org/std/pin/index.html)

Rust's pinning documentation uses intrusive doubly linked lists to explain
stable storage and teardown before reuse. It leaves the actual pointer edits
to an unsafe implementation. `Pin<Ptr>` preserves the pointer's layout; `Pin::set`
runs destruction before replacement in the same storage. Address stability must
therefore permit destruction and reconstruction, not prohibit reuse permanently.
[Pin layout and replacement](https://doc.rust-lang.org/std/pin/struct.Pin.html)

Five small programs checked with Rust 1.90.0 distinguish these contracts:

| Program | Result |
|---|---|
| Save a reference, destroy its owner, then use the reference | Reject with E0505 |
| Use the reference for the last time, then destroy its owner | Accept |
| Edit reciprocal `Cell<Option<&Hook>>` links, then clear both links | Accept |
| Clear both links, destroy one node, then use the other node | Reject with E0505; the containing type still carries the borrowed lifetime |
| Write an ordinary raw-pointer unlink function without `unsafe` | Reject with E0133 at the neighbor stores |

Thus safe Rust can mutate borrowed links without runtime borrow counters.
The missing operation is independent reclamation through a verified changing
graph. More precise borrow endpoints alone do not provide that graph invariant.
[Nonlexical lifetimes](https://rust-lang.github.io/rfcs/2094-nll.html)

The historical record is a useful constraint on this experiment. Rust credits
C++ for RAII and moves, Cyclone and ML Kit for regions, and NIL and Hermes for its
removed typestate system. The 2012 regions proposal froze unique owners during
temporary borrowing and restricted reference escape. These are useful local
rules, but do not prove persistent graph updates.
[Rust influences](https://doc.rust-lang.org/reference/influences.html),
[Regions-lite proposal](https://smallcultfollowing.com/babysteps/blog/2012/02/15/regions-lite-dot-dot-dot-ish/)

Rust removed its early typestate system after reporting that it was the slowest
pass except translation and that few programs used it. A separate issue records
users avoiding cumbersome preconditions. This is evidence against unbounded
proof inference and difficult annotations, not evidence that every static
permission system must be slow.
[Typestate removal](https://github.com/rust-lang/rust/issues/2178),
[Precondition ergonomics](https://github.com/rust-lang/rust/issues/1805)

Destruction obligations must also survive discarded guards. Rust's old scoped
thread guard could be forgotten while borrowed stack storage was reclaimed.
Crust must reject discarding a required obligation or preserve the storage
obligation with it; a destructor on a forgettable proxy is insufficient.
[Rust destructor leaks](https://doc.rust-lang.org/nomicon/leaking.html)

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
| Hare | A small language with manual ownership conventions | Keep the small vocabulary. Add enforcement where the language promises it. |
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
progress. Keep stage reports and visible generated code. The
[metacompilation study](metacompilation.md) separates a baseline without
expansion from an experiment with explicit generation stages and a public
compiler pipeline.
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
This keeps declarations compact. Crust instead starts declarations with fixed
keywords so that readers and parsers see their role immediately. This is a design
choice, not evidence that Jai's parser is slow.

Do not treat a community feature list as the current Jai specification. The
reviewed evidence does not establish current parser complexity, speedup across
cores, or isolated front-end speed. Those claims need a public compiler version,
a fixed corpus, stage timings, and the same C baseline.

Keep Jai's focus on fast complete builds, visible data representation, and
compiler reports. Investigate its ordinary-language build driver and typed-code
interface. Do not assume that its broad metaprogramming design satisfies
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
checker must restrict those aliases if it has no runtime exclusivity checks.
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
The paper excludes pointers into the middle of a block. Embedded hooks require
an additional checked subobject path and an enclosing construction identity.
[Alias Types for Recursive Data Structures](https://www.cs.princeton.edu/~dpw/papers/alias-recursion-tr.pdf)

Separation logic supplies local field permissions and procedure contracts.
VeriFast checks explicit predicate operations and terminating lemma functions;
its design limits proof search, but still uses an SMT solver. Its published C
list example is evidence for checking actual pointer edits. Neither source
establishes Crust's compilation-speed or annotation limits.
[Separation logic](https://www.cs.cmu.edu/~jcr/seplogic.pdf),
[VeriFast design](https://people.cs.kuleuven.be/~bart.jacobs/nfm2011.pdf),
[VeriFast doubly linked list](https://github.com/verifast/verifast/blob/de42db8c2193f18754115f5ee958e6db10f9d226/examples/doubly_linked_list.c)

A recursive list predicate needs a way to expose an arbitrary interior node.
Repeated unfolding can require a walk through its proof representation. Viper's
quantified field permissions instead describe graphs and cycles through a set
of locations. Local edits need only a bounded neighborhood, but the invariant
still needs proof. Its general solver is not a demonstrated C-speed checker.
[Viper quantified permissions](https://viper.ethz.ch/tutorial/quantified-permissions.html)

Two historical alternatives fail specific requirements. Cyclone's manual-memory
study reports that unique pointers could not express Boa's doubly linked request
structures. Mezzo's adoption and abandon operations use a hidden adopter pointer
and a dynamic check; its static nesting mechanism cannot reverse the transfer.
Neither is a complete zero-bookkeeping solution for independently freed hooks.
[Cyclone manual memory management](https://www.cs.umd.edu/projects/PL/cyclone/scp.pdf),
[Mezzo, sections 7 and 8](https://gallium.inria.fr/~fpottier/publis/pottier-protzenko-mezzo.pdf)

The `generational-arena` implementation demonstrates another route: a safe Rust
pool with generation-bearing indices. It forbids unsafe code in its implementation.
This supports an optional safe-pool library. It does not establish direct-pointer
performance or justify requiring that storage model for ordinary lists.
[Generational arena source](https://docs.rs/generational-arena/latest/src/generational_arena/lib.rs.html)

Static fractional ownership is another useful lead. The public
`ghost-collections` experiments combine GhostCell and StaticRc, but describe
extra pointer/write costs and experimental cursor mechanisms. Do not call this
a completed zero-overhead answer.
[Ghost collections](https://github.com/matthieu-m/ghost-collections)

### Fil-C: address, authority, and construction lifetime

Fil-C separates the address bits of a pointer from an invisible capability.
Pointer arithmetic retains the capability; accesses check it. Stored pointers
need auxiliary capability storage and extra loads and stores. Preserving
`sizeof(pointer)` therefore does not establish zero runtime overhead.
[Fil-C InvisiCaps](https://fil-c.org/invisicaps)

Release invalidates the capability before physical reclamation. The collector
can redirect heap capability references to a permanent invalid object, so reuse
does not revive old pointers. Stack roots can retain freed storage instead.
This depends on runtime metadata and delayed reclamation, which this experiment
excludes.
[Fil-C collector](https://fil-c.org/fugc),
[Stack-root handling](https://github.com/pizlonator/fil-c/blob/8028dec6f484d67ade089d03fe5a05f25e0736b0/libpas/src/libpas/filc_runtime_inlines.h#L412)

Its allocation identity also differs from a logical construction identity.
Address calculation preserves the allocation capability. We infer that an
object destroyed and reconstructed inside one still-live backing allocation
does not obtain a new capability merely through that operation. Crust must
track storage, construction lifetime, access permission, and link topology
separately. Two embedded hooks share a destruction boundary even when their
addresses differ. This inference is from source inspection, not a Fil-C run.
[Fil-C address calculation](https://github.com/pizlonator/fil-c/blob/8028dec6f484d67ade089d03fe5a05f25e0736b0/llvm/lib/Transforms/Instrumentation/FilPizlonator.cpp#L14249)

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
are permitted. Foreign pointers and unclassified raw storage require an unsafe
contract before safe access. The direct-link pointer contract in section 6.9
must permit the user-written list algorithm; it is not established by these raw
pointer rules. Use a tagged optional type when absence is valid.

Evaluate `Option[T]` and `Result[T, E]` as standard-language library forms in the
checked experiment. They are not privileged seed types. They describe tagged
data, not arbitrary generic function bodies. Do not assume tag removal or a
special ABI until it is specified and tested.

### 6.2 Ownership and cleanup

Each resource has one cleanup obligation. Successful initialization creates it.
A permitted move transfers it and makes the source unusable. Moves do not call
user code. Initialized address-stable objects need a separate rule that prohibits
implicit relocation. Their owning handles can still move.
Assignment evaluates the new value before it releases an old live value.

A safe `replace(place, value)` operation installs the new complete value and
returns the old owned value. It leaves the place initialized on every normal path.
Use it to extract an array element of a movable type without a partial move.
It cannot relocate an initialized address-stable object. This is a fixed
ownership operation, not a generic function search.

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

This local-view experiment uses second-class borrows. Such a view can be a
parameter or local value, but cannot escape into persistent storage. Aggregate
and pointer conversions must preserve that restriction.

This is a rule for the local view category, not a ban on all stored references
in the language. Direct list links, graph edges, and scoped stack attachments
need their own lifetime and alias contract. Section 6.9 states the required
witness. An address is not automatically an exclusive borrow, and it does not
prove that the target remains alive. Optional integer handles are another
library representation; they are not the required replacement for pointers.

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

The local-borrow subset must prevent use after move, duplicate resource release,
dangling local views, and conflicting borrowed access. It must also prevent
uninitialized reads, out-of-bounds access, and unchecked union access.
The direct-link extension must state and establish its own access guarantees.
The rules above do not prove full temporal memory safety for stored pointers.

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

Shared reads are transitively read-only. The first standard language has no
safe mutation through a shared view. An unsafe wrapper cannot override this rule while a read
loan exists. Aliased mutable storage needs an explicit type rule before safe
link fields, atomics, or cells can use it. Ordinary shared reads must not
silently acquire that behavior. This missing rule is part of the systems test.
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

The first measured slice has no user-defined generics. This bounds the experiment;
it does not establish a complete language for GCC or LLVM workloads.
Use concrete records, byte buffers, and typed function pointers with concrete context
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
they become standard language features.

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
| Put a local lexical view inside a returned ordinary record | Reject that view's escape; this does not decide the stored-link contract. |
| Return a view of a local copy under `from input` | Reject the false storage origin. |
| Retain a returned view from a call-only temporary owner | Reject the missing lexical owner. |
| Re-enter a mutable global from a callback | Require an unsafe boundary; no hidden shared alias is permitted. |
| Return storage tied to a local allocator | Reject the independent owner contract or keep it scoped. |
| Register a borrowed context for a later foreign callback | Require owned registration state and completion of all uses before release. |
| Reset an arena that contains live resource values | Run explicit destructors or reject those element types. |
| Move an initialized self-linked hook by value | Reject implicit relocation under the address-stable rule. |
| Destroy a linked node, then use a saved independent pointer | Reject or check the stale access under the selected pointer contract; auto-unlink alone is insufficient. |

### 6.9 Intrusive lists with individual destruction and reuse

Use direct embedded links as the primary representation. A list must not dictate
how its nodes are allocated. Support stack objects, separate heap allocations,
and application-selected slabs or arenas. Individual destruction and storage
reuse remain required. A pool is an optional container library.

Patrick Wyatt's example is the practical starting point: embedded hooks and
automatic unlinking on destruction. The linked Coho source separates list
membership from payload ownership. Its hook has two pointers. Its list destructor
detaches nodes; a separate operation deletes them.
[Article](https://www.codeofhonor.com/blog/avoiding-game-crashes-related-to-linked-lists/),
[Coho source](https://github.com/webcoyote/coho/blob/c545721bac81f9bff567a29c337ce18c56766b32/Base/List.h#L111-L234)

The [systems source study](systems-capabilities.md) adds stack waiters, bulk
splice, compiler use lists, callbacks, and controlled relocation. These are
requirements for the language target. The two-hook example alone does not
establish that target.

#### Direct representation and operations

Start with a circular head and two address fields per hook. A detached hook
points to itself. Each payload can contain several independent hooks.
The following is representation pseudocode. It is not a checked Crust program.

~~~text
record Hook {
    prev: address Hook;
    next: address Hook;
}

unlink(h):
    p = h.prev
    n = h.next
    p.next = n
    n.prev = p
    h.prev = h
    h.next = h
~~~

This operation needs live, stable hooks and permission to change their links.
It must not run concurrently with conflicting link changes. The pseudocode
states the algorithm; it does not prove those preconditions.

Use `node.hook.unlink()` as the basic removal interface. There is no list
argument whose membership must be checked. Insertion can transfer a hook from
its current list. Define insertion relative to the same hook as a no-op before
any detach. Keep head-only operations distinct from payload removal.

A whole-list `splice_init(destination, source)` changes boundary links and
resets the source head. It must work between two nonempty lists without a walk
over the moved nodes. Handle equal heads before editing. Do not attach a list
identity to every node merely to support an unused wrong-list removal API.
An API that asks whether a node belongs to a named list can pay for a scan or
an explicit membership mechanism.

Plain unlink and insertion must allocate nothing. The two-pointer layout uses
16 bytes per hook under an ordinary 64-bit pointer ABI. This is a layout target,
not a measured Crust result. The revised static ownership contract permits no
additional runtime metadata, including metadata hidden in the allocator.

#### Ownership and automatic cleanup

List membership does not own the payload. An owner can destroy one node while
other nodes remain linked. For an automatic hook, destruction first removes its
membership before the hook storage becomes invalid. A non-owning list destructor
detaches all surviving nodes; it does not destroy their payloads. Thus, either
the node or the head can be destroyed first.

Section 6.2 runs the enclosing drop body before field cleanup. Thus, automatic
hook cleanup can occur after that body. If teardown can call back into a list,
detach all hooks before those callbacks or before payload fields become invalid.
Later hook cleanup is an idempotent unlink. The pointer contract must prevent
new external views of an object whose destruction has started.

Use separate owning-list operations when the list owns its elements. Detach
returns a live node. Erase destroys it. Transfer changes the owner when the
container contract requires it. These distinctions also occur in LLVM.

A hook initialized with self-links needs a stable address even while detached.
Move-only is insufficient: a move can still change an object's address.
Test an explicit address-stable type rule, propagated through containing records.
Initialize such objects in their final storage. An owning handle may move while
its pointee stays fixed. Do not insert user code into implicit moves.

Explicit relocation can be a separate operation that repairs references.
GCC PHI growth is a real witness for this operation. The permission to relocate
must cover every affected reference, or checked references must become invalid.
A stable-address rule does not supply that permission by itself.

Automatic unlink is useful for a single-threaded owner or a correctly held lock.
For concurrent lists, detach under the required locks. Follow the reader-lifetime
protocol before destroying reader-visible state or reusing storage. RCU can
require a grace period for both steps. Other cleanup can run after lock release.
Do not make every resource destructor acquire a lock or reclaim storage at once.

#### Exact safety question

Automatic unlink repairs the list's own neighbor links. It does not revoke
an independent pointer or iterator:

~~~text
saved = node
destroy(node)       // its hooks unlink correctly
use(saved)          // the payload is dead
~~~

The same issue occurs when a callback destroys the saved successor during
iteration. Reuse of the same address does not restore the old object's identity.
A generation stored only inside freed payload memory cannot be read safely.

There are three separate obligations:

| Obligation | Required mechanism |
|---|---|
| Cleanup and stable storage | Run hook cleanup on every normal exit; prevent implicit movement after address-dependent initialization. |
| Valid link edits | Establish live endpoints and permitted aliasing throughout the edit; restore the library's link invariants. |
| Saved access after destruction | Reject statically when no proof establishes that the original construction is still live. Address equality after reuse is insufficient. |

A lexical access guard can prevent destruction during a current view. It does
not invalidate an address saved before that guard. A lock protects the state
covered by its contract. It does not prove that a pointer retained after unlock
still has live storage. Do not give aliased link pointers an exclusive `mut`
contract or emit `noalias` merely because the enclosing function mutates a list.

The required list algorithm must still be writable without `unsafe`.
Renaming unchecked pointer operations does not meet that requirement.
The local-borrow rules in section 6.4 do not yet establish a safe direct-link
contract. The design must state this gap instead of routing all nodes through
a pool to avoid it.

Use this bounded comparison to resolve the gap:

| Candidate | Concrete proof or cost to establish |
|---|---|
| Scoped cursors plus static link permissions | Show safe user-written insert, unlink, and destruction with two hooks. Prove the validity of surviving links. A scope token alone is insufficient. |
| Erased mutation permission plus a graph invariant | Keep liveness and field access in a checked invariant. Require this permission for mutation and destruction; reject conflicting cursor loans. Prove the actual edits. |
| Plain pointers with RAII | Useful C/C++ reliability baseline. Lifetime preconditions remain on the programmer; this alone does not pass the stronger safe-code requirement. |
| Tracked observers and generation keys | Historical alternatives only. Their runtime validity metadata violates the revised ownership requirement. |

No candidate in this table has passed the combined safety and simplicity gates.
First specify a complete contract for one direct two-hook example.
Test the invalid programs in section 10.2, then measure the checker and generated
code. More expensive static proof is permitted in an explicitly selected stage.
Stop a candidate that requires runtime alias metadata or fails its safety and
usability contract. Do not add a larger container system before this decision.

#### Static ownership candidate and unresolved proof

The experiments support an external stage based on permissions and explicit
contracts. The following model is selected for the next implementation step.
The current resource stage does not implement it. The seed needs no ownership
types or list operations.

Separate these compile-time facts:

| Fact | Purpose |
|---|---|
| Stable storage | Prevent moves after address-dependent construction; allow movement of an owning handle |
| Fresh construction name | Distinguish objects constructed at the same address at different times |
| Subobject path | Relate each hook and payload field to its enclosing object without granting access to sibling fields |
| Owner permission | Identify the party responsible for teardown and storage release |
| Field permission | Authorize a read or write, separately from copying address bits |
| Closed invariant | Establish live link targets and the relationships needed for later operations |
| Cursor loan | Prevent conflicting access and destruction while a derived view can still be used |

Names, paths, and permissions must erase before emission. They must not become
hidden arguments, owner fields, domain pointers, or allocations. Object layout
and calls must match the direct implementation even without optimization.
Construction names describe fresh lifetimes symbolically; the checker does not
enumerate runtime allocations or generate a counter for loop iterations.

One possible rule gives each stored edge a linear share of target liveness.
For a two-pointer hook, reciprocal fields locate the two incoming shares.
Unlink transfers the outgoing shares to the neighbors and recovers the incoming
shares in the detached self-links. Fixed named portions suffice for this case;
general fractional arithmetic is unnecessary. However, the shares alone do not
prove that the expected neighbors and permissions exist.

A potentially smaller first experiment uses one erased mutation permission for
a set of cooperating objects. Call this set a permission domain. It selects no
allocator, reserves no storage, and needs no runtime representative. Stack nodes
and independent heap allocations can belong to the same domain. Avoid storing
the exact list identity in each node's static type; splice must not change every
node or every owner description.

The domain invariant describes the live hooks and their field permissions.
For circular links, a useful algebraic model is:

```text
H contains live hook subobjects.
next maps H bijectively to H.
prev is the inverse of next.
Detached(h) means next(h) = h and prev(h) = h.
```

A useful generic proof exchanges two successors and repairs their inverse
fields. Exchanging the successors of `prev(h)` and `h` isolates `h`. A second
proof removes this fixed point from the permutation. Both statements can use
finite cases on the changed keys and an abstract unchanged remainder. The
stage must check these proofs; neither is a trusted list primitive.

This model supports a local description of these ordinary stores:

```text
p = h.prev
n = h.next
p.next = n
n.prev = p
h.prev = h
h.next = h
```

The stage must expose the relevant field permissions, check every assignment,
and restore the invariant. In the singleton case, `p` and `n` are the same head
but name different fields. In the detached case all three hooks coincide;
the proof must not consume the same field permission twice. These are alias
cases in the proof, not justification for runtime ownership flags.

The permutation model is insufficient by itself. A list also needs a proved
head and payload-projection contract. Two different heads can occur in the same
cycle; applying the usual splice can break the inverse relationship or preserve
it while losing nodes in an orphan cycle. For example, splicing the two supposed
heads `d` and `s` in `d-e-f-s-b-c-d` can produce `d-b-c-d`, `s-s`, and `e-f-e`.
All three results are reciprocal, but traversal from either head has lost nodes.

Splice requires disjoint rooted cycles or its declared self-splice case. A root
predicate must describe the complete set of hooks in its cycle. Splice transfers
an abstract set between roots without a runtime list ID or a proof expansion per
node. Unlink without a head argument must update the affected root description
through a checked general lemma. The experiments below supply two algorithm-level
proofs of this update. A non-head hook must also have the expected enclosing
payload before a container projection.
Neither a different address nor a domain brand proves these facts.

Ordinary cursor views borrow domain access. In the conservative first rule, a
live shared cursor blocks mutation and destruction anywhere in that domain.
Use the same domain permission for registered payload access in this first
experiment; a separate payload-permission protocol is not yet justified.
Payload projections, returned views, and captured views retain this loan.
Owner access must obey the same permission rule, including access through another
embedded hook. Internal link reads need named liveness facts; obtaining the
domain again must not make
a saved stale address usable.

Owner cleanup requires the mutation permission and the absence of conflicting
loans. It detaches every hook, removes the construction from the invariant, and
then releases storage. Head cleanup detaches surviving nodes before head storage
ends. The permission cannot go out of scope while registered owners still need
it for cleanup. These requirements apply equally to stack exit and heap release.
Moving an owner between scopes must carry its cleanup dependency explicitly.
The initial witness uses one domain. Combining independent domains needs a
proved transfer rule and cannot follow from casting one brand to another.

An open invariant cannot cross a callback that can touch the affected objects.
No normal return or error exit may leave the invariant open.
Before payload teardown calls user code, all hooks must be detached and the
invariant closed. A saved successor is not necessarily safe during destruction
of the current node: a destructor can reach it through another hook or a captured
owner. Different hook addresses can even share one enclosing object. Reject the
call unless its complete cleanup effects preserve every retained view. A
remove-current operation must consume its current view and establish the next
view after the permitted mutation; it cannot retain an unchecked successor.

A checked, reusable proof must expose a local neighborhood from the invariant
and restore the invariant after the stores.
It must preserve facts about all untouched fields. A recursive segment proof
or an abstract set of field locations can express this, but neither provides
a cheap checker automatically. Domain permission reduces liveness bookkeeping;
it does not remove the graph proof. Do not implement both domain permission and
per-edge shares before this simpler candidate has been tested.

Use explicit procedure contracts and checked proof helpers. Check each body
independently; reuse a helper's checked contract at its calls. Proof helpers
must terminate and have no runtime effects. An unchecked axiom named `unlink`,
an unchecked invariant declaration, or a stage exemption for hook records fails
the experiment. The generic rules must justify user-defined field relationships.

The inexpensive profile can use local permission transfer and explicit
contracts. An optional relational profile can use invariant proofs and an
external solver. The root selects these stages through ordinary calls. Solver
failure, timeout, or an unsupported construct must stop the selected proof;
there is no automatic downgrade to unchecked compilation. Independent bodies
can use declared contracts in parallel. Reuse checked helper results only with
their exact definitions, interfaces, stage, solver configuration, and target
layout. Report fresh checking and proof-result reuse separately.

The first decision point is the complete two-hook witness: unlink, individual
destruction, exact-address reconstruction, continued use of the remaining list,
head-first teardown, and constant-work splice. Reject faulty stores and escaped
views through the same generic rules. Compare emitted operations and annotations
with the direct baseline, then measure the complete stage. Stop if it requires
runtime ownership state, trusted list algorithms, per-node runtime splice work,
or proof code that fails the readability gate in section 10.2. Measure proof
work without imposing the basic profile's C-speed gate on an optional profile.
The experiments below establish parts of this boundary through executable
checks. They do not establish a complete checked Crust application.

#### Executable experiments and model selection

The next model combines linear owners, scoped access permissions, and verified
library contracts. Stronger proof is optional compiler work. All profiles keep
proof state out of the application. A less capable checker rejects operations
that it cannot justify; it does not silently accept their memory preconditions.

The useful separation-logic representation pairs matching fields:

```text
edge(p, q) = owns(p.next = q) * owns(q.prev = p)
```

Here `*` combines disjoint field permissions. It does not require disjoint whole
objects. An edge from a hook to itself owns its two different fields. A circular
path joins these edge predicates. A detached hook owns `edge(h, h)`.

This representation makes the destruction rule precise. The allocation owner
keeps the deallocation right. The domain holds registered field permissions.
Unlink returns the detached hook fields. Destruction must recover both hooks,
all payload permissions, and the allocation right, with no remaining view.
Membership never manufactures ownership. Removing a current cursor can return
a detached place; it cannot return a destruction right that the cursor did not
have. A list head's cleanup detaches members without taking their owners.

One permission domain governs the first implementation. Its external shared
views prevent mutation and destruction in that domain. This conservative rule
also blocks edits to unrelated members. A projected payload view retains the
loan after its cursor goes out of scope. A callback can use the domain only
after its invariant is closed and conflicting views have ended. Teardown first
detaches all hooks and prevents new views of the dying construction.

Three independent experiments support this model:

| Experiment | Established result | Boundary |
|---|---|---|
| Symbolic checking of actual Crust bodies | The ordinary reader, resolver, and checker export init, unlink, insertion, and splice operations. Their real stores satisfy an unbounded rooted-ring invariant. | The caller supplies valid disjoint typed storage and exclusive domain permission. This slice does not check allocator or owner code. |
| Annotated C with VeriFast | Checked edge and path lemmas justify actual pointer edits over arbitrary-length lists. A client uses two embedded hooks, independent heap owners, and stack nodes. Deallocation requires both hooks back. | This verifier has its own C provenance model. It is evidence for the permission rules, not a Crust frontend. |
| Executable lifetime model | Owner rights, cursor and projected-view loans, both hooks, teardown phases, and exact-address reuse obey one transition contract. Tests cover thousands of membership and destruction orders. | This is a concrete state model. Its scans and ghost counters are an oracle, not compiler algorithms or emitted state. |

The independent proof uses [VeriFast 26.09](https://github.com/verifast/verifast/releases/tag/26.09).
It verifies 318 statements and rejects 13 mutation and misuse cases. Its iterative
head-clear loop returns every former member's detached fields. The head can then
leave scope before the independently owned heap nodes are destroyed. There is no
assumed unlink lemma. Checked ghost lemmas expose and restore the ring fields.

That proof contains 171 nonblank executable C lines and 452 lines of annotations
and comments, including 15 checked ghost lemmas and 9 predicates. This supports
the permission mechanism, not a claim of simple proof authoring. Library helpers
must carry the repeated proof work. The proof uses explicit erased ring witnesses;
it does not establish automatic selection of a ring from a client's domain.

The reuse results have different scopes. The C proof permits reconstruction in
the same stack slot after both hooks are detached. A separate negative witness
assumes that a new heap allocation has the freed block's numeric address; that
equality still cannot authorize access through the old pointer. This does not
prove that two constructions within one continuously allocated block receive
distinct lifetime permissions. The executable lifetime model tests that rule;
the Crust source checker must still enforce it.

The first Crust experiment is a real compiler path. An ordinary Crust stage reads
source through the existing APIs, exports resolved operation identities, invokes
the selected checker, and emits from the same unchanged context after success.
It has no additional source parser, list-name exemption, or trusted unlink
operation. A scratch Python executor constructs solver queries from that tree;
it is not itself a Crust implementation of the ownership checker.

The library supplies its invariant and function contracts separately from the
generic operation executor. Declaration and field identities bind them to the
checked input. Renaming functions, records, and fields preserves the proof.
The solver receives the stores from the source, not replacement stores from the
contract. Missing backlinks, wrong neighbors, wrong splice boundaries, and
missing source-head reset fail before emission. Unsupported bodies and solver
uncertainty fail too. Direct calls in this experiment expand the actual callee
body; modular checking from a saved summary is not yet exercised.

The symbolic model uses ghost maps for live hooks, roots, ranks, and ring lengths.
Ranks distinguish a rooted cycle from an orphan cycle. Universal invariant
instances at affected locations are enough for the tested operations; the proof
does not enumerate a bounded number of nodes. The initial unrestricted
quantifier experiment timed out on a rank obligation. Explicit instantiation
and a preserved rank-uniqueness fact discharged it. This is a reason to make
proof policy and budgets explicit, not to accept `unknown` as success.

The accepted C for the four list operations is byte-identical to ordinary
backend output before target optimization. A native client exercises two hooks,
stack and separate heap storage, individual destruction, head-first cleanup,
constant-work splice, and reconstruction at the exact address. It passes
unoptimized, optimized, and address/undefined-behavior sanitizer runs. This
client supplies runtime evidence; it is not checked by that Crust lifetime model.
No frontend speed claim follows from these checks.

#### Implemented optional proof profile

The [static memory tutorial](../../examples/ownership/README.md) now contains a
separate complete checked client. Its executor, memory policy, and ring policy
are ordinary Crust code. They consume the existing typed tree and call the Z3
C API directly. The seed has no new syntax, ownership state, or solver operation.

The memory profile tracks allocation identity, byte extent, alignment,
initialization, and live storage. It checks each actual load and store. Before
release or scope exit, other live objects must not retain persistent pointers
into the retiring storage. Scalar aliases can remain but cannot access that
storage. A later allocation can have the same numeric address; it receives a
different proof identity. The emitted application has ordinary pointer fields.

The direct client uses the same link bodies as the unbounded library proof.
It checks two hooks, individual heap destruction, head-first cleanup, and typed
payload projection. Accepted C text must match ordinary backend output byte
for byte. Mutation tests remove required unlink or head cleanup operations.
Other tests cover null access, double release, stack escape, uninitialized
reads, bounds, alignment, pointer-to-pointer backlinks, and stale aliases under
possible equal-address reuse. Allocation failure tests exercise stage cleanup.

This profile expands direct calls and unfolds loops under explicit budgets.
At the bound it must prove that the loop cannot continue. Unsupported cases,
counterexamples, and solver uncertainty stop output. The library proof is a
separate conditional check; callers do not consume it as a permission summary.
There is no claim of C-speed proof checking or completed modular ownership.

The resource stage supports a result view tied to one input loan. Its moves,
RAII, and `defer` use retained cleanup plans. The
[combined stage](../../examples/intrusive/README.md) now brings those
plans, source storage scopes, deferred captures, and owner transfers into the
memory proof. A check of the lowered tree alone would still omit cleanup calls.
The same transfer facts support consuming pointer reads with `move place`.
The two-hook RAII destructor consumes its node field, unlinks both hooks, and
releases the node without clearing that field. Consumed-field reads through
aliases, repeated drop, reentrant reads, and surviving external links reject.
Pointer moves emit the same C operations as ordinary pointer reads. Other
fields retain their permissions; no destructor has an exemption from checking.
The resource interface also delegates plain-value initialization explicitly.
The memory proof follows output stores through aliases, branches, loops, and
cleanup. Owner construction and loan bindings retain their source-flow rules.
The stack-hook example initializes each hook at its final address and uses a
separate RAII guard to detach it before storage ends. Missing initialization
and missing cleanup both reject. This adds no initialization store or flag.
The next modular interface must connect owner rights and field permissions to
verified library contracts. The combined stage can now reuse concrete memory
effects for selected straight-line, unit-returning functions. It derives the
template from the current checked body and full resource proof view. Each call
must still prove the access obligations and typed-write separation. It keeps
the written pointer cells and consumed-field effects for later lifetime checks.
The two-hook destructor uses this path for `unlink`. Removing a backlink store
from that body must fail the caller's destruction check.

This is body-effect reuse, not an abstract ownership contract. An SMT function
encoding increased solver cost on the actual RAII witness. The selected form
binds a template with fresh names and emits flat definitions. It leaves emitted
C unchanged. Timing captures and alternative encodings remain in ignored build
storage; this result makes no general speedup claim.

Subobject projection needs its own contract. The default VeriFast C model
rejects subtraction outside a field subobject, even with a known parent. Crust's
existing storage rules retain the whole allocation origin for a field address.
A separate symbolic check of the actual Crust `offsetof` projector uses those
rules. Given a live typed parent and a loan to the specified embedded hook, it
proves that pointer casts and subtraction recover that parent. Wrong member
offsets, wrong element strides, and offsets outside the allocation fail. Native
stack and heap projector calls also pass. No pointer tag or runtime test is used.

That proof cannot infer a parent from address bits. A typed list must preserve
the payload type and hook path at insertion and through traversal. A head has no
payload projection. Two hooks in the same node retain the same construction
identity and destruction boundary. The projection must carry its input loan;
returning the address alone cannot extend the construction's lifetime. Recovering
the parent address also grants no additional access permission. Reading payload
needs its domain permission; a loan of one hook cannot become an exclusive view
of the whole parent or its sibling hook.

The selectable boundary is therefore between local checking and relational
proof, not between two pointer representations. Local checking handles moves,
cleanup obligations, scoped views, and declared capability transfers. A
relational stage proves pointer-manipulating library bodies and loop invariants.
Clients should consume checked contracts without repeating the library proof.
That requires binding a summary to the exact body, types, layout, imports, and
checker configuration. Such summaries may be cached by an ordinary stage.

The next contract work is to abstract the checked call effects and loops. Every exit
must return its domain
permission or transfer it explicitly. Every projected or returned view must
retain its loan. The checker must reject destruction while that loan survives,
including through callbacks and another hook. The current experiments establish
the field-edit and permission foundations; they do not replace these source
checks. Keep the research-only exporters, alternate verifier inputs, and timing
artifacts in ignored build storage. The executable tutorial and its regression
tests are source-controlled. The C99 core remains unchanged.

### 6.10 Systems programming capability target

Linux, GCC, and LLVM set the required level of storage and mutation control.
Their source does not imply that every operation must enter the safe subset.
Hardware access, foreign code, and raw layout primitives still need explicit
contracts. The safe user-written list remains a separate hard requirement.

Preserve these capabilities:

- Several hooks per object, with ownership independent of membership.
- Stack, static, heap, slab, and arena storage selected by the application.
- Stable published addresses and explicit relocation with reference repair.
- Constant-time plain-list splice and individual destruction with storage reuse.
- Persistent graph edges, pointers to fields, and variable-size operand storage.
- Explicit lock scopes, atomics, lifetime pins, and deferred reclamation.
- Callbacks that can change a registry under a defined notification protocol.
- Exact layout, alignment, foreign ABI, and optional pointer tagging.
- Reusable typed container operations without mandatory indirect calls.

The [source study](systems-capabilities.md) maps each item to real functions.
The first measured slice can use concrete types. That choice is an experiment
boundary, not a decision that a complete language needs no reusable abstraction.
General templates, inheritance, and unrestricted compile-time execution do not
follow from these capability requirements.

## 7. Syntax that is simple to parse and read

For the default Crust grammar, prefer keywords and visible boundaries over minimum
character count. Its parser must not consult declarations to decide whether an
expression is a type. It must not backtrack over arbitrary token sequences.

Proposed surface rules:

- `fn`, `struct`, `enum`, `resource struct`, `let`, and `var` introduce declarations.
- Write names before types: `count: u32`.
- Use braces for blocks and semicolons for simple statements.
- Require `-> Type` on every function, including `-> unit`.
- Use fixed operator precedence and explicit casts with `as`.
- Use type arguments only in type positions in the first grammar.
- Use `make Type { field: value }` for record construction. This separates a
  constructor from an `if condition { ... }` block without type lookup.
- Keep textual macros, global grammar mutation, and newline-dependent insertion
  out of the default grammar. Test fixed expansion sites separately.
- Use a small fixed token set. ASCII identifiers are sufficient for the first
  slice; UTF-8 remains available in comments and string data.

The parser is a public, replaceable compiler stage. A custom driver can use
another lexer, complete grammar, and language rules. It can combine parsing
with name resolution when that language requires it. The
[C frontend experiment](compiler-extension-experiment.md#4-c-compiler-witness)
tests this boundary. Measure that frontend against the same speed requirement.

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

The graph shows the default baseline without generation. The public driver can
insert explicit generation stages. The arrows show dependencies, not global
barriers. A ready module can advance while another file is still being parsed.
A function can start after its own
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
For the baseline, constants form a finite dependency graph and use literals,
fixed arithmetic, and type-layout queries. The interface resolver does not
execute arbitrary user functions. In the extension experiment, an earlier
generation stage can compute inputs before resolution starts.

Public interfaces include type identity, visible fields and layout, function
signatures, ownership modes, drop properties, and required constants. A private
body edit must not change an interface. A private layout change can still affect
an exported by-value type; record that dependency instead of hiding it.

Use fixed target configuration for conditional declarations in the default
driver. Complete generation before dependent workers check bodies. An explicit
earlier generation stage can publish new declarations and imports. Include
its preparation, execution, and output processing in the measured build.
The [metacompilation study](metacompilation.md#52-make-each-dependency-stage-explicit)
defines this candidate schedule and its cache boundaries.

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

The core representations, passes, and driver setup are fully exposed.
Users can replace, remove, reorder, and add stages. Stage preconditions and
postconditions define valid composition. A custom checker becomes part of
that compiler's trusted implementation. Editing checked IR requires preservation
of its facts or renewed checking. Include the selected pipeline in cache identity.

Parallel workers can increase memory traffic and total CPU time. A long function
or deep import chain limits available parallel work. Report these limits in
measurements. Do not promise linear speedup. Avoid concurrent mutation of one
LLVM context; use backend-supported independent work units at handoff.

### 8.1 D design for parallel compilation

Walter Bright's posts support separating the language design from the compiler's
implementation status. These are historical statements, not a current DMD audit.

**4 April 2009: Multithreaded I/O.** Bright states that D was designed to permit
compilation in parallel threads. His implemented experiment reads files on one
thread while another thread lexes and parses previously read files.
He then proposes a separate lex/parse thread for each module. That step was a
plan in this article, not an implemented parallel parser.
Cached local files gave no measurable gain from the I/O experiment. A test with
uncached removable storage did improve. His many-core parser estimate was not
a measured scaling result.
[Original article](https://digitalmars.com/articles/b28.html)

**17 August 2010: C++ Compilation Speed.** Bright explains how textual headers
and context-dependent translation obstruct lookahead, reuse, and parallel work.
This is historical context for the D design. It is not a description of current
C++ module implementations.
[Original article](https://digitalmars.com/articles/b54.html)

**February 2016: Official compiler.** Bright identifies substantial work inside
the compiler that could run in parallel, but explicitly excludes semantic
analysis from that statement. He distinguishes this from separate compiler
processes started by a build tool.
[Walter's forum message](https://forum.dlang.org/post/nao7mi%242m2o%241%40digitalmars.com)

**2 May 2020: independent stages.** Bright says the lexer is independent of the
parser, and the parser is independent of the rest of the implementation.
He says he rejected enhancement proposals that would break these boundaries.
[Walter's comment](https://news.ycombinator.com/item?id=23054712)

**12 July 2023: design versus implementation.** Asked whether D can compile
modules in parallel, Bright says the language permits it but the compiler does
not do it. He also says parallel file reading had been removed because its speed
benefit was insufficient. This describes the compiler at that date.
[Question](https://news.ycombinator.com/item?id=36689544),
[Walter's answer](https://news.ycombinator.com/item?id=36695523)

**29 April 2024: modules and parsing.** Bright describes module meaning as
independent of the importer. He also identifies separation of lexing and parsing
from semantic analysis as a deliberate response to C/C++ compilation costs.
[Walter's comment](https://news.ycombinator.com/item?id=40194136)

The D specification supports the phase-boundary claim. Earlier phases do not
depend on later phases; in particular, semantic analysis does not control the
scanner. This does not mean that later phases need no output from earlier ones.
[D compilation phases](https://dlang.org/spec/intro.html#phases-of-compilation)

There is a related 10 November 2011 post by **Don, not Walter**. It describes
parallel evaluation after an ordered `static if` and mixin pass. It explicitly
says the compiler did not implement that parallelism. It also explains why
compile-time mutation of globals would impose an order.
[Don's message](https://forum.dlang.org/post/j9f8id%24pf3%241%40digitalmars.com)

For Crust, the design inference is to preserve the phase boundaries in the language.
Do not make lexing or parsing call semantic analysis to interpret source syntax.
Keep a module's meaning independent of the context that imports it.
These rules expose parallel work in files. They do not prove independent semantic
analysis of arbitrary modules. The explicit signatures and fixed interface
dependencies above address that separate problem.

Measure parallel I/O, parsing, and body checking separately. A faster storage
device or a warm cache can remove the benefit of I/O overlap. A language design
claim is not speedup evidence. A claim of C-level speed still requires the
single-worker gate. Other selected profiles must report their measured costs.

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
| Direct hooks with RAII | Pointer fields and required unlink writes | Cleanup and address-stability checks; persistent-pointer contract still to establish | No hook fields on other records |
| Proposed static link permissions | No proof metadata; ordinary pointer fields and required edits | Local invariant checking, not yet implemented | No graph proof for code without the selected stage |

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

Use a concrete node with two embedded hooks, as in the Coho example.
Write insertion, unlinking, traversal, and cleanup in ordinary user code.
Use stack nodes and separately allocated nodes. Reuse one node's storage while
the list and its other nodes remain live. The application selects its allocator.

Require these cases:

- Empty, singleton, first-node, last-node, and middle-node operations.
- Forward and reverse traversal; removal of the current node.
- One payload in two lists through different hooks.
- Transfer of a linked hook, repeated unlink, and self-insertion.
- Bulk splice between two nonempty lists with a constant number of link writes.
- Node destruction before head destruction, and the reverse order.
- Exactly-once cleanup of initialized fields after failed construction.
- No enclosing drop action before successful construction; normal cleanup on early return.
- Rejection of an implicit move of an initialized address-stable hook or head.
- Immediate storage reuse after permitted individual destruction.
- A saved external cursor across destruction and exact-address reuse.
- A callback that destroys the current node or saved successor.
- A destructor or field cleanup that re-enters a list containing the node.
  Detach before exposing partial teardown, or reject that re-entry.
- Rejection of destruction or relocation during a live protected view.
- A stack iterator marker that unlinks on early exit.
- Detach under a lock followed by cleanup outside that lock.

The direct C/C++ baseline has lifetime preconditions for saved pointers.
For the proposed safe version, each invalid lifetime or permission use must have
a stated static rejection. An uncontrolled crash, undefined behavior,
or a changed allocation policy does not satisfy that safety gate.
A no-op for self-insertion is part of the declared valid-operation contract.

Require no unsafe code in the user-written list algorithm. Document every trusted
primitive. No built-in list operation can hide the algorithm being tested.
Include assignment, destruction, subobject projection, callback, and permission
lifetime rules. Count shared proof helpers as well as the small surface program.

Insertion and unlinking should each fit within 40 nonblank lines, excluding shared
helpers. Count helper code and annotations separately. This is a proposed
readability gate, not a measured result. Reject permission syntax that makes the
example substantially harder to read than its C/C++ baseline.

Measure hook, head, node, and external metadata sizes. Count allocations, pointer
writes, dependent loads, validity branches, and bytes retained after destruction.
Report traversal and mutation costs for working sets inside and outside cache.
For bulk splice, count touched nodes as the moved list grows.
Repeated erase and reuse must not retain destroyed payloads or identity storage.
Construction identities are compile-time facts, not runtime records.

Compare direct C/C++ first. Require two pointer fields per hook, no hidden runtime
permission arguments, and no ownership checks, counters, or registration writes.
Null-before-release and debug bounds checks are separate declared behavior.
Inspect output before optimization; do not depend on removing proof machinery
through backend optimization. Record library proof size and per-call checking
work so a constant-work splice does not conceal proof expansion.

The [systems source study](systems-capabilities.md#acceptance-experiments) defines
the next bounded witnesses: Linux stack waiters and reclamation, GCC operand
relocation, and LLVM replacement with observers. They test required capabilities.
Passing the two-hook list does not establish all of them.

### 10.3 Define the timing boundary

Record two measurements:

- **Check time:** process start, source and interface I/O, lexing, parsing,
  name resolution, type checking, and ownership checks.
- **Handoff time:** all check work plus cleanup lowering, all specialization,
  ABI lowering, and complete input construction for the selected backend.

Handoff time ends before backend optimization, instruction selection, register
allocation, and object emission. If LLVM IR is the handoff, building that IR is
included. Moving a pass into a file named “backend” does not exclude it.
The [backend adapter is a public metastage](compiler-extension-experiment.md#3-the-backend-adapter-is-a-metastage).
Its package name does not change this timing boundary. Include native code
generation and linking if the measured request prepares a changed project
stage. The main application gate uses a compiled backend as a toolchain input.
Report backend bootstrap and automatic cache validation separately from that
gate. Include native library loading and ordinary root execution.

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
| Direct intrusive lists with destruction and exact-address reuse | Test user implementation, stable storage, and stale access |
| Linux, GCC, and LLVM source-derived slices | Test stack attachment, concurrency, graph edits, and operand relocation |
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
build time. Measure fresh compiler processes with no saved application
results and an identified compiled backend. Report backend construction,
automatic backend cache validation, and incremental target results separately.
Distinguish filesystem caches, backend artifacts, and application results.

Use at least 20 paired timing samples after setup checks. Randomize run order.
Report medians, variation, total CPU time, and peak memory. For each frozen
workload and each comparable boundary that claims C-level speed, require a median
candidate/C ratio at most 1.00. Require the upper bound of its 95% confidence
interval to be at most 1.00.
Otherwise, that speed claim is not established. An optional stronger checking
profile can have a higher measured cost. Do not average away a failing workload
or repeat samples solely to obtain a passing interval.

Measure the single-worker path first. A C-level speed claim must pass its gate
there. Then run 2, 4, and 8 workers where hardware permits. Report wall-time gain
and CPU/memory cost. Require identical diagnostics and equivalent program output
across worker counts.

Check final generated code for wrapper call ABI, cleanup branches, hidden
allocations, reference counts, indirect calls, and retained metadata.
Compare runtime with equivalent checked C and record every remaining abstraction
cost. No feature passes on an assumption that LLVM will remove that cost.

For ordinary owners, the runtime gate permits no extra allocation, reference
count, runtime loan table, owner metadata, or required indirect call on a
direct-access path. A resource wrapper must have the C representation's size
and alignment. Reject an abstraction that adds those costs for the same operation.

The direct list's representation and operations use C/C++ as the primary baseline.
The selected ownership model excludes runtime pointer-validity checks. A match
against a C implementation with such checks would not meet this requirement.
Null-before-release and debug bounds checks remain separately permitted behavior.

Also run repeated in-memory column processing with a checksum instead of output.
This prevents disk and terminal time from hiding callback cost. Require a median
runtime ratio at most 1.00 and the same confidence rule against equivalent checked C.
Match necessary validation and cleanup on both sides. If the strict callback API
fails, test the declared view-return alternative. Do not claim that callback cost
is free because it is small beside database I/O.

### 10.5 Decision sequence and stop conditions

1. Freeze the direct C/C++ witnesses, expected output, failure cases, and timing boundary.
2. State the direct-link lifetime contract. Reject contracts that hide unchecked access.
3. Specify and test the grammar independently of names and types.
4. Implement only the SQLite boundary and the direct intrusive-list witness.
5. Test forbidden programs as well as successful executions.
6. Measure one-worker check and handoff time for each selected capability level.
7. Compare the declared view-return alternative where callbacks add unnecessary cost.
8. Re-run safety, readability, layout, and runtime gates for each changed contract.
9. Test the source-derived systems slices before claiming that capability level.
10. Test parallel scheduling after the single-worker path is correct and measured.

Do not authorize a general compiler framework, trait system, or container
ecosystem from parser throughput or synthetic ownership tests.
The go/no-go evidence is both complete ownership boundaries, final output,
safe node reuse, measured compilation, and measured runtime cost.

## 11. Decision record

| Keep in the first experiment | Reason |
|---|---|
| Explicit signatures and semantic modules | Bound dependencies and expose independent work |
| Public core representations and compiler stages | Let ordinary user code configure and replace the compiler pipeline |
| Ownership, cleanup, and unsafe policy in standard language stages | Keep the seed small without removing the standard language checks |
| Regular keyword-based syntax | Parse without name resolution |
| Move-only resources and lexical cleanup | Remove repeated manual release logic |
| Restricted shared and exclusive local views | Check common lifetime and alias errors locally |
| Tagged data and explicit results | Make absence and failure visible |
| Explicit allocation and unsafe boundaries | Preserve storage control and name trust assumptions |
| Direct embedded links and independent ownership | Preserve the requested representation and storage control |
| Address stability and hook cleanup | Prevent accidental relocation and missed unlinking |

| Require a separate successful experiment | Concrete question |
|---|---|
| Safe direct-link pointer contract | Can the source checker connect the verified link algorithms to individual destruction, reuse, and readable client code? |
| Erased domain and invariant permissions | Can checked library contracts support simple callers without runtime state or repeated graph proofs? |
| Single-source borrowed returns | Can ordinary view APIs stay simple without general lifetime solving? |
| User generics | Can useful containers avoid both specialization growth and unwanted indirect calls? |
| Safe thread and retained callback APIs | Can transfer and quiescence be proved without hidden lifetime escape? |
| Arbitrary deferred blocks | Can capture and cleanup stay clear without a general closure model? |
| Staged language extensions and a small bootstrap core | Can useful generators and custom drivers meet the cold C-speed gate? |
| Complete C frontend and replaceable backend adapter | Can public stages compile unchanged C and preserve the check and handoff speed gates? |
| Persistent expansion caches | Can validation cost and invalidation remain correct with exposed compiler stages? |

| Exclude from the initial standard language | Reason |
|---|---|
| Unrestricted live compiler mutation in the default driver | Requires dependency and checking contracts beyond the bounded staged experiment |
| Open overload or trait search | Resolution work not bounded by one explicit interface |
| Exceptions, mandatory GC, and automatic reference counting | Runtime policy is imposed on programs |
| Escaping local lexical views and implicit moves of address-stable values | Violate the stated scope or address contract |
| Mandatory general graph and heap-shape proof machinery | Stronger proofs belong in selected stages; their cost must not affect the basic path |
| Mandatory pools and per-node list identities | Impose storage or mutation costs not required by direct intrusive lists |
| Implicit allocation, cloning, and conversions | Hide cost and ownership changes |

The next artifact after this exploration is a frozen witness and a small
experimental specification. This study does not authorize implementation
expansion before those gates are met.
