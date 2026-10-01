# RMD

RMD is a small systems programming language project.
The main requirement is C-level compilation speed before backend processing.

The RMD0 bootstrap compiler is implemented in pedantic C99 with arena
allocation. It emits textual x86-64 assembly for the system assembler and
linker. Run `make` to build it and `make check` to run the tests.
Read the [bootstrap guide](docs/bootstrap.md) for commands, public stage APIs,
the compiled replacement-stage example, and measurement boundaries.

An optional [C backend stage](docs/c-backend.md) is written entirely in RMD0.
Run `make c-stage` to build it through the seed and then through its own C
output. It uses GCC for native code and retains the C99 reader and checker.

Start with the [RMD0 language specification](docs/rmd0-spec.md). It defines the
minimal bootstrap language, complete grammar, execution rules, and public stage
contracts. Module management, ownership, richer syntax, and backend adapters
belong to compiled libraries. The seed has no import or module syntax.

Read the [language exploration](docs/language-exploration.md) for the research,
candidate checked-language rules, systems requirements, and acceptance tests.

Read the [compiler profiles](docs/compiler-profiles.md) for measured C, C++, and
Rust frontend costs, profiler overhead, and repeatable commands.

Read the [systems source study](docs/systems-capabilities.md) for direct intrusive
lists and storage requirements from Linux, GCC, LLVM, and Coho.

Read the [metacompilation study](docs/metacompilation.md) for Jai, Lisp, Scheme,
Forth, staged language extensions, a public compiler pipeline, and caching.

Read the [source metastage review](docs/source-metastages.md) for the Zig and
Jai comparison, source-defined compiler control, and the phase contract that
must precede new syntax.

Read the [compiler extension experiment](docs/compiler-extension-experiment.md)
for a small seed, ownership and unsafe stages, complete syntax replacement,
backend metastages, and a C compiler benchmark.

RMD0 has raw memory preconditions. The checked language's direct-list lifetime
rule still requires a specified rule and a checked implementation. The C99
bootstrap and its measurements do not establish that safety claim.
