<!-- SPDX-License-Identifier: Apache-2.0 -->

# Compile a program with LLVM

This example builds `hello` with LLVM, loads the resulting native library,
and calls it from the compilation program. LLVM is an external stage selected
by the application package.

## Run it

From the repository root:

```sh
make all
make fetch-llvm-release
build/crust examples/llvm/main.crs
```

The output is:

```text
Hello from LLVM!
```

The fetch target downloads the latest stable Linux x86-64 LLVM release and
records a local pin. Later compilations use that pin. Run the fetch target
again to select a newer release.

## Write the program

[program.crs](program.crs) defines an ordinary function and a foreign call:

```crs
extern fn puts(text:*u8)->i32="puts";
fn hello()->i32 {puts("Hello from LLVM!");return 0i32;}
```

`puts` comes from the host C library. `hello` returns a status to its caller.

## Select the compiler

[package.crs](package.crs) lists inputs, exports `hello`, and selects LLVM:

```crs
stage_source(stage,"../../api/crust0.crs");
stage_source(stage,"program.crs");
stage_export(stage,"hello");
stage_compiler(stage,"../../stages/llvm/compiler-package.crs","llvm_stage_compile");
stage_toolchain(stage,"llvm_stage_toolchain");
```

Paths are relative to this package. The core API supplies the package ABI
identity. The last two calls select the source-to-IR callback and the native
object toolchain. LLVM emits the machine code for `hello`.

## Load and call the result

[main.crs](main.crs) is the compilation program:

```crs
host_source(run,"../../stages/build/load.crs");
if !stage_setup(run,"../.."){return 1i32;};
var stages:*StageSession=stage_open(run,"../..","../../build/stage-cache");
if stages==null(*StageSession) || !stage_load(stages,"examples/llvm/package.crs"){return 1i32;};
extern fn hello()->i32="hello";
return hello();
```

The shared loader prepares the compiler package and its dependencies.
`stage_load` obtains the native application library and links it into the
running compilation program. The following declaration binds `hello` to its
native export. The final call executes it.

On a cache miss, the shared bootstrap compiles the LLVM emitter through C.
The emitter writes LLVM IR directly for the selected application. Clang
compiles that IR; the shared package builder applies exact native symbols,
links, and caches the library. A later invocation validates inputs and reuses
the library. `make all` builds only the seed.

## Change optimization or extend lowering

The supplied toolchain selects `-O0`. Supply an ordinary toolchain factory
with `llvm_toolchain(...,2u32)` to select `-O2`. A factory can also select a
locally built, pinned LLVM main installation.

For a language extension, lower its operations to checked raw Crust before
calling the emitter, or replace the emitter's expression callback. The
[backend reference](../../stages/llvm/README.md) specifies those interfaces,
input lifetimes, target rules, and toolchain configuration.

Run `make check-llvm` for the semantic and package bootstrap tests. The tests
also compile the resource stage's output, including cleanup, through LLVM.
