<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership stage contract

The ownership stage checks owners, loans, storage fields, and function
interfaces. It uses the public reader and AST APIs. It does not change the
C99 core. The [tutorial](ownership.md) introduces the source notation.

## Owners and loans

A `resource` declaration supplies a cleanup function. A record can own resource
fields. `owns(field)` makes a pointer field the owner of its allocation.
`move` transfers that owner. A move does not copy the destruction duty.

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

## Storage interfaces

A domain declares the complete set of record types whose storage it governs:

```crust
domain Graph(Node, Owner);
record Node { next: *Node; value: i64; }
    domain(Graph) references(next);
resource Owner { node: *Node; }
    domain(Graph) owns(node) drop owner_drop;
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
allocation, release, or scalar contract. Copying interface text does not make
an external implementation trusted.

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

A resource destructor must consume each owned pointer field. Embedded resources
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

Loops use an inductive check. The checker forgets assigned scalar values and
widens assigned domain cursors. It checks the body and the backedge under that
state. It does not choose a maximum list length or expand recursive calls.
Owner identity and loan lifetimes must remain valid across the backedge.

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
