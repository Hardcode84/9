<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: declare a different pointer graph

This program uses the same ownership stage as the intrusive-list tutorial.
It declares a branch with a parent and two children. The stage has no tree rule.

```sh
make ownership-stage
build/crust examples/ownership-graphs/main.crs
build/ownership-graphs
```

The program prints `OK`. It attaches a child, reads the child's payload through
the parent, destroys the parent, and checks that the child remains live with
no parent reference.

[program.crs](program.crs) declares three retained fields. The parent must name
this branch through either child field. Each child must name this branch as
its parent. `detach` states a postcondition in which all three fields are null.
It preserves the conditions of every other branch through ordinary stores.
Release then uses the general absence-of-surviving-references rule.

`attach_left` requires an empty left slot and a child with no parent. Its
caller checks those conditions. The write contract names field classes, so a
call that can change a class discards facts about that class on other objects.
A narrow `modifies` clause retains facts about unchanged fields. This tutorial
does not require a per-object write-set language.

Each allocation has a separate `Owner`. The parent and child fields do not own
storage. These conditions describe safe pointer connections; they do not prove
that a graph is acyclic or balanced. A program that requires those properties
needs an interface that establishes them.

Compare the declarations and function bodies with the
[intrusive tutorial](../intrusive/README.md). Both use the same `references`,
`invariant`, `requires`, `ensures`, and `modifies` forms. Neither registers
container operations or proof callbacks.
