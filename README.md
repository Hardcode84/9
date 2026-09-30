# RMD

RMD is a design study for a small systems programming language.
The main requirement is C-level compilation speed before backend processing.

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

Read the [compiler extension experiment](docs/compiler-extension-experiment.md)
for a small seed, ownership and unsafe stages, complete syntax replacement,
backend metastages, and a C compiler benchmark.

The repository does not contain an RMD compiler. RMD0 has raw memory
preconditions; the checked language's direct-list lifetime rule still needs
to be established. Neither language has a measured speed result.
