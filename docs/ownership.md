<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership: a practical tutorial

Ownership answers two questions: who must clean up a value, and who can use it
before that cleanup? Crust checks these rules during compilation. An owner can
transfer a value. A borrower can use it for a shorter time. Destruction must
wait until conflicting uses have ended.

This tutorial teaches the ownership stage. It combines owners and loans with
explicit storage schemas and ordinary field and function conditions. The
[stage contract](ownership-model.md) defines the rules used by the examples.

These examples use the current checker, whose graph checks need Z3. The
[replacement design](ownership-design.md) specifies a solver-free stage with
explicitly trusted container implementations. It is not implemented yet.

Start here if you can already write a function and a record. You do not need
to know the compiler implementation or a proof language.

Read the sections in order:

1. [Select the stage and run a program](#1-select-the-stage-and-run-a-program).
2. [Give a value a cleanup action](#2-give-a-value-a-cleanup-action).
3. [Transfer ownership](#3-transfer-ownership).
4. [Borrow for reads or changes](#4-borrow-for-reads-or-changes).
5. [Return a borrowed field](#5-return-a-borrowed-field).
6. [Own a heap allocation](#6-own-a-heap-allocation).
7. [Keep intrusive nodes at a stable address](#7-keep-intrusive-nodes-at-a-stable-address).
8. [Destroy embedded resources](#8-destroy-embedded-resources).
9. [Use library contracts](#9-use-library-contracts).

The [Rust comparison](ownership-rust.md) explains corresponding concepts,
differences in accepted code, and obligations for container authors.

The [stage contract](ownership-model.md) gives the declaration and checking rules.

## 1. Select the stage and run a program

Run these commands from the repository root:

```sh
make all ownership-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/ownership-basics/main.crs
build/ownership-basics
```

Use `Z3_FLAGS=-lz3` if the development library is installed. The output is `BC`
and a newline. The [root file](../examples/ownership-basics/main.crs) loads the
ownership stage and compiles [program.crs](../examples/ownership-basics/program.crs).
The target program does not link Z3. The stage uses it to check intrusive link
implementations; this first example has no links.

To check a target file without producing an executable:

```sh
build/crust examples/ownership-basics/main.crs --check \
    examples/ownership-basics/program.crs
```

The root can also compile a copy of the target file. Pass `-o OUTPUT FILE` in
place of `--check FILE`. Target paths on this command line are relative to your
working directory.

The raw seed has no ownership guarantee. Selecting this stage is part of the
program's safety contract. The [resource stage tutorial](../stages/resources/README.md)
describes a different selection: local cleanup and `defer`, with raw memory
operations inside explicit `unsafe` adapters. Do not combine its guarantees
with this stage's guarantees without selecting and checking that composition.

## 2. Give a value a cleanup action

A `resource` is a record with automatic cleanup. The example uses a small
resource whose destructor prints one character:

```crust
domain Demo(Ticket);
resource Ticket { code: i32; } domain(Demo) drop ticket_drop;

fn ticket_drop(ticket: mut Ticket) -> unit access(reclaim, Demo) {
    var result: i32 = emit(ticket.code);
    if result < 0i32 { trap; }
}
```

The complete file declares `emit` as the C `putchar` function with a scalar-only
foreign contract. This printing action makes cleanup visible. A real resource
can instead release an allocation or another native resource. Its fields can
hold integer handles, such as file descriptors or API object identifiers.
`resource` assigns cleanup to the wrapper value. `owns(field)` also checks
ownership of a native handle. `owns(field: storage)` adds allocation ownership.

A local such as `ticket` owns one `Ticket` value. The type defines its cleanup;
the owning local determines when cleanup runs. `mut Ticket` gives the destructor
access to the value without creating a second owner. Section 4 explains this
borrowed type.

`Demo` is an access domain: a compile-time name that groups storage and its
access rules. Cleanup of a resource in a domain requires reclamation authority.
Thus the destructor and the example's `main` declare `access(reclaim, Demo)`.
There is no runtime `Demo` object, pool, common allocation lifetime, or lock.

| Function contract | Permitted use of its domain |
| --- | --- |
| `access(read, Demo)` | Read through valid views. |
| `access(edit, Demo)` | Change valid storage and checked links. Do not destroy owners. |
| `access(reclaim, Demo)` | Create and destroy owners when conflicting uses have ended. |

A function can use weaker access inside `read Demo { ... }` or
`edit Demo { ... }`. The block ends before the function recovers its outer
authority. These declarations do not provide thread synchronization.

Unless stated otherwise, the following statement examples replace the body of
`main` in `program.crs`. Keep its `access(reclaim, Demo)` contract and add
`return 0i32;` at the end. Other declarations in that file supply the helpers.

```crust
{
    var first: Ticket = make Ticket { code: 65i32 };
    var second: Ticket = make Ticket { code: 66i32 };
}
```

The block prints `BA`. Local resources drop in reverse declaration order.
Normal `return`, `break`, and `continue` exits also run applicable cleanup.
A process exit or `trap` does not unwind scopes. RAII is the name for this
association between a value's lifetime and its cleanup.

Use `drop` to perform cleanup before scope exit:

```crust
var ticket: Ticket = make Ticket { code: 65i32 };
drop ticket;
ticket = make Ticket { code: 66i32 };
```

This prints `AB`: the first value drops explicitly, and the replacement drops
at scope exit. There is no second cleanup of the consumed value. A `record`
with only scalar fields has no cleanup action; reading an integer copies it.

### Own a native handle

The ownership rules apply to integers and opaque pointers. A file descriptor
uses an integer representation:

```crust
resource File { fd: i32; } owns(fd = -1i32) drop file_drop;
extern fn acquire_fd(fd: i32) -> i32 foreign(acquire File.fd) = "dup";
extern fn close_fd(fd: i32) -> i32 foreign(move fd: File.fd) = "close";

fn file_drop(file: mut File) -> unit {
    if file.fd != -1i32 {
        var status: i32 = close_fd(move file.fd);
        if status != 0i32 { trap; }
    }
}

fn file_new() -> File {
    var fd: i32 = acquire_fd(1i32);
    return make File { fd: move fd };
}
```

`owns(fd = -1i32)` defines an owned field with an invalid value of `-1`.
`acquire File.fd` returns a fresh owner or that invalid value. The acquired
integer cannot be copied into another owner. `move` transfers it to the field.
The destructor checks the invalid value before it consumes the handle. This
example traps if closing fails. That is the wrapper's explicit error policy.
The native close contract consumes the handle even if it reports an error.

A native operation can borrow a handle and acquire another in the same call:

```crust
extern fn duplicate(fd: i32) -> i32
    foreign(read fd: File.fd, acquire File.fd) = "dup";
```

Check `file.fd != -1i32` before `duplicate(file.fd)`. `read` permits shared use
for the duration of the native call. `mut` requires exclusive use. Neither
permits the native function to retain access after return. Ordinary source
helpers borrow `read File` or `mut File` and return or consume `File` values.

The [complete example](../examples/ownership-basics/handles.crs) also declares
`Stream.handle: *u8` with `owns(handle = null(*u8))`. It uses the same acquisition,
move, borrow, and cleanup rules. The pointer is opaque: it grants no permission
to dereference, reinterpret, or free memory. Memory owners use the additional
`storage` contract in section 6.

Raw integers cannot initialize these owned fields, even when their bits equal
a live descriptor. Different owned-field declarations identify different
resource kinds. To contain an existing kind, embed its resource wrapper.
A plain `fd: i32` field without `owns` remains copyable; cleanup alone does not
check the underlying native ownership.

Foreign effect declarations are trusted. The native implementation must obey
them. The checker rejects source violations of those contracts but cannot prove
a native library's implementation. A function with a scalar-only contract
cannot receive an owned handle. This prevents accidental loss of ownership
through an unannotated call.

These resources need no domain, pointer conversion, hidden allocation, runtime
tag, or solver. The foreign calls keep their original C ABI. Failure tests use
the declared integer or null literal with `==` or `!=`.

## 3. Transfer ownership

Use `move` when another local or function must take responsibility for cleanup:

```crust
var first: Ticket = make Ticket { code: 65i32 };
var second: Ticket = move first;
```

This prints `A` once when `second` leaves scope. `first` is no longer usable.
A move transfers the value; it does not clone the owned resource or increase
a reference count.

**Rejected: copying a resource.**

```crust
var first: Ticket = make Ticket { code: 65i32 };
var second: Ticket = first;
```

Two cleanup obligations would refer to one resource. Add `move` if the second
local must own it. Use a borrow if both pieces of code need temporary access.

**Rejected: using a moved value.**

```crust
var first: Ticket = make Ticket { code: 65i32 };
var second: Ticket = move first;
drop first;
```

Remove the last line. `second` now owns the cleanup obligation. A by-value
resource parameter transfers the same obligation to the callee; a resource
result transfers it back to the caller. The caller uses the signature to check
this transfer. It does not inspect the function body.

## 4. Borrow for reads or changes

A *loan* is the compiler's record of a borrow. A `read T` view permits reads.
A `mut T` view permits exclusive changes. Borrowing does not transfer cleanup.
The source spells both the requested borrow and the parameter type:

```crust
fn set_code(ticket: mut Ticket, code: i32) -> unit access(edit, Demo) {
    ticket.code = code;
}
```

Call it with `set_code(mut ticket, 66i32)` inside an `edit Demo` block.
The view uses ordinary field access. A borrowed scalar also uses its name
directly: write `view = 7i64`, rather than `*view = 7i64`.

Several shared views can coexist. An exclusive view excludes conflicting
reads and writes through other access paths. A named view lasts to the end
of its lexical scope, even if its last read occurs earlier.

**Rejected: changing a value while a named shared view is in scope.**

```crust
var count: i64 = 1i64;
var view: read i64 = read count;
if view != 1i64 { trap; }
count = 2i64;
```

**Correction: end the view's scope before the change.**

```crust
var count: i64 = 1i64;
{
    var view: read i64 = read count;
    if view != 1i64 { trap; }
}
count = 2i64;
```

Use the same repair before moving or destroying a borrowed owner. Copying a
scalar out of a view does not keep that view alive. A pointer or another
borrowed view still depends on the original storage.

A reborrow temporarily borrows through an existing view:

```crust
var count: i64 = 0i64;
{
    var view: mut i64 = mut count;
    { var child: mut i64 = mut view; child = 3i64; }
    view = 7i64;
}
if count != 7i64 { trap; }
```

The parent view cannot be used while a conflicting child view remains live.
In this example, the inner block ends before `view = 7i64`.

## 5. Return a borrowed field

A function can return a view if its signature states where the view comes from:

```crust
fn ticket_code(ticket: read Ticket) -> read i32 access(read, Demo) from ticket.code {
    return read ticket.code;
}
```

`from ticket.code` binds the result to that input field. It does not extend
the input's lifetime. The function body must return a view that satisfies this
relationship. A view of a local temporary or a different input is rejected.

```crust
var ticket: Ticket = make Ticket { code: 65i32 };
read Demo {
    var code: read i32 = ticket_code(read ticket);
    if code != 65i32 { trap; }
}
drop ticket;
```

The read block ends before `drop ticket`. A helper that returns `mut T` needs
an exclusive input and a matching result origin. A node view uses the same
syntax. The [intrusive tutorial](../examples/intrusive/README.md#traverse-and-borrow-payload)
shows views returned through typed pointer fields.

### Store views in a record

Use a view record when a helper needs to retain borrowed access:

```crust
record Editing { value: mut i64; }

fn editing_new(value: mut i64) -> Editing from value {
    return make Editing { value: mut value };
}

fn editing_set(view: mut Editing, value: i64) -> unit { view.value = value; }
```

`view.value = value` writes the borrowed integer. It does not replace the
reference. The caller keeps the source alive and excludes conflicting access:

```crust
var count: i64 = 1i64;
{
    var view: Editing = editing_new(mut count);
    editing_set(mut view, 7i64);
    var moved: Editing = move view;
    drop moved;
    count = 9i64;
}
```

The move transfers the held loan. `drop moved` ends that loan; it does not
destroy `count`. Ending the block has the same effect. A record with `read`
fields uses the same move rule, but permits shared access to its targets.
A shared loan of an `Editing` record also permits only reads of `value`.

**Rejected:** moving the view outside its source scope, copying it without
`move`, or changing `count` while the mutable view remains active. Keep the
view in a smaller scope, or drop it before direct access to the source.

The result contract names one exact origin for every borrowed result field.
A helper cannot return a view of a local variable or replace stored origins
through a borrowed record. Use a fresh result with `from` instead. View records
are scoped values; persistent graph links use `references` in a domain.

Run [views.crs](../examples/ownership-basics/views.crs) with the
[example instructions](../examples/ownership-basics/README.md#stored-views).
It also shows nested records and returned loans through stored fields.

## 6. Own a heap allocation

For heap storage, a resource can own the allocation addressed by a pointer
field. The [heap example](../examples/ownership-basics/heap.crs) declares the
handle and its allocation separately:

```crust
domain Cells(Cell, CellOwner);
record Cell { value: i64; } domain(Cells);
resource CellOwner { cell: *Cell; } owns(cell: storage) domain(Cells) drop cell_drop;
```

`owns(cell: storage)` gives the handle responsibility for that allocation.
Both types use the same access domain. Allocation, initialization, transfer, and release
remain explicit:

```crust
fn cell_new(value: i64) -> CellOwner access(reclaim, Cells) {
    var cell: *Cell = allocate(sizeof(Cell)) as *Cell;
    if cell != null(*Cell) { (*cell).value = value; }
    return make CellOwner { cell: move cell };
}

fn cell_drop(owner: mut CellOwner) -> unit access(reclaim, Cells) {
    var cell: *Cell = move owner.cell;
    if cell != null(*Cell) { release(cell as *u8); }
}
```

The file declares `allocate` and `release` as foreign allocation and release
operations. Those declarations are trusted adapters to `malloc` and `free`.
They are not proof that arbitrary foreign code obeys the contract.

The constructor returns a nullable owned field. Its caller checks allocation
failure before use. The destructor consumes the field and releases it once.
The stage rejects a missing release, a second release, or access after release.

```mermaid
flowchart LR
    H["CellOwner handle"] -->|"owns cell"| A["Cell allocation"]
    V["read Cell view"] -. "temporary access" .-> A
```

The solid arrow denotes the cleanup obligation. The dashed arrow denotes a
loan. Neither arrow adds a field to the generated program. A view must end
before the owning handle is destroyed.

Run the example:

```sh
build/crust examples/ownership-basics/main.crs -o build/ownership-heap \
    examples/ownership-basics/heap.crs
build/ownership-heap
```

The output is `AB` and a newline. The first owner is destroyed before the
replacement is created. The allocator can reuse the address. A new allocation
does not make a cursor from the old allocation valid again.

## 7. Keep intrusive nodes at a stable address

A retained pointer field uses `references(field)`. Its record belongs to a
closed domain schema. Each pointer must be null or refer to live storage of
its declared type. Record conditions state additional facts:

```crust
record Entry { peer: *Entry; } domain(Links) references(peer)
    invariant((*self).peer == null(*Entry) || (*(*self).peer).peer == self);
```

Declare `domain Links(Entry);` with this record. An edit function must preserve
its condition for every live entry. The function can declare `requires`,
`ensures`, and `modifies` conditions on ordinary fields. Destruction must prove
that no surviving retained reference points into the released storage.

The [intrusive example](../examples/intrusive/README.md) uses this rule for two
sets of pointer fields in a `Node`. Its insertion and removal functions are
ordinary source functions. Each allocated node has an independent owner.
The same owner can unlink, release, and replace a node while other owners
remain live.

The example uses full typed nodes as sentinels. Traversal accesses payload
through `*Node` directly. Publication fixes the node's address; moves of that
storage or its containing record are rejected. Read and edit cursors cannot
outlive their access scope or cross reclamation.

## 8. Destroy embedded resources

A node can contain resource fields as well as links. Its destructor detaches
the hooks, destroys the stored value, and then releases the outer allocation:

```crust
drop *node;
release(node as *u8);
```

This fragment is inside the checked destructor in
[fields.crs](../examples/intrusive/fields.crs). `node` is its non-null owned
allocation, and both hooks are already detached.

`drop *node` runs value cleanup; it does not free the outer allocation. A
resource callback runs before the automatic cleanup of embedded resource
fields. Those fields drop in reverse declaration order. The callback must
leave them initialized for that cleanup and consume its raw owned pointers.

Dropping one field separately is rejected because its containing value still
has a field-cleanup obligation. Releasing resource storage before value cleanup
is also rejected. These rules avoid hidden runtime flags for partial cleanup.
See the [nested-resource example](../examples/intrusive/README.md#embedded-and-recursive-ownership)
for allocation failure paths and the `BABAOK` cleanup trace.

## 9. Use library contracts

Each function is checked from its own body, declared fields, and called
interfaces. `read` and `mut` parameters describe access; by-value resources
describe transfer; `from` describes a returned view; `access` describes domain
authority. A declaration is an obligation for the implementation, not permission
to skip checking it.

A separately published library can supply verified interfaces and object code.
Its client needs no provider source and does not repeat proofs for imported
bodies. The compilation program retains the trusted publication receipt.
Changing contracts, object bytes, or checker images invalidates that receipt.
The [library-import instructions](../examples/intrusive/README.md#verify-the-emitted-program-and-the-boundary)
give the compilation API and trust boundary.

## Choose code that this stage can check

The following distinctions matter when you design an interface:

| Requirement | Current source rule |
| --- | --- |
| Borrow a value within a block | Use `read` or `mut`; named views end with the block. |
| Return a view | Declare its input origin with `from`. |
| Store a borrowed field in a record | Use `read T` or `mut T` fields in a scoped view record; move the record and declare `from` on a returned view record. |
| Store a persistent raw pointer | Declare `owns` or `references` in a closed storage schema. |
| Return an unchecked raw pointer | Rejected: use a borrowed result with an origin. |
| Replace a local owner across loop iterations | Accepted for initialized, movable resource records without stored loans. The declared type is the loop invariant. Owned targets and validity facts can change; other outer storage retains its state. |
| Traverse or detach an intrusive ring | Use ordinary field conditions and function contracts; traversal has no fixed node-count bound. |
| Register `defer` in this modular stage | Rejected. The separate resource stage supports it, but this stage has no deferred-effect contract. |

These rejections are not a request to add `unsafe`. Change the interface or
select a stage whose stated rules cover the required operation. Selecting the
raw seed removes these ownership guarantees.

Checking and proof can increase compile time. The generated ownership code has
ordinary values, pointers, and required cleanup calls. It has no added ownership
tags, validity checks, reference counts, or cleanup flags. Explicit allocation,
I/O, null guards, and destructor work still cost what their code does.
