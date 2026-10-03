<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership and cleanup in a Crust stage

Date: 2026-10-01. Status: design record with an implemented resource stage.

Implement ownership, RAII, and `defer` in an ordinary Crust compiler library.
The root program selects that library. Keep these rules out of the C99 seed.
RAII means that an initialized resource gets automatic scope cleanup.

The [resource library](../../stages/resources/README.md) now implements the bounded
component described here. Its reader, ownership checker, cleanup lowering, and
body emitter are Crust code. The C99 seed has no resource-specific change.
The [SQLite witness](../../examples/resources/sqlite/README.md) and
[measurement record](../../benchmarks/resources/README.md) give executable evidence.
This does not establish the persistent intrusive-list observer contract below.

This document makes the [resource rules](language-exploration.md#62-ownership-and-cleanup)
and [language-stage boundary](compiler-extension-experiment.md#ownership-and-unsafe-are-language-stages)
concrete for the current compiler. Those notes contain the wider research.
The [Crust0 specification](../crust0-spec.md) remains the seed contract.

## 1. Select the stage in the source program

Keep the invocation `crust main.crs`. Use the same transfer as the
[hello example](../../examples/hello/main.crs): the root loads an ordinary Crust
library, then calls its build function with the source and current cursor.
The resource compiler reads the remaining bytes in its own grammar.
It can also read separate target files. No launcher option or special package
name is required.

The stage owns reading, resource checks, cleanup lowering, and the call to the
selected backend. Its `resource_build` function has the same role as `c_build`.
The implemented syntax and API are specified in the resource library README.
Do not add new seed keywords to select it.

A stage can instead replace `CrustRun.read` and `CrustRun.execute` for later root
actions. The [reader example](../../examples/reader-switch/main.crs) shows this
route. Install both callbacks in one root action. The runner captures the
callback pair before it executes that action.

The initial root actions still use Crust0 rules. Selecting a new stage does not
check earlier actions again or change their meaning.

Compile the library with the current seed and C backend. Then load its native
code through the existing host interface. All resource decisions must be Crust
code. Existing host allocation, input, diagnostics, and compiler APIs can
remain in use. Do not add a C function that performs the resource analysis.

## 2. Keep the required facts until checking is complete

Use one resource representation per function. It must retain the source
location, declared type, storage identity, scopes, and the operations below.
Separate pass names do not require separate tree copies.

| Operation or fact | Required meaning |
|---|---|
| Initialize an owner | Create one cleanup obligation after successful initialization. |
| Move an owner | Transfer the obligation and make the source unavailable. |
| Borrow a place | Record the root storage, access mode, and lexical end. |
| Register a deferred call | Capture the callee and arguments now; schedule the call for scope exit. |
| Leave a scope | Identify all scopes crossed by fallthrough, return, break, or continue. |
| Adopt or release a raw resource | Apply the explicit unsafe contract and update the obligation. |
| Enter unsafe source | Permit only the operations authorized by that source context. |
| Call a function | Apply its declared parameter modes, result ownership, and escape contract. |

The stage can use its own records or retain side tables with stable node and
binding identities. Do not infer a move from an ordinary assignment after
lowering. Do not infer ownership from the pointer type or a destructor name.

Use this dependency order:

```text
read resource source and publish interfaces
    -> check types, initialization, ownership, and local loans
    -> select cleanup on each normal exit
    -> lower source values and calls to the selected ABI
    -> emit complete backend input
```

Basic type checks and resource checks can share a function walk. Reuse seed
layout and type operations where their contracts apply. A source resource
signature can require richer rules than a seed function signature.
Retain its meaning until the resource check is complete.

Published interfaces contain nominal resource identity, private raw fields,
copy or move mode, parameter access modes, result ownership, and drop rules.
They must contain enough information to check callers without reading callee
bodies. A checked resource may have a scalar representation. That does not
make it copyable in the source language.

Treat source bytes and foreign interfaces as input boundaries. Checked internal
resource operations are trusted input to lowering. The checker and lowering
are part of the selected language's trusted compiler. Editing a checked body
must preserve its facts or require that body to be checked again.

## 3. One cleanup mechanism, with separate ownership checks

Use a compile-time scope stack for both automatic drops and deferred calls.
Each scope has ordered cleanup slots. An exit runs its active slots in reverse
order, then processes each enclosing scope that it leaves.

Reserve an automatic drop slot at the local binding. Successful initialization
activates the obligation. A move makes that binding unavailable. Initialization
of the same binding again reuses its original slot. Assignment first evaluates
the new value, then releases the old live value, then installs the new value.
It does not register a second scope cleanup.

This is a proposed clarification of the earlier notes. They permit a moved
variable to be initialized again, but do not specify its cleanup position.
Keeping the original position gives each binding a fixed scope order.
A conditional assignment cannot reorder the enclosing scope's cleanup.

For example, let a scope declare owner `a`, then register deferred call `d`,
then declare owner `b`. Its exit order is `drop b`, `d`, `drop a`.
Moving `a` away removes its drop from that path. Restoring `a` before an exit
restores its original position after `d`.

The local checker uses these rules from the exploration:

- Each successful resource initialization has one obligation.
- A permitted move transfers that obligation without a user callback.
- A moved value cannot be read, borrowed, or released.
- Resource fields cannot be moved out separately.
- Continuing branches agree on the state of each outer owner.
- Loop back edges restore entry states. All loop exit paths agree.
- A returning branch does not join a continuing branch.
- A returned owner transfers to the caller before other locals are destroyed.

An initialized object with a stable address cannot be relocated. An independent
owning handle for that object can still be movable.

Thus the compiler knows which obligations exist at each exit. It needs no
hidden runtime drop flag for these rules. Dynamic optional ownership uses an
explicit tagged value. The tag is program data with a declared representation.

Cleanup slots are compiler records. They do not require a target runtime table,
reference count, or per-owner header. A statically named deferred function uses
a direct call; it needs no saved function pointer. Emit only the value captures
required by the source semantics. Check this cost in the emitted program.

Use the same scope mechanism for successful owning temporaries. Evaluate
operands and fields from left to right. If a later operation takes an error
exit, release the earlier completed temporaries. The callee gets ownership
only when the call starts. A partially constructed record releases its
initialized fields; it does not run the enclosing drop action.

Drop runs the enclosing action, then resource fields in reverse declaration
order. Drop cannot return a recoverable error, unwind, or publish the object
again. An operation such as checked close or commit reports failure explicitly.
If failure leaves the resource live, its result must retain the owner.
An implicit drop that can encounter a reportable error needs an explicit fatal
policy. It cannot silently discard that error.

Normal exits run cleanup. Abort, process termination, and hardware failure
do not promise it. Foreign unwinding and nonlocal jumps across a live resource
scope are prohibited. These rules require no exception runtime.

### Defer capture

Keep the candidate syntax `defer f(args);` from the exploration. The stage's
reader recognizes it. Arbitrary deferred blocks require no implementation in
this experiment.

Capture the callee and arguments once, from left to right, when execution
reaches the statement. A later assignment to the callee variable or an argument
variable does not change the saved call. Registration completes only after
all captures succeed. Until then, completed owning captures are temporaries.

Copied arguments are local values. Moved arguments transfer ownership into
the cleanup slot. Borrowed arguments retain their loan through the deferred
call. Invocation transfers owning arguments to the callee; the slot must not
release them again. The deferred function returns `unit`. A fallible operation
needs an ordinary wrapper with an explicit error policy.

A deferred exclusive borrow reserves its owner until the call ends. A deferred
borrow cannot outlive its owner. Moving an owner into a deferred call makes
the original variable unavailable immediately. Automatic drop is the way to
keep an owner usable until scope exit.

Each branch or loop body has its own scope. A defer inside a loop runs when
that iteration's scope ends. There is no heap queue or accumulation across
iterations. A branch-local defer runs before the branch joins its parent.

### Local loans

Start with the notes' lexical `read` and `mut` modes. Track the whole root
owner. Shared access prevents mutation, movement, and destruction. Exclusive
access prevents independent access to the same root. Reborrowing reserves
the parent for the inner loan.

Check overlap across all call arguments, including aliases with different
names. A call-only loan lasts for the complete call. Named loans have explicit
scopes. These local views cannot escape into persistent storage.

The strict experiment uses concrete synchronous callbacks for borrowed
results. The [single-origin return proposal](language-exploration.md#64-lexical-borrows)
is a separate comparison if that interface fails the real application test.
Neither form establishes the validity of stored list links.

## 4. What the current APIs permit

This audit records the input APIs at revision `5bd88f0`, before implementation.
The generic Crust reader and C body callback described after the table remove
the corresponding extension barriers. The seed scalar ABI remains unchanged.

| Current component | Consequence for the resource stage |
|---|---|
| [Runner](../source-runner.md) with source, cursor, and ordinary callbacks | Select a new language in the root without a launcher change. |
| [Public syntax, type, and declaration records](../../include/crust0.h) | Construct lowered seed input and preserve source locations. |
| [Seed reader](../../src/read.c) with private lexer and parser | Write the resource reader in Crust. There is no public keyword registration callback. |
| [Seed checker](../../src/check.c) with scalar parameters and scalar or unit results | Define a library ABI lowering for source resource records passed or returned by value. |
| Seed records with ordinary copying and raw field access | Enforce nominal resource modes, private representation, and unsafe adoption in the Crust checker. |
| Structured `CrustStmtKind` without labels or basic blocks | Account for the cost of copying cleanup into several exits. |
| [C backend API](../../stages/c/api.crs) accepting checked seed input | Call `c_backend_build` after lowering and checking that input. |
| `c_program` owning its read/check/build sequence | Use a resource driver. This function has no resource-pass insertion point. |

The implementation adds a [generic reader library](../../stages/reader/README.md)
with four syntax hooks and a [generic complete-body callback](../c-backend.md#custom-function-bodies).
Both are ordinary Crust libraries. The resource driver uses those interfaces.
The C backend's public callback does not require a seed function body and has
no resource-specific operation.

The scalar call restriction applies to all seed functions, not only C imports.
Local records already work. A library can lower source record parameters to
explicit storage pointers and results to caller-provided output storage.
It must specify ownership transfer and initialization on each result path.
Measure copies, stack storage, and calls against the corresponding C ABI.
Do not assume optimization will remove an extra cost.

`CrustDecl.checked` records the seed type check. It is not an ownership proof.
Checking a body again creates new local symbols. Resource facts must not
depend on the identity of those replaced symbols.

Keep original source locations through reading and lowering. A lexical source
translation can be an implementation technique only if it handles strings,
comments, scopes, and all retained resource facts. Text replacement of `defer`
is insufficient.

### Cleanup output size

With `N` live resources and `E` exits, copying every release sequence can emit
`N * E` cleanup operations. This can make a small source file expensive to
compile. Reusing one statement node at several locations also violates the
seed syntax tree's ownership contract.

Measure unique cleanup suffixes and emitted code size. Identical suffixes
with the same continuation can share a cleanup block. A library control-flow
representation and a Crust C emitter can express these blocks as C labels
and branches. The seed needs no resource keyword or general `goto` feature
for such an emitter.

The implemented representation interns equal cleanup suffixes with the same
continuation. Its body emitter writes C labels and branches. The bounded
application and exit-count stress case measure its construction and output.
Sharing does not prove a linear bound for all source control flow.

## 5. Trust and direct intrusive lists

The selected stage must check resource creation, copying, conversion, calls,
and escape. Registering a destructor for a seed record is not enough to enforce
those rules. In particular, safe clients cannot copy a raw field and use it to
construct another owner. Raw acquisition and release need audited contracts.

An unsafe region permits specified operations. It does not disable normal
typing or scheduled cleanup. Generated operations retain their definition's
authorization. Caller code inserted into a generated body retains the caller's
authorization.

Resource checking alone does not establish complete memory safety. The checked
configuration must also enforce initialized reads, bounds, valid tagged access,
and its raw-memory boundary. A custom driver can omit those checks, but then
it cannot claim the checked configuration's guarantees.

For direct intrusive lists, RAII can unlink a node during destruction.
That meets only one part of the [required list contract](language-exploration.md#69-intrusive-lists-with-individual-destruction-and-reuse):

1. Embedded hooks need stable addresses once initialized, including when detached.
2. Aliased link updates need a stated access rule that permits the user algorithm.
3. A saved observer must not access a destroyed object or a new object at its address.

For example, `saved = node; destroy(node); use(saved)` remains invalid after
automatic unlinking. A generation stored only in the freed node cannot be read
to prove that access safe. A checked observer needs valid metadata outside the
released storage, or another complete access-protection contract.

Opt-in checks are permitted. Such a contract must cover observer
assignment, node destruction, storage reuse, subobjects, metadata lifetime,
and callback re-entry. It must expose every added field, check, and allocation.
It must not require a node pool. The application still selects stack, heap,
slab, or other storage and can destroy one unlinked node while the list lives.

Keep the list algorithm in ordinary user code. Detach all hooks before teardown
can call back into a list or expose partially destroyed payload. A non-owning
head detaches its nodes; it does not destroy them. These requirements cannot
be discharged by placing a hidden unchecked list in the compiler library.

The existing [intrusive example](../../examples/intrusive/raw.crs) is a Crust0
raw-pointer example. It supplies a representation and behavior reference.
It does not establish this checked observer contract.

## 6. A bounded implementation experiment

Classify reading, binding, resource checks, and lowering as compiler hot paths.
Use function-local arenas, indexed owner states, a lexical loan stack, and
records of changed states at branches. Do not copy every local's state at every
branch. Publish immutable interfaces before dependent function checks.
Independent bodies can then be checked and lowered in parallel. Source-order
root actions still execute in their declared order.
When using seed APIs, give each worker a separate context and owned function
nodes. Share only published declarations under the `crust_bind` contract.

Functions without resource effects can skip resource-specific analysis after
their types and called interfaces establish that fact. Absence of an ownership
keyword is not sufficient. General initialization and access rules still apply.

Start with one Crust package and one application. Do not build a pass registry,
general effect solver, closure system, or generic container library for it.
Use explicit error branches and concrete result types. A propagation operator
is not required to test cleanup.

Use the [SQLite reader witness](language-exploration.md#101-establish-one-complete-boundary)
already selected in the exploration. It must open a real database, prepare and
step a statement, expose a scoped column view, write the final output, finalize,
and close. Keep the complete connection-to-view ownership boundary.
Compare direct C and C with the same callback interface.

The foreign contracts determine the cleanup states. Open can return a handle
that needs release even on failure. Finalize destroys a statement even when it
returns an evaluation error. Close can fail while leaving a connection alive.
Represent each case explicitly.
[SQLite open](https://www.sqlite.org/c3ref/open.html),
[finalize](https://www.sqlite.org/c3ref/finalize.html),
[close](https://www.sqlite.org/c3ref/close.html).

Column access must retain the row and statement until the view ends. Another
conversion, step, reset, or finalization can invalidate a column pointer.
Preserve the distinction between SQL NULL, an empty BLOB, and allocation
failure. Read the error state before another operation can change it.
[SQLite column access](https://www.sqlite.org/c3ref/column_blob.html).

Use the following checks for the first executable component:

| Case | Required result |
|---|---|
| Nested locals and defers; fallthrough, return, break, continue | One correct reverse cleanup sequence for the scopes exited. |
| Return expression with side effects or an owning result | Evaluate once before cleanup; transfer the result first. |
| Deferred callee and argument reassignment | Invoke the values captured at registration. |
| Failure after an earlier owning operand succeeds | Release each completed temporary once. |
| Moved owner, restored owner, and divergent branch states | Reject invalid access and joins; retain the fixed binding cleanup position. |
| Repeated loop iterations and early exits | No accumulated defer queue or hidden owner-state flag. |
| Overlapping call arguments or an escaping local view | Reject the program with the relevant source locations. |
| Forged owner or foreign release without obligation transfer | Reject the safe program. |
| Real SQLite errors and cleanup errors | Preserve errors and any still-live owner. |
| Increasing live resources and identical early exits | Report analysis work, cleanup graph size, output bytes, and elapsed time. |

Freeze the source and direct C baseline before implementation measurements.
Include root setup, stage loading and execution, parsing, checks, cleanup,
ABI lowering, and C text output. Record checking and complete handoff separately.
Exclude final target GCC compilation and linking from these frontend timings.
Report preparation of the native stage as a separate explicit input cost.
An unprepared custom stage cannot be counted as free.

Use the exploration's [timing boundary and pass rule](language-exploration.md#103-define-the-timing-boundary).
Meet the single-worker C-speed gate before using parallel execution as evidence.
Check final runtime output, representation, copies, allocations, and call cost.
The current seed's timing results are not measurements of this resource stage.

Passing the SQLite boundary authorizes assessment of that component only.
Acceptance of the checked language also requires the
[two-hook list witness](language-exploration.md#102-intrusive-list-witness),
with a complete observer contract, individual destruction, exact-address reuse,
and safe user-written list operations. Fix a failed contract or measurement
within the bounded experiment before extending the language.
