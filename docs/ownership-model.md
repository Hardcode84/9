<!-- SPDX-License-Identifier: Apache-2.0 -->

# Generic ownership proposal

The ownership stage must understand owners, loans, storage, and access. It must
not understand lists, trees, anchors, or reciprocal pairs.

This proposal uses ordinary ownership for most code. For persistent mutable
references, it adds a sealed storage interface and checked field conditions.
The interface states where references can remain. The conditions state what an
operation must preserve. Destruction has one rule for all data structures: no
surviving reference may point into the storage being destroyed.

This is a design for an external Crust stage. The notation below is proposed
source notation, not syntax accepted by the current compiler. The
[implemented guide](ownership.md) describes the current stage. Its dedicated
list verifier is not the implementation of this proposal.

## 1. The small model

| Concept | Meaning | Target representation |
| --- | --- | --- |
| `own<T>` | The right and duty to destroy one value. Moving it transfers that duty. | The value, or one pointer for allocated storage |
| `read<'a, T>` | A shared loan that remains valid for lifetime `'a` | One pointer |
| `mut<'a, T>` | An exclusive loan for lifetime `'a` | One pointer |
| `own<D, T>` | An owner of address-stable storage in domain `D` | One pointer for allocated storage |
| `link<D, T>` | A persistent, non-owning address governed by domain `D` | One pointer |
| Domain access | Permission to read, edit, or reclaim the domain's storage | No permission data |
| Field and function conditions | Facts checked before emission | No target instructions |

A domain is an access boundary, not an allocator or a pool. Its objects can
come from separate allocations or stable stack places. Each allocation keeps
its own owner and can be destroyed separately. There is no allocation registry,
handle table, generation, reference count, or implicit runtime scan.

The model separates three facts:

1. The owner determines who can destroy storage.
2. A loan or domain permission determines who can access it.
3. A lifetime or a checked storage condition determines why a retained
   reference remains valid.

A pointer address alone supplies none of these facts. In particular, a live
owner does not grant an independent exclusive reference to a domain object.
The object can have aliases through links. Access must use the domain.

Ordinary owners and loans do not require a domain or a solver. Domains are
needed when a program retains references whose targets can change or be
reclaimed independently of the other targets.

## 2. Ordinary ownership and stored views

An owned value has one destruction path. Move transfers the owner. Reading an
uninitialized or moved value is an error. Owned record fields describe disjoint owned subtrees. A child owner can move between
fields without copying its allocation. The destination must not be inside
the subtree being moved; an owner cannot own its own containing storage. This
is part of the owner contract, not a consequence of pointer uniqueness alone.
A recursive type does not require recursive expansion of its storage.

Shared loans permit reads. Exclusive loans permit reads and writes. Overlapping
exclusive loans are rejected; disjoint fields can be borrowed separately. The
checker uses local control flow to end a loan after its last possible use.
Function interfaces give input and output lifetime relationships.

Stored loans are ordinary fields:

```crust
record View<'a> {
    item: read<'a, Item>;
}

fn view<'a>(item: read<'a, Item>) -> View<'a> {
    return View { item: item };
}
```

`View` cannot outlive `item`. A mutable stored view has the same exclusive
access rule as a mutable local view. Moving the view does not remove its loan.
Destroying it ends the loan. These rules also cover borrowed slices and
one-way references when the target already has a sufficient lifetime.

There is no special prohibition on borrowed fields. There is also no conversion
from a raw pointer to a checked view without a verified source of lifetime,
initialization, bounds, and access facts.

## 3. A sealed storage interface

Ordinary lifetimes cannot describe every independently reclaimable cycle.
For that case, a domain declares a closed storage schema:

```crust
domain Work {
    root: Heads;
    storage: Node;
}
```

Each domain instance has one root and any number of the declared storage
objects. The root is an ordinary record. It can be empty. `storage` lists types,
not allocated addresses. Embedded records and arrays contribute their fields
recursively. The schema can list more than one storage type.

The interface determines every place where a persistent `link<D, T>` may
remain: the root and the declared storage fields. Owning handles may be stored
outside this schema; they are affine owners, not additional retained links.
A local link is a cursor with the lifetime of its access scope. Outside the
schema, an address can escape only as an ordinary loan with that lifetime.

