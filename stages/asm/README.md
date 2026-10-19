<!-- SPDX-License-Identifier: Apache-2.0 -->

# Assembly backend in Crust

This library maps checked Crust operations to Linux x86-64 System V assembly
or Windows x64 COFF assembly. Source packages select the platform provider.
The C99 seed contains no assembly emitter. A root can interpret this source,
compile it, or load its compiled library through the ordinary runner API.

```sh
make all test-tools build/crust0
build/crust0 -o build/list.s examples/intrusive/raw.crs
gcc -no-pie build/list.s build/libcrust0_host.a -o build/list
build/list
make check-asm
```

`crust0` is a native test driver linked to this stage. Application roots use
[package.crs](package.crs) with the [shared loader](../build/README.md).
The [cache tutorial](../../examples/cached-backend/README.md) also shows how to
interpret the assembly stage directly for a first native library.

## Interface

The [C header](../../include/crust0_x64.h) defines the public layout and function
contract. `tools/api.py` generates both the
[consumer declarations](../../api/crust0_x64.crs) and [model](model.crs).
A native C consumer links `libcrust_asm.a` before `libcrust0.a`. A source root
prepares `stages/asm/package.crs` before it calls these functions.

The Windows package compiler uses MinGW-w64 `as` and the shared DLL linker.
It supports integer and binary32 scalar calls, including native callbacks.
Each function reserves its outgoing argument area in its fixed frame, saves
the nonvolatile registers it uses, probes the stack through `___chkstk_ms`,
and emits Windows unwind records. RSP does not change in the function body.
Frames that exceed the supported unwind encoding size are rejected.
Binary32 operations and saturating casts use SSE registers. The Linux provider
retains its existing binary32 rejection. See the
[Windows checks](../../tests/windows_backends.py) for ABI and generation tests.

`crust_x64_prepare` requires checked declarations with assigned native names.
An empty name selects an owned private definition. External declarations need
a nonempty name. The plan exposes stack slots, expressions, aliases, and
functions. A caller can edit the plan while it keeps these invariants valid.

`crust_x64_emit_program_with_ops` accepts optional expression, place, and
statement callbacks. A null callback selects the default operation. Public
`crust_x64_try_*` functions return false with a diagnostic on failure. Native
callers check that result and retain control of their own cleanup. The
[custom operation example](../../examples/custom-stage/README.md) shows how to
install an emitter callback.

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
and a map of visited pairs.

`make check` covers behavior, public layouts, callbacks, allocation failures,
and output failures. `make check-asm` verifies that the seed and core archive
have no backend symbols. It then builds three assembly stage generations,
compares their emitted assembly, and runs the intrusive-list program from the
last generation. These generation checks use no artifact cache.

## Compile a cached package with ASM

A package can select this backend for native library builds:

```crust
stage_compiler(stage, "../asm/compiler-package.crs", "asm_stage_compile");
stage_toolchain(stage, "asm_stage_toolchain");
```

Adjust the compiler path relative to the package file. Add the package's sources
and exports with the usual `stage_source` and `stage_export` calls. This compiler
accepts raw Crust sources and rejects source options. It emits complete assembly
with the selected native names. Its symbol map is empty. GNU assembler produces
the object; the shared package builder links and caches the library.

The [package guide](../build/README.md#select-an-object-toolchain) defines the
factory, captured tool inputs, object callback, and output lifetimes.
