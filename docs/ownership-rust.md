<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership: Crust and Rust

This comparison covers the implemented modular Crust stage and ordinary Rust.
It separates application code from container implementation. Read the
[ownership tutorial](ownership.md) first if the terms are new.

Both models use owners, moves, shared views, exclusive views, and scope cleanup.
Crust uses explicit field and function conditions for retained mutable references.
These conditions are checked by the selected stage and add no runtime state.
The [stage contract](ownership-model.md) describes their source notation.
This comparison does not establish that Crust is easier to use than Rust.

The [replacement design](ownership-design.md) changes the container boundary:
opaque implementations can be explicitly trusted, while their clients use
local ownership checks. That design is not implemented. The comparisons below
describe the current stage, including its solver-checked container bodies.

## How Rust organizes the learning material

Rust separates introductory teaching, worked examples, language rules, and
unsafe implementation guidance. Its [learning page](https://rust-lang.org/learn/)
links these as distinct resources.

| Material | Organization | Corresponding Crust reading |
| --- | --- | --- |
| [The Rust Book](https://doc.rust-lang.org/book/ch00-00-introduction.html#how-to-use-this-book) | Basics and small projects; ownership in chapter 4; lifetimes in chapter 10; smart pointers and `Drop` in chapter 15. Failing examples have an explanation and repair. | Follow the [ownership tutorial](ownership.md), then build the intrusive program. |
| [Rust By Example](https://doc.rust-lang.org/rust-by-example/scope.html) | Short examples grouped by scope: RAII, moves, borrowing, and lifetimes. | Run [ownership-basics](../examples/ownership-basics/README.md) and change one operation at a time. |
| [Rust Reference](https://doc.rust-lang.org/reference/destructors.html) | Detailed rules, including exact destruction order. | Use the stage language contracts and the [core specification](crust0-spec.md). |
| [Standard-library pinning guide](https://doc.rust-lang.org/std/pin/index.html#an-intrusive-doubly-linked-list) | Address-sensitive types and the obligations of intrusive container authors. | Continue to [modular intrusive ownership](../examples/intrusive/README.md). |

The Crust beginner guide follows the concept-and-example approach. Stage data
structures and compiler callbacks stay in the implementation tutorials. A user
does not need them to understand a move or repair a loan conflict.

## Start with the same resource operations

[program.crs](../examples/ownership-basics/program.crs) and
[program.rs](../examples/ownership-basics/program.rs) implement the same small
exercise: create a ticket, transfer it, borrow its integer field, change that
field, destroy the ticket, and destroy another ticket at scope exit. Both print
`BC` and a newline.

```sh
build/crust examples/ownership-basics/main.crs
build/ownership-basics
rustc --edition=2024 examples/ownership-basics/program.rs -o build/ownership-rust
build/ownership-rust
```

The [example README](../examples/ownership-basics/README.md) gives the Crust
build prerequisites. Rust needs no external crate. The two output adapters are
different; this exercise compares ownership behavior, not I/O performance or
instruction counts. The Rust examples and diagnostic comparisons were checked
with Rust 1.90.0 in the 2024 edition.

| Operation | Crust | Rust |
| --- | --- | --- |
| Resource declaration | `resource Ticket ... drop ticket_drop` | `struct Ticket` and `impl Drop for Ticket` |
| Transfer a resource local | `var second: Ticket = move first;` | `let second = first;` for this non-`Copy` type |
| Borrow for reads | `read ticket`, parameter `read Ticket` | `&ticket`, parameter `&Ticket` |
| Borrow for changes | `mut ticket`, parameter `mut Ticket` | `&mut ticket`, parameter `&mut Ticket` |
| End ownership early | `drop ticket;` | `drop(ticket);` |
| Return a field view | Explicit `from ticket.code` | An input/output lifetime relationship, often elided |
| Restrict graph access | Domain and `access(read/edit/reclaim, Domain)` | No direct built-in equivalent |

Rust's moves are implicit for non-`Copy` values. Its `Drop` implementation runs
when an initialized owner is destroyed; `drop(value)` consumes the value to
request early destruction. See [moves](https://doc.rust-lang.org/rust-by-example/scope/move.html)
and [the Book's `Drop` chapter](https://doc.rust-lang.org/book/ch15-03-drop.html).

This Crust example declares a domain to show access authority. A scalar-only
resource can omit that domain. The [native-handle example](../examples/ownership-basics/handles.crs)
does so for integer descriptors and opaque pointers. A storage domain groups
access authority and can restrict operations on several allocations at once.
It is separate from the resource's move, borrow, and cleanup rules.

For heap storage, Rust supplies [`Box<T>`](https://doc.rust-lang.org/std/boxed/index.html)
as a standard owning type. The Crust heap tutorial writes `CellOwner`, its
allocation function, and its destructor explicitly. A nullable owned field is
closer to `Option<Box<Cell>>` than to a `Box<Cell>`, which cannot be null.
This compares ownership roles; it does not equate the allocation-failure policy
of the Crust `malloc` adapter with that of Rust's constructor.

## Loan duration and error repair

Rust normally allows a mutation after the final use of an earlier shared loan.
This complete program succeeds:

```rust
fn main() {
    let mut count = 1_i64;
    let view = &count;
    assert_eq!(*view, 1);
    count = 2;
    assert_eq!(count, 2);
}
```

The [Book's borrowing chapter](https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html)
explains this last-use behavior. The equivalent Crust fragment is rejected:

```crust
var count: i64 = 1i64;
var view: read i64 = read count;
if view != 1i64 { trap; }
count = 2i64;
```

The diagnostic is `initialization conflicts with an active borrow`. Crust keeps
the named view until its scope ends. Put its declaration and use inside an inner
block. Rust needs that repair only when a conflicting use would remain live.

| Mistake | Crust result and repair | Rust result and repair |
| --- | --- | --- |
| Use a resource after moving it | `value is uninitialized or has been moved`; use the destination owner. | [E0382](https://doc.rust-lang.org/error_codes/E0382.html); use the destination owner. |
| Copy this non-copyable resource | Requires explicit `move`; borrow if transfer is not wanted. | Assignment moves it automatically; a subsequent old-owner use reports E0382. |
| Keep using an old shared view after a write | Borrow conflict; end its scope before the write. | [E0506](https://doc.rust-lang.org/error_codes/E0506.html) for this scalar assignment; end the old view's uses before the write. |
| Return a view of a local variable | Result-origin check rejects it; return an owned value or a view from the declared input. | [E0515](https://doc.rust-lang.org/error_codes/E0515.html); return an owned value or borrow caller-owned storage. |
| Borrow disjoint fields exclusively | The current resource checker can reject both loans from one binding; split their scopes. | Direct borrows of separate struct fields can coexist. |

The disjoint-field difference is concrete. Rust accepts this body:

```rust
struct Pair { left: i64, right: i64 }

fn main() {
    let mut pair = Pair { left: 0, right: 0 };
    let left = &mut pair.left;
    let right = &mut pair.right;
    *left = 1;
    *right = 2;
    assert_eq!(pair.left + pair.right, 3);
}
```

Crust currently rejects simultaneous `mut pair.left` and `mut pair.right`
loans from a corresponding record. This is a source restriction, not a claim
that the accesses overlap. Rust's [borrow-splitting discussion](https://doc.rust-lang.org/nomicon/borrow-splitting.html)
also distinguishes struct fields from cases that require a library abstraction.

## Returned and stored views

The Crust helper publishes an exact origin:

```crust
fn ticket_code(ticket: read Ticket) -> read i32 access(read, Demo) from ticket.code {
    return read ticket.code;
}
```

Rust's corresponding helper is shorter:

```rust
fn ticket_code(ticket: &Ticket) -> &i32 {
    &ticket.code
}
```

It is equivalent here to
`fn ticket_code<'a>(ticket: &'a Ticket) -> &'a i32`. Rust relates the result
lifetime to an input lifetime. That lifetime does not specify an exact field.
Crust's `from` path also constrains the returned storage origin. Neither form
extends the owner's life. Rust explains explicit relationships, lifetime
elision, and borrowed struct fields in its
[lifetime chapter](https://doc.rust-lang.org/book/ch10-03-lifetime-syntax.html).

Rust can express `struct View<'a> { code: &'a i32 }`. Crust uses an ordinary
record field and a function origin contract:

```crust
record View { code: read i32; }
fn view_new(code: read i32) -> View from code {
    return make View { code: read code };
}
```

The [stored-view example](../examples/ownership-basics/views.crs) exercises
shared and mutable fields, moves, nested records, and returned reborrows.
A stored field is one pointer. Scope exit or explicit `drop` ends the held
loans without destroying their targets. These checks do not start a solver.
A separate provider test removes the factory source before checking its client.

Crust makes all view records affine, including shared-only records. Its result
contract names one exact source path for every borrowed result field. Rust's
lifetime parameters can express relationships between several field and input
lifetimes. Crust does not have that syntax. It also rejects replacement of a
view record through a borrowed parameter: that operation needs a contract for
replacement origins. Use a fresh result and replace a consumed local instead.
These rules are narrower than general lifetime-polymorphic containers.

## Cleanup order and conditional ownership

Both examples clean up local resources in reverse declaration order. Embedded
fields differ: Crust destroys them in reverse declaration order; Rust destroys
struct fields in declaration order. In both, a user destructor runs before
automatic field cleanup. These Rust rules are in the
[destructor reference](https://doc.rust-lang.org/reference/destructors.html).

For a record containing tickets `first = A` and `last = B`, Crust's automatic
field trace is `BA`; Rust's is `AB`. Port code according to the required
dependency order. Do not assume that the two languages use the same order.

Rust can merge control-flow paths where a resource has moved on only one path.
Some such programs need compiler-generated drop flags; optimization can remove
flags whose values are statically known. The [Rustonomicon](https://doc.rust-lang.org/nomicon/drop-flags.html)
describes that distinction. Crust requires compatible owner states at a join
and rejects the corresponding uncertain cleanup. It does not generate a flag.

For example, put `drop ticket;` in only one branch of a runtime condition.
Crust rejects the branch merge in the tutorial program. Rust accepts its
equivalent. Put the drop on both paths, or move the single drop after the
conditional. Both repairs give Crust one clear cleanup state. This trades
accepted programs for a simpler cleanup model.

The separate Crust resource stage has `defer`. The modular ownership stage
currently rejects it because it has no deferred-effect contract. Rust has no
equivalent [language keyword](https://doc.rust-lang.org/reference/keywords.html);
scoped guard types can implement cleanup actions.
Do not compare the union of several Crust stages with one Rust configuration.

These examples compare normal scope exits. Crust's `trap` does not unwind and
run pending destructors. Rust supports both unwinding and aborting
[panic strategies](https://doc.rust-lang.org/reference/panic.html); unwinding
runs cleanup in the frames it exits. The failure-path guarantees also differ.

## Direct intrusive lists: client and implementer

A safe Rust API can hide a pointer-based intrusive implementation. Its author
must justify pointer validity, aliasing, address stability, and destruction.
The [standard pinning guide](https://doc.rust-lang.org/std/pin/index.html#an-intrusive-doubly-linked-list)
describes these obligations and the role of `Drop` for intrusive links.

Crust's [intrusive tutorial](../examples/intrusive/README.md) declares a closed
storage schema, retained pointer fields, and Boolean field conditions. The
implementation uses normal field stores. The stage verifies each function
against its precondition, postcondition, and changed field classes.

| Obligation | Crust stage | Rust implementation |
| --- | --- | --- |
| Keep the node address fixed | Publication prevents relocation of the storage and its containing record. | An address-sensitive implementation can use `Pin` and a type that is not `Unpin`. |
| Preserve pointer equations | Ordinary `invariant` expressions are checked after edits. | The author of raw-pointer operations must maintain the data structure's invariants. |
| Access payload | The tutorial uses typed `Node` pointers and full-node sentinels. | The chosen node and sentinel representation determines whether pointer recovery is needed. |
| Reclaim one node | Consume its owner and prove the absence of surviving retained references. | The implementation must discharge its safety obligations before it frees storage. |
| Keep an old cursor across release | Reclaim access excludes active cursors and loans. | A safe API must prevent a borrowed reference from outliving its target. |
| Reuse a checked library | Import its verified interface and object receipt. | Call its safe public API under the library's documented contract. |

A full-node sentinel uses more head storage than a link-only sentinel. That
cost is visible in the Crust example's source. Ownership verification adds
no pointer metadata, runtime validity checks, or allocation registry.

These models put different work on a container author. Crust requires explicit
storage and field conditions. Rust requires safety reasoning for an unsafe
pointer implementation. The amount of annotation in a real container, the
quality of diagnostics, and the accepted programs determine usability.

## Recursive owners

The [recursive intrusive example](../examples/intrusive/recursive/README.md)
adds a runtime-sized owner chain. Its `owned_next: *Node` field has an `owns(owned_next: storage)`
contract. A corresponding Rust ownership field is:

```rust
struct Node {
    owned_next: Option<Box<Node>>,
    value: i64,
}
```

Both declarations describe a recursive owning structure with a finite layout.
Neither requires a user-written heap-depth bound or a proof annotation for
recursive calls. The Rust Book teaches this layout with its
[recursive `Box` example](https://doc.rust-lang.org/book/ch15-01-box.html#enabling-recursive-types-with-boxes).
For a sized `Node` and the global allocator, Rust guarantees that
[`Option<Box<Node>>` has the same size and alignment as `Box<Node>`](https://doc.rust-lang.org/std/option/index.html#representation).

This snippet compares the owner chain only. It omits the two intrusive hooks,
address stability, and their destruction protocol. Crust still needs explicit
field roles, domain effects, nullable allocation handling, and callback code.
The example has one explicit owner pointer per node in addition to both hooks.
That storage cost belongs to the chosen representation.

The Crust example uses iterative construction and cleanup. Each loop iteration
consumes a chain and stores an initialized replacement. Its declared type is
the loop invariant; the source needs no proof annotation. Stack use does not
grow with node count. Rust can express the corresponding transfer with
`Option::take`.

Attachment uses one pass through both hooks. Its cursor parameters require
declared edit access and live storage. A helper that instead holds unused
mutable loans into the domain still encounters domain-wide loan exclusion.
The choice of interface affects the source obligations; the loop rule does
not split domain permissions or shorten lexical loans.

## What the comparison establishes

The basic examples compare the same resource operations and native output.
The intrusive example exercises direct pointers, two memberships, individual
release, reuse, and payload loans. Its implementation and annotations are
available for inspection.

The ordinary owner and loan rules remain narrower than Rust's borrowing model.
Named Crust loans use lexical scopes. View records support stored loans, but
returned records use one exact origin and borrowed record parameters retain
their stored origins. A field condition cannot replace a missing lifetime
relationship. The stage rejects interfaces that do not express the required
relationship.

The generic field checker supports conditions expressed by its source grammar.
It does not verify arbitrary user logic or infer a missing contract from caller
bodies. Solver errors and unknown results reject the program.