A type parameter such as `D: Work` denotes an instance of the complete `Work`
schema. It does not mean an arbitrary domain with some matching fields.

This closure is essential. Suppose a library proves deletion by repairing two
fields, while a client adds an unreported third reference in an index. Deletion
is no longer safe. The checker must reject that index field, or the program
must declare a different schema and verify the deletion against it. It must
not search all source files for possible indexes.

A schema is therefore part of a library interface, like a record layout. It
is not extended after its functions have been verified. A parameterized library
can publish schema constraints, but it cannot assume that an unknown extension
has no incoming references. Adding an index changes the relevant contract and
invalidates proofs that depended on the smaller schema.

Different instances have distinct static domain identities. A link from one
instance cannot be stored in another. These identities have no runtime
representation. The root also becomes address-stable before a link can target
it or one of its fields. The domain binding must outlive its domain owners and
loans; this is a lifetime constraint, not a requirement to reclaim all nodes together.
List heads can be cleared while the domain and unrelated node owners remain.

## 4. Access and mutation

A domain has three access modes:

| Mode | Permitted operations | Excluded operations |
| --- | --- | --- |
| Read | Traverse links; create shared views | Mutation and reclamation |
| Edit | Read and write through cursors; create scoped payload loans | Reclamation |
| Reclaim | Construct or destroy individual storage; enter nested edit scopes | Coexisting external domain access scopes |

Read access can be shared. Edit and reclaim access are exclusive. An edit
cursor is an address usable under the one edit permission. Copying that cursor
does not create another exclusive permission. This permits aliases during
ordinary pointer rewiring without creating two `mut` references.

A payload loan borrows domain access. While it is live, conflicting domain
operations are suspended. This proposal applies that suspension to the whole
domain for a payload loan. This is a compile-time restriction; finer disjointness must
not introduce a second mutable authority. Read/edit cursors cannot escape their
scope through locals, returns, closures, or stored views with a longer lifetime.

An erase operation consumes an owner under reclaim access. It can open an edit
scope to remove references, close that scope, and then destroy the allocation.
The caller cannot keep an old cursor across this operation. A fresh allocation
has a fresh proof identity even if its numeric address equals the old address.
No numeric equality test can restore the old reference's lifetime.

This first contract is sequential. It supplies no concurrent read/reclaim
protocol. Sharing access across threads requires a separately checked
synchronization contract; plain copies of a domain token are rejected.

Construction reserves fresh storage under its allocation owner. The object is
not yet a published instance of its record type. Its constructor can initialize
fields and form self-links at the final address. It cannot read an uninitialized
field or expose the object to a function that assumes the complete type.
Publication establishes initialization, owned-field separation, and all type
conditions. An error path releases the reserved storage and each initialized
owned field; it does not call a destructor on an incomplete object.

## 5. Ordinary field conditions

A record may declare a condition over its fields, typed field paths, its own
address, and the domain root. Conditions use equality, Boolean operations,
and guarded scalar comparisons. They have no side effects. Nullable paths
must be guarded before dereference. Each referenced field must lie in the
same domain, or be protected by an ordinary lifetime and loan.

For example, the following are source expressions, not built-in list rules:

```crust
record Node<D> {
    ready: Links<D>;
    active: Links<D>;
    value: i64;
}
where self.ready.prev.ready.next == self
   && self.ready.next.ready.prev == self
   && self.active.prev.active.next == self
   && self.active.next.active.prev == self;
```

The checker applies the condition to every initialized object of the type.
It also checks obligations that the user cannot remove: each retained link
has a live, correctly typed target; each accessed field is initialized; owners
are unique; and accesses have permission. A user condition of `true` does not
turn off memory safety.

The first condition language has no user quantifiers, recursive predicates,
ghost containers, solver terms, proof lemmas, or checker callbacks. A named
abbreviation must expand to the same finite expression language. A condition
can have more than one pointer hop; it is still a finite source expression.
Unbounded structure comes from applying type rules to all live objects, not
from an author-written recursive heap predicate.

