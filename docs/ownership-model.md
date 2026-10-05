<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership stage contract

The stage uses finite body-local ownership, initialization, loan, and access
facts. Each body uses function and field contracts. All ownership rules are
implemented in Crust. Read the [tutorial](ownership.md) for examples and the
[design](ownership-design.md) for the implementation boundary.

## Owners and loans

`resource` adds a destructor. `move` transfers its cleanup duty. `read T` lends
shared access; `mut T` lends exclusive access. Ordinary values remain copyable.
The checker rejects use after move, duplicate owners, uninitialized reads,
conflicting loans, and destruction through a borrower. A local view ends after
its last use, at a statement boundary, once its child loans and deferred captures
also end. This includes stored views and pointers obtained through a named loan.
Explicit `drop` can end a local view; all child loans and deferred uses must have
ended. It invalidates the binding without destroying the borrowed value or
emitting code. Borrowed parameters cannot be dropped.
Reborrows prevent conflicting use of their parent.

Liveness joins the uses from both branches. Each branch can end a view after
its own last use. An outer view used inside a loop remains live on its backedge;
a view declared inside the loop can end in that iteration. Loop exits use the
uses after the loop. Parameters retain their declared loan contracts. Resource
cleanup keeps its scope order.

Direct fields of an ordinary record can be borrowed separately. A loan of the
whole record covers all its fields. Moving, replacing, or destroying a record
requires every conflicting field loan to have ended.

A plain record can be copied at a value boundary. Its copy has independent
storage and loan state. An explicit `move` of a movable record consumes the
old binding, including when that record needs no cleanup.

Taking a raw address of an owner or an inline record inside it fixes that
storage for the rest of its lifetime. An address taken through a loan follows
that loan's lifetime instead. Taking an address inside a heap allocation keeps
the allocation in place while permitting movement of its separate owning handle.

Passing an owner by value ends access through its old raw aliases when the call
runs. A mutable call can replace owned allocations. Raw aliases to allocations
that its contract permits it to replace also expire. Obtain new pointers from
the current owner after the call. Returned owners and views supply access
through their declared contracts.
A deferred call keeps its captured owner until invocation.

Automatic cleanup and explicit `drop` require the same destructor permission.
Checked code cannot call a destructor function directly or defer it. Use `drop`
to consume an owner, or defer a helper that takes the owner by value.
Resources drop in reverse declaration order. Destructors run before embedded
resource fields drop, in reverse field order. A destructor must consume its
owned native fields and leave embedded resources initialized for cleanup.
A trap ends the process; it does not unwind resources.

`defer call(...)` captures arguments at registration and invokes a unit-returning
source function at scope exit. Moves transfer owners into the capture; borrows
remain live until the call runs. Deferred calls and local cleanup run in reverse
registration order. The checker applies mutable effects when the call runs.
In-place construction cannot be deferred. Wrap a foreign function in a checked
unit-returning source function before deferring it. This keeps native acquisition
and consumption in the ordinary checked call path.

## Generic records and functions

The optional [generic ownership stage](../stages/generics/ownership/README.md)
accepts declaration-local parameters and explicit type arguments:

```crust
fn transfer!(Value)(value: Value) -> Value { return move value; }
```

Each parameter has one contract: a sized movable record, closed ownership,
and complete cleanup without domain access. The checker follows nested fields
and owned storage. Native owned handles end those paths. Stored loans, opaque
storage, stable or scoped values, and domain-bound records fail that contract.

The body is checked once with distinct symbolic identities for its parameters.
Parameter values are affine. Transfers require `move`; shared and exclusive
loans use the ordinary rules. A parameter exposes no fields or constructors.
Concrete type arguments are validated before specialization receives a checked
body receipt. Each specialization still receives seed type and layout checks
and concrete cleanup generation. Trusted definitions retain their separate
root-selected status.

See the [generic container tutorial](../examples/generics/ownership/README.md)
for plain and resource payloads, generic destructors, owner-based loans, and
independent imports. The standalone ownership entry point retains its ordinary
record syntax; the combined entry point selects the generic reader too.

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

Owned native fields and exclusive allocation trees need no storage domain.
Use a domain for a closed boundary with persistent internal aliases. A resource
without a domain can be embedded in a record that has a domain. Function
bodies use the field and function declarations. Imported bodyless interfaces
retain the same contracts. An ordinary mutable call can replace an owned field;
the caller must check its invalid value again. Loop backedges must preserve
initialized owners and any validity required at loop entry.

The [native resource example](../examples/ownership-basics/handles.crs) uses
POSIX descriptors and opaque C streams. Native arguments retain their integer
or pointer ABI. Moves and resource validity facts have no runtime representation. The emitted cleanup consists of ordinary calls
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
Last use, scope exit, `drop`, or a consuming call ends its held loans without
destroying the borrowed storage. Outstanding reborrows still prevent conflicting
access. The record cannot move into a scope that outlives any held loan.

