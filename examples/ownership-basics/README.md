<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership basics

Read the [ownership tutorial](../../docs/ownership.md) for the rules, small
examples, and corrections for rejected code. The [Rust comparison](../../docs/ownership-rust.md)
uses the same resource operations and separate intrusive-list examples.

From the repository root:

```sh
make all ownership-stage Z3_FLAGS=-l:libz3.so.4
build/crust examples/ownership-basics/main.crs
build/ownership-basics
```

The output is `BC` and a newline. [program.crs](program.crs) moves a resource,
borrows its field, changes it, and checks explicit and scope-exit destruction.

```sh
build/crust examples/ownership-basics/main.crs -o build/ownership-heap \
    examples/ownership-basics/heap.crs
build/ownership-heap
```

The output is `AB` and a newline. [heap.crs](heap.crs) owns individual heap
allocations. Each allocation can be released before the next one is made.
The allocator can reuse the address; the program does not require reuse.

The Rust version of the first example needs no external crate:

```sh
rustc --edition=2024 examples/ownership-basics/program.rs -o build/ownership-rust
build/ownership-rust
```

## Stored views

[views.crs](views.crs) keeps shared or exclusive access inside ordinary records.
This is useful when a helper needs to retain a reference together with scalar
state. It does not need a pool, allocation, or runtime loan registry.

```sh
build/crust examples/ownership-basics/main.crs -o build/ownership-views \
    examples/ownership-basics/views.crs
build/ownership-views
```

The output is `OK` and a newline. `Reading` holds a shared integer loan and a
scalar tag. `Editing` holds a mutable integer loan. `MeterView` borrows a whole
record; `Wrapped` contains another view record by value.

The factory contract states the origin:

```crust
fn editing_new(value: mut i64) -> Editing from value {
    return make Editing { value: mut value };
}
```

`editing_set(mut view, value)` changes the borrowed integer. `editing_read`
and `editing_mut` return reborrows through `from view.value`. The source
uses `move` to transfer a view and `drop` to end it before direct access to
the integer. Neither operation destroys that integer.

The stage retains each field's loan, checks its source scope, and rejects
conflicting access. Function bodies must establish their declared result
origins. Callers use those declarations without inspecting bodies. Borrowed
record parameters must retain their stored origins. A returned record's borrowed
fields must all derive from its one declared `from` path.

Resource lowering turns stored views into pointer fields and ordinary loads
or stores. Ownership facts remain in the checker. The example checks pointer
layout and verifies that borrowed records remain usable after their view ends.

```sh
make check-ownership check-ownership-imports Z3_FLAGS=-l:libz3.so.4
python3 tests/ownership_views.py --sanitize
```

The tests compare emitted C before and after verification, execute optimized
and unoptimized programs, and reject scope escape, alias conflicts, incorrect
result origins, source destruction, and use after a move. They also check a
client after removing its provider source. The basic view checks run with an
interceptor that fails if the stage starts Z3. Domain field conditions still
use the separate proof path.
