<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership without a graph solver

This design is implemented by the optional ownership stage. The
[stage contract](ownership-model.md) defines its accepted syntax and rejection
rules. Z3 and the earlier graph-proof stages are removed.

Use local ownership checks for application code. Permit an explicitly trusted
implementation for containers whose internal pointers require stronger reasoning.
The trusted implementation must preserve the guarantees of its checked API.
A defect in that implementation can cause memory errors. The compiler does not
prove its pointer algorithms correct.

The stage stays in Crust. The C99 core needs no ownership rules, graph analysis,
new runtime, or solver interface.

## 1. The checked language

Keep these rules:

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

Use lexical loan scopes in the first replacement. Explicit `drop` of a view
ends its loan. Last-use inference is not required to remove Z3. This restriction
can need more explicit scopes than Rust; it is not a claim of equal ergonomics.

## 2. Function boundaries

An interface contains types, ownership modes, loan origins, initialization
outputs, access effects, and cleanup requirements. These are finite type and
effect facts. They are not Boolean formulas about arbitrary objects.

A returned view declares one exact input path with `from parameter.path`.
Every borrowed field of a returned view record must derive from that path.
Local view records can combine loans from several inputs. A function cannot
return that combination through one `from` path or replace stored origins
through a borrowed parameter. The checker rejects these interfaces. A finite
per-field result and replacement map would be needed to accept them. This
implementation does not add that interface before a production API needs it.

Borrowed storage must be initialized again before return. A mutable call
invalidates scalar facts for its declared writable places. Native-handle
validity facts must also be rechecked after a call that can replace the handle.
The stage can recognize a direct invalid-sentinel test; it does not prove
arithmetic conditions to recover ownership or validity.

A destructor's required permission is part of the resource type. Implicit
cleanup cannot call a destructor that an explicit call could not call at the
same point. Check generated cleanup paths as well as written calls. Deferred
calls keep their captured owners or loans until they run.

There are no checked `invariant`, `requires`, or `ensures` formulas in this
profile. Ordinary application conditions still execute. Assertions do not
create ownership authority. A Boolean result cannot manufacture an owner or
end a loan unless a finite, declared type transition supplies that behavior.
Do not add such transitions before an API needs them.

## 3. Optional domains for opaque shared storage

Ordinary owners and loans need no domain. Use a domain when a trusted library
manages stable objects with internal aliases. A domain is a static access
boundary. It is not an allocator, pool, arena, registry, or reference count.

Each instance has a distinct compile-time identity and one reclamation
authority. Types and interfaces carry that identity. A second authority for
an existing identity cannot be constructed. Independent instances cannot be
mixed. Creating a fresh instance does not permit existing objects to change
their identity.

A `domain D { ... }` block introduces the identity in a lexical scope. Objects and
views dependent on it cannot escape that scope. Helpers are checked once with
an abstract domain parameter. Instantiation substitutes an identity; it does
not specialize or recompile the helper. Returning a fresh domain and its dependent objects is rejected: the interface
cannot bind a new identity in a result.

Retain the existing access distinction:

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
The first profile treats unknown aliases in one domain conservatively.

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

This client sequence is pseudocode, not a proposed source grammar. The domain
identity and required access modes are interface annotations. They add no
runtime argument.

```text
first = construct node
second = construct node
construct ready and active heads in their final stack locations

edit domain:
    insert first and second into ready
    insert first and second into active

read domain:
    traverse both lists through cursors
    end all payload views and cursors

destroy first
construct replacement, possibly at the same address

edit domain:
    insert replacement into both lists

destroy the heads
destroy the remaining node owners
```

The destruction and construction lines occur outside the access scopes. The
compiler rejects moving `destroy first` inside the read scope. It also rejects
using an old cursor after that scope. Destroying the head first is valid because
its trusted destructor detaches the surviving nodes.

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

