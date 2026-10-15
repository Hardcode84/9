<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: Hello World in one file

[main.crs](main.crs) contains the compilation program and the target program.
The compilation program selects a backend and an output file. The target
program prints a greeting.

## Build and run

Use Linux x86-64 with the tools listed in the
[bootstrap guide](../../docs/bootstrap.md). Run from the repository root:

```sh
make all
build/crust examples/hello/main.crs
build/hello
```

The executable prints `Hello, world!` and returns zero.
`make all` builds the seed. The compilation program prepares its backend from
source and reuses the cached library on later builds.

## Select the build

```crust
host_source(run, "../../stages/build/load.crs");
if !application_setup(run, "../..") { return 1i32; };
var stages: *StageSession = stage_open(run, "../..", "../../build/stage-cache");
if stages == null(*StageSession) { return 1i32; };
return application(stages, "../../build/hello", c_backend_build);
```

`run` is the current compilation program's state. Setup loads the shared
build interfaces. `stage_open` prepares the backend and retains its libraries
until the root ends. It must succeed before the root takes a native backend
callback. Paths start at the directory that contains `main.crs`.

`application` compiles the source after the final `return` statement.
Its last argument selects the backend callback. Here, `c_backend_build` emits C
and calls GCC. A root can pass another loaded callback with the same contract.
The [build helper guide](../../stages/build/README.md#build-an-application)
describes the callback and command-line backend overrides.

The build helper uses a separate target context. Target declarations have their
own scope. Diagnostics refer to line numbers in the complete source file.
The comment before the target is for the reader; the root cursor sets the
source boundary.

## Write the target program

```crust
extern fn puts(text: *u8) -> i32 = "puts";

fn main(argc: i32, argv: **u8) -> i32 {
    if puts("Hello, world!") < 0i32 { return 1i32; }
    return 0i32;
}
```

The external declaration gives the type and native link name of `puts`.
The backend links the system C library. `puts` appends a newline; a negative
result causes the target to return one.

The hosted entry takes an argument count and an argument array, even when it
does not use them. The executable runs independently of the compiler library.

Change the greeting, then repeat the build and run commands. To change the
output path, edit the second argument to `application`.

## Continue

The [multiple-file example](../multiple-files/README.md) selects source files
explicitly. The [arguments example](../arguments/README.md) shows how a root
handles compiler and target arguments. The [C backend tutorial](../../stages/c/README.md)
explains emission. The [source runner contract](../../docs/source-runner.md)
defines execution and source boundaries.
