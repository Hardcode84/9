<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: ownership, RAII, and defer as a source stage

An owned descriptor must close exactly once on normal control flow. A move
must transfer that obligation. A borrowed view must not outlive its owner.
This stage checks those rules and emits explicit cleanup code.

RAII associates resource lifetime with scope. `defer` adds a call to that
scope's cleanup. Both are library policies here: the root selects a Crust
stage that reads the syntax, checks ownership, and supplies C function
bodies. The seed has no resource keyword or destructor policy.

Start with [Hello World](../../examples/hello/README.md) and the
[C backend tutorial](../c/README.md). This tutorial follows a descriptor
owner, makes cleanup order visible, and inspects the compiler's retained
plans. The [reference](reference.md) gives the complete source and API rules.

## 1. Run a real descriptor owner

Run from the repository root on Linux x86-64:

```sh
make all resource-stage
build/crust examples/resources/hello/main.crs
build/resource-hello
```

The target prints `Hello, resources!` and a newline, then returns zero.
The [root](../../examples/resources/hello/main.crs) loads [api.crs](api.crs)
and `build/crust-resource-library.so`. Its final `resource_build` call passes
the unread target source, just as `c_build` does in Hello World.

The target declares an owner:

```crust
resource Output { descriptor: i32; } drop output_drop;
```

`output_open` duplicates standard output with `dup`. Thus the owner has its
own descriptor to close. `output_drop` takes `mut Output` and calls `close`.
`hello` also takes `mut Output` and handles partial writes in a loop.

The entry function establishes the lifetime:

```crust
var first: Output = output_open();
var output: Output = move first;
defer hello(mut output);
return 0i32;
```

| Step | Ownership and cleanup state |
| --- | --- |
| `output_open()` | `first` owns one descriptor and owes one drop |
| `move first` | `output` takes the obligation; `first` is unavailable |
| `defer hello(mut output)` | The call captures an exclusive loan until cleanup |
| `return 0i32` | Save the return value, call `hello`, then drop `output` |

There is no second drop for `first`. The deferred loan prevents conflicting
access to `output` before the call runs. The final drop closes the duplicate,
so the process's original standard output remains open.

Native calls and resource fields are inside `unsafe` regions. Those adapters
must satisfy the native API contracts. `unsafe` does not disable the stage's
move and loan checks. In this example, failed writes terminate with status
one; a failed close terminates with status two. Process termination and
`trap` do not run pending cleanup. Normal scope exits do.

## 2. Make cleanup order visible

The descriptor example has a silent successful drop. Use this small target
to print the order. `Trace` owns a cleanup obligation for this demonstration;
its label points to a string literal and needs no allocation.

```sh
mkdir -p build/tutorial-resources
cat > build/tutorial-resources/trace.crs <<'EOF'
extern fn puts(text: *u8) -> i32 = "puts";

resource Trace { label: *u8; } drop trace_drop;

fn trace_open(label: *u8) -> Trace {
    unsafe { return make Trace { label: label }; }
}

fn print_line(text: *u8) -> unit {
    unsafe { if puts(text) < 0i32 { trap; } }
}

fn trace_drop(value: mut Trace) -> unit {
    unsafe { print_line(value.label); }
}

fn main(argc: i32, argv: **u8) -> i32 {
    var first: Trace = trace_open("drop");
    var second: Trace = move first;
    defer print_line("defer");
    return 0i32;
}
EOF
build/crust-resource -o build/tutorial-resources/trace \
    build/tutorial-resources/trace.crs
build/tutorial-resources/trace
```

Expected output:

```text
defer
drop
```

`defer` captures its callee and arguments once when execution reaches the
statement. It is not a block that reads variables later. At scope exit,
cleanup runs in reverse registration order. Here the deferred call runs
before the owner's drop. The moved-from binding adds no call.

The standalone `build/crust-resource` command takes target declarations,
not a root compilation program. It calls the same stage library as the
source-controlled root.

