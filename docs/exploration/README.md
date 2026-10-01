<!-- SPDX-License-Identifier: Apache-2.0 -->

# Language and compiler exploration

These notes preserve the research and experiments that informed Crust.
Each document states its date and status. Proposed syntax and interfaces
are not additional features of the current language. Commands in historical
experiments can require the revision named in that document.

Start with the [current design guide](../design.md) for the implemented
architecture. Use the [language specification](../crust0-spec.md) and
[runner contract](../source-runner.md) for current rules.

| Study | Contents |
| --- | --- |
| [Language exploration](language-exploration.md) | C, C++, D, Rust, Zig, Jai, academic work, syntax, ownership, and acceptance criteria |
| [Compiler profiles](compiler-profiles.md) | Measured C, C++, and Rust frontend costs and reproduction commands |
| [Systems capabilities](systems-capabilities.md) | Linux, GCC, LLVM, and Coho source requirements, including direct intrusive lists |
| [Metacompilation](metacompilation.md) | Jai, Lisp, Scheme, Racket, Forth, small cores, stage dependencies, and caching |
| [Compiler extension experiment](compiler-extension-experiment.md) | Replaceable syntax and stages, backend adapters, and a proposed C compiler benchmark |
| [Source metastages](source-metastages.md) | Zig and Jai comparison and the choice to select stages in source |
| [Native host-stage experiment](source-stages.md) | The removed native host-block launcher and its measured preparation cost |
| [Source-order compilation study](source-order-compilation.md) | Action boundaries, execution choices, and the experiment that led to the current runner |
| [Resource stage design](resource-metastage.md) | Ownership and cleanup design, implementation evidence, and the separate intrusive observer requirement |
| [Syntax highlighting](syntax-highlighting.md) | Reader token probe, stage-owned classifications, HTML output, and VS Code interfaces |

Recorded benchmark data remains in [benchmarks](../../benchmarks/).
Its source names, revisions, and hashes identify the measured inputs.
Moving these notes does not update those historical inputs or results.
