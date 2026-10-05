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

## Measured client gate

Run the comparison from the repository root. It requires `rustc` with Rust
2024 edition support, in addition to the normal Crust build tools.

```sh
make check-ownership-ergonomics
python3 tests/ownership_ergonomics.py --report
```

The first command checks the reviewed source budget, builds both languages at
optimization levels 0 and 2, and runs each program with two argument lists.
Both versions must pass their internal assertions, return zero, and produce
the expected output. The test also checks five Rust rejection cases: tree
destruction and editing with live cursors, index destruction and removal with
live selections, and cursor dereference without `unsafe`.

The comparison uses these complete programs:

| Program | Crust client | Rust client | Output |
| --- | --- | --- | --- |
| Resource move, field loan, cleanup | [basics](../examples/ownership-basics/program.crs) | [basics](../examples/ownership-basics/program.rs) | `BC` |
| Two intrusive memberships, individual retirement, payload edit | [intrusive](../examples/intrusive/program.crs) | [intrusive](../examples/intrusive/program.rs) | `OK` |
| Owning tree, parent view, detach, retirement | [tree](../examples/ownership-graphs/program.crs) | [tree](../examples/ownership-graphs/program.rs) | `OK` |
| One-way aliases, retained selection, rebind, retirement | [index](../examples/ownership-index/program.crs) | [index](../examples/ownership-index/program.rs) | `OK` |

Each output ends with a newline. Providers keep direct links and individual
allocations. The tree ports use parent links for iterative destruction. Both
index providers clear incoming aliases before release. The Rust index uses
`Cell` for alias rebinding through a shared index reference; a selection keeps
an ordinary index loan that blocks removal. This permits the same old-selection
test after rebinding. It also permits rebinding while a shared payload loan is
live; Crust's domain rule rejects that operation.

The Rust intrusive provider pins stack heads and unlinks nodes on destruction.
Its cursor retains a raw address. The client must prove that address remains
live for cursor access, and must exclude conflicting payload access. Three
explicit unsafe operations carry these duties. The Crust client gets these
checks from its access scopes and trusted provider contract. Thus the intrusive
row compares source costs and behavior across different checking guarantees.
Its Rust count supplies no safety-equivalent bound. Rust's
[pinning contract](https://doc.rust-lang.org/std/pin/index.html#an-intrusive-doubly-linked-list)
describes address stability and destruction; the
[unsafe contract](https://doc.rust-lang.org/reference/unsafe-keyword.html)
assigns additional obligations to unsafe callers.

### Count ownership syntax

The [counter](../tests/ownership_ergonomics.py) reports each function and a
separate declaration total. It reads `program.crs` and `program.rs`; provider
implementation and compilation setup are outside the count. The providers are
available beside the clients. Their source hashes are part of the review.

Count written syntax with these rules:

- Count each `read`, `mut`, and `&`. This includes Rust local `mut` bindings
  and Crust addresses passed to head initializers. Count each explicit `move`.
- Count each cleanup `drop`, `defer`, and `forget`, plus Rust's `Drop` trait
  name. Exclude the function name in `fn drop`.
- Count each ownership type marker, such as `resource`, and each Rust lifetime
  token, including `'_`. A declared and a used lifetime each count once.
- Count `from` and each identifier in its origin paths. Count `access` and
  its permission and domain names. Punctuation has no weight.
- Count an access block's mode and domain name. Report the number of these
  blocks separately. Count each written `unsafe` and `pin!` invocation.
- Exclude comments, string contents, general type names, dereference operators,
  ordinary punctuation, implicit reborrows, and inferred lifetimes. Rust's
  [elision rules](https://doc.rust-lang.org/reference/lifetime-elision.html)
  define when lifetime annotations can be omitted.

This lexical metric measures explicit syntax. The programs have no local macros
that hide ownership operations. Standard assertion and printing macros are
outside the count. Moving code into a helper or provider changes the review
boundary and requires a new review.

| Client / function | Crust tokens | Rust tokens |
| --- | ---: | ---: |
| Basics / destructor | 1 | 2 |
| Basics / `ticket_code` | 6 | 3 |
| Basics / `set_code` | 1 | 2 |
| Basics / `main` | 5 | 5 |
| Basics / declarations | 2 | 1 |
| Intrusive / `main` | 39 | 23 |
| Tree / `main` | 22 | 15 |
| Index / `comparison_equal` | 1 | 3 |
| Index / `expect_alias` | 12 | 5 |
| Index / `expect_unbound` | 6 | 2 |
| Index / `remove_required` | 5 | 2 |
| Index / `main` | 37 | 47 |
| Index / declarations | 2 | 6 |

The intrusive Rust count includes three `unsafe` tokens and two `pin!` calls.
The other Rust clients use safe interfaces. The basics total is 15 versus 13;
the tree total is 22 versus 15; the index total is 63 versus 65. These counts
do not meet a universal bound of Crust annotations less than or equal to Rust.

### Count required changes in program structure

Review the purpose of each scope, explicit view drop, and loop-control flag.
Syntax alone cannot tell whether a block is required by the checker or by the
program's cleanup order. The review in
[the budget file](../tests/ownership_ergonomics.json) records this distinction.

| Required structure | Basics | Intrusive | Tree | Index |
| --- | ---: | ---: | ---: | ---: |
| Crust read/edit blocks omitted by the Rust port | 0 | 2 | 2 | 1 |
| Extra plain blocks needed only by the Crust checker | 0 | 0 | 0 | 0 |
| Explicit view drops needed only by the Crust checker | 0 | 0 | 0 | 0 |
| Flags used instead of `break` or `continue` | 0 | 0 | 0 | 0 |
| Rust pin bindings for stable stack heads | 0 | 2 | 0 | 0 |

The intrusive and index clients each also have one named Crust domain block.
The Rust versions have an ordinary block there to preserve cleanup order.
The head and replacement-owner blocks in the intrusive example, and the last
ticket block in the basics example, also preserve required destruction order.
Explicit owner destruction serves the same purpose in both languages.

### Acceptance rule

Keep the recorded per-function counts and restructuring audit as the regression
budget for these four clients. The pre-commit check compares counts and hashes
of tokens against the reviewed budget. Any source change requires review,
including a reduction in tokens. This prevents a change in behavior, trust, or
hidden helper work from passing only because it has a smaller count.

For an update, run `--report`, compare the changed operations and guarantees,
review all scopes and cleanup sites, and run the executable comparison. Update
the budget and these tables together. An increase needs a concrete program
requirement and an explanation at the affected API or example. Lower counts
must preserve the paired behavior and the stated checks. The script prints
candidate counts; it never accepts them automatically.

The measured claim is a stable, reviewed client budget. Provider author effort,
diagnostic quality, learnability, and the full set of accepted programs need
different evidence. A general claim that the entire ownership model is at most
as complex as Rust exceeds what this gate measures. All local safety contracts,
erasure checks, and trusted-provider tests remain required.

For native memory checks, run:

```sh
python3 tests/ownership_ergonomics.py --sanitize
```

This adds ASan and UBSan to the Crust output and ASan to the Rust ports. The
Rust command uses the installed compiler's `-Zsanitizer=address` pass with
`RUSTC_BOOTSTRAP=1`. A compiler without that pass fails the command explicitly.
Generated artifacts stay under `build/`. These runs check native behavior;
they supply no compilation-speed result.
