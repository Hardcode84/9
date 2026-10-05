<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership: Crust and Rust

Both models use owners, moves, shared loans, exclusive loans, and scope cleanup.
Crust's optional stage checks each body from local facts and declared function
and field contracts. An opaque raw container implementation requires explicit
root-selected trust. This is a library correctness obligation,
not a compiler proof of its internal pointer algorithm.

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

## Application code

| Task | Crust stage | Rust |
| --- | --- | --- |
| Transfer an owner | Explicit `move` | Move for a non-`Copy` value |
| Shared or exclusive access | `read T`, `mut T` | `&T`, `&mut T` |
| End a named loan | Last use at a statement boundary, scope exit, or explicit `drop` | Borrow checking can end it after its last use |
| Return a view | Finite `from parameter.path, other.path` set | Declared lifetime relationships, with elision where applicable |
| Store several local origins | View record fields retain their loans | References with lifetime parameters |
| Return several distinct origins | One origin set shared by all result fields; separate calls retain independent field origins | Distinct declared lifetimes can express the relationship |
| Replace a stored origin through a borrower | Rejected; replace a local view after consuming it | Must satisfy the declared reference lifetimes |
| Own an integer handle | Native acquisition and consumption contracts on `owns(field)` | A wrapper owns the handle; native implementation establishes its contract |
| Own an allocation | `owns(field: storage)` with local loans; transparent owned trees need no domain | `Box<T>` with ordinary reference lifetimes |
| Direct graph access | Opaque scoped view and domain permission | A safe library interface over implementation-specific invariants |

Rust's [borrowing chapter](https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html)
explains shared and mutable references and last-use lifetimes. Crust ends local
views at statement boundaries and joins uses across branches. An outer view
used in a loop remains live at the loop backedge. Child views and deferred
captures retain their source loans. These are bounded body-local rules; the
table gives the function and stored-origin boundaries.

## Container authors

Crust's intrusive provider has direct pointer fields, in-place stack heads, and
independent node owners. Its retirement functions unlink before release. The
root selects those definitions as trusted; clients cannot access their opaque
representation. A fresh domain scope separates independent instances. Read and
edit scopes suspend reclamation, including implicit cleanup. A payload loan
also excludes conflicting access inside the domain.

Rust's [pinning documentation](https://doc.rust-lang.org/std/pin/#an-intrusive-doubly-linked-list)
describes the same address-stability problem for intrusive lists. Its drop
guarantee requires notification before pinned storage is invalidated. `Pin`
alone does not prove a pointer algorithm correct. A safe interface must uphold
its implementation contract.

Crust's trusted provider boundary serves a similar purpose to a Rust library's
unsafe implementation boundary. Neither annotation repairs an incorrect unlink.
The [Rustonomicon](https://doc.rust-lang.org/nomicon/working-with-unsafe.html)
explains why safe callers must not be able to violate the invariants required
by unsafe internals. Crust therefore binds opaque representation, domain access,
and destructor permission in the public interface. Imported receipts preserve
root-selected trust; a library cannot approve itself.

## Cost and limits

Crust uses ordinary pointers and explicit cleanup calls. Domain identities,
loan origins, and verification facts have no runtime representation. There is
no pointer checking, tag, reference count, membership counter, hidden ownership
chain, or dynamic drop flag. Branches must agree on cleanup state.

This is not a claim that all Rust abstractions have overhead. Both languages
can use compile-time ownership facts. Compare the same library behavior and
emitted code. Crust's erasure tests compare C and symbol bytes before and after
verification, at no optimization level. Its [benchmark](../benchmarks/ownership/README.md)
measures compiled-stage checking separately from target GCC.

The [intrusive tutorial](../examples/intrusive/README.md) and
[owning tree](../examples/ownership-graphs/README.md), and
[one-way index](../examples/ownership-index/README.md) show all annotations and
trusted pointer bodies. The compiler has no rules for those field names or
operations. Safety depends on correct trusted providers and foreign contracts.
The stage is not a concurrency model or a formal proof of the compiler.

The [returned-origin example](../examples/ownership-basics/origins.crs) uses
`from left, right` to select either borrowed input. The caller keeps both inputs
borrowed while the result is live. Rust expresses this case with a shared
lifetime parameter on both inputs and the result:

```rust
fn pick<'a>(left: &'a i64, right: &'a i64, first: bool) -> &'a i64 {
    if first { left } else { right }
}
```

A Crust result record uses one origin set for all borrowed fields. Rust can give
separate fields distinct lifetime parameters. Crust code can use separate
factory calls to preserve those independent origins. The index and stored-view
examples combine such results locally and replace a local view after `drop`.
