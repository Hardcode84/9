<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: intrusive lists with ordinary ownership contracts

This example stores two sets of links in each allocated node. Each node has an
independent owner. A node can leave both lists, be destroyed, and have its
allocation reused while the other nodes and heads remain live.

The ownership stage knows about storage, retained references, access, and
function conditions. The list implementation is ordinary Crust code in
[links.crs](links.crs). Its types and ownership operations are in
[program.crs](program.crs). No list operation is registered with the stage.

## Build and run

Install the Z3 library and a system C toolchain, then run:

```sh
make ownership-stage
build/crust examples/intrusive/main.crs
build/intrusive-checked
```

The program prints `OK`. It checks empty traversal, insertion, two memberships,
forward and backward traversal, payload views, early destruction, reuse, and
cleanup of heads before the remaining node owner.

Use `Z3_LIBDIR` if the Z3 library is in a separate directory. Ownership checking
is an explicit stage choice; the C99 seed does not load a solver.

## Declare the storage interface

The domain lists every storage type that can retain an address:

```crust
domain Graph(Node, Owner, ReadyHead, ActiveHead);
record Node {
    prev: *Node; next: *Node;
    active_prev: *Node; active_next: *Node;
    value: i64;
} domain(Graph) references(prev, next, active_prev, active_next)
  invariant((*self).prev != null(*Node) && (*self).next != null(*Node) &&
            (*(*self).prev).next == self && (*(*self).next).prev == self)
  invariant((*self).active_prev != null(*Node) && (*self).active_next != null(*Node) &&
            (*(*self).active_prev).active_next == self &&
            (*(*self).active_next).active_prev == self);
resource Owner { node: *Node; } owns(node: storage) domain(Graph) drop owner_drop;
```

The four retained pointer fields are ordinary machine pointers. The conditions
state the equations the implementation must preserve. They also require live,
initialized targets through the ordinary `references` contract.

The owner pointer has a different duty: it must be moved or destroyed exactly
once. A traversal cursor cannot acquire that duty by copying a node address.

Each head contains a full `Node` as a sentinel. The unused payload and second
set of links occupy their declared space. This keeps every traversal pointer
of type `*Node`; payload access is a normal field access. The example needs no
pointer type conversion or containing-object operation.

## Construct in final storage

`node_init(node, value)` declares `initializes(node)`. It writes all fields,
forms the self-links, and establishes the type conditions. Its precondition
requires a non-null pointer. `owner_new` tests allocation failure before it
calls the constructor, then moves the allocation into `Owner.node`.

The head is first made with explicit placeholder values. Its constructor then
runs at the head's final address. Once storage is published through its type,
the stage rejects relocation of that storage and its containing record.

There is no pool, allocation table, generation check, pointer tag, or hidden
runtime pin object. The source calls `malloc` and `free` through their declared
foreign contracts.

## Check an ordinary update

The ready-list removal function is:

```crust
fn ready_unlink(node: *Node) -> unit access(edit, Graph)
    modifies(Node.prev, Node.next)
    requires(node != null(*Node))
    ensures((*node).prev == node && (*node).next == node) {
    var before: *Node = (*node).prev;
    var after: *Node = (*node).next;
    (*before).next = after;
    (*after).prev = before;
    (*node).prev = node;
    (*node).next = node;
}
```

`modifies` names the field classes this function can change. The active links
and payload keep their values. The body must establish its postcondition and
restore the conditions of every live object in the domain.

The stage derives these obligations from the declarations. It does not infer a
container operation from the function name. Renaming the types, functions, and
fields leaves the checks unchanged.

The active-list functions use their own two fields. Insertion first calls the
verified removal interface, then connects the node at its new position. Calls
use preconditions, postconditions, and changed fields. They do not expand
callee bodies.

## Destroy a node

`owner_drop` moves out the allocation owner, enters an edit scope, and calls
both removal functions. After that scope ends, it releases the allocation.

The release check asks whether any surviving declared reference field can
still point to the node. The query includes an arbitrary live source object.
It is not restricted to nodes allocated by `main` or by a test fixture.
Omitting either removal leaves a possible incoming reference and is an error.

A head destructor drains its selected list and clears its other link set.
The complete `Node` type permits either membership, so destruction accounts
for both. This rule follows from the declared fields. It is also why adding
another retained reference field can require a change to destruction code.

The head does not own the nodes. Its cleanup leaves the node owners live.
A later owner destructor can release each node separately.

## Traverse and borrow payload

A read scope permits cursor traversal. Each iteration reads a typed `Node`
pointer, accesses its payload, and follows the selected field. The loop check
uses the declared type conditions and an inductive cursor state; it has no
maximum list length.

`node_view`, `value_view`, and `value_mut` show returned loans. Their `from`
paths name the storage that keeps each result valid. A live payload loan
prevents a conflicting edit or reclamation. A cursor from a read or edit scope
cannot escape that scope.

## Embedded and recursive ownership

[fields.crs](fields.crs) adds two resource fields to each node. It demonstrates
reverse field cleanup, destruction of a heap value before its allocation is
released, and allocation failure during construction:

```sh
build/crust examples/intrusive/fields-main.crs
build/intrusive-fields
```

The [recursive tutorial](recursive/README.md) uses a recursive owning chain
with a runtime node count. The list links remain non-owning. The owning field
is checked through its declared interface, without expanding the full chain.

## Verify the emitted program and the boundary

```sh
make check-ownership check-ownership-imports check-ownership-alloc
```

The tests run generated native programs, force allocation failures, reuse an
exact allocation address, and compare C output before and after verification.
They also reject incomplete updates, invalid conditions, undeclared writes,
stale cursors, owner copies, and release with a surviving retained reference.

The compilation program can publish a checked object and a bodyless interface
with `ownership_publish`, then import the pair with `ownership_import_program`.
The receipt binds the interface, object, and checker. Consumers verify their
own bodies against that interface; provider source is not required.

## Other proof profiles

These source roots select separate stages. They do not change the ownership
contracts above.

| Root | Build target | Check |
| --- | --- | --- |
| [raw-main.crs](raw-main.crs) | `all` | Compile the raw pointer program |
| [closed-main.crs](closed-main.crs) | `resource-memory-stage` | Check the complete client, including cleanup, with call and loop budgets |
| [contract-main.crs](contract-main.crs) | `memory-contract-stage` | Check declared library contracts and their callers |
| [walk-main.crs](walk-main.crs) | `memory-loop-stage` | Check an inductive traversal before cleanup |

The three proof stages require Z3. The raw program is a bootstrap witness;
compiling it does not establish memory safety. See the
[static memory tutorial](../ownership/README.md) for the direct memory checks.
