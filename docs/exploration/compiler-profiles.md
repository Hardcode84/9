<!-- SPDX-License-Identifier: Apache-2.0 -->

# Frontend compilation profiles

This study defines reproducible C, C++, and Rust checks before backend work.
Historical reports are retained outside the current source tree. Rerun the
commands below for the selected compiler versions and host; this document does
not publish machine-specific timings or claim current Crust performance.

The original profiles motivated separate investigations of C token handling,
source locations and allocation; C++ header and template work; and Rust type
checking, constants, MIR, and ownership checks. A simple grammar does not remove
these other costs. The controls below test those mechanisms without treating
different programs as an equivalent-language ranking.

## Measurement boundary

All headline runs stop at semantic checking:

| Compiler | Stop condition | Included work |
|---|---|---|
| Clang 20.1.8 | `-fsyntax-only` | Driver startup, preprocessing, parsing, semantic checks, and required template instantiation |
| GCC 13.3.0 | `-fsyntax-only` | Driver startup, preprocessing, parsing, semantic checks, and deferred frontend work |
| rustc 1.90.0 | `--emit=metadata` | Startup, module parsing, expansion, resolution, type and borrow checks, and metadata generation |

No headline run performs LLVM optimization, instruction selection, register
allocation, object emission, or linking. Rust still enters small metadata and
backend-setup paths. A timer named `codegen_crate` does not mean that functions
were compiled to machine code.
[Clang stage selection](https://clang.llvm.org/docs/CommandGuide/clang.html),
[GCC check-only exit](https://github.com/gcc-mirror/gcc/blob/releases/gcc-13.3.0/gcc/toplev.cc#L438),
[Rust metadata-only exit](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_codegen_ssa/src/base.rs#L643-L670)

This is the **check boundary** in the language design. It is not the complete
backend-handoff boundary. In particular, Rust metadata-only checking skips the
normal monomorphization collector and function LLVM IR construction. Clang also
skips LLVM IR construction. Code-generation-only checks are not forced.

Do not replace Rust's command with `-Zno-codegen` and assume identical work.
That option can still request monomorphization through generic-symbol exports.
Its output selection also requests more MIR work. `--emit=mir` is not an
equivalent stop condition either.
[Rust output classification](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_session/src/config.rs#L912-L923),
[generic-symbol queries](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_codegen_ssa/src/back/symbol_export.rs#L315-L336),
[MIR metadata policy](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_metadata/src/rmeta/encoder.rs#L1089-L1142)

## Inputs and controls

The source inputs are pinned and checked with SHA-256 before use.

| Input | Configuration |
|---|---|
| SQLite 3.50.4 | Published `sqlite3.c` amalgamation; default feature macros; GNU C11 |
| nlohmann JSON 3.12.0 | Published single header; C++17; installed libstdc++ 13 headers |
| regex-syntax 0.8.8 | Rust 2021; default `std` and Unicode features, then `std` only |

The C++ client parses JSON, converts an array to `vector<int>`, computes a sum,
adds two fields, and serializes the result. A second file only includes the
same header. Both files are in the repository.
[C++ client](../../benchmarks/frontend/json_client.cpp),
[include-only file](../../benchmarks/frontend/json_include.cpp)

The Rust crate has no enabled external crate dependencies. Its Unicode features
select generated data tables and related code. Disabling them changes supported
functionality; it is not an optimization of the same program.
[regex-syntax feature description](https://docs.rs/crate/regex-syntax/0.8.8),
[SQLite amalgamation](https://sqlite.org/amalgamation.html),
[nlohmann release](https://json.nlohmann.me/home/releases/#v3120-2025-04-11)

## Interpret profiles

Collect phase timers and sampling profiles separately from uninstrumented timing.
Timer overhead can affect phases unequally. Clang trace serialization can also
add work outside the `ExecuteCompiler` interval. Sampled user-cycle shares are
not elapsed-time shares or exact operation counts. Keep unresolved samples in
the denominator; resolving them requires matching compiler debug symbols.

For C, a parse scope includes token handling and semantic actions. It does not
isolate grammar recognition. Source-location lookup, hash tables, conversions,
and allocation can execute beneath those scopes. Leaf samples in a parser or
checker exclude its callees, so grouping functions by class name does not give
a complete cost partition.

For C++, compute unions of header and template intervals rather than adding
nested totals. Distinguish header-only time, template-only time, their overlap,
and the remaining action. Header time includes parsing and semantic work, not
only preprocessing. An include-only control tests inherited interface cost;
it does not prove that compiled interfaces eliminate deferred instantiation.

For Rust, `parse_crate` covers the root file; expansion can parse submodules.
The type-check driver evaluates nongeneric constants. Constant evaluation can
request MIR and borrow checks before the later borrow-check stage runs. That
later stage can reuse cached queries. A high-level stage timer therefore does
not isolate one semantic analysis.
[Type-check driver](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_hir_analysis/src/lib.rs#L234-L255),
[constant evaluation to borrow checking](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_mir_transform/src/lib.rs#L456-L499),
[required analyses](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_interface/src/passes.rs#L1079-L1110)

Query self time excludes helper queries. Inclusive query intervals can overlap
and must not be added. A flattened query summary cannot identify each caller's
stage. Named trait-solving rows also need not cover every operation that trait
analysis caused. Preserve these distinctions when using profiles to guide the
ownership stage or the compiler's parallel dependencies.

## Consequences for the proposed language

1. **Keep the parser independent of name resolution, but measure more than parsing.**
   Source locations, names, allocation, types, and semantic actions are material
   parts of the C profiles.
2. **Use small compiled interfaces.** The C++ include-only control shows a large
   inherited cost. Test interface loading and deferred work separately.
3. **Bound template and overload work.** C++ instantiation remains costly before
   any backend optimization. Syntax-only checking does not make it disappear.
4. **Keep constants simple.** Rust's data tables cause work across several query
   systems. Test a direct checked representation for literal aggregate data.
   Do not route every literal through a general execution engine by default.
5. **Measure the proposed ownership checker directly.** Rust's checker has a
   material cost, but these measurements do not predict a smaller checker's cost.
   Removing the borrow checker alone would not remove all other frontend work.
6. **Keep pass dependencies visible.** Query names and high-level stage names
   can describe different ownership of the same computation. A parallel design
   must expose the actual dependencies and measure waiting and total CPU use.

The current experiment uses one core. It gives no parallel-scaling result.
The library interfaces and program bodies differ between languages. It gives
no equivalent-program language ranking.

To validate the design's complete handoff gate, the measurement must also include
specialization, cleanup and ABI lowering, and backend-input construction.
That requires an instrumented stop after IR construction and before optimization
and output serialization, with serialization reported separately. The check-only
commands used here cannot establish that result.

## Reproduce and inspect

Run these commands from the repository root with Python 3.12 or newer.
The selected compilers, GNU `time`, `taskset`, and Linux `perf` must be available.
Each output directory must be new. The scripts fail on a compiler error.
They do not install or rebuild compilers.

~~~sh
python3 benchmarks/frontend/profile.py prepare
python3 benchmarks/frontend/profile.py measure --output build/benchmarks/frontend/check-runs --repeats 20 --cpu 4
python3 benchmarks/frontend/profile.py profile --output build/benchmarks/frontend/phase-runs --repeats 3 --cpu 4
python3 benchmarks/frontend/sample.py --output build/benchmarks/frontend/samples --repeats 20 --cpu 4 --cases sqlite-gcc sqlite-clang-20 json-client-g++ json-client-clang++-20
~~~

Do not run the measurement commands concurrently.
The CPU number is a measurement parameter, not a portable requirement.

Build the pinned Rust profile reader before measurement, or after all compiler
runs. Its build time is not part of any result.

~~~sh
git clone https://github.com/rust-lang/measureme .profile-cache/tools/measureme
git -C .profile-cache/tools/measureme checkout 5ac839c602b59eee9c908b3b35b6d6c0cd1c42f7
cargo generate-lockfile --manifest-path .profile-cache/tools/measureme/Cargo.toml
cargo build --manifest-path .profile-cache/tools/measureme/Cargo.toml --release --locked -p summarize -p crox --jobs 8
python3 benchmarks/frontend/analyze.py --output build/benchmarks/frontend/analysis
~~~

The profile reader is measureme 12.0.3, which matches rustc 1.90's dependency.
Generate and retain the dependency lock inside the ignored tool checkout.
The analyzer records its hash with the tool revision and binary hash. Keep that
lock unchanged when comparing runs; the tool revision alone does not pin its
transitive dependencies.
Its command is `summarize summarize --json PROFILE.mm_profdata`. The JSON is
written beside the input, not to standard output.
[Rust dependency lock](https://github.com/rust-lang/rust/blob/1.90.0/Cargo.lock),
[measureme reader](https://github.com/rust-lang/measureme/tree/5ac839c602b59eee9c908b3b35b6d6c0cd1c42f7/summarize)

The scripts use these compiler mechanisms:

- Clang 20 syntax-only traces use `-Xclang -ftime-trace=PATH` and
  `-Xclang -ftime-trace-granularity=0`. The normal driver option is ignored for
  this output-free action.
- GCC reports distinguish phase timers, stack timers, and overlapping lookup
  timers. The `|name lookup` and `|overload resolution` rows are overlays.
- Rust uses `-Ztime-passes-format=json` for precise durations and
  `-Zself-profile` for query attribution.

[Clang trace scheduling](https://github.com/llvm/llvm-project/blob/llvmorg-20.1.8/clang/lib/Driver/Driver.cpp#L5962),
[GCC timer accounting](https://github.com/gcc-mirror/gcc/blob/releases/gcc-13.3.0/gcc/timevar.cc#L294),
[Rust timer output](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_data_structures/src/profiling.rs#L849-L919)

The Clang trace reader subtracts nested complete events and computes unions
for overlapping intervals. It excludes synthetic `Total` events. LLVM 20
stores header `Source` spans as adjacent asynchronous begin/end records.
The reader verifies that format and rejects unsupported event layouts.
[Trace reader](../../benchmarks/frontend/clang_trace.py),
[LLVM trace format](https://github.com/llvm/llvm-project/blob/llvmorg-20.1.8/llvm/lib/Support/TimeProfiler.cpp#L228)

Measureme's label “Total cpu time” is not OS user-plus-system time when the
wall-time counter is selected. It sums per-thread event spans. The report uses
the name “event-span total” and keeps external CPU time separate.
[Measureme analysis](https://github.com/rust-lang/measureme/blob/5ac839c602b59eee9c908b3b35b6d6c0cd1c42f7/analyzeme/src/analysis.rs)

Keep raw traces, dependency locks, profiler output, and derived reports in
ignored storage. The analyzer reads `build/benchmarks/frontend/` by default;
use `--runs` for another captured run directory. It reads the profile-reader
checkout from `.profile-cache/`, or the directory selected by `--cache`.
Never replace a captured report with results from changed source bytes.
