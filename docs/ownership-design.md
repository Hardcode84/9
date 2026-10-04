<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership checker design

This design is implemented by the optional ownership stage. The
[stage contract](ownership-model.md) defines its accepted syntax and rejection
rules. The [ownership tutorial](ownership.md) explains them through programs
that you can build and run.

Use local ownership checks for application code. Permit an explicitly trusted
implementation for containers whose internal pointers require stronger reasoning.
The trusted implementation must preserve the guarantees of its checked API.
A defect in that implementation can cause memory errors. The compiler does not
prove its pointer algorithms correct.

The stage is written in Crust. It reads annotations, checks each body against
declared interfaces, and passes cleanup plans to the C backend.

## 1. The checked language

The checked interface uses these concepts:

| Concept | Rule |
| --- | --- |
| Owner | One value has the cleanup duty. Transfer it with `move`. |
| Resource field | `owns(field)` applies to a native resource, including an integer handle. Storage ownership also grants access to an allocation. |
| Shared loan | `read` permits reads and prevents conflicting changes and destruction. |
| Exclusive loan | `mut` permits changes and prevents conflicting access. |
| Stored or returned loan | Local facts retain origins; returned views declare one exact input path. |
| Cleanup | Scope exit, explicit `drop`, and `defer` use the same ownership and access checks as an ordinary call. |
| Stable storage | After construction, the value cannot move or be overwritten before its destructor completes. Its owning pointer can move. |
| Opaque resource | Clients can use its exported operations. They cannot inspect, construct, copy, cast, or overwrite its representation. |

Plain values remain copyable. Resource and view records remain affine. A view
record holds loans, not cleanup authority over their targets. Reborrowing a
mutable view temporarily suspends use of the parent view.

Native resource ownership does not imply pointer semantics. An owned file
descriptor can be borrowed, transferred, and closed with the same rules as an
owned opaque pointer. The declared foreign interface supplies the acquisition
and release contract. Only a storage owner permits memory access.

An initialized owner must be consumed, returned, or cleaned up on each path.
The stage does not add hidden drop flags. Continuing branches must agree on
which resource places are initialized. Put cleanup or reinitialization in the
branches when they would otherwise disagree. Ordinary scalar initialization
uses intersection at a join.

Loans have lexical scopes. Explicit `drop` of a view ends its loan. The target
remains borrowed until the view's scope ends or the view is consumed, even
after its last read. Use `drop` or an inner block to end a local view before
the surrounding scope. Explicit ending requires all child loans to have ended.
Borrowed parameters cannot be dropped.

## 2. Function boundaries

An interface contains types, ownership modes, loan origins, initialization
outputs, access effects, and cleanup requirements. These are finite type and
effect facts. They are not Boolean formulas about arbitrary objects.

A returned view declares one exact input path with `from parameter.path`.
Every borrowed field of a returned view record must derive from that path.
Local view records can combine loans from several inputs. A function cannot
return that combination through one `from` path or replace stored origins
through a borrowed parameter. Return single-origin views separately, then
combine them in the caller. To change a local view's origin, drop that view
and assign a new result.

The [one-way index](../examples/ownership-index/README.md) checks this boundary:
a helper compares a selected payload with a separate caller input through a
local view record. The [stored-view example](../examples/ownership-basics/views.crs)
combines two single-origin factory results and replaces a local view after
ending its old loan. Both forms preserve the origins declared at function
boundaries.

Borrowed storage must be initialized again before return. A mutable call
invalidates scalar facts for its declared writable places. Native-handle
validity facts must also be rechecked after a call that can replace the handle.
The stage can recognize a direct invalid-sentinel test; it does not prove
arithmetic conditions to recover ownership or validity.

A destructor's required permission is part of the resource type. Implicit
cleanup requires the same permission as explicit `drop` at that point.
Check generated cleanup paths as well as written calls. Deferred calls keep
their captured owners or loans until they run.

