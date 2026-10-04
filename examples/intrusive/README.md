<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: modular ownership for intrusive lists

Start with the [ownership guide](../../docs/ownership.md) for moves, loans,
cleanup, and returned views. The [Rust comparison](../../docs/ownership-rust.md)
separates client syntax from container implementation obligations.

This tutorial documents a specialized reciprocal-list verifier. Its member,
anchor, and isolation rules depend on list topology. The implementation fails
the [generic ownership requirement](../../docs/design.md#checked-ownership-target).
Its passing tests establish the declared list contract only. Keep them as
executable evidence; do not extend these special rules as the language model.

This program uses ordinary `prev` and `next` pointers. Each node has one owner
and two independent hooks. A destructor detaches both hooks, then releases that
node. A head destructor detaches its members without destroying them. Nodes can
be destroyed and allocated again while the heads and other owners remain live.

The [root](main.crs) selects an external ownership stage. The stage checks each
function from its own body and declared interfaces. It does not expand callees
or start a whole-program proof at `main`. The C99 seed has no new operation.

The [recursive owner tutorial](recursive/README.md) extends this program to a
runtime node count. It uses an explicit owner chain and recursive functions.

## Build and run

```sh
make all ownership-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/intrusive/main.crs
build/intrusive-checked
```

The output is `OK` and a newline. Use `Z3_FLAGS=-lz3` when the Z3 development
library is installed. Z3 checks the link implementations during compilation.
The compiled program does not depend on Z3.

Check the link library without a client or entry function:

```sh
build/crust-ownership-test --library --check examples/intrusive/links.crs
```

The compilation root takes compiler arguments when arguments are supplied.
All provider definitions are checked before emission. A separate publication
operation can save their verified interfaces and object code for client builds.

## Reuse a verified library

The compilation program can load [library_model.crs](../../stages/ownership/library_model.crs)
and [library_api.crs](../../stages/ownership/library_api.crs), then call these
operations from the same ownership stage library:

```crust
if ownership_publish(provider_request, cache_directory, library_receipt) != 0i32 { return 1i32; }
return ownership_import_program(client_request, imports);
```

Both requests use the ordinary `CrustBuild` interface. Publication accepts
provider sources and C compilation flags. It checks each function, emits an
object, and saves one bundle that contains the object and the complete source
interface. The generated interface keeps types, field roles, effects, destructor
names, and returned-view origins. It contains no function bodies. Publication
compiles the provider on each call; it does not cache GCC execution.

`OwnershipLibrary` contains the artifact path and its SHA-256 digest.
`OwnershipImports` selects an absolute cache directory and an array of these
receipts. The trusted compilation program must retain receipts from successful
publication. Receipt strings belong to the provider request context; copy them
before that context is destroyed. A digest supplied with an untrusted object
does not establish that its contracts were checked.

The cache directory must belong to the caller and have no untrusted writers.
The bundle binds its interface and object to the exact checker executable and
loaded library images. A changed checker requires new publication. Imported
record layouts are checked by that same compiler. Changing the saved object,
contract, or type bytes fails the retained digest check, even if the cache
checksum file is also changed.

Import captures the bundle once and links a private object copy from those
bytes. Replacing the published path cannot replace the object used for linking.
Client checking uses the verified interfaces, without reading provider sources
or making solver calls for their bodies. The current compiler host still links
Z3. New client link-function bodies still require their own proofs. Imports
support linked output and `--check`; C-only and object-only output reject because
they cannot retain the imported object dependencies.

```sh
make check-ownership-imports Z3_FLAGS=-l:libz3.so.4
```

This check publishes the intrusive provider, removes its source files, builds a
separate client process with a solver trap, and runs the result. It also checks
changed artifacts, changed checker images, replacement during linking, and
compiler allocation failures.

## Declare storage and access

The [complete program](program.crs) declares these facts:

```crust
record Hook { prev: *Hook; next: *Hook; } reciprocal(prev, next);
record Node { ready: Hook; active: Hook; value: i64; }
    members(ready, active) domain(Graph);
resource Owner { node: *Node; } owns(node) domain(Graph) drop owner_drop;
resource ReadyHead { hook: Hook; }
    anchor(hook, Node.ready) domain(Graph) drop ready_drop;
```

`reciprocal` pairs inverse pointer fields. `members` declares their exact
containing fields. `Node.ready` and `Node.active` are separate families with the
same physical layout. `anchor` declares a head that has no node payload. The
example uses a separate head type for each family; it requires no generic types.

`owns(node)` gives the resource exclusive destruction authority for that
allocation. A move transfers that authority. Reading the pointer gives a cursor,
not a second owner. Construction requires initialized payload and hooks before
publication. Linked storage stays at its address. Self-linked storage also stays
at its address, because its own fields contain that address.

`Graph` names access authority. It is not an allocator, pool, or runtime object.
All hooks and the owner of one allocation share the same domain.

| Interface | Permission |
| --- | --- |
| `access(read, Graph)` | Read storage in the domain. |
| `access(edit, Graph)` | Edit links through checked relation functions. |
| `access(reclaim, Graph)` | Create owners and destroy them when no domain cursor is live. |
| `read Graph { ... }` | Restrict this scope to reads. |
| `edit Graph { ... }` | Restrict this scope to edits; destruction is excluded. |

A saved cursor has a lexical lifetime. It cannot escape its access scope.
Reclamation rejects any live cursor in that domain, including a saved neighbor.
End the scope before destruction and obtain a new cursor afterward.

## Check the link implementation

The [link library](links.crs) adds contracts to normal pointer code:

```crust
fn unlink(h: *Hook) -> unit links(edit, Hook) cursor(h) isolated(h) {
    var before: *Hook = (*h).prev;
    var after: *Hook = (*h).next;
    (*before).next = after;
    (*after).prev = before;
    (*h).prev = h;
    (*h).next = h;
}
```

Every body must prove its declared results. `cursor` accepts an initialized
member or anchor. `member` excludes anchors. `construct` requires fresh stable
storage and establishes an initialized isolated hook. `isolated(h)` requires
both links to point to `h` on return. Reciprocity then excludes incoming paired
links from other hooks. Isolation alone does not grant destruction authority.

Insertion accepts a member and can call `unlink` through its contract. Splice
requires two anchors. Its `isolated(source) unless_same(source, at)` result is
conditional on distinct arguments. Parameter names bind the contract; annotation
order does not change argument meaning.

The relation checker models arbitrary hooks, not a fixed number of nodes. It
checks each access and proves inverse fields at calls, returns, and loop edges.
Temporary broken inverses are permitted between stores. A call cannot observe
them. The head-drain loop uses the same invariant for an arbitrary iteration;
there is no unfolding count or termination proof.

## Detach before destruction

```crust
fn owner_drop(owner: mut Owner) -> unit access(reclaim, Graph) {
    var node: *Node = move owner.node;
    if node != null(*Node) {
        edit Graph {
            unlink(&(*node).ready);
            unlink(&(*node).active);
        }
        release(node as *u8);
    }
}
```

The resource drop entry receives destruction authority for its handle or stack
place. Ordinary mutable helper calls do not acquire that authority. The first
unlink establishes isolation for `ready`. Editing `active` preserves it because
the families have separate fields. Release requires both results and the unique
allocation owner. No runtime clear store or ownership flag is needed.

The program moves its first owner into a smaller scope. Cleanup removes that
node while the second node and both heads remain live. It then creates and
removes a replacement. Head cleanup detaches the survivor before stack storage
expires. Its owner destroys it at function return.

The foreign declarations are the explicit trust boundary. `foreign(allocate)`
means a null result or fresh aligned storage of the requested size.
`foreign(release)` consumes an allocation base. `foreign(scalar)` permits no
pointer arguments, program-memory access, or callback. The stage checks their
source signatures; it does not verify C library implementations.

## Read the containing node

```crust
read Graph {
    var cursor: *Hook = active.hook.next;
    if cursor == &active.hook { trap; }
    var node: *Node = parent(Node.active, cursor);
    if (*node).value != 66i64 { trap; }
}
```

A cursor followed from a head retains that head association. Excluding that
head proves an exact member origin. `parent` then lowers to a constant byte
offset subtraction. The example checks both offsets, including the nonzero
`active` offset. An unrelated head comparison cannot authorize projection.

The checker uses erased group identities to prove that a member cursor cannot
silently refer to another anchor. Edits invalidate head associations in that
family. A member origin already proved before an edit remains valid while the
allocation lives. No colors, tags, or hidden arguments reach the target.

Projection gives a read-only payload view. Pointer or owner-bearing payload
fields require an additional field-loan contract to preserve alias identity;
this stage rejects them. It does not fabricate new owners from a projection.

## Traverse with a shared cursor

```crust
fn ready_count(head: read ReadyHead) -> usize access(read, Graph) {
    read Graph {
        var count: usize = 0usize;
        var cursor: *Hook = head.hook.next;
        while cursor != &head.hook {
            var node: *Node = parent(Node.ready, cursor);
            if (*node).value < 0i64 { trap; }
            count = count + 1usize;
            cursor = (*cursor).next;
        }
        return count;
    }
}
```

The checker infers a loop invariant from the cursor's declared family and head
association. It checks one arbitrary iteration. Every path back to the condition
must preserve that family, head, and access lifetime. The condition excludes the
head before each payload read. Advancing the cursor requires that check again.
No loop bound, user invariant, or termination proof is required.

The cursor remains borrowed for the enclosing `read` scope. It cannot escape
that scope. The loop cannot edit links or reclaim storage. The checker does not
carry facts from one particular iteration to the exit. The program checks empty,
two-member, and one-member lists, with forward and backward traversal.

## Connect the stages

The [ownership stage](../../stages/ownership/program.crs) combines the ordinary
reader and resource lowering with two checks:

1. The [relation stage](../../stages/relations/check.crs) checks each declared
   link body. Calls use only registered interfaces. Missing stores and incorrect
   unused functions fail before emission.
2. The local ownership checker checks each other body. It tracks initialization,
   unique owners, fixed addresses, cursor scopes, and cleanup obligations.
   Resource types and function effects provide the facts at each boundary.

The original resource emitter supplies RAII cleanup. The checker accounts for
normal scope exit, return, and discarded owner results. It rejects borrowed
fields of anonymous owner temporaries. Such a view would require an explicit
expression lifetime because the resource lowering destroys that temporary.

## Borrow payload and return a view

A named `read T` loan permits shared reads until its scope ends. A named `mut T`
loan permits exclusive access. A reborrow prevents conflicting use of its parent
until the child scope ends. Ordinary helpers can accept either mode. A domain read parameter requires a
read-only function effect. Mutable helpers can read or edit; resource callbacks
receive destruction authority. Evaluate nested calls before passing borrow
arguments. Scalar copies do not retain the source loan.

A returned view declares its origin with the existing `from` clause:

```crust
fn node_view(owner: read Owner) -> read Node access(read, Graph) from owner.node {
    if owner.node == null(*Node) { trap; }
    return read *owner.node;
}

fn value_mut(node: mut Node) -> mut i64 access(edit, Graph) from node.value {
    return mut node.value;
}
```

Each definition must prove that origin on every return. A caller uses the
signature and keeps the input loan alive for the result. The source syntax
accesses a view directly:

```crust
edit Graph {
    var value: mut i64 = value_mut(mut *second.node);
    value = 66i64;
}
read Graph {
    var node: read Node = node_view(read second);
    if node.value != 66i64 { trap; }
}
```

`first_hook` returns `read Hook from head.hook.next`. Its result can include the
head. `first_node` uses the same path with result type `read Node`; its body must
exclude the head and prove the exact member field before projection. A reciprocal
path names a family and ring origin, not a fixed list length or position. A
caller can take the address of the returned hook view and traverse that ring.
The complete program exercises both interfaces.

Payload loans retain allocation and field identity through owned pointers.
Projections can read embedded resources and their owned payload. An arbitrary
member projection grants shared access; it cannot transfer an owner. Mutable
access uses an exclusive loan from checked storage. A link edit can touch
neighbors, so direct edits and `access(edit, Domain)` calls exclude other live
loans in that domain, except the loans passed to the operation. Reclamation
excludes every active domain loan, including a view of one scalar field.

A mutable helper can exchange owned pointer fields. Its caller discards prior
pointer facts and must check nullable fields again before access. An owner
returned from a by-value owner input can reuse that input's storage. The checker
retains that possible alias relationship with earlier cursors. It does not
inspect the helper body to derive either rule.

## Destroy embedded resources

[fields.crs](fields.crs) adds two resource payloads to a node. Each payload owns
an allocation. [fields-main.crs](fields-main.crs) selects the same stage:

```sh
build/crust examples/intrusive/fields-main.crs
build/intrusive-fields
```

The output is `BABAOK` and a newline. Each node destroys its second payload before
its first. The example destroys one node explicitly and a replacement at scope
exit while the head stays live. It also reads an owned payload through a checked
member projection.

The node destructor first detaches both hooks, then uses:

```crust
drop *node;
release(node as *u8);
```

`drop *node` destroys the stored value in place. It does not release the outer
allocation. The resource callback runs first; embedded resources then drop in
reverse field order. A callback must consume its raw owned pointers and leave
embedded resource values initialized for this automatic field cleanup.

`drop owner;` consumes a whole local owner and prevents a second scope-exit drop.
Dropping a field separately is rejected: the containing value still has an
unconditional field cleanup obligation. A heap value with resource fields must
be destroyed before release. Linked hooks, active loans, partial initialization,
and a second destruction reject. These checks add no target flags, pointer tags,
or validity checks. They reuse the original cleanup emitter.

## Keep the interface boundary explicit

Stored raw pointer fields still require an owner or reciprocal-field contract.
Borrowed record fields require a declared stored-lifetime relationship; the stage
has no such field form and rejects them. Raw pointer results must instead use a
borrowed result with `from`. Deferred actions and changes to loop-carried owner
sets also reject. Accepting changing owner sets requires a local loop invariant
for ownership and initialization; the read-cursor invariant supplies only
traversal. No whole-program proof fills in these missing interfaces.

For the Rust comparison, clients use affine moves, scoped loans, and address
stability. Container authors add inverse fields and role, effect, and result
contracts. They write no solver terms or ghost lemmas. Lexical scopes and domain
exclusion can reject code that Rust accepts with narrower inferred loans. The
separate verified provider and client now cover returned views and nested
resources and a recursive runtime-sized owner chain. The iterative owner-loop
rule and broader container comparison in
the [acceptance gate](../../docs/design.md#checked-ownership-target) remain
necessary before adding another ownership mechanism.

## Test the boundary

```sh
make check-ownership Z3_FLAGS=-l:libz3.so.4
python3 tests/ownership.py --sanitize
python3 tests/ownership_fields.py --sanitize
python3 tests/ownership_loans.py --sanitize
make check-ownership-alloc Z3_FLAGS=-l:libz3.so.4
```

Tests check valid native output at `-O0` and `-O2`, exact-address allocation reuse,
allocation failure cleanup, and relevant rejections. They compare emitted C and
symbol maps before and after both checks. The bytes must be equal before backend
optimization. Compiler allocation tests inject failures with ASan, UBSan, and
leak detection. Generated results stay in the ignored build directory.

## Closed-program proof examples

[closed-main.crs](closed-main.crs) and [closed-program.crs](closed-program.crs)
retain the earlier resource-memory witness. That checker expands calls or uses
concrete effect templates. It also reconstructs complete source scopes and
cleanup chains. It is a separate profile, not the modular checker above.

```sh
make resource-memory-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/intrusive/closed-main.crs
build/intrusive-closed
```

The root selects `unlink` through `PmOptions.summaries` and `summary_count`.
The checker derives a concrete effect template from its straight-line body.
Other calls expand their bodies. Set those fields to `null(**u8)` and `0usize`
to expand every call. Neither choice supplies a modular library contract.
The selected function must have a unit result, no calls or local storage, and
supported scalar operations. Unsupported shapes reject before output.

This profile follows source storage scopes, deferred captures, and retained
cleanup plans, as well as the lowered operation tree. Owner transfers consume
initialized-field permissions without a runtime clear store. Its loop bound
must prove that each loop stops before the bound. It checks stack expiry,
double release, stale aliases, and links that remain at destruction. It does
not substitute this complete execution for the modular interface rules above.

### Check a declared call contract

[contract-main.crs](contract-main.crs) checks an exact finite-write contract for
`unlink`, including unchanged memory outside the effect. The target is
[closed-program.crs](closed-program.crs). The [contract](contract.crs) uses public
memory-stage operations to describe reads, writes, and conditions. It is a
proof experiment with user-written terms, not a requirement of the modular model.

```sh
make memory-contract-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/intrusive/contract-main.crs
build/intrusive-contract
```

### Check a runtime-sized traversal

[walk-main.crs](walk-main.crs) checks [walk.crs](walk.crs) with the earlier
read-only inductive loop stage. It requires unchanged memory and a decreasing
integer variant. Mutable graphs require another frame rule and reject that
profile. The modular head-drain rule above does not require a variant.

```sh
make memory-loop-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/intrusive/walk-main.crs
build/intrusive-walk
```

[output-main.crs](output-main.crs) checks [output-init.crs](output-init.crs), where
helpers initialize uninitialized stack hooks through output pointers. Its complete
resource-memory proof includes cleanup before stack storage expires.

[raw-main.crs](raw-main.crs) builds [raw.crs](raw.crs), the unchecked seed witness
used for backend bootstrap and C reference comparisons. `make witness` runs that
case. It is not an ownership proof.