These restrictions deliberately leave some safe algorithms unproved. Failure
to prove an obligation rejects the function. It never introduces a runtime
check, assumes the condition, or falls back to an unchecked operation.

### When a condition must hold

At a public function entry, its type and preconditions hold. During exclusive
editing, field conditions can be temporarily false. Every individual load and
store must still have live, initialized storage and the required permission.

All type conditions must hold again at a normal call, return, and loop boundary.
A called function can then assume its published contract. The checker cannot
re-assume entry conditions after a store that invalidates them. Conditions that
depend on changed fields are discarded and must be re-established.

This gives small pointer-update functions a useful atomic checking boundary.
It does not make their machine instructions atomic. A callback cannot observe
the intermediate state. A function with a partially repaired structure cannot
call an ordinary helper until it has restored the helper's entry conditions.
There is no hidden callee expansion to repair an insufficient contract.

## 6. Destruction: one rule for every shape

Let `A` be the allocation being destroyed, including all its subobjects. At
its destruction point the checker must establish:

1. The function consumes the unique destruction owner of `A`.
2. No live ordinary loan or domain cursor can access `A` afterward.
3. No retained reference in surviving storage points into `A`.
4. Cleanup has the required initialized fields and obeys these same rules.

References stored inside `A` do not prevent destroying `A`. A self-reference is
one example. An incoming reference from another object does prevent it, even
if the program does not plan to traverse that reference again.

Rule 3 is generated from the complete schema. It includes all declared fields,
embedded fields, and relevant array elements. The library author does not write
a quantifier over the heap or supply an inventory of just the fields they
remember to update.

For ordinary borrowed fields, lifetimes discharge the rule. For persistent
domain links, the checker uses the schema's field conditions and the function's
stores and callee contracts. If those facts cannot exclude an incoming link,
the destruction is rejected. A diagnostic should name the retained field:
`cannot release node: Node.saved may still point into this allocation`.
For an analysis timeout, report that the absence of that reference was not
proved; do not report a concrete dangling reference without a valid witness.

Clearing outgoing links alone is insufficient. Clearing an actual incoming
reference works even when that reference has no inverse partner. This rule does
not mention detachment, membership, a head, a ring, or a tree.

## 7. A direct two-hook intrusive list

This example uses two circular lists with nullable head pointers. Each hook has
ordinary `prev` and `next` pointers to `Node`. There is no sentinel allocation,
owner-chain pointer, pool, or observer metadata.

```crust
record Links<D> {
    prev: link<D, Node>;
    next: link<D, Node>;
}

record Heads<D> {
    ready: link<D, Node>?;
    active: link<D, Node>?;
}
```

Use the `Node` conditions in section 5 and the `Work` schema in section 3.
A new node starts with both hooks pointing to itself. Construction occurs at
its final address, and publication must establish all field conditions.
`own<D, Node>` can move; its pointee cannot move while these links exist.

The following notation shows the complete contract needed for ready unlink.
`writes` names field classes and root paths, not individual runtime nodes.
`edit D` denotes the access permission for this domain instance. Passing the
root address costs only the argument that the body actually uses.

```crust
fn unlink_ready<D: Work>(g: edit D, x: link<D, Node>) -> unit
    writes(g.root.ready, Node.ready)
    ensures x.ready.prev == x && x.ready.next == x
         && g.root.ready != x
{
    var before = x.ready.prev;
    var after = x.ready.next;
    if g.root.ready == x {
        if after == x { g.root.ready = null; }
        else { g.root.ready = after; }
    }
    before.ready.next = after;
    after.ready.prev = before;
    x.ready.prev = x;
    x.ready.next = x;
}
```

`unlink_active` has the same body and contract with the other field paths.
A library can use ordinary source generation for that repetition. The
ownership checker needs no field-family feature.

An owner destructor has this shape:

```crust
fn destroy_node<D: Work>(g: reclaim D, node: own<D, Node>) -> unit {
    edit g {
        var x = address(node);
        unlink_ready(g, x);
        unlink_active(g, x);
    }
    release(move node);
}
```