A checked helper can forward a borrow of an opaque owner handle to a
reclamation call. The handle borrow protects its own storage. An interior
view, heap loan, or payload loan still prevents reclamation. Ordinary alias
checks prevent destruction or conflicting use of the borrowed handle itself.
Direct and deferred calls to destructor functions are rejected in checked
code: those calls would leave the original cleanup duty live. Use `drop` or
pass an owner by value to a consuming helper.

The checker derives ownership authority from declarations and checked transfers.
Application conditions and assertions execute as ordinary code. A Boolean
result alone cannot create an owner or end a loan.

## 3. Optional domains for opaque shared storage

Ordinary owners and loans need no domain. Use a domain when a trusted library
manages stable objects with internal aliases. A domain is a static access
boundary. It is not an allocator, pool, arena, registry, or reference count.

Transparent exclusive allocation trees use `owns(field: storage)` and local
loans. Their constructors and destructors are checked from their declarations.
Their stored fields must be transparent and domain-free, including embedded
value records. Stored loans are rejected because owning result interfaces
cannot describe their origins. Independent owner trees can be destroyed
independently, including while another tree has a live loan.

Each domain instance has a distinct compile-time identity and one reclamation
authority. Types and interfaces carry that identity. A second authority for
an existing identity cannot be constructed. Independent instances cannot be
mixed. Creating a fresh instance does not permit existing objects to change
their identity.

A `domain D { ... }` block introduces the identity in a lexical scope. Objects and
views dependent on it cannot escape that scope. Helpers are checked once with
an abstract domain parameter. Instantiation substitutes an identity; it does
not specialize or recompile the helper. Returning a fresh domain and its dependent objects is rejected: the interface
cannot bind a new identity in a result.

The domain has three access permissions:

| Permission | Permitted work |
| --- | --- |
| `read` | Observe published objects. No mutation or reclamation. |
| `edit` | Change links or payload through declared operations. No destruction, relocation, or storage reuse. |
| `reclaim` | Construct objects and invoke their retirement operations. No outstanding domain access scope or view is allowed. |

A read scope borrows the authority for reads. An edit scope borrows it
exclusively. The stronger permission is unavailable while that scope is open.
These permissions are erased. They are not locks and do not insert atomics.

### Cursors and payload views

A cursor is an opaque address with a domain identity and an access-scope
origin. It has one pointer at runtime and follows the view move and reborrow
rules. It grants no direct field access and no ownership. Navigation uses the
library API. A cursor cannot be stored in an owner that outlives its scope,
returned without its origin, or converted into an unrestricted pointer.

Its scope origin keeps reclamation unavailable. It does not borrow the edit
permission itself. This is a general contract for an opaque scope-bound view;
the checker has no cursor type or navigation operation built in.

Holding a cursor permits edits in the same edit scope. An edit cannot invalidate
its storage. Reading or changing payload requires a separate `read` or `mut`
view. That view borrows the domain access permission as well as its declared
storage origins. While a mutable payload view is live, another operation that
could alias it is rejected. A shared payload view prevents conflicting edits.
The checker treats unknown aliases in one domain as potentially overlapping.

This separates navigation from a reference to the payload. It does not make
several potentially aliased mutable references safe.

No cursor or payload view can survive return of reclamation authority. A new
access scope after destruction creates new views. Old pointer bits cannot be
used as a new view, even if an allocation reuses the same address. No runtime
generation number is needed.

## 4. The trusted boundary

A trusted container consists of opaque types, exported contracts, and their
implementation. The compilation program explicitly selects that implementation
as trusted. An implementation annotation or an imported artifact cannot grant
itself that status. The root can select a definition in the same source file;
the boundary is a compilation policy, not a file boundary.

The guarantee assumes that the root selects the checker and the stated trusted
dependencies. A root that selects only the raw seed provides no such guarantee.

The module layer supplies stable declaration identities and representation
visibility. The ownership stage consumes those identities. It must not select
trust by a function name, record name, source path, or container category.

The interface exposes layout size and alignment where stack storage needs
them, but it does not expose access to private fields. The backend can use the
layout without granting clients permission to project those fields. In-place
construction must initialize all storage before the client obtains a live
resource. This permits stack heads without an implicit allocation.

