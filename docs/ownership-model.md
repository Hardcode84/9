<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership stage contract

The ownership stage checks owners, loans, storage fields, and function
interfaces. It uses the public reader and AST APIs. It does not change the
C99 core. The [tutorial](ownership.md) introduces the source notation.

This document describes the implemented checker. Its graph checks still use
Z3. The [replacement design](ownership-design.md) uses bounded local rules and
an explicitly trusted container implementation behind a checked API. It is not
implemented. Keep the existing checks until the replacement passes its stated
gate. Removing the solver call does not establish safe destruction.

## Owners and loans

A `resource` declaration supplies a cleanup function. A record can own resource
fields. `owns(field)` makes a scalar field own a native resource. The field
can be an integer or an opaque pointer. `owns(field: storage)` also grants
ownership of the allocation addressed by that pointer. `move` transfers an
owner. A move does not copy the destruction duty.

`read T` lends shared access. `mut T` lends exclusive access. The stage rejects
conflicting loans, reads of moved values, and destruction through a borrower.
A returned view uses `from parameter.field` to identify the storage that keeps
it valid. The caller retains that loan for the result's scope.

Moving an owned field out of published storage requires reclaim access and
proof that no surviving reference can observe the incomplete containing record.
The record must be detached before that transfer. The allocation remains owned;
only access through retained references ends. Owned paths use the owner and
initialization rules separately from the set of published objects.

A retained reference gives access to an object. It does not grant ownership of
that object's resource fields. To transfer those fields, use an ownership
origin. A mutable loan of a resource also requires an ownership origin.
A cursor can lend a scalar payload field without acquiring its containing
object's destruction duty.

## Native resources

Ownership and representation are separate. An owned integer is not copyable
because its representation is an integer. An owned opaque pointer does not
permit memory access because its representation is a pointer. A record can
contain resources by value. Those fields use their resource type's cleanup.

```crust
resource File { fd: i32; } owns(fd = -1i32) drop file_drop;
extern fn duplicate(fd: i32) -> i32
    foreign(read fd: File.fd, acquire File.fd) = "dup";
extern fn close_fd(fd: i32) -> i32 foreign(move fd: File.fd) = "close";
```

The field declaration identifies a resource kind. Two fields with the same
integer type do not describe the same resource kind. Nest an existing resource
type to reuse its kind and cleanup. The optional `= VALUE` clause gives the
invalid representation. It must be a representable integer literal or a typed
null literal. Without this clause, acquisition promises a valid resource.

A foreign resource contract has independent argument and result effects:

| Effect | Contract |
| --- | --- |
| `acquire Type.field` | Return a new owner, or the declared invalid value |
| `read arg: Type.field` | Use the resource during the call without changing it or retaining access |
| `mut arg: Type.field` | Use the resource exclusively during the call without consuming it or retaining access |
| `move arg: Type.field` | Consume an explicitly moved owner, on every return path |

The raw ABI type must equal the field's type. An unannotated argument must be
an ordinary scalar. An unannotated result must be a scalar, not a pointer.
The existing allocation interfaces add storage extent and initialization
contracts. They cannot acquire or release opaque native resources.

These declarations are trusted foreign boundaries. The native implementation
must establish new ownership on successful acquisition and obey its declared
effects. The checker cannot verify an external implementation. Declaring a
native function incorrectly can invalidate the guarantee. A `move` effect ends
ownership even when the native call reports an error. An API that retains a
resource on error needs a different contract; this unconditional effect cannot
describe that API.

An acquisition result is affine even before the failure test. Compare it with
its declared invalid literal using `==` or `!=` before borrowed use or
consumption. The success branch permits those actions. The failure branch has
no cleanup duty. Moving the result into its declared owned field preserves
these facts. A destructor can test the field and consume it on success.
Neither branch needs a runtime ownership flag.

The checker rejects raw-value fabrication, duplicate owners, arithmetic or
casts that remove ownership, unannotated calls with owned arguments, use after
consumption, and conflicting native argument borrows. Borrow the containing
resource with `read` or `mut`; a raw owned field cannot become a scalar loan.
Pass or return the resource wrapper across ordinary source function boundaries.
The current scalar function types do not declare a native resource kind.

Owned native fields need no storage domain. A domain is needed when the program
also declares persistent storage references or allocation ownership. A resource
without a domain can be embedded in a record that has a domain. Function
bodies use the field and function declarations. Imported bodyless interfaces
retain the same contracts. An ordinary mutable call can replace an owned field;
the caller must check its invalid value again. Loop backedges must preserve
initialized owners and any validity required at loop entry.

The [native resource example](../examples/ownership-basics/handles.crs) uses
POSIX descriptors and opaque C streams. Local checks need no solver. Native
arguments retain their integer or pointer ABI. Moves and resource validity facts
have no runtime representation. The emitted cleanup consists of ordinary calls
and the explicit failure tests in the source.

