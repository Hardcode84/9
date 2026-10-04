<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: an owning tree with parent links

Use the same opaque boundary as the [intrusive tutorial](../intrusive/README.md).
A parent owns its child through an ordinary child pointer. Each child also has
a non-owning parent pointer. There is no second ownership chain or tree rule
in the checker.

```sh
make all ownership-stage
build/crust examples/ownership-graphs/main.crs
build/ownership-graphs
```

The program prints `OK`. [main.crs](main.crs) explicitly trusts
[provider.crs](provider.crs) and checks [program.crs](program.crs).

`Tree` is an opaque owner. `TreeCursor` is an opaque scoped view. Both belong
to `Forest`. `tree_attach_left(mut parent, move child)` consumes one child owner
and transfers its cleanup duty into the parent's ordinary child link. The
trusted body uses `forget move child` after that transfer. This operation
requires implementation trust; checked clients cannot use it to escape cleanup.

`tree_take_left(mut parent)` clears that ownership link, repairs the parent
reference, and returns an independent owner. The client can destroy the old
parent while the removed child remains live. `tree_drop` destroys an entire
owned subtree through iterative pointer operations. It uses the parent links
for traversal and allocates no cleanup stack.

All ownership transfers require reclamation access. Read access creates scoped
cursors and payload loans. A cursor from either the child or its parent prevents
reclamation until its access scope ends. The checker does not infer acyclicity
or inspect heap edges. The provider must preserve its tree representation and
its declared retention and retirement contract. Invalid attach or remove calls
trap explicitly.

The client tests ownership transfer, navigation to a parent, removal, individual
release, replacement, and subtree cleanup. `make check-ownership` also compares
emitted C and symbols before and after checking. Run
`python3 tests/ownership.py --build build --sanitize` for native ASan and UBSan.
