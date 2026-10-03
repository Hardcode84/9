<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: checked intrusive links with RAII

This program gives each heap node an owner. The node has two ordinary hooks
and can belong to two lists. A node destructor removes both hooks and releases
that node. A head destructor removes the remaining members without destroying
them. No pool or shared allocation lifetime is required.

The [program](program.crs) has no `unsafe` region. Its raw pointer operations,
including the shared [link functions](../links.crs), pass the memory checker.
The selected stage combines the resource rules with that check. An `unsafe`
region in its input would not bypass the proof.

## Build and run

```sh
make all resource-memory-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/ownership/resources/main.crs
build/ownership-resources
```

The program prints `OK` and a newline. Use `Z3_FLAGS=-lz3` with the Z3
development library, or select a library directory with `Z3_LIBDIR`.
The [root](main.crs) selects the stage, foreign effects, proof budgets, source
files, and output. The C99 core has no new syntax, policy, or library dependency.

## Follow the lifetimes

`Owner` contains one node pointer. `Head` contains a hook. Both are resource
types with ordinary Crust destructors. The program creates two owners, then
creates the heads in an inner scope and inserts both nodes into both lists.

A smaller scope takes the first owner with `move`. At its end, that owner
unlinks both hooks and releases the node. The other owner and both heads remain
live. At the end of the head scope, both head destructors detach the second
node. Its owner releases it when the function returns. Failed allocation also
returns through the applicable cleanup chains.

## Use the complete annotations

The target declarations and destructors are:

```crust
record Node { ready: Hook; active: Hook; value: i64; }
resource Owner { node: *Node; } drop owner_drop;
resource Head { hook: Hook; } drop head_drop;

fn owner_drop(owner: mut Owner) -> unit {
    var node: *Node = move owner.node;
    if node != null(*Node) {
        unlink(&(*node).ready);
        unlink(&(*node).active);
        release(node as *u8);
    }
}

fn head_drop(head: mut Head) -> unit {
    while head.hook.next != &head.hook { unlink(head.hook.next); }
}
```

`Hook` and both link operations come from [links.crs](../links.crs). They use
ordinary pointer fields and stores. The checker executes their actual bodies.
They have no trusted unlink declaration or additional ownership annotation.

| Source annotation | Contract |
|---|---|
| `resource Owner ... drop owner_drop` | Each live owner has one automatic cleanup obligation. |
| `resource Head ... drop head_drop` | Each live head has a cleanup obligation to detach its members. |
| `mut Owner` and `mut Head` | The destructor receives a mutable loan. |
| `move owner.node` | Read the pointer once, then consume permission to read that field. |
| `{ var early: Owner = move first; }` | Transfer the owner to this scope. Run its drop at the scope's end. |

A pointer move leaves the source bits unchanged. It emits no null store. The
source field cannot be read again, including through an alias, until a new
assignment initializes it. Other fields remain available. Saved copies of the
pointer can still access the live allocation; release makes their accesses
invalid. A separate live field that retains the pointer still blocks release.
The rule applies to pointer variables, fields, array elements, and indirect
places. It gives destructors no permission to skip checks.

The root supplies the three foreign-effect contracts:

```crust
var contracts: [PmForeignSpec; 3] = make [PmForeignSpec; 3] {
    make PmForeignSpec { name: "allocate", alignment: 16usize, kind: PM_ALLOCATE },
    make PmForeignSpec { name: "release", alignment: 1usize, kind: PM_RELEASE },
    make PmForeignSpec { name: "emit", alignment: 1usize, kind: PM_SCALAR }
};
```

These describe trusted foreign behavior. `allocate` returns null or a fresh
allocation of the requested size and alignment. `release` accepts null or a
live allocation base and ends that allocation. `emit` has scalar effects and
does not access program storage or call back into it. The selected C library
functions must meet these contracts; the checker does not inspect their bodies.
The allocation entry specifies its storage alignment. Other entries use
`alignment: 1usize`.

