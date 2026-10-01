# crust

Crust is a small systems programming language project.
The main requirement is C-level compilation speed before backend processing.

The Crust0 bootstrap compiler is implemented in pedantic C99 with arena
allocation. `crust` executes compilation programs; `crust0` emits textual x86-64
assembly for the system assembler and linker. Run `make` to build them and
`make check` to run the tests. The host runner uses libffi.
Read the [bootstrap guide](docs/bootstrap.md) for commands, public stage APIs,
the compiled replacement-stage example, and measurement boundaries.

An optional [C backend stage](docs/c-backend.md) is written entirely in Crust0.
Run `make c-stage` to build it through the seed and then through its own C
output. It uses GCC for native code and retains the C99 reader and checker.

Run a [compilation program](docs/source-runner.md) with `crust main.crust`.
The root selects its sources, stages, and outputs through ordinary calls.
It can change the reader for its remaining bytes. The
[hello-world example](examples/hello/main.crust) keeps the compilation program
and target program in the same file:

```sh
make all c-stage
build/crust examples/hello/main.crust
build/hello
make check-examples
```

The root controls reading, checking, and output through public APIs.
Root and target code use separate namespaces, even when they share a file.
The [example index](examples/README.md) also covers arguments, multiple target
files, intrusive lists, a new root grammar, and a custom assembly stage.

Start with the [Crust0 language specification](docs/crust0-spec.md). It defines the
minimal bootstrap language, complete grammar, execution rules, and public stage
contracts. Module management, ownership, richer syntax, and backend adapters
belong to compiled libraries. The seed has no import or module syntax.

Read the [language exploration](docs/language-exploration.md) for the research,
candidate checked-language rules, systems requirements, and acceptance tests.

The optional [resource stage](stages/resources/README.md) implements ownership,
local loans, RAII, and `defer` entirely in Crust. It uses a generic Crust reader and
a generic C function-body callback. Run `make resource-stage` to build it.
The [design record](docs/resource-metastage.md) explains its contracts and
bounded SQLite application test.

The optional [overload stage](stages/overload/README.md) selects functions by
exact parameter types and assigns stable native names. It is also written in
Crust. The root can select it alone or compose it with the resource stage.
Run `make overload-stage`, then try the
[same-file example](examples/overload/hello/main.crust) or the
[separate-object example](examples/overload/separate/main.crust).

Read the [compiler profiles](docs/compiler-profiles.md) for measured C, C++, and
Rust frontend costs, profiler overhead, and repeatable commands.

Read the [systems source study](docs/systems-capabilities.md) for direct intrusive
lists and storage requirements from Linux, GCC, LLVM, and Coho.

Read the [metacompilation study](docs/metacompilation.md) for Jai, Lisp, Scheme,
Forth, staged language extensions, a public compiler pipeline, and caching.

Read the [source metastage review](docs/source-metastages.md) for the Zig and
Jai comparison and the phase contract used by the source-stage design.

Read the [source-order design study](docs/source-order-compilation.md) for
the research and experiment plan. The [runner contract](docs/source-runner.md)
defines the implemented interface and its measurement boundary.

Read the [compiler extension experiment](docs/compiler-extension-experiment.md)
for a small seed, ownership and unsafe stages, complete syntax replacement,
backend metastages, and a C compiler benchmark.

Crust0 has raw memory preconditions. The checked language's direct-list lifetime
rule still requires a specified rule and a checked implementation. The C99
bootstrap and its measurements do not establish that safety claim.
