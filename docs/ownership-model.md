<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership stage contract

The stage uses finite body-local ownership, initialization, loan, and access
facts. It has no graph solver or whole-program analysis. All rules are in
Crust. The C99 core has no ownership policy. Read the [tutorial](ownership.md)
for examples and the [design](ownership-design.md) for the implementation boundary.

## Owners and loans

`resource` adds a destructor. `move` transfers its cleanup duty. `read T` lends
shared access; `mut T` lends exclusive access. Ordinary values remain copyable.
The checker rejects use after move, duplicate owners, uninitialized reads,
conflicting loans, and destruction through a borrower. Named loans last to the
end of their lexical scope. Reborrows prevent conflicting use of their parent.

Automatic cleanup and explicit `drop` require the same destructor permission.
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


## Opaque storage and explicit trust

The root selects trusted declarations with `os_trust(stage, declaration)`, or
supplies captured trusted sources to `ownership_program`. Source annotations
cannot grant trust. Every selected body still passes syntax, type, and resource
lowering checks. Its pointer algorithm is not checked by the ownership pass.
All other bodies are checked from their own source and published interfaces.

```crust
domain Graph(Node, Owner, Head, Cursor);
record Node { prev: *Node; next: *Node; value: i64; } opaque domain(Graph);
resource Owner { node: *Node; } opaque domain(Graph) drop owner_drop;
resource Head { node: Node; } opaque stable domain(Graph) drop head_drop;
record Cursor { node: *Node; } opaque scoped domain(Graph);
```

Opaque fields are private to the selected implementation. Checked clients
cannot project, construct, cast, or duplicate the representation. `stable`
requires a resource destructor. After in-place construction, its storage cannot
move. `scoped` requires a domain and forbids a destructor or stable storage.
It produces an affine value whose origin is the current read or edit scope.
The stage has no built-in cursor, list, tree, membership, or navigation rule.

A domain lists the types in one retention boundary. Only the root can admit
opaque types and their implementations. Merely naming a domain cannot add a
persistent observer. Outside observers must retain ordinary loans.

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
Transparent records cannot store non-owning raw pointers. Use view fields for
ordinary borrows or an opaque interface for persistent internal aliases.

The stage rejects Boolean heap contracts (`invariant`, `requires`, `ensures`)
and raw pointer arguments without an initialization interface. `modifies`
can restrict field classes written by a checked function; it does not assert
heap relationships. A failed or unsupported check never selects trust.

## Local flow and loops

Continuing branches must agree on owner consumption and loan origins. Scalar
initialization uses intersection. No drop flags reconcile different owner
states. Initialize or consume owners explicitly in both branches.

The checker checks one loop body from its declared local type state. Continuing
backedges must preserve initialization, ownership, and loan origins. Movable
owner records can be replaced with new initialized owners. The checker forgets
old allocation and native-handle validity facts; check them again before use.
It does not unroll iterations, solve arithmetic conditions, or search heap graphs.
An opaque cursor can advance through a declared operation. Raw pointer merges
are rejected. `break` and `continue` have no local-state join implementation in
this profile and are rejected; use a loop condition or return.

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
