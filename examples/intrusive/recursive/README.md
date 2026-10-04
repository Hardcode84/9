<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: a runtime-sized owner chain

This example retains a runtime number of heap nodes. Each node belongs to two
intrusive lists. The program removes one node, allocates a replacement, and
then destroys both list heads while the nodes remain alive.

Read the [basic intrusive tutorial](../README.md) first. This example uses the
same specialized list verifier and ownership stage. Recursive owned fields
add no syntax or compiler-core API. The combined example still depends on
reciprocal fields and anchor roles, so it does not pass the
[generic ownership gate](../../../docs/design.md#checked-ownership-target).

## Build and run

Run from the repository root:

```sh
make all ownership-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/intrusive/recursive/main.crs
build/intrusive-recursive one two three
```

Each argument requests one node. The argument text is not read. The output is
`OK` and a newline. No arguments selects an empty chain. Allocation failure
returns status 1 after cleanup. Use `Z3_FLAGS=-lz3` with the development library.

## Separate ownership from membership

The [target program](program.crs) declares:

```crust
resource Chain { node: *Node; } owns(node) domain(Graph) drop chain_drop;
resource Node { ready: Hook; active: Hook; owned_next: *Node; value: i64; }
    owns(owned_next) members(ready, active) domain(Graph) drop node_drop;
```

`Chain.node` owns the first allocation. `Node.owned_next` owns the next
allocation. A null pointer ends the chain. This recursive field uses the same
`owns` contract as a non-recursive field.

The `ready` and `active` hooks each contain ordinary `prev` and `next` pointers.
They describe list membership. They do not own allocations. Head cleanup can
therefore detach all members without destroying the owner chain.

`owned_next` is an explicit data-structure choice. It costs one pointer per
node in addition to the two hooks. The stage does not insert it. This example
does not establish that a container can own all nodes through a reciprocal
hook alone. There is no pool, node tag, reference count, or runtime owner flag.

## Build and remove nodes

`chain_new(count)` constructs the tail through a recursive call. `chain_push`
then allocates the next node, transfers the tail, and initializes both hooks
at their final address. Each function is checked against its declared types
and effects. The checker does not expand the recursive call.

`chain_push` consumes its input chain. If allocation fails, it destroys that
input and returns an empty chain. `chain_new` propagates this result, so a
nonzero request produces either the complete chain or an empty chain. The
client checks for null before attaching nodes.

`chain_pop` transfers the tail into a new handle:

```crust
var rest: Chain = make Chain { node: move (*node).owned_next };
(*node).owned_next = null(*Node);
drop *node;
release(node as *u8);
return move rest;
```

The null assignment leaves the node ready for its destructor. `drop *node`
runs the callback, which detaches both hooks. `release` then frees that one
allocation. The remaining chain stays alive. The example inserts a replacement
while both heads remain live.

A full chain drop uses the same contracts. `node_drop` destroys the owned tail
and then detaches its own hooks. The callback must consume `owned_next` and
leave both hooks isolated. Releasing a linked node or leaving an owned field
unconsumed is rejected.

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

Construction, attachment, and destruction use a call stack proportional to the
node count. Select this source only when the maximum count fits the available
stack. A constant-stack version needs a local invariant that permits an outer
owner to change on each loop iteration. The current loop rule preserves outer
owner identity and rejects that operation. Recursive types do not supply that
loop rule.

The stage also excludes active loans across a whole domain. A helper that
receives both heads cannot edit one family while it holds the unused loan to
the other head. This source uses separate `attach_ready` and `attach_active`
passes. Narrower family effects would need to specify all storage that a call
can change, including storage reached through reciprocal links.

The [Rust comparison](../../../docs/ownership-rust.md#recursive-owners) explains
which parts correspond to `Option<Box<Node>>`. It does not claim a complete
safe Rust implementation of the same intrusive API.

## Validate the contracts

```sh
make check-ownership check-ownership-imports Z3_FLAGS=-l:libz3.so.4
python3 tests/ownership_recursive.py --sanitize
make check-ownership-alloc Z3_FLAGS=-l:libz3.so.4
```

The tests execute empty and nonempty chains at `-O0` and `-O2`. The count can
exceed the source nesting limit. They check exact-address reuse, allocation
failure cleanup, emitted-code erasure, and rejected lifetime errors.

A separate test publishes the provider, deletes its source files, and checks
the client from the retained interface and object. It disables solver calls
for that client. The import must still reject a saved cursor across node
reclamation. Compiler allocation tests also cover the recursive input.
