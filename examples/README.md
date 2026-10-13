<!-- SPDX-License-Identifier: Apache-2.0 -->

# Examples

Run the commands below from the repository root. Build the tools once:

```sh
make all
```

The [LLVM tutorial](llvm/README.md) shows how to select a pinned LLVM toolchain
and compile an application through the generic package interface. Run
`make check-llvm` for this tutorial and the LLVM semantic tests.

## Select a backend

The application roots accept a backend selection before their compiler arguments.
They use C by default. To compile the same source through LLVM:

```sh
make fetch-llvm-release
build/crust examples/hello/main.crs \
  --backend stages/llvm/compiler-package.crs llvm_backend_build
build/hello
build/crust examples/intrusive/main.crs \
  --backend stages/llvm/compiler-package.crs llvm_backend_build
build/intrusive-checked
```

[backend.crs](backend.crs) implements this option in ordinary compilation code.
It loads a package, gets its output callback, and passes the callback to the
frontend. The callback receives checked raw bodies, the entry declaration, and
`BackendOptions`. Root source controls this selection. Package paths are
relative to the repository directory selected by each root.

`--stage-compiler PACKAGE ENTRY TOOLCHAIN` also selects how `example_load`
builds the frontend libraries. Its compiler must accept the packages' source
annotations: `raw`, `trusted`, or empty for checked ownership code. The helper
preserves these annotations. It marks ordinary raw packages as `raw`. This
keeps the union stage's checked implementation under ownership checking when
its backend changes. The initial C bootstrap prepares the selected compiler.

To define a root with a fixed backend, pass its output function directly.
For example, `c_build(source, begin, argc, argv, c_backend_build)` selects C.
The selector is a convenience shared by these tutorials.

## Test the backend matrix

Prepare the pinned SQLite input as described in the
[SQLite tutorial](resources/sqlite/README.md), then run:

```sh
make fetch-llvm-release
make check-tutorials
```

The matrix runs application tutorials through C, LLVM `-O0`, and LLVM `-O2`.
The LLVM profiles also compile their loaded frontend libraries with LLVM.
One set of source files and expected results covers separate modules, overload
objects, ownership, cleanup, intrusive containers, generics, tagged unions,
and SQLite success and failure. Native highlighter and CCN stages must produce
the same output as their interpreted tutorial roots. Rejections must retain
the same diagnostic across profiles. The test also checks text emission,
preparation without publication, and preservation of output after tool failure.
It records results and hashes under `build/tutorial-matrix/`.

The C-emitter, LLVM-package, ASM bootstrap, custom assembly, cache, and reader
replacement tutorials teach explicit execution policies. Their checks preserve
those policies. Run `make check-c check-llvm check-examples check-native
check-cache check-stage` for those paths. The matrix covers their shared target
language and frontend services through the application tutorials.

For a selected local LLVM build, use an explicit installation path:

```sh
python3 tests/tutorials.py --llvm build/toolchains/llvm/main-build
```

## Tutorials

The [getting started guide](../docs/tutorial.md) teaches the core language and
compilation stages through one program that you can build and extend.

Start with Hello World, then read the [ownership guide](../docs/ownership.md)
for the user-facing rules. The stage tutorials explain implementation and
commands to inspect compilation. The [Rust comparison](../docs/ownership-rust.md)
separates application rules from container-author obligations.

| Order | Tutorial | What you will build or inspect |
| --- | --- | --- |
| 1 | [Hello World](hello/README.md) | A compilation program and target program in one file |
| 2 | [C backend](../stages/c/README.md) | C text, explicit evaluation order, native symbols, and body callbacks |
| 3 | [Function overloads](../stages/overload/README.md) | Exact type selection, symbol mangling, and separate objects |
| 4 | [Ownership, RAII, and defer](../stages/resources/README.md) | Moves, loans, rejected programs, and explicit cleanup calls |
| 5 | [Syntax highlighting](../stages/highlight/README.md) | HTML, editor tokens, custom reader services, and a VS Code extension |
| 6 | [Modules](../stages/modules/README.md) | Separate contexts, selected imports, native exports, and provider lifetimes |
| 7 | [Native bootstrap](../stages/native/README.md) | Build stages from source and hand following compilation code to native execution |
| 8 | [Cyclomatic complexity](../stages/ccn/README.md) | Count decisions with the public AST and reject functions before backend emission |
| 9 | [Intrusive lists](intrusive/README.md) | Use a trusted opaque provider with checked traversal, destruction, and reuse |
| 10 | [Owning tree](ownership-graphs/README.md) | Transfer child ownership behind the same checked interface |
| 11 | [One-way index](ownership-index/README.md) | Retire a symbol with incoming aliases and check local views from separate inputs |
| 12 | [Generics](generics/README.md) | Declare type parameters beside records and functions; use explicit type arguments |
| 13 | [Generics with ownership](generics/ownership/README.md) | Check generic payload contracts and use an intrusive container with plain and resource payloads |
| 14 | [Stage composition](composition/README.md) | Select ownership and overload providers through ordered reader and source query chains |
| 15 | [Tagged unions](union/README.md) | Define variants and select an arm with an exhaustive match in an external stage |

