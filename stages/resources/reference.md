<!-- SPDX-License-Identifier: Apache-2.0 -->

# Resource compiler stage

This ordinary Crust library implements ownership, local loans, RAII, and `defer`.
The C99 seed has no resource policy or new keyword. The root program chooses
the library with ordinary source calls.

```sh
make all resource-stage
build/crust examples/resources/hello/main.crs
build/resource-hello
make check-reader check-resources
```

The [hello source](../../examples/resources/hello/main.crs) contains the
compilation program and target program. The [SQLite application](../../examples/resources/sqlite/README.md)
uses separate target files and tests actual connection, statement, and byte-view
lifetimes. Its root also contains all compiler and linker options.

## Source rules

The stage extends Crust0 with these forms:

```crust
extern fn release(handle: *u8) -> unit = "free";
resource File { handle: *u8; } drop file_drop;

fn file_drop(value: mut File) -> unit {
    unsafe { release(value.handle); }
}
fn use(value: read File) -> unit {}
fn update(value: mut File) -> unit {}
fn consume(value: File) -> unit {}

// Within a function:
var second: File = move first;
use(read second);
defer update(mut second);
```

This wrapper requires a pointer that can be passed to C `free`. The three
empty helpers show parameter modes. `consume` takes the cleanup obligation
and drops its parameter on return.

A resource is a nominal record with a declared drop function. Its raw fields
and construction require `unsafe`. Ordinary records and fixed arrays own their
resource fields and elements. Other values retain Crust0 copy semantics.

- Initialization creates one cleanup obligation. A move transfers it and makes
  the whole source binding unavailable. A resource value can move only from a
  whole local binding. Resource copies and moves of resource-valued fields or
  elements fail.
- An owner passed by value requires `move` or a fresh owning result. Return of
  a local owner requires `move`. The caller owns a returned resource.
- Reassignment captures the new value, drops the old live value, and installs
  the new value. Assignment after a move reactivates the binding's original
  cleanup position. `value = move value` retains one obligation.
- Normal scope exit drops live bindings in reverse declaration order. A record
  runs its declared drop function before it drops fields in reverse order.
  Arrays drop elements in reverse order.
- A `read` loan permits shared access. A `mut` loan permits exclusive access.
  All field and element loans reserve the whole root. Reborrowing reserves the
  parent loan. Loan types cannot occur in stored fields. A function can return
  a loan tied to one named borrow parameter with `from`, as described below.
  A borrow mode applies to a value type; modes cannot be stacked.
  Constants and their fields and elements permit `read` loans. Their storage
  lives for the whole program. They do not permit `mut` loans.
- Named local loans end at lexical scope exit or `drop name`. Explicit ending
  requires all child loans and deferred uses to have ended. It invalidates the
  local binding and emits no code. A borrowed parameter cannot be dropped.
  Temporary call loans end after the
  complete call. Borrow modes are part of a source function type, including
  function pointers and constants. Lowering them to pointers does not erase
  their source contract.
- `defer f(args);` captures the callee and arguments once, from left to right.
  Its result type must be `unit`. Moved arguments transfer at registration;
  borrowed arguments remain reserved until invocation. Defer runs in reverse
  order with the same scope's automatic drops.
- A return value is captured before cleanup. `break` and `continue` clean the
  scopes that they leave. Each loop iteration has its own cleanup scope.
- Continuing branches must agree on outer initialization and ownership states.
  Loop conditions and backedges, including `continue`, must restore entry states.
  `break` paths must agree with each other and with the condition-false exit.
  A literal `while true` has only `break` exits. The checker rejects disagreement
  instead of adding runtime drop flags.
- A `while true` loop with no `break` that exits it cannot reach the next
  statement. Parentheses around `true` do not change this rule. Other loop
  conditions can reach the next statement; the checker does not evaluate
  constant expressions for this decision.

### Consuming pointer reads

```crust
var node: *Node = move owner.node;
```

`move` also accepts a writable pointer place: a variable, field, element, or
dereference. It reads that place once and consumes its initialized permission.
No store clears the source. It has no readable value until assignment
initializes it again. This applies through aliases and to null pointer values.
Other fields and the pointed-to allocation remain unchanged. The operation
does not create a cleanup obligation for the returned raw pointer.