### Destroy a value before scope exit

`drop value;` runs the same cleanup as scope exit and consumes the whole local
owner. A later use or second drop rejects. The binding can then receive a new
owner. No runtime flag selects which cleanup to run.

`drop *pointer;` destroys a resource value, including its embedded resources,
without freeing the allocation. The ordinary resource stage requires `unsafe`
for this operation. A composed ownership stage must establish unique destruction
authority and prevent later reads of the destroyed value. The modular ownership
stage checks that contract before it accepts a following `release(pointer)`.
Explicit drop accepts a resource record or a record with resource fields.
Partial field destruction does not suppress a containing record's automatic
cleanup and is rejected by the modular stage.

## 3. Observe a rejected move

Create a version that moves `first` twice:

```sh
sed 's/defer print_line("defer");/var third: Trace = move first;/' \
    build/tutorial-resources/trace.crs > build/tutorial-resources/moved.crs
build/crust-resource --check build/tutorial-resources/moved.crs
```

The check must return one with this diagnostic:

```text
value is uninitialized or has been moved
```

Changing the second move to `move second` transfers the remaining obligation
and makes the program valid:

```sh
sed 's/var third: Trace = move first;/var third: Trace = move second;/' \
    build/tutorial-resources/moved.crs > build/tutorial-resources/fixed.crs
build/crust-resource -o build/tutorial-resources/fixed \
    build/tutorial-resources/fixed.crs
build/tutorial-resources/fixed
```

It prints `drop` once. The rejected operation was replaced, and the deferred
print is absent from this version. Both earlier bindings have moved.

Other useful checks in the descriptor example are:

| Change | Reason for rejection |
| --- | --- |
| Replace `move first` with `first` | An owner cannot be copied |
| Add `hello(mut output)` after its deferred call | The defer holds an exclusive loan |
| Move an outer owner in only one continuing branch | The paths disagree on the live cleanup obligation |

