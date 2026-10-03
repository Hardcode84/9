<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: static checks for direct intrusive links

An intrusive link is an ordinary field in an application object. Insertion
does not allocate. Unlink does not destroy the object. The object can belong
to several lists and can have an owner that is independent of those lists.

This tutorial checks such code before the C backend runs. The checks use the
typed Crust tree. There is no second parser and no list operation in the C99
core. The application has ordinary pointers. Proof identities, field maps,
and validity facts exist only during compilation.

## Build and run

Use Linux x86-64 and a Z3 library that provides its C API. With the development
library installed:

```sh
make all memory-stage
build/crust examples/ownership/main.crs
build/ownership
```

The program prints `OK` and a newline. If only the system runtime library is
installed, select its linker name explicitly:

```sh
make memory-stage Z3_FLAGS=-l:libz3.so.4
```

For a separate installation, pass `Z3_LIBDIR` to `make`. The build adds that
directory to the link and runtime search paths. The ordinary `make all` build
does not require Z3.

The [root](main.crs) selects the checker, its foreign contracts, its proof
budgets, and the source files. It loads a compiled ordinary stage library.
It does not receive a privileged runner operation.

## Two different checks

The tutorial has two checks with different claims:

| Check | Claim | Input boundary |
|---|---|---|
| Closed-program memory check | Accesses use live, aligned storage within bounds; reads require initialized compatible values; release has no incoming persistent link from another live allocation | One entry and the actual bodies it calls |
| Ring library proof | Init, unlink, insert, and splice preserve rooted rings of arbitrary length | Valid disjoint hook storage, exclusive edit authority, and the operation rules below |

Init requires a valid hook that is not yet initialized. Other operations require
initialized rooted rings. Unlink accepts a non-root member or a singleton.
Insertion requires the same condition for the hook that moves. Splice requires
both arguments to be roots. Equal roots give a no-op. Distinct roots name
disjoint cycles.

The closed-program check expands actual calls. It does not consume the ring
proof as a call summary. Thus a successful ring proof alone cannot authorize
a caller to free linked storage. Both checks use the same link source.

The [generic executor](../../stages/proof/model.crs) knows typed operations,
paths, terms, and proof callbacks. The [memory policy](../../stages/memory/model.crs)
defines allocation and access rules. The [ring policy](ring_contracts.crs)
defines link invariants. Field and declaration identities connect policies to
the checked tree; names are selected by the compilation program.

## Follow an allocation

The root declares three trusted foreign effects. The memory checker does not
recognize `malloc`, `free`, or `putchar` by name.

| Effect | Required native behavior |
|---|---|
| `PM_ALLOCATE` | Take one byte count; return null or fresh storage with the declared alignment |
| `PM_RELEASE` | Accept null or release one live allocation at its base address |
| `PM_SCALAR` | Take and return scalar values; do not access application storage; return normally |

Changing a foreign binding requires a contract that matches the new native
function. These contracts and the selected checker are trusted compiler code.
The checked target cannot grant itself a permission with an assertion.
Every registered release function must accept storage from every registered
allocator. Distinct native allocator families need a policy that tracks their
different release rights; the three effects above do not express that split.

An allocation receives a fresh symbolic identity. Pointer casts and field
offsets preserve that identity. Equality compares numeric addresses. A later
allocation can reuse an old address, but access through the old identity still
fails. Release accepts only a live heap allocation at offset zero. Stack storage
ends at its lexical scope exit.

Pointer writes through fields, array elements, or indirect places are persistent
links. Before storage ends, other live objects must not retain a pointer into it.
Local scalar aliases
can survive, but cannot access the retired storage. This policy proves actual
accesses; it does not require unique pointer values or infer Rust-style exclusive
borrows for every pointer.