The overload and ownership tutorials include deliberate compiler errors.
They state the required diagnostic and then show the correction. The stage
references retain the complete API and language contracts.

## Runnable examples

Each example has its own directory and README.

| Directory | Example | Output |
| --- | --- | --- |
| [hello](hello/README.md) | Compilation code and target code in one file | `Hello, world!` |
| [ownership-basics](ownership-basics/README.md) | Moves, loans, returned views, cleanup, and individual heap owners | `BC`; heap example: `AB` |
| [arguments](arguments/README.md) | Separate compiler arguments from target arguments | Each target argument on its own line |
| [multiple-files](multiple-files/README.md) | Select and compile two target files | `Hello from another source file!` |
| [modules](modules/README.md) | Compile separate namespaces and import selected names | `modules: 42` |
| [union](union/README.md) | Construct events and handle each variant | `union: OK` |
| [generics](generics/README.md) | Specialize a shared pair definition for two payload types | `generics: OK` |
| [native](native/README.md) | Bootstrap stages and execute compilation functions natively | `Hello from a bootstrapped native stage!` |
| [intrusive](intrusive/README.md) | Check two intrusive memberships with node and head destructors | `OK` |
| [ownership-graphs](ownership-graphs/README.md) | Detach a child owner and destroy an owned subtree | `OK` |
| [ownership-index](ownership-index/README.md) | Clear one-way aliases before individual symbol release and reuse | `OK` |
| [cached-backend](cached-backend/README.md) | Bootstrap native stages from source and reuse the library | Native ASM/C handoff and hello output |
| [reader-switch](reader-switch/README.md) | Replace the reader and executor from the root | Two lines read with a new grammar |
| [custom-stage](custom-stage/README.md) | Compile a decimal number with a custom reader and assembly operation | Target exit status 42 |
| [highlight](highlight/README.md) | Classify source with ordinary Crust stages | Highlighted HTML or JSON tokens |
| [ccn](ccn/README.md) | Measure function complexity and select a compilation limit | CCN report or checked executable |
| [resources/hello](resources/hello/README.md) | Select ownership, RAII, and defer in the same source file | `Hello, resources!` |
| [resources/returned](resources/returned/README.md) | Return a field view tied to a source loan | `42` |
| [resources/sqlite](resources/sqlite/README.md) | Own SQLite connections and statements; borrow column bytes | Typed rows and separate error codes |
| [overload/hello](overload/hello/README.md) | Select overloads and a typed function value in the same file | Two greeting lines |
| [overload/separate](overload/separate/README.md) | Link overloaded functions from a separate native object | `types: 42` |
| [composition](composition/README.md) | Select independent ownership and overload stages in the root | `!B` |
| [overload/resources](overload/resources/README.md) | Combine overloads, ownership, overloaded drops, and defer | Owned and deferred output |

The root files prepare their compiler stages from captured source packages.
Run `make all` to build the seed. Each root reuses the shared bootstrap and
cache code. The SQLite example also needs its pinned native SQLite input;
its README gives the command. The intrusive `raw-main.crs` root contains the
unchecked seed-language bootstrap witness.
Paths passed to `host_source`, `host_input`, and `host_path` are relative to the
root file. A raw `-o` argument passed to the C backend is relative to the working
directory. Each example states its output path. A root builds an executable;
run that executable as a separate command.

`reader-switch` executes text actions directly and does not build an executable.
`custom-stage` uses the seed compiler to build a separate compiler executable.

Run `make check-examples` to check the root examples. The test copies their
unchanged source files and selected libraries into a path with spaces. It runs
them from a separate working directory, executes their outputs, and checks
reader and inline-target errors. `make check` and `make check-c` also check the
custom assembly stage. These checks use the raw intrusive witness. The modular
intrusive root runs in `make check-ownership`.

Run `make check-resources` for the resource hello and resource language tests.
Run `make check-ownership check-ownership-imports` for local ownership, trusted
containers, and independent library contracts. Run `make check-ownership-alloc`
for compiler allocation failures.
The SQLite verifier checks the native application against its frozen C baseline.
Run `make check-overload` for the overload examples, native symbols, separate
objects, and resource composition tests.
Run `make check-highlight` for the highlighter roots and native service.
Run `make check-vscode` with Bun for the editor adapter tests.
Run `make check-modules` for module bindings, exports, and allocation failures.
Run `make check-generics` for specialization, bindings, type identity, and allocation failures.
Run `make check-ownership-generics` for generic ownership contracts, cleanup,
native container behavior, and independent imports.
Run `make check-native` for native bootstrap, handoff, and cleanup. The root
prepares the assembly library and its executor through shared package code. Run `make check-cache` for source-only startup, artifact reuse,
invalidation, corruption, concurrency, and cleanup.
Run `make check-ccn` for function counts, the Lizard comparison, and the CCN build
example. This check needs `lizard==1.21.6` in the Python environment.

The [benchmark tools](../benchmarks/README.md) use the current example paths.
Keep generated reports and their input hashes in ignored build storage.

Run `make check-union check-union-alloc` for union syntax, layout, both backends,
evaluator execution, and allocation-failure checks under ASan and UBSan.