Trusted bodies still pass the seed's syntax and type checks. The ownership
stage does not certify their internal pointer stores. Their authors must
establish these obligations:

1. Published internal pointers refer to live, correctly typed storage at each
   public boundary.
2. An owning result transfers one cleanup duty. It does not duplicate an owner
   that remains in the container or with another caller.
3. Read and edit operations obey their access effects and preserve storage
   lifetime and address. They cannot free through an edit-only interface.
4. Retirement removes all internal references that would outlive the storage,
   then destroys the value, then permits release or reuse.
5. Returned views have the declared origins. Calls and callbacks cannot retain
   ordinary borrowed inputs beyond their contract.
6. Retirement covers every admitted retainer, including destruction of either
   end of a retained relation.

A managed resource's interface names its domain and retirement operation.
That operation requires reclamation authority. All ways to invalidate the
resource must go through it: explicit destruction, scope cleanup, replacement,
containing-object destruction, and allocation reuse. Clients cannot extract an
owned allocation and bypass retirement with a raw release call.

### Internal retention

A trusted operation can retain a managed object's address inside its own
domain. Its opaque type and domain declare this retention boundary. The client checker checks
the managed type, matching domain identity, and required access permission.
It does not create a per-edge loan or a membership counter. Correct retirement
is part of the managed type's trusted contract.

This permission does not apply to a borrow of arbitrary stack storage, a file
handle with an ordinary close operation, or a managed object from another
retirement boundary. Such retention needs an ordinary lifetime-bound view or
an explicitly different owning interface.

The domain's private representation and retirement implementation form one
closed retention boundary. A different module cannot add a persistent pointer
into it merely because it can name the domain. A new hook or retainer requires
an explicit extension of the trusted interface and its cleanup implementation.
A checked observer outside that boundary holds an ordinary loan, which blocks
conflicting reclamation until the observer is gone.

This rule prevents a third, unreported retainer from invalidating the cleanup
contract. The compiler checks visibility and interface authority, not the set
of heap edges. All implementations admitted inside the boundary share the
responsibility for that contract.

## 5. Intrusive lists

Use ordinary `prev` and `next` fields in the trusted implementation. Two
memberships use two pairs of fields. Nodes can be allocated individually, and
heads can use stable stack storage. There is no hidden ownership-chain field.

The library's node retirement routine unlinks both memberships before it frees
the allocation. Its head retirement routine detaches its members before it
releases the head. Detached hooks use ordinary self-links. The pointer code
can be the same direct loads and stores used in a C implementation.

The checker does not have linked or detached states for every node. It does
not need to update all external owner types when a head detaches its members.
The trusted library maintains that internal state.

These are the public operations and their contracts. Names belong to the
example library, not to the checker:

| Operation | Ownership and access contract |
| --- | --- |
| Construct node | Requires reclamation authority; returns one owner of stable node storage. |
| Construct head | Initializes final storage; creates a stable head resource with a reclamation-requiring destructor. |
| Insert into ready or active list | Requires edit access; borrows the owner handle; may retain the managed node inside the domain. |
| Remove from either membership | Requires edit access; preserves the node's lifetime and external owner. |
| First or next node | Requires access; returns a cursor tied to the current access scope. |
| Borrow payload | Returns a normal read or mutable view tied to the access permission and source origins. |
| Destroy node owner | Requires reclamation authority; consumes the owner; unlinks all hooks before release. |
| Destroy head | Requires reclamation authority; leaves all externally owned nodes live and detached from that head. |

The following is a complete target program for the example's provider. Save it
as `build/intrusive-small.crs`. From the repository root, run:

```sh
make all ownership-stage
build/crust examples/intrusive/main.crs -o build/intrusive-small \
    build/intrusive-small.crs
build/intrusive-small
```