`address` borrows an owned allocation within the access scope. `release` is the
checked allocation adapter: consuming its argument must satisfy the destruction
rule. These operations do not assert that unlink is correct.

Why can this destruction pass? Consider any surviving node `y`:

- If `y.ready.next == x`, the field condition gives
  `x.ready.prev == y`. Unlink establishes `x.ready.prev == x`, so `y == x`.
  That contradicts survival outside the destroyed allocation.
- The same argument applies to the other three pointer fields.
- The two unlink postconditions exclude the root head pointers.
- The `writes` contracts preserve the other hook's established facts.

These are consequences of ordinary source conditions and equality. There is
no compiler axiom that a detached hook has no incoming references. Adding a
`Node.saved` field can invalidate the destruction proof immediately, even when
both hooks remain correct.

Insertion after `at` requires the inserted hook to point to itself and
`at != x`. Its body is the normal four updates: save `at.next`, set the new
hook's two neighbors, set `at.next`, and set the old successor's `prev`.
The checker must establish the same field conditions afterward. The empty-head
case sets the head to an already initialized self-linked node. Conditions are
also checked when pointers alias; a singleton is not a special checker case.

Traversal takes read access and follows the selected `next` field until it
returns to the starting node. The null head denotes an empty list. Every next
pointer has a live `Node` target. A counter or termination proof is not needed
for memory safety.

Head cleanup repeatedly unlinks the current head until the root field is null.
Each iteration restores all type conditions. Node owners stay live, and the
other hook is unchanged. Nodes can be stored in caller locals, an ordinary
vector of owners, or an owned tree. That storage choice is not imposed by the
link checker.

### Representation boundary

This is a direct intrusive representation, but it is not the current tutorial's
standalone `Hook` sentinel representation. It uses one head pointer per list and
four link pointers per node. The payload has no extra owner pointer. This
choice must be explicit in a comparison.

Generic typed interior pointers retain an allocation origin and field path in
proof state. Projecting back to an enclosing object requires that origin.
Subtracting an offset from an arbitrary pointer does not establish it. In a
mixed sentinel/member ring, excluding one sentinel address does not prove that
another hook belongs to a `Node`; a second sentinel could remain. This proposal
does not invent colors or member roles to accept that cast. The displayed list
avoids the cast by storing typed node pointers. Accepting the old representation
requires a generic source-level origin contract and a checked constructor that
establishes it. Until that exists, the cast must be rejected.

## 8. Two different structures, the same rules

### An owned tree with parent links

The left and right fields own children. The parent field is a nullable domain
link. Root ownership and child ownership use the ordinary affine rules.

```crust
record TreeNode<D> {
    left: own<D, TreeNode>?;
    right: own<D, TreeNode>?;
    parent: link<D, TreeNode>?;
    value: i64;
}
where (self.left == null || self.left.parent == self)
   && (self.right == null || self.right.parent == self)
   && (self.parent == null
       || self.parent.left == self || self.parent.right == self);
```

Address comparisons inspect an owner without moving it. Removing a leaf takes
its owner out of the parent's field and clears the leaf's parent link. No
surviving parent link can target the leaf: the field condition would require
that leaf to own the referring child, but the leaf has no children. Affine
ownership excludes a second owning field. The generic destruction rule can
therefore release it. Removing only the owned field and leaving a retained
parent link is not permission to release its target.

A tree rotation moves owning fields and changes parent links under edit access.
Its interface must state the changed fields and result relationships. The same
record conditions apply at return. No tree case or balance predicate belongs
in the ownership checker. Balance is a separate functional property.

### One-way observers

A domain root can contain two nullable pointers, `lookup` and `current`, to
independently owned entries. Entries need no backlink or field condition.

```crust
domain Observers { root: Slots; storage: Entry; }
record Slots<D> {
    lookup: link<D, Entry>?;
    current: link<D, Entry>?;
}
record Entry<D> { value: i64; }
```

```crust
fn destroy_entry<D: Observers>(g: reclaim D, entry: own<D, Entry>) -> unit {
    edit g {
        var x = address(entry);
        if g.root.lookup == x { g.root.lookup = null; }
        if g.root.current == x { g.root.current = null; }
    }
    release(move entry);
}
```