## Stored views

An ordinary record can contain `read T` or `mut T` fields. `T` must be a scalar
or record type. Such a record holds scoped loans; it does not own their targets.
Value fields can contain other view records. A view record cannot be a resource
or belong to a storage domain, including through a containing value record.
Persistent domain references use the storage interfaces below.

```crust
record Editing { value: mut i64; }
fn editing_new(value: mut i64) -> Editing from value {
    return make Editing { value: mut value };
}
fn editing_set(view: mut Editing, value: i64) -> unit { view.value = value; }
```

Field access reads or writes the borrowed target. It does not replace the
stored reference. A shared loan of the containing record permits only reads,
even when the field declares `mut`. A view record is affine: use `move` to
transfer it. This rule also applies to records that contain only shared loans.
Scope exit, `drop`, or a consuming call ends its held loans without destroying
the borrowed storage. Outstanding reborrows still prevent conflicting access.
The record cannot move into a scope that outlives any held loan.

A returned view record requires `from parameter.path`, with a borrowed source
parameter. Every borrowed field in the result must refer to that exact storage
path and derive from its loan. A mutable result field requires a mutable source.
The path can pass through stored view fields. The caller reconstructs the result
loans from this interface, including for a bodyless imported function.

A function cannot replace a view record through a borrowed parameter. Its
signature has no contract to replace stored origins. Construct a new result
with a declared origin, then consume or drop the old local view. Results that
contain loans from different input paths require separate results or calls;
one `from` path cannot describe those independent origins.

Basic view checks use local owner and loan facts without a solver. Each stored
loan lowers to one ordinary pointer. View-only records need no generated
cleanup calls or runtime lifetime state. The [stored-view example](../examples/ownership-basics/views.crs)
checks native behavior, moves, reborrows, and pointer layout.

## Storage interfaces

A domain declares the complete set of record types whose storage it governs:

```crust
domain Graph(Node, Owner);
record Node { next: *Node; value: i64; }
    domain(Graph) references(next);
resource Owner { node: *Node; }
    domain(Graph) owns(node: storage) drop owner_drop;
```

`references` declares non-owning pointer fields. Each target must have a record
type in the same domain. The pointer representation is unchanged. A domain is
an access boundary; it does not select an allocator.

The type list is closed. Every record with that domain must appear in the list.
An imported interface includes this declaration. A client cannot add a new
storage type to that interface without changing and checking the interface.
This makes every possible retained reference field visible at the function
boundary. The checker does not inspect callers or search function bodies for
possible references.

Allocated objects have separate owners. Stable stack objects can also belong
to a domain. Publication makes their address fixed. The checker rejects a move
or copy of published storage, including a move of its containing record.

## Access

| Contract | Permission |
| --- | --- |
| `access(read, D)` | Read initialized storage in `D` |
| `access(edit, D)` | Read and change storage in `D` |
| `access(reclaim, D)` | Construct and destroy storage in `D` |

A function can call an interface that requires the same or weaker permission.
`read D { ... }` and `edit D { ... }` reduce the current permission for a scope.
They cannot acquire permission that the function does not have.

A local pointer into a domain is a cursor. It cannot escape its access scope.
Reclamation excludes active domain cursors and payload loans. Thus a cursor
cannot remain usable across the destruction and reuse of its target's storage.
The rule needs no runtime generation number or allocation registry.

## Field conditions

A record can state conditions with ordinary typed expressions:

```crust
domain Links(Entry);
record Entry { peer: *Entry; }
    domain(Links) references(peer)
    invariant((*self).peer == null(*Entry) || (*(*self).peer).peer == self);
```

`self` denotes the current object. Conditions can use field paths, pointer
and scalar comparisons, Boolean operators, null, and scalar literals.
Short-circuit operators guard the validity of the right operand. Conditions
cannot call functions, mutate storage, allocate, or contain user solver code.
Field maps cover types with `references` or `invariant`, and reference target
types. Scalar-field reads outside those maps have unknown values in the proof;
the checker does not retain a value that another alias could change.

For every published object, the checker requires these facts:

1. Its fields are initialized.
2. Each retained pointer is null or refers to live storage of the declared type.
3. Each declared `invariant` is true.

The condition applies to every object of the declared type, including objects
not named by local variables. Functions can temporarily break a condition while
they update fields. They must restore the complete conditions before an ordinary
call, a loop boundary, or return. An observer cannot run during a partial update.

The stage has no rule for a particular field name, pointer pair, or container.
The same field-expression checks apply to an index, a parent reference, or a
list node. The conditions that each data structure needs belong in its types
and function interfaces.

## Function conditions and changed fields