```crust
fn main(argc: i32, argv: **u8) -> i32 {
    domain Graph {
        var first: Owner = owner_new(65i64);
        var second: Owner = owner_new(66i64);
        {
            var ready: ReadyHead = uninit;
            var active: ActiveHead = uninit;
            ready_init(&ready);
            active_init(&active);
            edit Graph {
                ready_insert(mut ready, read first);
                ready_insert(mut ready, read second);
                active_insert(mut active, read first);
                active_insert(mut active, read second);
            }
            read Graph {
                var cursor: Cursor = ready_first(read ready);
                var value: read i64 = cursor_value(read cursor);
                if value != 66i64 { trap; }
            }
            drop first;
            var replacement: Owner = owner_new(67i64);
            edit Graph {
                ready_insert(mut ready, read replacement);
                active_insert(mut active, read replacement);
            }
        }
    }
    return 0i32;
}
```

The program returns zero. `drop first` retires an individual node while both
heads remain live. The replacement has a new owner and can join both lists.
Its scope cleanup unlinks it before the heads are destroyed. Head cleanup
then detaches `second`, whose owner is cleaned up at the domain boundary.

Destruction occurs outside the access scopes. Moving `drop first` inside the
read scope produces a diagnostic. A cursor can be used only within its access
scope. The [full example](../examples/intrusive/README.md) also checks traversal,
payload mutation, both head counts, and surviving nodes after head destruction.

An owning container can keep ownership in its existing links. Removal returns
an owner and removes the container's ownership of that node. This transfer is
trusted implementation work. It does not require a second `owned_next` chain,
a pool, or a compile-time list of runtime nodes. Non-owning intrusive views of
those same nodes use the domain's retention contract. A non-owning list cannot
return ownership that belongs to its caller.

## 6. Other structures

The checker uses the same rules for all these interfaces:

| Structure | Trusted implementation duty | Checked client duty |
| --- | --- | --- |
| Tree that owns its children and has parent pointers | Transfer child ownership once; clear or repair parent references on detach; retire children and incoming internal references in a valid order. | Use owned results, respect access scopes, and keep returned views within their origins. |
| Hash table or one-way observer index | Remove every retained entry before target retirement, or keep an ordinary loan on the target. | Do not turn an index cursor into an owner or let it outlive access. |
| Intrusive work queue with two memberships | Maintain both hooks and detach both before node release. | No destruction during traversal or payload borrowing. |
| File or integer-like native handle | Obey acquisition, borrowing, invalid-value, and release contracts. | Move ownership once and do not close through a borrower. No domain is needed for ordinary use. |
| Local record containing views from two inputs | Create checked loans for both fields. | Keep both source loans until their dependent views end; return them through separate declared interfaces. |

A one-way index cannot claim cheap individual deletion if its representation
has no way to find or remove incoming entries. It must supply that algorithm,
retain a loan that prevents deletion, or reject that operation. The compiler
does not invent a reverse index or pay for one invisibly.

The index tutorial owns symbol entries and separate alias entries. Symbols have
no reverse alias link. Removing a symbol scans and clears every alias to it,
then releases that symbol. The checked client tests two incoming aliases,
unaffected targets, rebinding, individual release, replacement, and automatic
cleanup of a runtime-sized index. The native test forces address reuse. The
same client also compiles from a bodyless imported interface. This supplies
the one-way retention example without another ownership feature.

## 7. Body-local checker

Build a finite interface table once. It contains resource kinds, field paths,
opaque layout identities, destructor effects, borrow-origin paths, domain
parameters, and trust dependencies. Names are interned; places retain declaration and scope identities. Do not create
symbolic field arrays or expand heap objects.

Check each body independently:

1. Create places for parameters, locals, and field paths used by the body.
   Recursive owned types remain nominal summaries. Do not unfold an owned
   tree to discover its nodes.
2. Track initialization and moves. An owning store consumes its input.
   Replacing a live owner requires explicit consumption or cleanup.
3. Track loans by origin, mode, parent reborrow, and scope. Direct disjoint
   fields of an ordinary record can be separate places. Unknown aliases do
   not become disjoint because their pointer expressions differ.
4. At each call, substitute the interface's input places and domain identities.
   Check required permissions, apply moves and initialization outputs, and
   attach the declared loans to results. Apply writable-place invalidation.
