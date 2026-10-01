# Measured frontend compilation costs

Date: 2026-09-30. These are local measurements of installed compilers.
They are not measurements of the proposed Crust language.

## Main results

The costly work differs by workload. The profiles show costs beyond grammar
recognition. They do not measure the speedup from a different grammar.

| Language and workload | Main finding |
|---|---|
| C: SQLite amalgamation | Work is spread across token handling, semantic checks, source locations, tables, and tree allocation. There is no single dominant resolved sampled function. |
| C++: nlohmann JSON client | Header processing and template work dominate the trace. An include-only file already takes 88–89% of the client's check time. |
| Rust: regex-syntax | Type checking, constant evaluation, MIR construction, and borrow checks are substantial. Disabling Unicode features reduces check time by 43.4%. |

For C++, template-instantiation intervals cover about 54% of the instrumented
Clang action. For Rust, the high-level type-check stage takes about 50% of the
instrumented default-feature check. The later borrow-check stage takes 21%.
These percentages describe different compiler scopes. They are not comparable
language complexity scores.

The useful design consequence is broader than a simple grammar: keep declaration
loading, lookup, type checking, constant handling, and ownership analysis cheap.
The measurements support experiments in these areas. They do not prove that the
proposed rules can match C.

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

The machine has an AMD Ryzen Threadripper PRO 7995WX with 96 physical cores and
192 logical CPUs. It has approximately 503 GiB of RAM. Each command was pinned
to logical CPU 4. Its SMT sibling is CPU 100. The sibling was not reserved.
The CPU governor was `performance`; boost remained enabled.

The compilers were Clang 20.1.8, GCC 13.3.0, and rustc 1.90.0
(`1159e78c4`). They are the selected installed versions, not a claim about the
newest compiler releases. All used optimization level zero and no debug data.
Rust used one frontend thread and no incremental compilation.

Each case had one discarded warmup and 20 measured fresh processes.
The case order was shuffled in each round with a fixed seed. Commands ran
sequentially. Source downloads and profiler-tool builds finished before timing.
The initial machine load averages were below 0.2.

The filesystem cache was warm. No PCH, C++ modules, compiler cache, or compiler
daemon was used. Rust loaded its installed prebuilt standard library; C and C++
read installed headers. This difference is part of these workloads. It prevents
using this table as a cold standard-library build comparison.

The harness measured wall time around the process. GNU `time` recorded process
user time, system time, and peak resident memory. The wall measurement includes
the small `time` and `taskset` launcher costs. The Rust environment enabled
`RUSTC_BOOTSTRAP=1` to use the explicit thread and profiling flags in the same
installed compiler. It did not rebuild or replace that compiler.

## Uninstrumented check times

These runs had no phase timers, time traces, self profiler, or sampling profiler.
Times are milliseconds. Memory is peak resident memory, expressed in MiB.

| Workload | Compiler | Median wall | Min–max wall | Median user + system | Median peak memory |
|---|---|---:|---:|---:|---:|
| SQLite | Clang | 359.1 | 355.5–370.5 | 350 | 123.6 |
| SQLite | GCC | 219.6 | 214.6–225.1 | 210 | 79.7 |
| JSON include only | Clang | 710.6 | 703.1–716.9 | 700 | 175.7 |
| JSON client | Clang | 808.0 | 799.2–816.7 | 790 | 184.7 |
| JSON include only | GCC | 560.2 | 555.4–568.0 | 550 | 184.7 |
| JSON client | GCC | 629.5 | 620.8–638.5 | 620 | 198.2 |
| regex-syntax, default features | rustc | 587.0 | 578.5–600.1 | 575 | 246.6 |
| regex-syntax, std only | rustc | 332.2 | 327.2–340.2 | 320 | 161.2 |

These are different source workloads. The table does not establish that one
language compiles faster than another. Within the same C or C++ workload, it
does compare the selected installed compiler configurations.

The controlled variants give stronger local conclusions:

