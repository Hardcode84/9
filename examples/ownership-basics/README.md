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