Let `N` be body operations, `P` the distinct place paths, and `L` the loan facts
in a body. Their sizes depend on source, not runtime heap population. Use
local fact chains indexed by fixed hash buckets and explicit origin paths.
Branch state copies the bucket heads; earlier facts remain immutable. Structured branch joins
need work proportional to the local state they join. A simple implementation
can take quadratic time in unusually large bodies; do not call it linear
without measurement. It must not have exponential pointer-case search.

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

The first performance gate uses the compiled stage and a fresh client check.
Exclude target GCC compilation and linking. Compare the same source through
resource lowering and C emission with and without the ownership pass in the
erasure harness. Require identical emitted C and symbols. Do not expose the
unchecked harness path as an alternative with the same safety claim.

Use the intrusive client, native-handle code, a returned-view client, and an
owning-tree client. Also measure independent provider and client builds. The
initial budget is a median total frontend ratio at most `2.0` against the
resource-only path on a large client workload, using randomized paired runs
and reporting uncertainty. Measure `1x`, `2x`, and `4x` copies of independent
function bodies to detect scaling faults. Report the ownership pass separately.
This is a design acceptance budget, not a measured result or a change to the
raw frontend's C-speed requirement.

No runtime representation is added for ownership state, domain identities,
permissions, trust, or borrow origins. An owner handle and a cursor keep their
ordinary representations. Link rewrites and cleanup calls remain executable
work, as in the corresponding C implementation. Compare those operations;
do not assume an optimizer will erase extra bookkeeping.

## 9. Replacement gate

Implement one trusted provider and its checked client before adding another
ownership feature. Use the direct two-hook intrusive example, independent node
release and reuse, and native output. Add an owning tree with parent references
to ensure that the boundary has no list-specific rule.

The client checker must reject duplicate owners, borrowed destruction, cursor
escape, reclamation during access, wrong-domain arguments, replacement of
stable storage, private-field access, retirement bypass, undeclared result
origins, and unapproved trust. It must check cleanup on failure and early exit.

Test the trusted pointer implementation with native behavior tests and
sanitizers. A missing backlink store in that implementation is a library defect;
it is not a promised compiler rejection. A malicious trusted declaration can
also break safety. Keep those facts explicit in the test names, documentation,
and compilation policy.

Compare the complete provider and client annotations with a corresponding
Rust API and its unsafe implementation. Do not hide required proof scripts in
the library or require a second proof language to satisfy this gate.

Only after that provider/client boundary and the cost gate pass should the
modular ownership stage remove its Z3 dependency. The old closed-program proof
experiments are separate code. Remove or migrate them explicitly; do not claim
a repository-wide removal while they still link the solver.

## 10. Basis and tradeoffs

The basic loan contracts follow the same reason for explicit lifetime
relationships as [Rust's function and record lifetimes](https://doc.rust-lang.org/book/ch10-03-lifetime-syntax.html):
check a body and its callers from an interface. This design retains simpler
lexical scopes at first and does not claim all Rust borrow-checker behavior.

The stable-address and retirement contract follows the principle used for
[intrusive lists in Rust's pinning documentation](https://doc.rust-lang.org/std/pin/#an-intrusive-doubly-linked-list).
The library must unlink before storage becomes invalid. Crust additionally
makes the required reclamation permission part of the destructor interface.

[GhostCell](https://plv.mpi-sws.org/rustbelt/ghostcell/paper.pdf) supports separating
access permission from pointers. It does not by itself supply the individual
retirement guarantee used here. That guarantee belongs to the trusted container.

The alternatives do not remove this obligation for free.
[Ghost collections](https://github.com/matthieu-m/ghost-collections) documents
allocation-identity checks when StaticRc shares join.
[Mezzo's adoption and abandon](https://cambium.inria.fr/~fpottier/publis/pottier-protzenko-mezzo.pdf)
uses runtime ownership state and checks.
[Alias types](https://www.cs.princeton.edu/~dpw/papers/alias-recursion-tr.pdf)
can describe recursive ownership and aliasing through explicit store types.
This design does not add those store descriptions to the user's interface.
It accepts a visible trusted implementation instead.
