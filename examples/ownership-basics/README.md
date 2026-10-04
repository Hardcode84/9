<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership basics

Read the [ownership tutorial](../../docs/ownership.md) for the rules, small
examples, and corrections for rejected code. The [Rust comparison](../../docs/ownership-rust.md)
uses the same resource operations and separate intrusive-list examples.

From the repository root:

```sh
make all ownership-stage
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

## Native handles

[handles.crs](handles.crs) owns POSIX file descriptors and opaque C streams.
The descriptor uses an `i32`. The stream uses a `*u8`. Both need one owner,
borrowed access, and one cleanup action. Neither needs a storage domain.

```sh
build/crust examples/ownership-basics/main.crs -o build/ownership-handles \
    examples/ownership-basics/handles.crs
build/ownership-handles
```

The output is `OK`, a newline, then `SFF`. `S` marks stream cleanup. Each `F`
marks descriptor cleanup. The failed acquisition has no cleanup duty. Moving
the duplicate descriptor does not add a cleanup action.

The declaration `owns(handle = -1i32)` identifies an owned native value and its
invalid representation. An acquisition function returns that kind. An ordinary
integer cannot initialize the field. The opaque stream uses the same contract
with `null(*u8)` as its invalid value. This pointer cannot be dereferenced.
Allocation owners use the additional `owns(field: storage)` contract.

The `clone_fd` declaration has two independent effects. It borrows its input
and returns a new owner. `close_fd` consumes an explicitly moved input. The
source calls use the native scalar ABI, with no wrapper conversion at the C
boundary. Check the declared invalid value with `==` or `!=` before native use.
Move or borrow whole wrappers across ordinary Crust function boundaries.

The native declarations are trusted. Their implementations must obey the
acquisition, borrowing, and consumption contracts. Consumption applies even
when the native function reports an error. Both example destructors trap on a
cleanup error. A caller can instead consume an unwrapped acquisition result
explicitly and process the returned status before it continues.

The reader records these contracts on the existing AST. The checker follows
owned values through local control flow. The native resource kind and validity
facts do not appear in the output. Resource lowering inserts ordinary cleanup
calls. The example checks that each wrapper has the size of its raw handle.

```sh
python3 tests/ownership_native.py --sanitize
```

This test runs the program at `-O0` and `-O2`, compares output before and after
ownership verification, and checks a client after removal of its provider
source. It rejects duplicate owners, unguarded use, invalid transfers,
conflicting borrows, and ownership loss across branches and loops.

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

`Comparison` combines two independently returned views locally. A helper can
borrow that record without a new result-origin contract. The example also
drops a local `Reading`, assigns a new factory result, and changes the old
source. The new source remains borrowed until the replacement view ends.
Replacing a view through `mut Reading`, or returning both independent origins
through one `from` path, is rejected.

Resource lowering turns stored views into pointer fields and ordinary loads
or stores. Ownership facts remain in the checker. The example checks pointer
layout and verifies that borrowed records remain usable after their view ends.

```sh
make check-ownership check-ownership-imports
python3 tests/ownership_views.py --sanitize
```

The tests compare emitted C before and after verification, execute optimized
and unoptimized programs, and reject scope escape, alias conflicts, incorrect
result origins, source destruction, and use after a move. They also check a
client using only the published interface and native object. Ownership checks
use finite local rules.