Plain resource checking requires `unsafe` for this operation. In that mode,
the programmer must meet the consumed-read contract. The
[ownership stage](../../docs/ownership-model.md) checks moves through declared
owned storage and rejects unchecked aliases. A source loan that forbids writing
the place also forbids moving its pointer.

### Returned views

```crust
record Pair { first: i32; second: i32; }
fn first(value: read Pair) -> read i32 from value {
    return read value.first;
}
```

`from value` ties the result to that input loan. Each return must derive from
the named parameter, including returns through other checked calls. A local,
an unrelated parameter, or a raw pointer cannot supply the result. A `mut`
result requires a `mut` source. The caller keeps the source loan until the
returned view ends. Other temporary argument loans end with the call.

The view uses the same pointer representation as a local loan. The dependency
exists only in compiler state. Named views last until `drop` or scope exit and
reserve the whole root. This rule does not add stored views or independent
loans for disjoint fields.

Functions with returned views require direct calls. A function value cannot
carry the `from` dependency in the current source type grammar. Such a
conversion is rejected, including in `unsafe` code. The overload reader does
not accept the `from` clause; that adapter must preserve the result mode and
source parameter index in its declaration contract before it can accept it.

In the standalone resource policy, only whole bindings have initialization
facts. A partially initialized record or array cannot be read through a checked
place. An unsafe raw address can name
uninitialized whole storage without reading it. Raw stores do not change the
checked initialization fact. A raw store transfers the new value without
reading or dropping the previous target bytes. Unsafe code must release any
previous resource before overwriting it and must arrange cleanup for the new
resource. It must read only bytes that it has initialized.
This contract supports foreign output buffers without forced
zero initialization or partial-initialization tables.

An unsafe region permits raw pointer access, address formation, pointer and
function casts, foreign calls, resource construction, and resource fields.
`unsafe fn` requires such a region at every source call. A designated drop
function also requires unsafe permission for an explicit call. Neither kind
can be stored as an ordinary safe function value. Generated automatic cleanup
has the drop function's explicit contract.

`unsafe { forget move value; }` discharges an obligation without calling drop.
The caller must account for the raw resource. Unsafe code still obeys move and
loan bookkeeping. It does not grant copying of owners or mutation through a
shared loan.

Drop returns `unit` and must not publish the object or unwind. A library must
handle a failed close explicitly before scope exit, or use an explicit fatal
drop policy. Trap and process termination do not promise cleanup. Foreign
unwinding or nonlocal jumps across resource scopes violate the library contract.

Fixed-array indexing checks bounds. Indirect calls check for null at invocation,
including deferred calls. A statically named call has no null check. Arithmetic
retains the seed's defined wrapping and trap rules.

## Compiler interfaces

[api.crs](api.crs) provides `resource_build` and `resource_program` for a root.
Both take ordinary source and option data. There is no special runner path,
package name, destructor name, or foreign API recognized by the seed.

The command wrapper selects `main`, or the name supplied with `--entry`, with
the source signature `fn(i32, **u8) -> i32`. Borrow parameters do not match this
signature even when their lowered pointer representation is the same.

[extension.crs](extension.crs) exposes the lower-level sequence:

1. Initialize a context and `RsStage`.
2. Call `rs_read` for each retained source range.
3. Call `rs_prepare` after all source units have been read.
4. Assign native link names and pass `rs_c_body` to the C backend's body callback.
5. Destroy the context after output is complete.

To delegate memory checking, use `rs_prepare_delegated` in step 3. It permits
raw accesses without `unsafe` and delegates memory overlap checks and
initialization of plain values to the caller. A plain value has no resource cleanup obligation and is not a
`read` or `mut` binding. The caller must prove every reachable memory access, transfer, and
cleanup before step 4. Each read needs initialized storage, including reads
through aliases and on branch and loop paths. Address formation does not
initialize storage. A delegated raw address can come from a shared loan. The
caller must preserve its access permission when checking pointer uses. The
[intrusive stages](../../examples/intrusive/README.md) provide these checks
and stop output if they fail.