- Clang: adding the JSON client costs 97.4 ms. The include-only ratio is 87.95%.
- GCC: adding the JSON client costs 69.2 ms. The include-only ratio is 89.00%.
- Rust: disabling Unicode features removes 254.8 ms, or 43.40% of check time.

Paired bootstrap intervals use 10,000 draws from the 20 measurement rounds.
The 95% intervals for the differences are 93.9–101.4 ms, 64.2–72.3 ms, and
250.3–260.2 ms, respectively. They describe sampling variation in this run;
they do not cover other machines, libraries, or compiler versions.

The C++ delta is additional frontend work caused by this client. It is not pure
template cost. The include-only file already causes substantial instantiation
and semantic work.

## The profiler changes the result

Each phase profile was collected three times, separately from the timing runs.
Clang used a trace with zero duration threshold. GCC used `-ftime-report`.
Rust used JSON pass timers and the self profiler together.

| Workload | Instrumented median wall | Ratio to uninstrumented median |
|---|---:|---:|
| SQLite, Clang | 607.2 ms | 1.69 |
| SQLite, GCC | 1786.8 ms | 8.14 |
| JSON include only, Clang | 814.1 ms | 1.15 |
| JSON client, Clang | 945.9 ms | 1.17 |
| JSON include only, GCC | 2246.0 ms | 4.01 |
| JSON client, GCC | 2412.4 ms | 3.83 |
| regex-syntax, default | 661.4 ms | 1.13 |
| regex-syntax, std only | 378.2 ms | 1.14 |

The GCC effect is too large to treat its phase percentages as the normal
runtime distribution. Timer overhead can also affect phases unequally.
The raw reports are retained as evidence, but their percentages are not used
to claim that a normal C check spends half its time in the lexer.

Clang's C trace is also intrusive. Its per-event values locate work, but do not
establish uninstrumented costs. Trace serialization adds time outside the
`ExecuteCompiler` interval.

To check the hotspots without these timers, Linux `perf` sampled user-space
cycles at 997 Hz. Each sampling command ran 20 uninstrumented compiler checks.
There were no lost samples. The four profiles contain 4,164 to 16,025 samples.
Sampling still has overhead. These are sampled cycle shares, not wall-time
shares or exact operation counts.

