<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership: Crust and Rust

This comparison covers the implemented modular Crust stage and ordinary Rust.
It separates application code from container implementation. Read the
[ownership tutorial](ownership.md) first if the terms are new.

For ordinary resources, both models use owners, moves, shared views, exclusive
views, and scope cleanup. Crust currently needs more explicit contracts and
accepts fewer borrowing patterns. For direct intrusive lists, Crust checks
declared pointer relationships that Rust's ordinary borrow checker does not
prove. This is a useful difference, but it does not establish that the complete
Crust user model is no more complex than Rust's.

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

The extra Crust domain contract is visible even in this scalar-only resource
example. It cannot be omitted from a comparison of what beginners must learn.
It is not Rust's lifetime syntax under another name: it groups access authority
and can restrict operations on several allocations at once.

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

Rust can also express `struct View<'a> { code: &'a i32 }`. The current Crust
stage has no corresponding stored-lifetime field contract. It rejects a record
with a borrowed field. Returned local views do not establish support for stored
views or general lifetime-polymorphic containers.

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

The required operation is a direct intrusive doubly-linked list: two hook
families in each node, independent owners, unlink before destruction, and node
allocation reuse while other owners and heads remain live. An index arena or
reference-counted graph changes that requirement.

Crust's actual declarations and client are in the
[intrusive tutorial](../examples/intrusive/README.md). Rust's standard-library
[pinning guide](https://doc.rust-lang.org/std/pin/index.html#an-intrusive-doubly-linked-list)
uses an intrusive doubly-linked list to explain stable addresses and the need
to detach before storage invalidation.

| Obligation | Crust container author | Rust container author using pinned raw links |
| --- | --- | --- |
| Keep node addresses stable | Declare hook members; initialize in final storage. Checked moves reject afterward. | Use an address-stability contract, commonly `Pin` with a `!Unpin` node; preserve it in unsafe code. |
| Maintain inverse links | Declare `reciprocal(prev, next)`; link bodies must prove it. | Maintain the invariant in the implementation; the borrow checker does not prove raw pointer equations. |
| Select the correct containing field | Declare `members` and `anchor`; checked `parent(Node.ready, cursor)` excludes a sentinel and the wrong family. | Define the adapter or containing-field projection and justify its offset, provenance, and type. |
| Detach before freeing | Destructor must establish isolation of every hook before release. | Destructor must detach before deallocation; raw-link validity depends on this implementation contract. |
| Protect a returned payload view | Declare its origin and domain access; conflicting edits or reclamation reject. | Give the safe API a lifetime/access design that prevents deletion or conflicting writes while the view is live. Pinning alone does not provide this. |
| Use the container | Explicit owners, domain scopes, and checked calls. | A sound library can expose safe calls and hide its unsafe implementation. |

These are different ways to express and discharge obligations. Rust's
[`unsafe` chapter](https://doc.rust-lang.org/book/ch20-01-unsafe-rust.html)
explicitly separates an unsafe implementation from a safe public abstraction.
Requiring unsafe pointer operations inside a library does not imply that Rust
application code must use `unsafe`.

### Compare one pointer-edit operation

Crust's checked link function is ordinary pointer code with a contract:

```crust
fn unlink(h: *Hook) -> unit links(edit, Hook) cursor(h) isolated(h) {
    var before: *Hook = (*h).prev;
    var after: *Hook = (*h).next;
    (*before).next = after;
    (*after).prev = before;
    (*h).prev = h;
    (*h).next = h;
}
```

The corresponding Rust raw operation can use the same fields and stores:

```rust
#[repr(C)]
struct Hook { prev: *mut Hook, next: *mut Hook }

/// # Safety
/// The links form a valid reciprocal ring of live, initialized hooks.
/// Each touched field permits raw writes, with no conflicting references
/// or concurrent access. The storage remains stable throughout this call.
/// On return, h is isolated and the remaining ring is reciprocal.
unsafe fn unlink(h: *mut Hook) {
    unsafe {
        let before = (*h).prev;
        let after = (*h).next;
        (*before).next = after;
        (*after).prev = before;
        (*h).prev = h;
        (*h).next = h;
    }
}
```

The Rust function's documentation is a caller obligation. Rust checks its types
and unsafe-operation rules; it does not prove the ring contract. Crust checks
the declared result. Removing the `(*after).prev = before` store compiles as Rust
but fails Crust's relation proof. Never run the broken Rust body on the strength
of compilation alone.

This comparison checks one operation. It does not present that unsafe function
as a complete safe Rust container. A complete wrapper must enforce its
preconditions on every public path, including destruction and returned views.
Neither spelling has a runtime validity check or link tag.

### Safe borrowed links have a different lifetime contract

Rust can also store shared references in `Cell` without reference counting or
dynamic borrow checks:

```rust
use std::cell::Cell;

struct Hook<'a> {
    prev: Cell<Option<&'a Hook<'a>>>,
    next: Cell<Option<&'a Hook<'a>>>,
}

fn main() {
    let left = Box::new(Hook { prev: Cell::new(None), next: Cell::new(None) });
    let right = Box::new(Hook { prev: Cell::new(None), next: Cell::new(None) });
    left.next.set(Some(&right));
    right.prev.set(Some(&left));
    assert!(std::ptr::eq(left.next.get().unwrap(), &*right));
}
```

The [`Cell` API](https://doc.rust-lang.org/std/cell/struct.Cell.html) permits
interior mutation through shared access. This small borrowed graph is safe
Rust. Insert `drop(right);` before the assertion and Rust rejects E0505: the
node is still borrowed by the link. It does not establish the required
independent destruction-and-reuse API. A fixed common lifetime, a different
owning representation, and an encapsulated pinned raw implementation must be
compared as different designs.

## What the comparison establishes

For ordinary application code, Crust has familiar ownership concepts but more
explicit syntax and more conservative acceptance. Lexical scopes, whole-binding
loan restrictions, domain-wide exclusion, mandatory returned origins, and
branch-state agreement all impose visible work on the user. Calling the
current model simpler than Rust would omit that work.

For the implemented intrusive operations, Crust replaces manual raw-pointer
invariant reasoning with checked declarations. Authors do not supply solver
terms or ghost lemmas. They still learn member and anchor roles, domain effects,
isolation results, and exact field origins. Rust authors instead discharge the
corresponding address, aliasing, and destructor obligations inside an unsafe
implementation and design a safe API around it. Counting keywords alone would
not compare those tasks.

The full [acceptance gate](design.md#checked-ownership-target) remains open.
Crust has no accepted general contract for creating a runtime-sized owner set
across iterations, and it cannot yet supply the same range of stored-view
interfaces. The direct-list library/client comparison therefore does not cover
the complete required API. That prevents a claim that the overall complexity
ceiling has passed. This document adds no ownership mechanism to bypass it.

The examples establish source behavior, not compilation-speed equivalence.
Rust compiler timings are not measured here. Crust's target GCC and linker
costs must remain separate from frontend and ownership checking measurements.
