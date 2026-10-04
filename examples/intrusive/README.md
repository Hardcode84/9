<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: intrusive lists behind a checked interface

Keep direct `prev` and `next` pointers, independent node allocation, and stack
heads. Put the pointer algorithm behind an explicitly trusted opaque interface.
Check the client with local ownership and domain access rules. The node and
head fields are the complete runtime representation.

## Build and run

From the repository root:

```sh
make all ownership-stage
build/crust examples/intrusive/main.crs
build/intrusive-checked
```

The program prints `OK`. [main.crs](main.crs) captures [links.crs](links.crs)
as the trusted implementation and checks [program.crs](program.crs). This is a
root policy choice. An annotation in `links.crs` cannot grant itself trust.
The lower-level `os_trust(stage, declaration)` API can select individual
declarations, including declarations in the same source file as the client.

## Representation and obligations

`Node` has `prev`, `next`, `active_prev`, `active_next`, and a payload. `Owner`
has one node pointer. The two head types contain full sentinel nodes. `Cursor`
has one node pointer. These fields are the complete runtime representation.

| Annotation | Meaning |
| --- | --- |
| `opaque` | Client code cannot access or construct the representation. The root must approve the implementation. |
| `domain Graph(Node, Owner, ReadyHead, ActiveHead, Cursor);` | The list defines the types in this closed retention boundary. |
| `stable` | Construct in final storage; then prohibit relocation. |
| `scoped` | The value depends on the current read or edit scope; it cannot escape. |
| `drop owner_drop` | Cleanup calls this function. Its reclamation permission also applies to implicit cleanup. |

The trusted node destructor unlinks both hooks before `free`. Each head
destructor detaches its members before the sentinel dies. These duties cover
both destruction orders. External owners remain valid after head destruction.
A defect in these routines can cause memory errors. The stage does not prove
their pointer stores correct.

The representation is private to the whole selected implementation. A separate
checked module cannot add another retained raw pointer merely by naming Graph.
It must keep an ordinary loan, or the root must explicitly extend the trusted
boundary and its retirement contract.

## Construct and link

```crust
domain Graph {
    var owner: Owner = owner_new(65i64);
    var ready: ReadyHead = uninit;
    ready_init(&ready);
    ready_insert(mut ready, read owner);
}
```

The domain block creates a fresh static identity and reclamation permission.
It allocates no runtime object. A helper's `access(MODE, Graph)` parameter is
abstract in that identity. Helpers are checked once; calls do not specialize
bodies. Objects from different domain instances cannot mix.

`ready_init` declares `initializes(head)`. The head has no value and no cleanup
duty before the call returns. The call initializes its final stack storage and
makes it stable. The checker rejects a second construction or a later move.
Taking the address alone does not initialize storage.

Insertion borrows the handle without consuming it. Its edit contract permits
internal retention in the same domain and forbids destruction. Actual insertion
uses ordinary pointer loads and stores. It performs no ownership bookkeeping.
The domain block's reclamation permission permits this edit call. A read or
edit block is needed when the client creates scoped cursors and payload views.

## Traverse and borrow payload

```crust
read Graph {
    var cursor: Cursor = ready_first(read ready);
    var end: Cursor = ready_end(read ready);
    var done: bool = cursor_equal(read cursor, read end);
    while !done {
        { var value: read i64 = cursor_value(read cursor); }
        cursor_advance(mut cursor);
        done = cursor_equal(read cursor, read end);
    }
}
```

A cursor keeps the access scope alive. It does not expose a raw pointer or own
the node. It can move through the declared navigation interface. A payload view
is a separate loan. End that loan before a conflicting operation.
`cursor_mut` requires edit access. While its mutable result is live, the checker
rejects other calls that could access the same domain without that loan.

The example has no node-count bound. The local checker verifies one loop body
and its ownership-state backedge. The trusted library maintains the topology.

## Destroy and reuse

The complete client links two independent owners into both lists. It traverses,
destroys one owner, allocates a replacement while the heads remain live, and
checks both memberships. It then destroys the heads before the remaining owner.
The runtime test forces exact-address reuse and rejects double release.

Move `drop first` into an access block and compilation fails: retirement needs
reclamation permission. Move a cursor out of its block and compilation fails:
the destination would outlive its origin. Copy an owner, read `owner.node`, or
move an initialized head and compilation also fails. These are client checks;
a missing unlink store inside trusted code is a library bug.

## Verify the emitted program and the boundary

```sh
make check-ownership check-ownership-imports check-ownership-alloc
python3 tests/ownership.py --build build --sanitize
```

The tests execute C output at `-O0` and `-O2`, check client rejection, exercise
address reuse, and compare C and symbol output before and after verification.
The ownership pass adds no runtime code even before optimization.

For separate libraries, `ownership_publish` returns an `OwnershipLibrary`
receipt with artifact path, digest, and selected trust status. Retain all three
in the root. `ownership_import_program` validates the receipt, checks client
bodies against bodyless interfaces, and links captured objects. No provider
source is required. Tests change contract bytes, object bytes, checker images,
and trust status; each mismatch must fail.

The [owning-tree tutorial](../ownership-graphs/README.md) uses the same rules
for ownership transfer and parent links. The [ownership guide](../../docs/ownership.md)
starts with simpler resources, integer handles, and loans. The
[benchmark instructions](../../benchmarks/ownership/README.md) separate checking
cost from target GCC compilation and linking.

[raw.crs](raw.crs) and [raw-main.crs](raw-main.crs) retain the raw seed backend
witness. They do not select ownership checks or establish memory safety.