These rules keep cleanup statically determined. Named local loans last until
explicit `drop` or scope exit; temporary call loans last through the call.
Ending a local loan requires all child loans and deferred uses to have ended.
A borrowed parameter cannot be dropped. A field or element
loan reserves its complete root binding. The checker does not infer shorter
last-use lifetimes or independent loans for disjoint fields. The composed
[ownership stage](../../docs/ownership.md#borrow-separate-fields) checks field
overlap and permits separate loans for disjoint ordinary fields.

The [returned-view example](../../examples/resources/returned/README.md) adds a
field accessor whose result retains its input loan. Its `from` clause names the
source parameter. The caller cannot move or change the owner while that view
is live. The [reference](reference.md#returned-views) gives the exact rules.

## 4. Follow the compiler state

Read the implementation in this order:

| File | What to follow |
| --- | --- |
| [read.crs](read.crs) | Four reader hooks for declarations, statements, prefix expressions, and types |
| [model.crs](model.crs) | Owners, loans, scopes, change records, cleanup actions, and exit plans |
| [types.crs](types.crs) | Source contracts, owning types, and separate lowered ABI types |
| [state.crs](state.crs) | Access checks, loan state, rollback, and cleanup chain construction |
| [expr.crs](expr.crs) | Move and call checking, capture order, temporary lifetimes, and defer |
| [control.crs](control.crs) | Branch joins, loop edges, return capture, and `rs_prepare` |
| [cleanup.crs](cleanup.crs) | Shared record drop functions and reverse array loops |
| [drop.crs](drop.crs) | Explicit value destruction and consumed-place facts |
| [emit.crs](emit.crs) | `rs_c_body` emits function bodies with cleanup branches |

The reader extends ordinary identifier tokens with library rules. For
example, `rs_read_declaration` uses the record reader, then reads the
`drop` clause. Other hooks recognize `move`, `read`, `mut`, `defer`, and
`unsafe`. The shared reader does not contain these policies.

### Keep source contracts until checking is complete

Each `RsLocal` records initialization, ownership, borrow mode, active shared
loans, and an exclusive-loan flag. These are compiler facts, not fields
added to target objects. A whole-binding move marks its source unavailable.
A read or write checks that state before producing lowered operations.

`read T` and `mut T` retain distinct source types even though both lower to
pointers. Owning records and arrays use pointers to captured caller values
for parameters and caller-provided storage for results. This is a Crust
stage ABI. Native foreign declarations use explicit scalar ABI types.

### Branches must agree without runtime drop flags

`rs_note` records state changes. At a branch, the checker saves a marker,
checks one arm, snapshots the changed outer bindings, and rolls back to
check the other arm. `rs_join` compares paths that continue. A returning
arm has its own cleanup and does not contribute a continuing state.

Loop conditions and edges must restore the entry state of outer bindings.
Each iteration still has its own local cleanup scope. This bounded rule
rejects conflicting states at compilation. The target needs no hidden flag
to decide whether an owner has already moved.

Temporary values also need scopes. A call consumes or borrows its arguments
through the full call. A defer promotes its borrowed arguments to the
enclosing cleanup scope. Releasing those loans at registration would permit
the owner to die before the deferred call.

## 5. Inspect cleanup output

Emit the trace program as C:

```sh
build/crust-resource --emit-c -o build/tutorial-resources/trace.c \
    --symbols build/tutorial-resources/trace.rsp \
    build/tutorial-resources/trace.crs
cat build/tutorial-resources/trace.c
```

Find the function containing `"drop"` and `"defer"`. Its return path goes
through `rs_exit_` labels. Follow the branches to the deferred print and the
drop call, then to the saved return value. Label numbers are emitter details.

`RsAction` describes a drop or a captured deferred call. `RsChain` pairs an
action with its next continuation. `rs_chain` shares a suffix only when
both the action and continuation agree. Sharing a drop sequence across
different destinations would send control to the wrong return or loop edge.

`return`, `break`, `continue`, and normal block exits refer to these plans.
A return captures its result before cleanup. Record drops run before the
record's owned fields; fields and array elements then drop in reverse order.
Array cleanup uses a loop, so a large array does not create one emitted
statement per element.

Each owning record type gets one private drop helper when cleanup first needs
it. A parent record calls its children's helpers. A record with two fields
of the same type does not copy the child's cleanup code twice. Calls still
run separately for the two values. This keeps generated code proportional
to the used record definitions. The exit plan still selects which whole
bindings are live; a helper never decides whether a moved binding is live.
An owning field assignment calls only that field's helper before the store.

The helpers are ordinary checked seed functions. Their empty C link names
select private definitions, so separately compiled files cannot export or
capture one another's helpers. The stage keeps their declaration identities
separate from the source declarations.

### Retain the plan through emission

`rs_prepare` checks source ownership, builds lowered operations and cleanup
plans, then calls the seed checker on generated operations. These checked
trees alone are not a complete replacement program: exit cleanup remains
in side tables.

The driver passes `rs_c_body` and the live `RsStage` to the C backend's
complete body callback. It emits ordinary statements plus branches through
the retained plans. Passing only the checked tree to ordinary seed emission
or evaluation would omit the planned cleanup.

Keep source storage, the context, and resource stage alive through output.
`resource_program` completes emission while its local stage is live. Keeping
only its context after the call does not retain an API for emitting again.
For custom composition, follow [extension.crs](extension.crs) and keep the
stage yourself.

`rs_init` reserves a syntax kind range in the context. `RS_READ` through
`RS_DROP` are local offsets. Use `rs_kind(stage, offset)` to obtain a node kind.
Each resource stage instance has its own range. Compose type hooks with other
readers, then lower their types before `rs_prepare`. When copying resource
syntax between contexts, map kinds to the destination resource stage's range.
The [composition test](../../tests/kind_composition.crs) combines this reader
with an independent type wrapper and checks both initialization orders.

The retained function plan also maps checked blocks to source scopes. Actions
retain their registration scope; exits retain their start and stop scopes.
Deferred captures name the scope that holds their storage. Owning copies and
consuming pointer reads have transfer facts attached to their checked
assignment. These facts let another stage check source lifetimes and consumed
values without changing emitted C.

`rs_prepare_delegated(stage)` delegates raw memory, loan lifetimes, and initialization
of non-owning values to the caller's stage. This includes `read` and `mut` bindings. The caller must prove every reachable read, write,
transfer, and cleanup before emission. This includes initialization through
aliases and all branch and loop paths. Taking an address does not initialize
storage. Delegated address formation can read a shared loan; the caller must
check the resulting pointer's access permission before use. Owner construction,
resource moves, and cleanup eligibility keep their source checks. Their states must still agree at continuing control-flow
edges. The [intrusive tutorial](../../examples/intrusive/README.md) describes
the modular checker. Plain `rs_prepare` retains
whole-binding initialization checks and its explicit `unsafe` requirement.

Memory delegation also permits borrowed record fields and explicit record
moves or drops whose validity the caller must prove. Borrowed fields lower to
pointers; field access addresses the target. A record with no resource fields
needs no cleanup call for `drop`. The consuming-place fact still identifies
the ended value. The caller must check stored-loan lifetimes, alias permissions,
and moves. Plain `rs_prepare` rejects borrowed record fields.

`RsStage.delegate_return_loans` separately delegates proof of returned-view
origins, including `from` contracts on record results. A stage that sets it must check each returned loan against the declared
input and any field path. Memory delegation alone keeps the original source
loan check. The modular ownership stage sets this option and checks field-origin
contracts.

## 6. Check the proof and cost boundaries

Resource lowering adds levels to the tree passed to the seed checker. For the
exact fixtures in the [stage limit table](../reader/README.md), 250 nested blocks
around a return pass; 249 around a scalar assignment pass. The next depth fails
with a diagnostic. Overload composition has the same bounds. The 256-level
traversal budget is not a promise to accept 256 nested source blocks.

The emitted program has no runtime cleanup table, dynamic registration,
reference count, owner header, or hidden drop flag. It does execute the
required drop calls. Captured values, aggregate ABI storage, bounds checks,
and indirect-call null checks can also have a cost. Inspect optimized native
output before calling a specific use free.

This checker proves local ownership and loans. Native adapters still require
correct foreign contracts. The optional combined stage checks direct intrusive
links through actual function bodies and cleanup plans. Its checks do not make
the standalone resource stage a memory checker or provide reusable ownership
summaries for separately checked callers.

Run `make check-resources check-resource-alloc` for language, cleanup, and
allocation failure checks. `--check` stops after semantic checks;
`--prepare` also emits C into memory. Both exclude target GCC compilation
and linking. See the [measurement record](../../benchmarks/resources/README.md)
for measured costs and input contracts.

Continue with the [SQLite example](../../examples/resources/sqlite/README.md)
for connections, statements, borrowed column bytes, and error paths. The
[overload composition example](../../examples/overload/resources/README.md)
shows why source overload selection runs before borrow types are lowered.

## In-place outputs for composed checkers

A source-linked composer can call `rs_initializes(stage, signature, index)`
after `rs_collect` and before `rs_publish`. A normal return must initialize
that complete pointee. The composer must verify this promise and exclusive
access to each uninitialized output. The signature is the collected source
function type, not the lowered C type.

The lowerer accepts an uninitialized local's address or a forwarded pointer.
It schedules local resource cleanup after construction succeeds. It adds no
zero fill or runtime flag. It rejects replacement of an initialized local and
deferred construction. The ownership stage uses this generic contract for
opaque stable stack resources.
