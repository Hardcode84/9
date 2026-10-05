<!-- SPDX-License-Identifier: Apache-2.0 -->

# Overloads with ownership and cleanup

Read the [overload tutorial](../../../stages/overload/README.md) and
[resource tutorial](../../../stages/resources/README.md) first. This example
shows where their source contracts meet. Run from the repository root:

```sh
make all overload-stage
build/crust examples/overload/resources/main.crs
build/overload-resources
```

Expected output:

```text
Owned overloads.
Deferred overload.
```

The root selects a package that composes two Crust stages. Overload selection
runs before ownership checking and cleanup lowering.

`write` accepts a raw string or a shared view of owned text. The source type
selects the function. The two `release` functions close a file descriptor and
free allocated text. Resource declarations select these drop functions by
their exact `mut` parameter types. `move` transfers the text owner. `defer`
schedules the final write before the output descriptor is closed.

The native calls and raw pointer operations remain inside `unsafe` regions.
Overload selection does not change their safety rules.

Read [main.crs](main.crs) from its root setup to its target entry. The root
loads `resource_api.crs` and the composed library, then calls
`overload_resource_build`. The composed driver performs these operations:

1. Read the complete overload and resource syntax.
2. Select calls and each declared drop using source types.
3. Assign distinct internal names and stable native link names.
4. Check moves and loans, then build cleanup plans.
5. Emit C with the resource body callback.

The order matters. `read Text` and `mut Text` lower to pointers, but grant
different permissions. Resolving overloads after lowering would lose that
source distinction. Drop selection also needs the exact `mut Output` or
`mut Text` type before the resource checker can validate it.

The [resource provider](../../../stages/resources/source.crs) supplies source
query services and marks source ABI imports. The
[compilation driver](../../../stages/overload/resource_program.crs) selects
those services and the reader chain. `make check-overload` checks output and
rejection paths. The [composition tutorial](../../composition/README.md) adds
field ownership checks through the same query interface.
