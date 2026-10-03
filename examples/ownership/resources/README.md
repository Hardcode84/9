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

The destructor clears `owner.node` before release. The current memory policy
treats stored pointer fields as persistent links, including this owner field.
A live field must not retain a pointer to released storage. This is an explicit
source store, not a hidden flag. Eliminating it needs a checked destruction
contract that consumes that field's permission while still checking all
remaining destructor operations. The current stage has no such contract.

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
4. After an owning copy, remove initialized-field permissions from the source.
   Reading that source through a saved raw alias then fails.

A return captures its result before cleanup. Aggregate copies read a snapshot
of the complete source. The resource stage lowers aggregate arguments and
results to ordinary pointer operations, which the memory stage can check.
Full calls on assignment right-hand sides execute their actual bodies and keep
all resulting paths.

These views and permissions exist only in the compiler. Emission still uses
`rs_c_body` and the original checked operations and cleanup plans. The tests
compare C output from both stages on identical accepted resource input, then
execute it at `-O0` and `-O2`. No optimization is needed to erase proof state.
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

Moves consume initialized-field permissions. They do not create a fresh
construction identity when an existing slot is assigned again. The stage
checks storage accesses and source loans. It does not prove a separate
partial-destruction, concurrent reclamation, or in-place reconstruction protocol.

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
Native tests use the emitted C and its symbol map. The intrusive test also
loads the stage through the ordinary compilation-program interface.