A returned view or view record requires a finite origin list:
`from parameter.path, other.path`. Each parameter must be borrowed. Each
returned loan must derive from a listed path. All listed paths must have the
borrowed target type. A mutable result requires mutable source parameters.
Paths can pass through stored view fields.

The caller retains a result loan against every listed source. A function that
forwards that result must list every possible origin. Each borrowed field of a
returned view record uses the same origin list. Separate factory calls allow
independent origins for separate fields. Two mutable result fields with this
shared origin set conflict at the call. Return those fields through separate
contracts to preserve their independent sources.

A result with several origins identifies one selected target. The checker uses
an initialized target with unknown field values. A successful call does not
establish a null or native-handle validity fact for each alternative. A mutable
result invalidates those facts for all its possible targets. Restore moved
fields before the selected loan ends. The caller can check each original field
again after the result loan ends.

A function cannot replace a view record through a borrowed parameter. Its
signature has no contract to replace stored origins. Construct a new result
with declared origins, then consume or drop the old local view.

The [returned-origin example](../examples/ownership-basics/origins.crs) selects
between two inputs, forwards the result, and returns a view record. The
[index tutorial](../examples/ownership-index/README.md) combines independent
loans in a checked local record. These operations retain every source loan
until its dependent views end. Bodyless library interfaces carry the complete
origin list. Their receipts cover the interface bytes and the checker inputs.

View checks use local owner and loan facts. Each stored loan lowers to one
ordinary pointer. View-only records need no generated
cleanup calls or runtime lifetime state. The [stored-view example](../examples/ownership-basics/views.crs)
checks native behavior, moves, reborrows, and pointer layout.


## Opaque storage and explicit trust

The root selects trusted declarations with `os_trust(stage, declaration)`, or
supplies captured trusted sources to `ownership_program`. Source annotations
cannot grant trust. Every selected body still passes syntax, type, and resource
lowering checks. Its pointer algorithm is not checked by the ownership pass.
All other bodies are checked from their own source and published interfaces.

```crust
domain Graph(Node, Owner, Head, Cursor);
record Node { prev: *Node; next: *Node; value: i64; } opaque;
resource Owner { node: *Node; } opaque drop owner_drop;
resource Head { node: Node; } opaque stable drop head_drop;
record Cursor { node: *Node; } opaque scoped;
```

Opaque fields are private to the selected implementation. Checked clients
cannot project, construct, cast, or duplicate the representation. `stable`
requires a resource destructor. After in-place construction, its storage cannot
move. `scoped` requires a domain and forbids a destructor or stable storage.
It produces an affine value whose origin is the current read or edit scope.
The stage has no built-in cursor, list, tree, membership, or navigation rule.

A domain declaration lists all types in one retention boundary. Each type can
belong to one domain. The list determines membership, including in imported
interfaces. Types can appear before or after the domain declaration. A missing
type, repeated member, or membership in two domains is an error. Only the root
can admit opaque types and their implementations. Outside observers must
retain ordinary loans.

A trusted implementation must keep internal references valid, transfer each
owner once, obey access effects, and remove every admitted internal reference
before storage retirement. Node retirement must handle all memberships. Head
retirement must detach survivors. A missing pointer store in a trusted body is
a library defect, not a compiler rejection. Native tests and sanitizers test
these bodies separately from checked-client rejection tests.

## Domain instances and access

`domain Graph { ... }` introduces a fresh static identity and reclamation
permission. Values from distinct instances cannot mix or escape their instance
scope. There is no runtime domain value, allocator, lock, or counter.

`access(MODE, Graph)` on a helper is an abstract domain interface. A call binds
it to the caller's current instance. The body is checked once, with no caller
inspection or specialization. A function with that interface can return an
owner in the same domain; it cannot return an owner from a fresh nested instance.
Only one domain instance is accessible at a time in this profile. End a nested
instance scope to restore the outer permission.

| Mode | Permission |
| --- | --- |
| `read` | Read published storage; update an opaque local handle only through declared operations. |
| `edit` | Change links or payload; preserve storage lifetime and address. |
| `reclaim` | Construct and retire storage; no outstanding domain views. |

`read Graph { ... }` and `edit Graph { ... }` narrow existing permission.
They cannot regain stronger permission. Cleanup inside either scope cannot
invoke a reclamation destructor. Put its owner outside that access scope, or
consume it before entering the scope. Cleanup after scope exit uses the restored
outer permission only after scoped views have ended.

An opaque scoped result retains its access scope. It does not itself borrow
payload access. A library operation can navigate or edit links while cursors
exist. A returned payload `read` or `mut` view separately borrows the domain's
access permission and its declared origin. Potential aliases in one domain are
conservative: a mutable payload view blocks other read or edit calls unless
they receive that view's authority. Shared payload loans block conflicting edits.
Neither cursor bits nor address reuse can create a new checked lifetime.

A direct borrow of an opaque resource handle protects that handle's storage.
It can be forwarded to a reclamation call. This permits checked helpers such
as `remove(index: mut Index) access(reclaim, Symbols)`. The checker still
rejects conflicting handle access and destruction through the borrower.
Interior views and payload loans remain subject to the domain restrictions
above; they cannot be treated as independent owner handles.