The example detaches both hooks before releasing a node. It splices a source
ring, then allocates a replacement while the lists remain live. The checker
explores both allocation outcomes. It also clears stack heads before their
storage ends, while another heap node and a stack node remain live. The
`offsetof` projectors preserve the containing allocation origin. A head is too
small to be a node. A projection outside its live allocation fails an extent or
access obligation. Memory safety alone does not prove that a valid pointer names
the payload that the algorithm intended.

## Loops, branches, and failure

The root selects traversal depth, path count, loop unfolding, and a solver search
timeout. SMT parsing and query construction are outside that timeout. At the
last permitted loop iteration, the checker must prove that the
loop cannot continue. Reaching the budget never counts as success. This profile
has no loop-invariant or modular-call interface. It rejects a traversal when
the remaining continuation cannot be proved unreachable at the selected bound.

Each access obligation retains the assumptions available when it occurred.
Later allocation constraints cannot hide an earlier error. Immutable SMT
definitions share terms without adding assumptions. An unreachable path can
be removed only after its preceding obligations have been proved.
Each active stack allocation must also admit a valid placement under every
preceding state. The checker uses a sufficient capacity bound: each live
allocation reserves its extent plus room for one aligned gap for the new
object. It also reserves one gap before those allocations. This bound can
reject a feasible layout when the address space is nearly full. An impossible
layout cannot make later checks pass by
contradiction. This checks abstract address-space placement. It does not prove
that the operating system's stack limit is sufficient. That check needs a
target stack budget and evidence for the generated frame sizes.

The checker models storage for aggregates and variables whose address is
taken. Other scalar variables use symbolic values. This reduces proof work and
keeps address, initialization, and scope checks for every exposed storage slot.

Solver counterexamples, timeout, unknown results, unsupported operations, and
checker allocation failures stop output. Existing output files remain unchanged
when proof fails. There is no unchecked fallback.

Direct calls in statements and assignment right-hand sides use their actual
bodies, including branch results. A nested value helper requires one
unconditional return expression and no foreign calls. Aggregate copies read
the complete old value before stores, including self-copy. Array copies use
the selected iteration budget. Recursive and indirect
calls, aggregate function arguments and results, global values, string values,
arbitrary integer-to-pointer conversions, and external calls without an effect
contract are rejected. The checker has no concurrency, RCU, or
partial-destruction rule.

## Inspect output and test failures

```sh
make check-memory
make check-memory-alloc
python3 tests/memory.py --build build --sanitize
build/crust-memory-test --ring --check --library examples/ownership/links.crs
```

The tests compile accepted programs, compare their C text with the ordinary
backend, and execute that output. Rejection cases cover use after free, double
free, stack escape, stale equal-address aliases, uninitialized reads, bounds,
alignment, retained links, and incomplete loops. Ring source mutations remove
backlinks or corrupt splice boundaries and must fail the library proof.

The proof stage adds no application allocation, pointer tag, generation,
reference count, flag, cleanup table, or runtime validity check. It leaves the
seed's arithmetic and bounds behavior unchanged. Identical emitted C is the
erasure test; optimization is not needed to remove proof state.

## Relation to resource ownership

The [resource stage](../../stages/resources/README.md) supplies moves, RAII,
`defer`, and returned views tied to an input loan. This memory checker consumes
complete seed operation trees. Resource cleanup also exists in retained exit
plans, so checking only its lowered tree would omit cleanup and would be wrong.

The [RAII composition tutorial](resources/README.md) preserves source storage
lifetimes and executes the retained cleanup at each exit. It also removes
initialized-field permissions after owner transfers. Its emitted C uses the
same resource body emitter. It checks a complete two-hook client with automatic
node and head destruction, without `unsafe` regions.

Both closed-program profiles expand actual calls. Reusable call effects need
verification against the exact implementation and layout, plus caller checks
for their preconditions and destructive effects. The executor has no consumer
for those summaries. The separate ring proof does not supply that interface.

See the [systems source study](../../docs/exploration/systems-capabilities.md#static-model-reassessment)
for the differences that matter to Linux, GCC, and LLVM.