5. Check both arms of a branch, then join their finite states. Do not split
   again on possible pointer identities or search for a feasible heap.
6. Check a loop with a declared type and ownership state at its boundary.
   Forget scalar values and old allocation identities that can change. Check
   one body under that abstract entry and require each continuing backedge
   to restore the same ownership and loan interface. Do not unroll iterations.
7. Check each return and cleanup path against the function and destructor
   interfaces. An access scope cannot silently regain stronger authority to
   run a destructor. Keep reclamation-requiring owners outside that scope or
   transfer them out before their cleanup.

The state has no set of all live heap objects, incoming-edge relation, pointer
formula, arithmetic prover, quantifier instantiation, or alias-case search.
Trust does not make an unsupported checked operation succeed. It applies only
to the explicitly selected definitions. Exceeding a checker work limit is a
diagnostic, not permission to accept the body.

## 8. Compilation cost and parallel work

Checker state consists of places, objects, and loans encountered in one body.
Its size depends on the source, not the runtime heap population. Local fact
chains use fixed hash buckets. A branch copies bucket heads and retains the
immutable facts. A join scans local slots, objects, and loans. It reuses an
unchanged slot binding and records a new binding when the merged value changes.
Large bodies and long fact chains can increase lookup and join cost; measure
those cases separately from many small independent functions.

A declaration pass precedes body checking. Bodies read interface summaries and keep separate local state in the
request arena. The current driver runs bodies serially. Separate check contexts permit
parallel body work after interface publication; no scheduler is supplied here. Recursive calls
use the same published summaries and do not require an interprocedural fixed
point. A changed body needs a new check; an unchanged interface need not force
unrelated bodies to be checked again.

Interface and object receipts include the checker version, policy options,
ABI, exported contracts, and trust dependencies. A client may use a separately
built provider without its bodies. Cache keys must distinguish a body checked
by the ownership stage from a body explicitly trusted by the root. An artifact
cannot change that status through its own metadata.

The ownership performance gate uses the compiled stage and a fresh client check.
Exclude target GCC compilation and linking. Compare the same source through
resource lowering and C emission with and without the ownership pass in the
erasure harness. Require identical emitted C and symbols. Do not expose the
unchecked harness path as an alternative with the same safety claim.

Use the intrusive client, tree with parent links, one-way index, native handles,
stored views, and exclusive heap owners. Also measure independent provider and
client builds. The budget is a median total frontend ratio at most `2.0` against the
resource-only path on a large client workload, using randomized paired runs
and reporting uncertainty. Measure `1x`, `2x`, and `4x` copies of independent
function bodies to detect scaling faults. Report the ownership pass separately.
The [ownership measurement guide](../benchmarks/ownership/README.md) gives the
commands and report fields. The raw frontend has a separate C-speed gate.

No runtime representation is added for ownership state, domain identities,
permissions, trust, or borrow origins. An owner handle and a cursor keep their
ordinary representations. Link rewrites and cleanup calls remain executable
work, as in the corresponding C implementation. Compare those operations;
do not assume an optimizer will erase extra bookkeeping.

## 9. Validation

Run from the repository root:

```sh
make all ownership-stage
make check-ownership check-ownership-imports check-ownership-alloc
```

The checks cover trusted direct-pointer providers and checked clients: two-hook
intrusive lists, an owning tree with parent references, and a one-way index.
They exercise individual release, address reuse, native output, independent
imports, and identical code before and after ownership verification.

Client rejection tests cover duplicate owners, borrowed destruction, cursor
escape, reclamation during access, wrong-domain arguments, replacement of stable
storage, private-field access, retirement bypass, undeclared result origins,
and unapproved trust. Cleanup checks cover failure and early exit.

Test trusted pointer implementations with native behavior checks and sanitizers.
A missing backlink store is a provider defect. A malicious trusted declaration
can also break safety. The root selects the implementation whose correctness
it relies on. Native tests and checked-client rejections cover different parts
of this boundary.

The [Rust comparison](ownership-rust.md) describes the annotations needed by
application and container authors. The tutorials show complete provider and
client sources alongside their build commands.