```crust
fn clear(entry: *Entry) -> unit access(edit, Links)
    modifies(Entry.peer)
    requires(entry != null(*Entry))
    ensures((*entry).peer == null(*Entry)) {
    var peer: *Entry = (*entry).peer;
    if peer != null(*Entry) { (*peer).peer = null(*Entry); }
    (*entry).peer = null(*Entry);
}
```

`requires` states a caller obligation. `ensures` states a condition established
by the body. Parameter names in conditions denote the supplied argument values.
Field reads use the state at the checked boundary. Assigning a local parameter
does not change that condition binding. `modifies(Type.field, ...)` names the
field classes the function can change. This example permits changes to `peer`
on any `Entry` in the domain.
An empty `modifies()` clause permits no domain field changes. Without a clause,
an edit or reclaim interface permits all domain fields to change.

The checker verifies direct writes and callee write contracts against that
list. At a call, it checks the precondition, forgets the old values of permitted
fields, and uses the verified postcondition and restored type conditions.
It does not execute or expand the callee body. Unchanged field classes retain
their values.

A function's implementation is checked even when no other function calls it.
An external interface needs a verified library receipt, or an explicit foreign
allocation, release, scalar, or native resource contract. Copying interface text
does not make an external implementation trusted.

## Construction and destruction

`initializes(parameter)` identifies unpublished output storage. A constructor
must initialize every field and establish the record conditions before return.
The caller must supply suitable checked storage. It cannot use this contract
to replace a published object. A nullable allocation still needs a null test
before a constructor that requires a non-null pointer.

An owner can publish an allocation when it transfers it into an owned field.
An ordinary pointer or borrow argument must also satisfy its storage type before
the callee can use it. This checks initialization at the boundary, including
construction done directly in the allocation's final storage.

Destruction has one retained-reference rule: no surviving declared reference
field may point into the storage being destroyed. The query covers each field
in the closed domain schema and an arbitrary live source object. References
inside the same retiring allocation do not prevent its destruction. Local
cursors and loans have separate lifetime checks.

A resource destructor must consume each present owned field. Embedded resources
retain their declared cleanup order. Allocation failure paths must discharge
all owners that were successfully constructed. The checker adds no runtime
cleanup flags.

## Local proof and loops

The owner and loan analysis follows local control flow. Pointer field conditions
use symbolic field maps and a solver. A successful obligation requires an
UNSAT result for its negation. A timeout, unknown result, or malformed condition
is an error. Each function has a separate solver context. Queries reuse its
declarations; each query scopes its assumptions so that one path cannot supply
premises to another. The context is released after the function check.

Each function starts from its published type and function contracts. Heap
conditions are instantiated at symbolic addresses; omitted instances weaken
the premises. They cannot turn a failed proof into a successful proof.
A destruction query uses an arbitrary surviving source address, not a list of
allocations observed in a test run.

Loops use an inductive check. The checker forgets local scalar values, including
scalar loan targets, and widens assigned domain cursors. A helper or a mutable
loan can change scalar storage without a direct assignment to its name.
The entry state does not retain those scalar values as loop invariants. The
checker checks the body and the backedge under that state. It does not choose
a maximum list length or expand recursive calls.

A loop can replace a local resource record. The record must be initialized and
movable on entry and at each backedge. The checker uses its declared type as
the invariant. It forgets the old owned targets and their null or native-handle
validity facts. Test those values again before use. For example:

```crust
while chain.node != null(*Node) {
    chain = chain_pop(move chain);
}
```

The callee consumes the old chain and returns an initialized replacement. It
is checked from its own interface. The loop needs no extra annotation. A
replacement cannot overwrite a live owner, leave a moved field uninitialized,
escape a loan, or move address-stable storage. Records with stored loans keep
their existing origin contracts and cannot use this replacement rule.

Other outer storage keeps its identity, initialization, and loan origins at
the backedge. This includes fields reached through an owner or a borrowed
record, not only the outer variable. A field condition must also hold at the
boundary. An early return checks function exit and cleanup; it has no backedge.
These checks add no runtime state.

## Output and verification

Ownership data exists only during compilation. Field maps, access permissions,
proof identities, and conditions do not appear in emitted code. The erasure
check emits C before and after ownership verification and compares the output.
RAII cleanup remains ordinary generated calls and follows the resource contract.

The intrusive tutorial uses a full typed node as each sentinel. That is a
visible representation choice in the source, not hidden ownership metadata.
Its two sets of links support separate memberships. The example tests removal,
individual release, allocation reuse, payload access, and head cleanup while
other owners remain live.

`make check-ownership` exercises the native programs and rejected programs.
`make check-ownership-imports` checks bodyless provider interfaces and their
artifact receipts. `make check-ownership-alloc` checks allocation failure paths
in the compiler stage. Z3 is needed for the selected field-condition checks.
