<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: checked intrusive links with RAII

This program gives each heap node an owner. The node has two ordinary hooks
and can belong to two lists. A node destructor removes both hooks and releases
that node. A head destructor removes the remaining members without destroying
them. No pool or shared allocation lifetime is required.

`ready` and `active` name two separate list memberships. Each `Hook` has its
own `prev` and `next` pointers. A node can belong to both lists at the same
time. One doubly linked list requires only one hook.

The [program](program.crs) has no `unsafe` region. Its raw pointer operations,
including the shared [link functions](../ownership/links.crs), pass the memory
checker.
The selected stage combines the resource rules with that check. An `unsafe`
region in its input would not bypass the proof.
This is a closed-program proof tutorial. It does not meet the
[modular ownership target](../../docs/design.md#checked-ownership-target), which
requires separate function checks from published contracts and a user-facing
model no more complex than Rust's.

## Build and run

```sh
make all resource-memory-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/intrusive/main.crs
build/intrusive-checked
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
record Hook { prev: *Hook; next: *Hook; }
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

`Hook` and both link operations come from [links.crs](../ownership/links.crs).
They use ordinary pointer fields and stores. The checker executes their actual bodies.
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

The root also selects one inferred call summary:

```crust
var summarized: *u8 = "unlink";
var options: PmOptions = make PmOptions {
    foreign: &contracts[0usize], foreign_count: 3usize,
    summaries: &summarized, summary_count: 1usize,
    max_depth: 128usize, max_paths: 256usize, max_iterations: 8usize,
    milliseconds: 10000u32
};
```

This selection grants no memory permission. The stage resolves the name to the
checked declaration and derives its effects from the complete body. Use
`summaries: null(**u8), summary_count: 0usize` to expand all calls instead.

### Check a declared call contract

The [contract root](contract-main.crs) selects a different check for the same
target program. It supplies an [unlink contract](contract.crs), proves the
selected body against that contract, then checks each caller. A missing
backlink store fails the body proof even when no caller uses the function.

```sh
make memory-contract-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/intrusive/contract-main.crs
build/intrusive-contract
```

The result is `OK` and a newline. The target source and its annotations are
unchanged. The root selects `unlink`, `prev`, and `next` through ordinary data.
The contract obtains the hook type and field offsets from checked declarations.
It also works with renamed functions, records, and fields.

The contract reads the two input links and requires live, aligned storage for
the hook and both neighbors. Storage permission does not imply initialization.
Each link read separately requires initialization and its pointer type. The
contract then declares these four ordered writes:

```text
before.next = after
after.prev = before
hook.prev = hook
hook.next = hook
```

Reads use the memory at function entry. Writes use the declared output memory
in sequence, so the model also covers aliased neighbors and singleton hooks.
Each declared write requires writable storage and a compatible type. A stored
pointer must be null or refer to live storage.

The [contract stage](../../stages/memory/contract.crs) uses these operations:

| Operation | Contract |
|---|---|
| `pm_contract_access` | Require live, aligned storage of the given extent; optionally require write permission. |
| `pm_contract_read` | Require an initialized scalar and return its input value. |
| `pm_contract_write` | Permit a scalar write and specify its required output value. |
| `pm_contract_require` | Add a Boolean input condition. |
| `pm_contract_register` | Prove the selected body, then install the verified effect for callers. |

Registration first checks that the input conditions can be satisfied. It runs
the actual body with symbolic parameters and input memory. Every access must
pass the memory policy. Every final memory map must equal the declared result;
this proves that memory outside the declared effect is unchanged. Every actual
write must also target a declared writable cell with the same representation.
This last check rejects a write outside the contract even if the body restores
the original value before return.

The body can contain branches, scalar assignments, scalar bindings without
local storage, and unit returns. Calls, loops, traps, aggregate copies, and
address-taken bindings reject this contract form. The proof uses the complete
resource view, so a deferred call cannot disappear from this check. Omit the
contract selection to use the normal complete-body check.

After the body proof, each caller must establish the input conditions and
typed-write separation from its existing cells. The caller receives the
verified output maps and written pointer cells. Those cells still participate
in later destruction checks. Registration retains an immutable term template;
it does not call the contract builder again for each caller. No disk artifact
or unchecked imported contract is used.

This is an exact contract for a finite memory effect. It adds an independent
body check and can increase compilation time. It does not summarize an
arbitrary owned graph. That requires predicates for an unbounded set of cells
and a rule for separating that set from the caller's memory. Runtime-sized
read-only loops use the separate inductive rule below.
Caller formulas in this implementation still grow with the selected calls.

The example compiles ordinary Crust sources into its own library. Its entry
calls `resource_memory_program_with` with a preparation callback. The combined
stage calls that callback after storage planning and construction of complete
cleanup views, before the entry proof. The callback registers the contract;
it must retain the memory policy and complete body semantics. A false result
stops output, with a diagnostic. The default entry uses no callback.
This interface and the contract implementation are external Crust code.
The C99 core has no contract operation.

Contract builders use the listed helpers and generated terms from the input
parameters and memory maps. They must not mutate proof state directly or
introduce free solver symbols. The selected compiler stages remain trusted
compiler code, as do the solver, backend, and explicit foreign-effect table.
The selected target body is checked rather than trusted.

The emitted C is byte-identical to the output with inferred effects. Native
tests run it at `-O0` and `-O2`, including sanitizer builds. The body proof,
contract maps, permissions, and frame checks add no target operations.

### Check a runtime-sized traversal

The [traversal root](walk-main.crs) selects an inductive check for the loop in
[walk.crs](walk.crs). The target walks the same embedded links, then uses RAII
to unlink a stack node before its storage expires. It walks the surviving head
again after cleanup. The trip count comes from a runtime argument. The default
bounded checker rejects this program.

```sh
make memory-loop-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/intrusive/walk-main.crs
build/intrusive-walk
```

The output is `OK`. These are all the annotations on the traversal itself:

```crust
fn walk(cursor: *Hook, remaining: usize) -> *Hook {
    while remaining != 0usize {
        cursor = (*cursor).next;
        remaining = remaining - 1usize;
    }
    return cursor;
}
```

The [stage](walk-stage.crs) supplies the proof separately. The root names the
function and link field with `make WalkNames { function_name: "walk", next: "next" }`.
The stage gets parameter symbols, field offsets, and the complete body from
checked declarations. It requires one loop, a hook pointer parameter, and a
`usize` count parameter. These are this example's selection rules. The generic
[loop checker](../../stages/memory/loop.crs) has no function, field, or source
names.

The invariant requires:

- The remaining count is between zero and its value before the loop.
- The cursor has live, aligned storage for a hook.
- The next field contains an initialized pointer with a compatible stored type.

The decreasing value, or variant, is the remaining count. This is the counter
already used by the program. The proof adds no runtime counter or loop bound.
It proves the invariant before entry. It then gives every modified outer
scalar binding an arbitrary value of its declared type, assumes the invariant,
and executes one complete iteration. Each continuation must preserve the
invariant and strictly decrease the nonnegative variant. This also checks that
the next cursor can safely read its link. Ring membership and reciprocal
topology require separate predicates.

`pm_loop_execute` accepts a statement, current proof state, and a predicate
callback. The callback receives the entry and arbitrary loop-head states. It
returns one Boolean invariant and one integer variant in `PmLoopTerms`.
It runs once. The checker retains immutable functions over the modified
bindings and applies them at entry and each continuation. `pf_define` terms
have lexical scope within those functions. Predicate nesting uses the proof
depth budget. The callback must only construct terms; it must not change proof
state or add premises. As with call contracts, the policy and solver are
trusted compiler code.

The checker derives modified bindings from the complete body, including both
arms of each branch. It supports scalar declarations, scalar assignments,
branches, `break`, `continue`, and terminating traps. Memory reads and array
bounds guards are allowed. Addressed bindings, aggregate storage, memory stores,
calls, nested loops, and returns in the
selected body reject. A deferred call in the cleanup view also rejects.
Modified outer bindings must be initialized before entry. Uninitialized
iteration-local scalars are permitted when every read follows initialization.

All eight memory maps must remain equal after each iteration or break.
This includes initialized permissions: a consuming pointer read cannot remove
a field permission and then disappear at the loop boundary. The checker proves
access obligations before it discards a continuation or assumes an invariant.
It retains checked condition-false, break, and trap paths for the caller. Cleanup
after the loop uses the ordinary resource-memory checker.

This form permits arbitrarily many iterations over the memory already proved
by the closed-program profile. A loop that changes a graph or allocates nodes
requires a frame rule for its changed cells, allocation identities, and
retained links. The read-only frame cannot authorize those effects.
Other loops keep their selected unfolding bound.

The emitted C and symbol names match ordinary resource lowering before
optimization. The root uses the existing preparation and statement callbacks.
The C99 core, target pointers, and runtime cleanup representation are unchanged.

## Connect the stages

### Initialize plain storage through a helper

The [output initialization example](output-init.crs) uses a stack head and
stack node. Each hook starts with uninitialized storage at its final address:

```crust
var head: Hook = uninit;
hook_init(&head);
{
    var node: Hook = uninit;
    hook_init(&node);
    var cleanup: Detach = make Detach { hook: &node };
    insert_after(&head, &node);
}
```

`Detach` is a resource whose drop function calls `unlink`. Its cleanup runs
before the node's storage expires. The memory proof checks the helper's actual
stores before any field read, then checks cleanup and the surviving head links.
Removing node initialization or the detach call rejects the program.
No null initializer, initialization flag, or runtime validity check is added.

Run its [root](output-main.crs), which selects only the scalar `emit` foreign
contract because this example has no foreign allocation or release:

```sh
build/crust examples/intrusive/output-main.crs
build/intrusive-output
```

The output is `OK` and a newline. This example delegates initialization of plain
hook storage. It constructs the `Detach` owner with an ordinary complete
initializer. A raw output store does not construct a resource owner.

### Check the complete resource program

Resource lowering hoists C storage and retains cleanup outside the operation
tree. Checking that tree alone would miss cleanup and extend source lifetimes.
The [adapter](../../stages/resource_memory/view.crs) uses the retained
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

For a selected straight-line function, the [summary stage](../../stages/memory/summary.crs)
executes the proof view once with symbolic input memory and parameters. It
retains each access obligation, the resulting memory maps, and every written
cell. Each call binds that template to its actual arguments and memory state.
It must prove all retained obligations and check typed-write separation from
the caller's cells. The caller keeps new pointer cells so that later destruction
checks every surviving link. Consumed-field effects also remain in the template.

The template uses fresh proof names at each call. It emits flat SMT definitions;
it does not place a large memory result in a nested solver function. Templates
exist only for the current checked context. There is no disk cache or unchecked
summary import. Changes to a body, type, layout, or resource plan produce a new
template in the next compilation. The C99 core has no summary operation.

These views and permissions exist only in the compiler. Emission still uses
`rs_c_body` and the original checked operations and cleanup plans. The tests
compare C output from both stages on identical accepted resource input. They
also compare pointer moves with plain reads to detect added target operations.
They execute the output at `-O0` and `-O2`. No optimization is needed to erase
proof state.
The source's copies, pointer stores, drop calls, and ordinary seed checks remain.

## Select the contract

The ordinary resource stage requires explicit `unsafe` regions for raw access.
The combined stage calls `rs_prepare_delegated` to delegate raw memory and
plain-value initialization checks to the memory proof. Plain values have no
resource cleanup obligation and are not `read` or `mut` bindings. Scalars,
pointers, and plain records and arrays can be initialized through output parameters or field stores.
The proof requires initialization at each read, through every alias and on each
reachable path. Taking an address grants no initialized permission.
Owner construction, moves, loan bindings, and cleanup eligibility retain their
resource checks. Their states must still agree at continuing branches and loop
edges. Plain initialization can differ between paths when later reads are safe.
The combined driver emits only after both checks pass. Foreign effects retain
the explicit trust boundary described in the [memory tutorial](../ownership/README.md).
Raw aliases obey the memory-access proof. This does not establish exclusive
borrowing for every raw pointer value or a concurrency rule.

This profile checks a closed sequential entry. It expands calls that the root
does not select for summaries. The default loop check must prove that each loop
stops within the selected unfolding bound. The optional traversal stage above
uses induction for its selected loop. Solver timeout,
unknown results, unsupported operations, and allocation failure stop output.
There is no unchecked fallback. Selected summaries require unit results,
scalar parameters and bindings without local storage, scalar assignments,
and straight-line bodies. Calls, branches, loops, and address-taken locals in
these bodies produce a diagnostic. This also rejects resource lowering that
introduces such operations. Omit that selection to check the complete body by
expansion. The template reuses concrete effects; the solver still checks them
at each call. Abstract ownership predicates require a rule for separating an
unbounded set of cells from caller memory. The ring proof is not a caller
memory proof.

An output write can occur in an expanded call, a selected effect template, or
cleanup. All three use the same memory state. Deferred arguments are still
captured at registration. A captured scalar or pointer value must already be
initialized. The pointed-to value needs initialization when the deferred body
reads it.
Plain `rs_prepare` retains whole-binding initialization checks, including in
`unsafe` regions. Summary selection does not change the selected source policy.

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
make check-memory-summaries Z3_FLAGS=-l:libz3.so.4
make check-memory-contracts Z3_FLAGS=-l:libz3.so.4
make check-memory-loops Z3_FLAGS=-l:libz3.so.4
python3 tests/resource_memory.py --sanitize
python3 tests/resource_initialization.py --sanitize
python3 tests/memory_contract.py --sanitize
python3 tests/memory_loop.py --sanitize
```

The suite covers deferred owners and loans, nested owned fields, owned arrays,
owner arguments and results, replacement, returned views, and loop cleanup.
It rejects moved-source reads through raw aliases, use after cleanup, a late
deferred read, double release, leaks, stale stack addresses, and retained links.
Initialization cases cover output parameters, partial aggregates, conditional
writes, loop exits, deferred captures, and destructor reads. They also check that
delegation retains owner construction and loan conflicts.
Pointer-move cases also check repeated destruction, argument evaluation order,
reentrant reads, field reinitialization, and automatic child cleanup after a
parent has consumed a child field.
Native tests use the emitted C and its symbol map. The intrusive test also
loads the stage through the ordinary compilation-program interface.
It also removes a backlink store from the selected `unlink` body. The resulting
summary must fail at the caller's destruction check. Summary tests cover
aliased arguments, new links, consumed fields, overlapping typed stores,
invalid accesses, and unchanged C output. Allocation tests inject failures
during summary construction and application.
Declared-contract tests also cover unused incorrect bodies, aliased parameters,
conditional implementations, restored writes outside the contract, inconsistent
input conditions, invalid callers, retained pointer cells, and allocation
failure during registration and application.
Loop tests check entry, invariant preservation, progress, scalar type ranges,
modified bindings in branches, intermediate invalid accesses, break and
continue paths, retained cursors after cleanup, and unchanged C output.
They reject consumed link permissions and unsupported effects. Allocation
tests inject host arena failures into scalar loops and the complete traversal.

## Raw bootstrap witness

[raw.crs](raw.crs) is the seed-language witness used by backend bootstrap tests
and the C reference comparison. It inserts and unlinks embedded hooks, releases
individual nodes while the list remains live, and allocates replacement nodes.
It has no ownership checker. Use the annotated [program.crs](program.crs) above
for the checked language example.

[raw-main.crs](raw-main.crs) selects the ordinary C backend and links the host
memory and output functions:

```sh
make all c-stage
build/crust examples/intrusive/raw-main.crs
build/intrusive-raw
```

The raw executable prints `intrusive: ok` and returns zero. With arguments, this
root passes those arguments to the C backend instead of its default output and
link arguments:

```sh
build/crust examples/intrusive/raw-main.crs --check
build/crust examples/intrusive/raw-main.crs -o build/list --ldflag build/libcrust0_host.a
build/list
```

Run `make witness` to execute the assembly-stage output and its C reference.
This command uses `raw.crs` and does not require the ownership stage or Z3.
