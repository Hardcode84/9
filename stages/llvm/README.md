<!-- SPDX-License-Identifier: Apache-2.0 -->

# LLVM backend

This Crust stage emits LLVM IR from complete, checked raw Crust bodies.
It targets Linux x86-64 with the System V scalar ABI. The C99 seed stays
unchanged. LLVM runs as an external tool.

Start with the [LLVM tutorial](../../examples/llvm/README.md). Fetch the
selected release before use:

```sh
make fetch-llvm-release
make all
build/crust examples/llvm/main.crs
make check-llvm
```

The fetch command selects the latest stable release. Compilation uses the
recorded selection. An absent pin is an error. See the
[fetch contract](../../docs/bootstrap.md#fetch-llvm) for checksums and updates.

## Package interface

Add these calls to an application package:

```crs
stage_compiler(stage,"../../stages/llvm/compiler-package.crs","llvm_stage_compile");
stage_toolchain(stage,"llvm_stage_toolchain");
```

Paths are relative to that package. The shared package builder compiles and
loads the emitter through its C bootstrap. The selected emitter then writes
LLVM IR and a symbol response file. Its object callback runs the pinned Clang
with `-O0` and `-fPIC`. The shared builder applies the symbol map with `objcopy`,
links the shared library, and publishes it in the cache.

The package builder captures emitter sources, tool configuration, Clang bytes,
and loaded tool libraries before cache lookup. It also captures its linker and
symbol tools. Source, optimization, or tool changes select a different artifact.
LLVM package compilation accepts no source options. Put checks and source
transformations in a compiler callback before emission.

## Frontend output interface

`compiler-package.crs` also exports `llvm_backend_build`. Its signature is:

```crs
fn llvm_backend_build(context:*CrustContext, entry:*CrustDecl,
                      options:*BackendOptions)->i32
```

Include `stages/c/api.crs` for `BackendOptions`. The frontend must supply
complete checked raw bodies and assigned native names. Keep these inputs and
all imported provider declarations live until emission returns. A null entry
selects a library. Other entries have type `fn(i32,**u8)->i32`.

Mode 0 builds an executable; mode 1 builds an object; mode 2 writes LLVM IR
and an optional symbol response file; mode 3 prepares both texts in memory
without file publication. `cflags` supplies extra Clang compilation arguments.
`ldflags` supplies extra GCC link arguments. The default package uses its
pinned release at `-O0`. The custom compiler configuration defines
`LLVM_DIRECTORY` and `LLVM_OPTIMIZATION` (0 through 3).

The driver reuses the C stage's output-file and process helpers. Clang consumes
LLVM IR directly. GNU `objcopy` assigns native symbols; GCC links executable
outputs. Failed tools retain the previous output and remove temporary files.
The call returns zero, a failed tool's status, or one for another failure.
It records failures in the caller's context.

The [tutorial matrix](../../examples/README.md#test-the-backend-matrix) uses this
interface after each frontend's lowering. It also uses `og_stage_emit` to
compile the frontend libraries through LLVM with their source trust annotations.

## Select another LLVM installation

A compiler package can include `compiler-sources.crs` and supply its own
factory instead of including `compiler-package.crs`:

```crs
fn selected_tools(tools:*StageToolchain)->bool {
    return llvm_toolchain(tools,LLVM_DIRECTORY,2u32);
}
```

Define `LLVM_DIRECTORY` as the absolute path of the selected installation.
It must contain `bin/clang`. Export `llvm_stage_compile` and `selected_tools`
from this compiler package. Select the latter with `stage_toolchain` in the
application package. The accepted optimization levels are 0 through 3. Clang
runs the corresponding LLVM optimization and code-generation pipeline.
The factory captures the selected tool and optimization level for the cache.

To use the pinned upstream main sources, build them explicitly:

```sh
make fetch-llvm-main
llvm_source=$(python3 tools/fetch_llvm.py main --locked)
cmake -S "$llvm_source/llvm" -B build/toolchains/llvm/main-build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DLLVM_TARGETS_TO_BUILD=X86 \
  -DLLVM_ENABLE_PROJECTS=clang -DLLVM_ENABLE_ASSERTIONS=ON \
  -DLLVM_FORCE_VC_REVISION="${llvm_source##*/main-}" \
  -DLLVM_FORCE_VC_REPOSITORY=https://github.com/llvm/llvm-project \
  -DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF \
  -DLLVM_INCLUDE_EXAMPLES=OFF
cmake --build build/toolchains/llvm/main-build --target clang llvm-as opt llc
```

Use the absolute path of `build/toolchains/llvm/main-build` as
`LLVM_DIRECTORY`. Keep the source pin and CMake configuration with the build.
The package cache keys the resulting tool bytes and library dependencies.
Treat that installation as immutable during compilation.

## Emitter interface

`package.crs` exports [api.crs](api.crs). Include the core API,
`stages/c/model.crs`, and [model.crs](model.crs) before those declarations.
The emitter reuses the C stage's arena and text-buffer utilities.

1. Read, resolve, and check the complete raw program.
2. Set each native declaration name. An empty name means a private definition.
3. Initialize a fresh `LlStage` with `ll_init`.
4. Call `ll_emit`. A null entry selects a library. A hosted entry has type
   `fn(i32,**u8)->i32`.
5. Consume `stage.memory.header` followed by `stage.memory.body` as LLVM IR.
   Consume `stage.memory.renames` as the `objcopy` response file.
6. Call `ll_destroy` after the last buffer use.

The checked input and its context must stay live through emission. Errors
return failure and set the context diagnostic. The output buffers belong to
the stage. `ll_save` in `compiler.crs` writes both output files; call it once
after emission. The shared builder owns temporary-file cleanup.

Set `stage.expression` to replace expression lowering. The callback receives
`LlFunction` and the checked expression. It returns a scalar LLVM operand or,
for an aggregate, the address of a snapshot. It must report an error before
returning null. `stage.user` carries caller-owned data. Use `ll_value` for
children so that nested expressions use the selected callback. Call
`ll_expression` for default lowering. Public helpers expose types, ABI
attributes, instructions, storage, places, and control flow.

To select a different pass pipeline or object tool, install your own
`StageObject` callback in a `StageToolchain` factory. Capture every tool and
configuration input before cache lookup. The package interface imposes no
LLVM-specific pass policy. A different target also needs a layout and ABI
adapter: the raw seed types have the current 64-bit host layout.

## Execution rules

- Locals and aggregate snapshots use entry-block storage. LLVM can promote
  this storage during optimization.
- Integer operations wrap. Division, remainder, and invalid shift counts
  have the required explicit trap paths.
- Expression evaluation follows source order. Boolean short circuit uses
  branches. General labels and jumps also carry lowered cleanup paths.
- Boolean storage is one byte. Function calls use `i1 zeroext`. Narrow integer
  parameters and results carry the System V extension attributes.
- Aggregate assignment takes a snapshot before the destination write. Raw
  pointers keep their alias behavior. The emitter adds no exclusive-access,
  signed-overflow, or object-bound promises.
- Function definitions use `no-builtins`. A raw function name grants no C
  library semantics. This also permits a Crust runtime to define `memset`.
- Generated LLVM names pass through the shared symbol map. This preserves
  accepted ASCII native names, including names the integrated assembler
  would otherwise treat as local labels.

Object files can require host memory routines for aggregate copies. Native
linking supplies them through the ordinary runtime libraries.

## Checks and measurement

`make check-llvm` checks raw arithmetic, native callbacks, aggregate overlap,
raw aliases, exact symbols, runtime definitions, a replaced lowering, resource
cleanup, checked intrusive lists, and SQLite. It runs native programs at
`-O0` and `-O2`. It also builds three successive emitter generations and checks
package reuse, invalidation, and diagnostics. Allocation tests fail each
emitter backing allocation and check diagnostics and storage release.

Run the same semantic checks against another LLVM build with:

```sh
python3 tests/llvm.py --llvm build/toolchains/llvm/main-build
python3 tests/llvm_packages.py --llvm build/toolchains/llvm/main-build
```

The [measurement tool](../../benchmarks/llvm/README.md) separates complete
frontend and IR text construction from LLVM tool execution and linking.

Typed field and element access uses LLVM `getelementptr` with the declared
record or element type. Record padding and array stride come from that type.
`ll_element` accepts explicit element, pointer, and index types. An adapter can
use an address-space-qualified pointer and a 32-bit index. `ll_offset` remains
available for explicit byte access. Neither helper adds `inbounds` promises.
The default emitter still uses the Linux x86-64 layout and scalar ABI.