The schema says these are the only persistent reference slots. Clearing both
permits destruction. Clearing only one fails when the other can still point to
the entry. If entries themselves contain arbitrary one-way `next` links, the
same body fails: some other entry can still refer to the victim.

That failure is necessary, not a missing reciprocal annotation. The interface
must then establish the source of every possible incoming link, or the program
must use lifetime-bound views, owned edges, or a destruction operation that
removes those references. A scan from one root proves nothing about unreachable
objects unless the declared contracts establish that the scan covers them.

## 9. Function boundaries and checking

A verified function interface contains:

- Parameter and result types, owner transfers, and loan lifetime relationships.
- The storage schema and type conditions on which the proof depends.
- Access modes, changed field classes, construction and destruction effects.
- Preconditions and postconditions expressed in the finite condition language.

Read these declarations through the external reader hooks. Keep lifetime,
schema, and permission facts in the stage's source representation. Check them
before lowering owners, loans, and links to the existing pointer and record
operations. The C99 seed and the backends need no ownership or topology rules.
The stage must also retain checked cleanup plans through emission.

Local effects can be inferred and exported. Conditions needed by callers must
be present in the published interface. Returned views carry the lifetime of
the input access loan. A result cannot extend that loan to the entire lifetime
of the domain merely because its pointer has the same domain brand.
A caller never reads the callee body.
The provider verifies its body before publishing that interface. Recursion uses
the declared contract; it does not unfold another copy of the body.

At a call, check preconditions, transfer ownership and loans, forget facts about
fields in the declared write set, and assume the checked postconditions. Preserve
unaffected facts. An opaque function with unrestricted write effects cannot
promise that previously established detachment facts survive.

Loop checking starts from initialized local types, owner states, active loans,
and closed schema conditions. It must show that one arbitrary iteration
preserves them and that all exits obey their contracts. The same method checks
an arbitrary list length; a maximum node count is not an invariant. If a body
needs a stronger invariant that this stage cannot infer from the allowed
contracts, reject it. Do not ask the user to write solver proofs to make the
required examples pass.

### Verification algorithm

Use a local control-flow pass for owners, initialization, loans, and effects.
Use symbolic field maps only for functions that need relational field facts.
The proof heap records live allocation identities, subobject paths, field values,
and permissions. This data never reaches the target program.

For each changed type condition, select an arbitrary surviving object and prove
its condition in the post-state. Unchanged fields use the store frame rule.
For destruction, select an arbitrary surviving reference slot from each schema
field class and prove that it does not target the destroyed allocation.

Instantiate declared field conditions at symbolic addresses relevant to those
obligations: arguments, accessed addresses, candidate post-state objects, and
field paths occurring in the conditions. A finite set of instances is a weaker
premise than the universal type rule. A proof from those instances is sound for
an arbitrary heap size. Failure to prove it is rejection, not proof that the
program is unsafe. No list-specific axiom, inverse-field recognizer, or
per-container callback is needed.

The selected relational stage can use Z3. Basic owners and ordinary loans need
no solver. Extra analysis may improve acceptance, but it cannot change the
safety contract or insert target checks. Solver timeout or `unknown` rejects
the unproved function and reports the outstanding obligation.

### Parallel work and caching

Type schemas must be available before their functions are checked. Independent
bodies can then be checked in parallel. There is no shared mutable proof heap
between compiler tasks. A type condition is not a global analysis of its
runtime instances.

Cache a body proof against body bytes, the complete imported interfaces and
schemas, layout and target rules, checker and solver versions, and options.
Keep diagnostics deterministic. A schema change, such as an extra retained
field, must invalidate the proof. Do not reuse a proof merely because the
function body is unchanged. Measure local checking, relational checking,
emission, and target compilation separately.

## 10. Cleanup and erasure

