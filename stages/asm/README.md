<!-- SPDX-License-Identifier: Apache-2.0 -->

# Assembly backend in Crust

This library maps checked Crust operations to Linux x86-64 System V assembly.
The C99 seed contains no assembly emitter. A root can interpret this source,
compile it, or load its compiled library through the ordinary runner API.

```sh
make all
build/crust0 -o build/list.s examples/intrusive/program.crs
gcc -no-pie build/list.s build/libcrust0_host.a -o build/list
build/list
make check-asm
```

`crust0` is a standalone consumer of this stage. The Make build first interprets
[the C bootstrap](../c/bootstrap.crs), then uses that compiler to build this
library. This route needs no checked-in generated file or binary. The same
assembly source can run under a separate evaluator and context.

## Interface

The [C header](../../include/crust0_x64.h) defines the public layout and function
contract. `tools/api.py` generates both the
[consumer declarations](../../api/crust0_x64.crs) and [model](model.crs).
A native C consumer links `libcrust_asm.a` before `libcrust0.a`. A source root
loads `crust-asm-library.so` explicitly before it calls these functions.

`crust_x64_prepare` requires checked declarations with assigned native names.
An empty name selects an owned private definition. External declarations need
a nonempty name. The plan exposes stack slots, expressions, aliases, and
functions. A caller can edit the plan while it keeps these invariants valid.

`crust_x64_emit_program_with_ops` accepts optional expression, place, and
statement callbacks. A null callback selects the default operation. Public
`crust_x64_try_*` functions return false with a diagnostic on failure. They do
not unwind through native callers. The C-only variadic and throwing entry
points have been removed. See the [custom operation example](../../examples/custom-stage/README.md).

## Implementation

| File | Responsibility |
| --- | --- |
| [plan.crs](plan.crs) | Native names and ABI agreement, frame storage, and expression plans |
| [output.crs](output.crs) | Text, numbers, diagnostics, and callback dispatch |
| [emit.crs](emit.crs) | Instructions, scalar ABI, wrapping arithmetic, traps, and aggregate snapshots |
| [program.crs](program.crs) | Public operations, constants, strings, and complete output |

Plans belong to the supplied context arena. Source bytes and checked facts
stay live through emission. Each emitter owns its error state and current
loop. Failed callbacks retain their diagnostic; a false result without one
gets a diagnostic. Output errors stop subsequent writes. Loop state is restored
before an operation returns, including after a nested failure.

Internal emission trusts checked input. Source nesting is bounded by the
reader and checker. Native function-type comparison uses an explicit worklist
and a map of visited pairs. No C-private failure frame or type-comparison
service is required.

`make check` covers behavior, public layouts, callbacks, allocation failures,
and output failures. `make check-asm` verifies that the seed and core archive
have no backend symbols. It then builds three assembly stage generations,
compares their emitted assembly, and runs the intrusive-list program from the
last generation. These generation checks use no artifact cache.