The [complete root](main.crs) loads the combined stage, passes this table and
explicit proof budgets, and selects both source files. It sets depth, path,
loop, and per-query solver limits. Reaching a limit rejects the compilation;
it does not permit a memory operation. There are no omitted lifetime, ring,
allocator, or destructor annotations in the [complete program](program.crs).

## Connect the stages

Resource lowering hoists C storage and retains cleanup outside the operation
tree. Checking that tree alone would miss cleanup and extend source lifetimes.
The [adapter](../../../stages/resource_memory/view.crs) uses the retained
resource plan to supply a complete proof view:

1. Put uninitialized storage in its original lexical scope. Extend a deferred
   capture to the scope that owns its deferred call.
2. Execute each exit's cleanup chain in order. This includes return, break,
   continue, and normal scope exit.
3. End the inner scope's storage before an outer cleanup runs. All storage in
   one scope ends together, after that scope's cleanup.
4. After an owning copy or pointer move, remove initialized-field permissions
   from the source. Reading that source through a saved raw alias then fails.

A return captures its result before cleanup. Aggregate copies read a snapshot
of the complete source. The resource stage lowers aggregate arguments and
results to ordinary pointer operations, which the memory stage can check.
Full calls on assignment right-hand sides execute their actual bodies and keep
all resulting paths.

These views and permissions exist only in the compiler. Emission still uses
`rs_c_body` and the original checked operations and cleanup plans. The tests
compare C output from both stages on identical accepted resource input. They
also compare pointer moves with plain reads to detect added target operations.
They execute the output at `-O0` and `-O2`. No optimization is needed to erase
proof state.
The source's copies, pointer stores, drop calls, and ordinary seed checks remain.

## Select the contract

The ordinary resource stage requires explicit `unsafe` regions for raw access.
The combined stage calls `rs_prepare_with_access` to delegate that access check
to the memory proof. It retains the resource stage's move and loan rules.
The combined driver emits only after both checks pass. Foreign effects retain
the explicit trust boundary described in the [memory tutorial](../README.md).
Raw aliases obey the memory-access proof. This does not establish exclusive
borrowing for every raw pointer value or a concurrency rule.

This profile checks a closed sequential entry. It expands actual calls and must
prove that each loop stops within the selected unfolding bound. Solver timeout,
unknown results, unsupported operations, and allocation failure stop output.
There is no unchecked fallback. Larger programs need verified call summaries
and loop invariants to avoid repeated body expansion; neither is consumed here.
The separate ring proof is not silently substituted for a caller proof.

Moves consume initialized-field permissions. Destruction can consume one
pointer field and continue to use other fields. Subsequent calls, including
direct reentrant reads and automatic child destructors, must obey the remaining
permissions. Indirect or recursive calls fail before output because this
executor does not check them. Foreign callback effects require a contract that
this profile does not provide.

Assignment to an existing slot does not create a fresh construction identity.
The stage checks storage accesses and source loans. A separate construction
identity requires rules for reconstruction and alias invalidation. Concurrent
reclamation requires a memory model and synchronization contracts. Neither
protocol is established by this sequential proof.

## Test the boundary

```sh
make check-resource-memory Z3_FLAGS=-l:libz3.so.4
make check-resource-memory-alloc Z3_FLAGS=-l:libz3.so.4
python3 tests/resource_memory.py --sanitize
```

The suite covers deferred owners and loans, nested owned fields, owned arrays,
owner arguments and results, replacement, returned views, and loop cleanup.
It rejects moved-source reads through raw aliases, use after cleanup, a late
deferred read, double release, leaks, stale stack addresses, and retained links.
Pointer-move cases also check repeated destruction, argument evaluation order,
reentrant reads, field reinitialization, and automatic child cleanup after a
parent has consumed a child field.
Native tests use the emitted C and its symbol map. The intrusive test also
loads the stage through the ordinary compilation-program interface.
