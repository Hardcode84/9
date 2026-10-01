# Examples

Run the commands below from the repository root. Build the tools once:

```sh
make all c-stage
```

## Tutorials

Start with Hello World. Then follow the compiler stages from source input to
native output. Each tutorial explains the motivation, design, implementation,
and commands to inspect the result.

| Order | Tutorial | What you will build or inspect |
| --- | --- | --- |
| 1 | [Hello World](hello/README.md) | A compilation program and target program in one file |
| 2 | [C backend](../stages/c/README.md) | C text, explicit evaluation order, native symbols, and body callbacks |
| 3 | [Function overloads](../stages/overload/README.md) | Exact type selection, symbol mangling, and separate objects |
| 4 | [Ownership, RAII, and defer](../stages/resources/README.md) | Moves, loans, rejected programs, and emitted cleanup plans |
| 5 | [Syntax highlighting](../stages/highlight/README.md) | HTML, editor tokens, custom reader services, and a VS Code extension |

The overload and ownership tutorials include deliberate compiler errors.
They state the required diagnostic and then show the correction. The stage
references retain the complete API and language contracts.

## Runnable examples

Each example has its own directory and README.

| Directory | Example | Output |
| --- | --- | --- |
| [hello](hello/README.md) | Compilation code and target code in one file | `Hello, world!` |
| [arguments](arguments/README.md) | Separate compiler arguments from target arguments | Each target argument on its own line |
| [multiple-files](multiple-files/README.md) | Select and compile two target files | `Hello from another source file!` |
| [intrusive](intrusive/README.md) | Build a direct intrusive list | `intrusive: ok` |
| [reader-switch](reader-switch/README.md) | Replace the reader and executor from the root | Two lines read with a new grammar |
| [custom-stage](custom-stage/README.md) | Compile a decimal number with a custom reader and assembly operation | Target exit status 42 |
| [highlight](highlight/README.md) | Classify source with ordinary Crust stages | Highlighted HTML or JSON tokens |
| [resources/hello](resources/hello/README.md) | Select ownership, RAII, and defer in the same source file | `Hello, resources!` |
| [resources/sqlite](resources/sqlite/README.md) | Own SQLite connections and statements; borrow column bytes | Typed rows and separate error codes |
| [overload/hello](overload/hello/README.md) | Select overloads and a typed function value in the same file | Two greeting lines |
| [overload/separate](overload/separate/README.md) | Link overloaded functions from a separate native object | `types: 42` |
| [overload/resources](overload/resources/README.md) | Combine overloads, ownership, overloaded drops, and defer | Owned and deferred output |

The root files select their compiler libraries explicitly. Resource examples
require `make resource-stage`. The SQLite example also needs its pinned native
SQLite input; its README gives the command.
Overload examples require `make overload-stage`.
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
custom assembly stage.

Run `make check-resources` for the resource hello and resource language tests.
The SQLite verifier checks the native application against its frozen C baseline.
Run `make check-overload` for the overload examples, native symbols, separate
objects, and resource composition tests.
Run `make check-highlight` for the highlighter roots and native service.
Run `make check-vscode` with Bun for the editor adapter tests.

Recorded benchmark JSON files retain the source paths and hashes from their
original revisions. The live measurement scripts use the current example paths.