Although the selected event is `cycles:u`, kernel-marked instruction addresses
account for 0.5–1.9% of the recorded sample weight. They remain unattributed.
The reported percentages retain the same complete denominator. These rows do
not establish a kernel CPU-time measurement.
Non-precise sampling can record an instruction pointer after a privilege
transition. This is a possible mechanism, not a diagnosis of this run.
[Linux event controls](https://man7.org/linux/man-pages/man2/perf_event_open.2.html),
[kernel sampling note](https://github.com/torvalds/linux/blob/3d8d74100954a3b17e5c5e37adfe14e16b1db103/kernel/events/core.c#L7812)

## C: many small frontend operations

SQLite is a substantial C input: the amalgamation has 262,899 physical lines,
including comments and disabled configurations. This count is not a count of
parsed statements or a throughput denominator.

In the Clang C traces, parse scopes contain about 79% of the instrumented action
after nested constant-evaluation scopes are subtracted. These parse scopes
include lexing and semantic actions. They do not measure grammar recognition
alone. Constant-evaluation scopes account for about 20% in this heavily
instrumented trace; that number is not an uninstrumented cost estimate.

The sampling profiles give concrete function-level evidence:

| Compiler | Sampled leaf function | Share of sampled user cycles |
|---|---|---:|
| GCC | `_cpp_lex_direct` | 8.00% |
| GCC | `get_combined_adhoc_loc` | 3.43% |
| GCC | `ht_lookup_with_hash` | 2.67% |
| GCC | `htab_find_slot_with_hash` | 2.44% |
| GCC | `linemap_position_for_column` | 2.17% |
| GCC | `convert_lvalue_to_rvalue` | 1.96% |
| GCC | `ggc_internal_alloc` | 1.94% |
| Clang | `Lexer::LexTokenInternal` | 3.22% |
| Clang | `StringMapImpl::LookupBucketFor` | 1.34% |
| Clang | `Preprocessor::Lex` | 1.17% |
| Clang | `Parser::ParseCastExpression` | 1.07% |

These are leaf samples. A caller's row does not include its callees.
All sampled functions are retained in the machine-readable results.
Unresolved user-mode addresses account for 28.6–35.2% of sampled cycles across the four
profiles. The named rows cannot provide a complete function-level cost partition.
Matching compiler debug symbols are required to resolve those addresses.
They can be applied to the saved perf data without repeating compilation.

For Clang, direct samples in `Sema` methods account for 18.1%. Lexer,
preprocessor, and token-lexer methods account for 10.3%. Parser methods account
for 6.6%. These name-based groups are incomplete operation totals: allocation,
AST, lookup, and helper functions can execute on their behalf.

The evidence supports keeping token access, source-location representation,
name tables, AST storage, and semantic actions cheap. It does not support a
claim that replacing the grammar alone removes most C frontend time.

## C++: headers and template work

Clang's template intervals cover about 54% of the instrumented JSON-client
action. This is the union of `InstantiateClass` and `InstantiateFunction`
intervals. Adding their individual totals would count nested work twice.

The median-action trace is useful because its buckets form one exact partition:

| Interval bucket | Time | Meaning |
|---|---:|---|
| Header without a template interval | 393.7 ms | Work while a header is active, outside the named instantiation scopes |
| Template interval outside headers | 404.3 ms | Mostly deferred instantiation and client-triggered work |
| Header and template overlap | 63.0 ms | Instantiation during header processing |
| Neither interval | 10.1 ms | Other action work |
| Total action | 871.2 ms | Instrumented `ExecuteCompiler` scope |

Values are rounded. The unrounded buckets sum to 871.174 ms.
Header time includes parsing and semantic work. It is not preprocessing time.
Template intervals do not include every operation caused by templates.

In the same trace, the disjoint X-scope self-time categories are approximately
48% template scopes, 36% parse scopes, 7% constant evaluation, and 9% residual
work. These are a second partition of the same time. Do not add them to the
header/template table.

The include-only result is particularly relevant to the language design.
It shows that a short client can inherit most of its frontend cost from a
library interface and its definitions. It does not prove that compiled module
interfaces remove all of that cost; deferred instantiation can remain.

Sampling also finds semantic work. In GCC, `push_to_top_level` accounts for
8.51% of sampled user cycles. Template argument hashing and `tsubst` account
for 1.43% and 1.32%. In Clang, sampled `Sema` methods account for 17.7%, while
parser methods account for 4.6%. These remain leaf-function observations.

## Rust: query dependencies cross phase boundaries

The following high-level timers are sibling intervals. Values are medians of
three profiled runs, in milliseconds.

| Stage | Default features | Std only |
|---|---:|---:|
| Expansion, including submodule parsing | 48.323 | 24.847 |
| Name resolution | 12.603 | 9.817 |
| Type-check stage | 309.526 | 121.401 |
| Later MIR borrow-check stage | 131.076 | 122.947 |
| Final checks, lints, and privacy | 28.335 | 16.280 |
| Metadata generation | 19.106 | 6.578 |
| Total internal timer | 617.540 | 337.723 |

The listed stages do not cover the complete total. Setup, HIR work, earlier
checks, teardown, and other work remain. The root-file `parse_crate` timer is
not all parsing: submodules are parsed during expansion.

Against the corresponding internal totals, the type-check stage takes
50.1% with default features and 35.9% with std only. The later borrow-check
stage takes 21.2% and 36.4%. Its label includes prerequisite checks and queries;
it is not an isolated lifetime solver.
[Rust required analyses](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_interface/src/passes.rs#L1079-L1110)

The self profiler provides another view. Self time subtracts nested events.

| Query or activity | Default self time | Std-only self time |
|---|---:|---:|
| `mir_borrowck` | 116.147 ms | 58.988 ms |
| `typeck` | 108.597 ms | 73.312 ms |
| `expand_crate` | 45.292 ms | 23.032 ms |
| `eval_to_allocation_raw` | 41.972 ms | 0.183 ms |
| `mir_built` | 31.879 ms | 16.167 ms |
| `hir_crate` | 26.553 ms | 12.457 ms |

The corresponding median event-span totals are 612.702 ms and 333.811 ms.
Thus `mir_borrowck` self time is 19.0% and 17.7% of those totals.
It is substantial in both configurations. It is not all frontend cost, and
its self time excludes helper queries called by the borrow checker.

The apparent mismatch between the two tables has a concrete cause.
The type-check stage eagerly evaluates nongeneric constants. Constant evaluation
requests MIR with drops and constant checks. That path requests borrow checking.
The later borrow-check stage reuses already computed query results.
[Type-check driver](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_hir_analysis/src/lib.rs#L234-L255),
[constant evaluation to borrow checking](https://github.com/rust-lang/rust/blob/1.90.0/compiler/rustc_mir_transform/src/lib.rs#L456-L499)

The default configuration has 1,531 `mir_borrowck` calls; std only has 1,004.
Constant-allocation evaluation has 1,082 calls versus 28. The default median
inclusive times are 212.507 ms for `mir_borrowck` and 268.873 ms for constant
allocation evaluation. These intervals overlap. They must not be added.

Therefore, the 8.1 ms difference in the later borrow-check stage is not the
total extra borrow-check cost from Unicode support. The query self-time
difference is 57.2 ms. The flattened query summaries cannot assign each call
to its requesting stage.

Nor do these profiles establish that trait solving is the main cost.
The named `evaluate_obligation` and `type_op_prove_predicate` queries use about
8.1 ms and 7.6 ms of default-feature self time. Those rows are not a complete
trait-analysis total. The large type-check stage also contains constant and
MIR work.

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
python3 benchmarks/frontend/profile.py measure --output .profile-cache/check-runs --repeats 20 --cpu 4
python3 benchmarks/frontend/profile.py profile --output .profile-cache/phase-runs --repeats 3 --cpu 4
python3 benchmarks/frontend/sample.py --output .profile-cache/samples --repeats 20 --cpu 4 --cases sqlite-gcc sqlite-clang-20 json-client-g++ json-client-clang++-20
~~~

Do not run the measurement commands concurrently.
The CPU number is a measurement parameter, not a portable requirement.

Build the pinned Rust profile reader before measurement, or after all compiler
runs. Its build time is not part of any result.

~~~sh
git clone https://github.com/rust-lang/measureme .profile-cache/tools/measureme
git -C .profile-cache/tools/measureme checkout 5ac839c602b59eee9c908b3b35b6d6c0cd1c42f7
cp benchmarks/frontend/measureme.Cargo.lock .profile-cache/tools/measureme/Cargo.lock
cargo build --manifest-path .profile-cache/tools/measureme/Cargo.toml --release --locked -p summarize -p crox --jobs 8
python3 benchmarks/frontend/analyze.py --output .profile-cache/reproduced-results
~~~

The profile reader is measureme 12.0.3, which matches rustc 1.90's dependency.
The repository retains the exact generated dependency lock used for its build.
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

The committed evidence includes all 160 timing samples, all 24 phase summaries,
Rust and GCC timer logs, sampling rows, source hashes, versions, and commands.
Large raw traces and perf data remain in the ignored cache. Their hashes are
recorded, and the scripts reproduce the collection procedure.
[Evidence directory](../../benchmarks/frontend/results/2026-09-30),
[timing summary](../../benchmarks/frontend/results/2026-09-30/timing-summary.json),
[phase profiles](../../benchmarks/frontend/results/2026-09-30/phase-profiles.json),
[sampling profiles](../../benchmarks/frontend/results/2026-09-30/sampling-profiles.json)