RAII calls the checked destructor for a live owner at its declared exit point.
`defer` schedules an ordinary checked call. Neither creates permission that the
function did not have. Cleanup that needs reclaim access must have it at every
exit, including error exits. A callback cannot keep a cursor after cleanup.
A function whose cleanup needs the domain root must receive that access in its
interface. Cleanup uses that root argument; it cannot discover it through an
ambient registry or a hidden pointer in the owner. If no suitable access is
available, the function is rejected.

Do not add hidden drop flags to merge incompatible owner states. Generate
cleanup on the control-flow edges where an owner is live, or reject a join whose
ownership state cannot be represented under this contract. A destructor that
can return early must still establish its destruction postconditions. Allocation
failure leaves no initialized owner and must take an explicit error path.

Domain brands, access tokens, lifetime parameters, schema declarations, and
conditions erase. Declared root fields, pointer stores, branches, explicit
allocations, and destructor calls remain. Do not mark domain link accesses as
independent `noalias` references: those links can alias. Backend metadata must
follow the verified access contract, not the surface word `own`.

The allocation and foreign-call adapters remain a trust boundary. An unchecked
external function can violate liveness and invalidates the safety result.
Checked library functions must not disguise such a function as a trusted list
primitive. Raw seed code retains its explicit raw-memory semantics.

## 11. Evidence and implementation decision

A scratch symbolic-heap probe exercised the same schema, field-store, and
incoming-reference obligations for two-hook rings, tree parent links, and
one-way root slots. It proved pointer-condition preservation and reference
removal for the positive operations. Counterexamples remained for a missing
neighbor store, destruction after unlinking only one hook, an additional retained
field, and clearing only outgoing links. Input satisfiability was checked to
exclude proofs from inconsistent premises.

The positive queries use an arbitrary symbolic object, with no maximum node
count. Separate queries check fresh self-link initialization and destruction
from bodyless unlink postconditions. The negative ring cases also use concrete
three-node heaps. The tree probe assumes the ownership uniqueness obligation; it does not implement its
checker. Direct unrestricted quantified queries were insufficient in the probe;
finite instantiation of the same declared conditions discharged the positive
obligations. This is evidence for the local proof method, not a compiler speed
result.

These probes are hand-written heap transitions. They do not parse the proposed
source, verify owner/loan rules, compile a library interface, or check target
code erasure. They must not authorize replacing the current checker yet.

The bounded implementation test is one vertical path through the external
stage: declare a schema and field conditions, check ordinary views and owners,
check the three structures above, publish a bodyless library interface, and
check a client that allocates a runtime number of nodes and destroys one while
the others remain live. Check exact-address reuse, root cleanup, and final native
behavior. Compare emitted code with the equivalent unchecked pointer program.

The authoring gate is equally strict: no user ghost state, loop proof scripts,
solver formulas, trusted container operations, or new checker cases. Compare
actual source and error repair with Rust for both clients and implementers.
This proposal removes topology concepts, but it adds storage schemas and field
conditions. It does not yet establish that the complete source model meets the
Rust complexity ceiling. If the required programs need stronger user proof
machinery, stop this candidate instead of adding that machinery incrementally.

## 12. Research used

[Mezzo](https://cambium.inria.fr/~fpottier/publis/pottier-protzenko-mezzo.pdf)
separates affine and duplicable permissions. Its adoption and abandon mechanism
uses dynamic ownership checks. That mechanism is not a solution under the
zero-runtime-bookkeeping requirement.

[Verus's linear ghost types](https://arxiv.org/abs/2303.05491) separate executable
pointers from erased permissions. Its
[doubly-linked example](https://github.com/verus-lang/verus/blob/main/examples/doubly_linked.rs)
uses explicit ghost state and proof code. This supports the feasibility of
zero-runtime permission tracking, not a claim of simple container authoring.
Here the checker, rather than the library author, must manage such proof state.

[VCC](https://www.microsoft.com/en-us/research/publication/vcc-a-practical-system-for-verifying-concurrent-c/)
uses modular contracts and object invariants for C verification. Its lesson here
is that invariant dependencies and mutation boundaries must be explicit. Merely
adding a `where` expression does not make it safe to assume that expression
after arbitrary writes.

These are design inputs, not evidence that this proposal is a new theorem or
that its implementation has met the acceptance gate.