## In-place construction and transparent storage

`initializes(parameter)` promises complete initialization on normal return.
The parameter must point to a record in the function's declared domain.
A client supplies `&local` for uninitialized final storage. Each output is
reserved exclusively while arguments are checked. It cannot replace a live
resource. The resource lowerer schedules cleanup only after construction.
There is no implicit zero fill or runtime initialization flag.

A checked wrapper can forward an output parameter when its own interface also
states `initializes`. The wrapper must initialize the output before each return.
Opaque constructors and destructors require root-selected trust. Transparent
owned allocations use `owns(field: storage)`, explicit allocation and null
checks, field initialization, and release. See the [heap example](../examples/ownership-basics/heap.crs).
An exclusive allocation tree needs no domain. Its record fields must be
transparent and domain-free, including embedded value records. They can hold
native resources and further owned allocations. They cannot hold borrowed
fields: an owning result has no contract for those stored loan origins.
Each owned pointer edge uses its declared target type. The checker validates
these declarations locally, including at independent library boundaries.
Loans protect the specific owner tree; another independent owner can be released.
The allocation argument must be `sizeof(Record)`, optionally in parentheses.
This identifies the record whose initialization and field ownership are checked.
A byte count or scalar type supplies no record contract. Direct allocation
inside a loop is rejected; call a function that returns an owning resource.
Transparent records cannot store non-owning raw pointers. Use view fields for
ordinary borrows or an opaque interface for persistent internal aliases.

The stage rejects Boolean heap contracts (`invariant`, `requires`, `ensures`)
and raw pointer arguments without an initialization interface. `modifies`
can restrict field classes written by a checked function; it does not assert
heap relationships. A failed or unsupported check never selects trust.

## Local flow and loops

Expressions evaluate their operands and call arguments once, in source order.
An argument loan stays active until its call returns. A returned view retains
its declared source loan. A deferred call retains its captured loans until
execution. Output construction reserves storage while its arguments evaluate.
The call checks reclamation permission after argument evaluation.

Conditions use the effects of that evaluation. `&&` evaluates its right operand
only when the left is true; `||` evaluates it only when the left is false.
The checker joins the evaluated and skipped paths. Condition temporaries end
before the selected body starts. A validity test applies to the value tested;
later replacement of an owner requires a new test.

Continuing branches must agree on owner consumption and loan origins. Scalar
initialization uses intersection. No drop flags reconcile different owner
states. Initialize or consume owners explicitly in both branches.

The checker checks a loop condition and body from their local type state.
The condition executes before each iteration and can call checked functions.
Continuing backedges must restore the state required before the condition,
including initialization, ownership, and loan origins. Movable
owner records can be replaced with new initialized owners. The checker forgets
old allocation and native-handle validity facts; check them again before use.
Raw aliases to replaced owners expire at the loop boundary. Read replacement
storage through the current owner.
`continue` follows the backedge rule. `break` joins the states after the loop,
including the state where the condition is false. These exits must agree on
owner consumption and loan origins. A scalar is initialized after the loop only
if each exit initializes it. For `while true`, only `break` paths reach the next
statement. Parentheses around `true` preserve this rule.

Both jumps leave inner scopes in order. Each scope runs deferred calls, drops
owners, and ends local loans in reverse order. Cleanup must obey the access
permission of its own scope. Nested loops send each jump to the nearest loop.

The checker uses one abstract iteration. It does not solve arithmetic conditions
or search heap graphs. An opaque cursor can advance through a declared operation.
Raw pointer merges are rejected.

## Independent libraries

`ownership_publish(request, directory, receipt, trusted, count)` checks the
provider's untrusted bodies and publishes its interface and native object.
`ownership_import_program(request, imports)` checks clients against those
interfaces and links captured objects. No provider body is read at import.

`OwnershipLibrary` retains the artifact path, digest, and explicit `trusted`
status. The receipt binds interface bytes, object bytes, selected trust, and
checker images. The root must preserve all three fields. A copied interface or
an artifact with a different trust flag cannot authorize unchecked bodies.
Publication requires a target source or root source in the request, in addition
to any separately supplied trusted implementation sources.
Imported record domains are fixed by the captured provider interface. A client
or a second provider cannot assign those records to another domain.

## Output and verification

Verification does not change the emitted C or native symbol table. Loans and
permissions add no runtime checks, tags, counters, ownership chains, or drop
flags. Cleanup and the library's explicit pointer operations remain ordinary
code. The pointer representation is unchanged before optimization.

Run `make check-ownership check-ownership-imports check-ownership-alloc`.
The checks cover client rejection, native containers, address reuse, erasure,
source-free imports, receipt tampering, and compiler allocation failures.
Use `--sanitize` with the ownership Python tests for native ASan and UBSan.
The [benchmark](../benchmarks/ownership/README.md) measures a compiled stage in
fresh application builds and excludes target GCC compilation and linking.
