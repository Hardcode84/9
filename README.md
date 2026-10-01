# Crust

Crust is a systems programming language built around three priorities:
**small, fast, and extensible**.

Keep the core small enough to understand and implement. Make compilation
fast enough to keep development interactive. Let programs define the
language they need through ordinary libraries, and pay only for what they use.

## Design principles

- **Compilation speed first.** C-level compilation speed before backend
  processing is the main requirement.
- **A small, extensible core.** Add language features through libraries.
  Keep the compiler interfaces open to replacement readers, checkers, and
  backends.
- **Compilation is a program.** `crust main.crs` executes the source from
  the beginning. That program selects inputs, stages, and outputs. It can
  change how the following source is read.
- **Explicit costs.** No implicit heap allocation or garbage collection.
  Programs use only the language stages they select.
- **Independent work.** Keep stage dependencies explicit so independent
  work can run in parallel. Root actions retain their source order.

## Quick start

The current implementation targets Linux x86-64. It uses a pedantic C99 bootstrap
compiler. Install GCC, GNU Make, GNU binutils, Python 3, and the libffi
development headers and library.

From the repository root:

```sh
make all c-stage
build/crust examples/hello/main.crs
build/hello
```

The program prints `Hello, world!`. The [example source](examples/hello/main.crs)
contains both the compilation program and the target program. The first
command builds the compiler and C backend; the second builds the example;
the third runs it.

## Documentation

- [Core design and compilation flow](docs/design.md)
- [Language specification](docs/crust0-spec.md)
- [Tutorials and examples](examples/README.md)
- [Compilation programs and stage APIs](docs/source-runner.md)
- [Build, tests, and contributor setup](docs/bootstrap.md)
- [Research and design exploration](docs/exploration/README.md)
