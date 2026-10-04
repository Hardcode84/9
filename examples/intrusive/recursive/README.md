<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: a runtime-sized owner chain

This example retains a runtime number of heap nodes. Each node belongs to two
intrusive lists. The program removes one node, allocates a replacement, and
then destroys both list heads while the nodes remain alive.

Read the [basic intrusive tutorial](../README.md) first. This example uses
the same storage schemas, ordinary field conditions, and function interfaces.
Recursive owned fields add no syntax or compiler-core API.

## Build and run

Run from the repository root:

```sh
make all ownership-stage
build/crust examples/intrusive/recursive/main.crs
build/intrusive-recursive one two three
```

Each argument requests one node. The argument text is not read. The output is
`OK` and a newline. No arguments selects an empty chain. Allocation failure
returns status 1 after cleanup. Install the Z3 development library before the build.

## Separate ownership from membership

The [target program](program.crs) declares:

```crust
resource Chain { node: *Node; } owns(node: storage) domain(Graph) drop chain_drop;
resource Node { prev: *Node; next: *Node; active_prev: *Node; active_next: *Node; owned_next: *Node; value: i64; }
    owns(owned_next: storage) domain(Graph)
    references(prev, next, active_prev, active_next)
    invariant((*self).prev != null(*Node) && (*self).next != null(*Node) &&
              (*(*self).prev).next == self && (*(*self).next).prev == self)
    invariant((*self).active_prev != null(*Node) && (*self).active_next != null(*Node) &&
              (*(*self).active_prev).active_next == self && (*(*self).active_next).active_prev == self) drop node_drop;
```

`Chain.node` owns the first allocation. `Node.owned_next` owns the next
allocation. A null pointer ends the chain. This recursive field uses the same
`owns` contract as a non-recursive field.

The `prev`/`next` and `active_prev`/`active_next` fields are ordinary pointers.
They describe list membership. They do not own allocations. Head cleanup can
therefore detach all members without destroying the owner chain.

`owned_next` is an explicit data-structure choice. It costs one pointer per
node in addition to the four list pointers. The stage does not insert it.
A retained pointer does not carry a destruction duty. There is no pool, node
tag, reference count, or runtime owner flag.

## Build and remove nodes

`chain_new(count)` starts with an empty chain and replaces it in a loop:

```crust
var chain: Chain = make Chain { node: null(*Node) };
var index: usize = 0usize;
while index < count {
    chain = chain_push(move chain);
    if chain.node == null(*Node) { return move chain; }
    index = index + 1usize;
}
return move chain;
```

`chain_push` allocates the next node, transfers the tail, and initializes both
link sets at their final address. Each function is checked against its declared
types and effects. The checker does not expand the call.

`chain_push` consumes its input chain. If allocation fails, it destroys that
input and returns an empty chain. `chain_new` propagates this result, so a
nonzero request produces either the complete chain or an empty chain. The
client checks for null before attaching nodes.

`chain_pop` first detaches the node, then transfers the tail into a new handle:

```crust
edit Graph { ready_unlink(node); active_unlink(node); }
var rest: Chain = make Chain { node: move (*node).owned_next };
(*node).owned_next = null(*Node);
drop *node;
release(node as *u8);
return move rest;
```

The null assignment leaves the node ready for its destructor. `drop *node`
runs the callback. Its removal calls also accept a detached node. `release` frees that one
allocation. The remaining chain stays alive. The example inserts a replacement
while both heads remain live.

A full chain drop uses the same operation in a loop:

```crust
fn chain_drop(chain: mut Chain) -> unit access(reclaim, Graph) {
    var node: *Node = move chain.node;
    if node == null(*Node) { return; }
    var rest: Chain = make Chain { node: move node };
    while rest.node != null(*Node) { rest = chain_pop(move rest); }
}
```

The empty case returns before it constructs a temporary chain. This prevents
cleanup of an empty temporary from calling itself without end. `chain_pop`
moves the tail out before it destroys the node. Thus that node's cleanup sees
an empty owned field. `node_drop` also supports direct destruction of a node
that still owns a tail: it detaches both link sets, transfers the tail, and
drops that chain through the same loop.

A transfer cannot leave a retained reference to an incomplete node. The callback
must consume `owned_next` and leave both link sets detached. Releasing a linked
node or leaving an owned field unconsumed is rejected.

## Check a recursive type with finite state

An initialized owned pointer promises a valid value of its declared type.
The checker retains that promise until the body accesses the pointee fields.
It then checks that record's fields. An owned child pointer retains its own
type promise; the checker does not enumerate the rest of the heap.

Field facts belong to each control-flow path. Reading a field in one branch
does not initialize that field in another branch. A branch can return to the
type promise only if it preserves initialization and ownership. A nullable
child remains nullable after the merge unless both paths establish otherwise.

These facts exist only in the stage. The emitted C and symbol map are identical
before and after ownership verification. No fold or unfold operation appears
in the source or the target program.

## Understand the costs of this source

Construction, attachment, traversal, and destruction use loops. Their call-stack
depth does not grow with node count. The type remains recursive.

At each owner-loop boundary, the chain must hold one initialized resource value.
The checker forgets its previous target and checks the body with the declared
type. A consumed chain must receive a valid replacement before the next iteration.
The loop cannot retain a cursor or loan across reclamation. These rules require
no loop annotation and insert no runtime owner state.

`attach` receives ordinary checked cursors and edit access. Its one loop updates
both list memberships. Its `modifies` clause names the four link fields and
preserves the owning field. The nested access scope bounds cursor lifetime.
It cannot destroy a node or take ownership through those cursors. A mutable-loan
interface would also have to obey domain-wide loan exclusion.

The [Rust comparison](../../../docs/ownership-rust.md#recursive-owners) explains
which parts correspond to `Option<Box<Node>>`. It does not claim a complete
safe Rust implementation of the same intrusive API.

## Validate the contracts

```sh
make check-ownership check-ownership-imports
python3 tests/ownership_recursive.py --sanitize
make check-ownership-alloc
```

The tests execute empty and nonempty chains at `-O0` and `-O2`. A separate native
run uses a bounded stack with a node count above the source nesting limit. The
tests check exact-address reuse, allocation failure cleanup, emitted-code erasure,
and rejected lifetime errors, including incomplete owners at loop boundaries.

A separate test publishes the provider, deletes its source files, and checks
the client from the retained interface and object. The client checks its own
code against the imported conditions.
The import must reject a saved cursor across node
reclamation. Compiler allocation tests also cover the recursive input.