Owner construction, moves, loan binding initialization, and cleanup eligibility
remain checked by the resource stage. The caller checks loan conflicts,
including field overlap, reborrows, and destruction under active loans. A raw output store does not construct an
owner or create its cleanup obligation. Assign an owning result to the whole
binding for that operation. These states must still agree at continuing
branches and loop edges; initialization of plain values need not agree if the
memory proof establishes each subsequent read. This adds no target state or
implicit initialization stores.

An earlier source stage can publish a source ABI import. It supplies an external
declaration with the complete source signature and native link name, then calls
`rs_source_import` before `rs_prepare`. This marker permits source aggregates and
borrow modes. It does not apply to a native C declaration. Unmarked `extern fn`
declarations still require scalar foreign signatures and unsafe calls.

For a returned-view import, call `rs_return_from(stage, declaration, name)`
before `rs_prepare`. `name` identifies the source parameter in that declaration.
The provider contract compares parameter positions, so names can differ across
the import boundary. Omitting or changing this dependency rejects the import.

Caller and provider must use the same source ABI, record definitions, resource
drop clauses, and unsafe function contracts. A source import is safe unless its
declaration has the source stage's unsafe marker. A safe source import can supply
a resource's drop function. It has the same exclusive-borrow signature and
explicit-call restrictions as a local drop definition.

The optional [overload adapter](../overload/resources.crs) reads bare function
prototypes, selects calls with source borrow modes, and assigns structural native
names. Initialize `RsStage`, then call `ov_resources_init`, `ov_resources_read`
for each source, and `ov_resources_prepare`. Call `rs_prepare` after that sequence.
Retain the two stages and the adapter hooks through overload preparation, and
retain the resource stage through body emission. The resource reader alone does
not add bare prototypes or overload selection.

The stage retains source signatures, storage identities, loans, and cleanup
plans. It lowers a separate set of target declarations and bodies. Generated
drop helpers are checked seed functions with private C linkage. Source
locations retain offsets in the original complete file. The seed checker
checks generated types and operations; it does not prove ownership.

The checked operation trees alone are not an equivalent seed program. Exit
cleanup remains in the retained plans. Use `rs_c_body`, or an emitter that reads
both representations. Ordinary seed evaluation or emission of those trees
alone omits the planned cleanup. `resource_program` completes output before
its local stage ends; a retained context from that call cannot be used alone
to emit the resource program again.

The [Crust reader](../reader/README.md) is independent of resources. Its four hooks
can add declarations, statements, prefix expressions, and type syntax. A stage
can also replace the complete reader. The reader contains no resource keyword.

The [C backend extension](../c/extension.crs) accepts a callback for each complete
function body. The callback can emit its own control flow and can use checked
expression and statement services. It does not require a seed body. A separate
test emits labels and branches from an external library with null seed bodies.
This API contains no resource or cleanup operation.

The compiler library uses context arenas and side tables. Separate compilations
have separate contexts and stage records. This implementation executes its
function checks serially; the public API does not provide a worker scheduler.

## Output and cost

Cleanup plans share equal suffixes that have the same continuation. Output uses
C labels and branches. It has no runtime cleanup table, dynamic registration,
hidden owner header, reference count, or hidden drop flag. A deferred direct
call stays direct. Each owning record type has one generated drop function
when cleanup needs that type. Parent records call those functions in reverse
field order. Arrays use reverse loops. Repeated nested record types do not
expand cleanup code once per stored element. Field names are indexed once
during collection for constructor and place checks.

Record and array parameters use pointers to caller snapshots. Aggregate results
use caller-provided storage. The stage retains explicit left-to-right evaluation
with local temporaries. This is an internal Crust ABI; foreign signatures must use
explicit scalar ABI types. Target optimization can remove temporaries, but the
ABI and its costs must be checked in actual output.

The [measurements](../../benchmarks/resources/README.md) separate frontend work
from final target GCC compilation and linking. They also report emitted size
and cleanup growth. Passing resource tests alone is not a speed result.

The stage proves local ownership and loan rules, including returned views.
The [ownership stage](../../docs/ownership-model.md) adds local memory and
interface checks. Opaque container implementations require explicit root-selected
trust. Raw pointer operations in the resource-only profile still need the
source's explicit unsafe boundary; cleanup alone cannot establish memory safety.
