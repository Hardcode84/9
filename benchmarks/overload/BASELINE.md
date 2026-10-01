# Overload stage baseline

The stage must select exact parameter types before the ordinary checker runs.
It must emit the same direct calls as a program with explicit function names.
This experiment tests that benefit and records its compilation cost. It does
not authorize candidate search, implicit conversion, or runtime dispatch.

## Frozen input

`measure.py` produces a provider and a caller. Each provider function accepts
a pointer to a distinct nominal record. All records have the same layout.
The caller makes each record, executes 4,096 calls, checks their sum, and writes
one result line. The compiler must keep the nominal types distinct.

The family has 1, 16, 64, or 256 members. The number of calls stays fixed.
Each input has an explicit-name and an overload-name form. Their callee names
have equal lengths, so each pair also has equal source byte counts. A second
pair uses shorter names. This separates source spelling cost from selection
cost. The one-member input also tests stage cost without an overload choice.

| Members | Padded source bytes | Short source bytes | Generated C bytes | Rename bytes |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 151,886 | 135,498 | 1,012,860 | 101 |
| 16 | 154,002 | 137,554 | 1,038,282 | 662 |
| 64 | 160,820 | 144,180 | 1,086,891 | 2,501 |
| 256 | 188,400 | 170,992 | 1,242,116 | 10,148 |

These byte counts use the explicit-name compiler. Its padded and short forms
produce byte-identical C and rename files. The measured overload candidate
must report its own output and symbol lengths. A longer native symbol must
not be treated as free work.

The separate functional witness is a typed number formatter with a provider,
a source ABI interface, and a caller. It must compile in one invocation and
as separate objects, link by the generated native names, and produce the
same text. The tests also check exact native extern names. Source order and
an unrelated declaration must not change a source function's native name.

## Explicit-name measurement

The initial run used `build/rmd-c` at revision
`9deca327c06b7fb9c989a13051193d08d71144fe`. Its SHA-256 was
`45b1e682b797a779dce1686e41e83f7d52ea33e56cc1ffad2bc220c608c9a136`.
The measurement script SHA-256 was
`24b7dc675d9c9f32998eba7c18c6c5afabd6a9d0c2a6155d6d2996fe6136c1ff`.

There were 21 paired rounds on CPU 6. Each round used a randomized endpoint
order. Each command started a fresh process with one worker. The operating
system file cache was warm. The run checked source and binary hashes before
and after measurement. Target GCC compilation, linking, and execution were
outside the timed samples.

`--check` includes parsing and ordinary semantic checks. `--prepare` also
constructs complete C text and the symbol rename response in memory. It does
not compile that C text or write output files.

| Members | Padded check, ms | Padded prepare, ms | Short check, ms | Short prepare, ms |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.689 | 5.963 | 3.717 | 6.010 |
| 16 | 3.786 | 6.218 | 3.806 | 6.222 |
| 64 | 4.011 | 6.892 | 3.996 | 6.874 |
| 256 | 4.804 | 8.164 | 4.802 | 8.154 |

These are wall-time medians. The raw report also has every sample, command,
CPU time, peak resident memory, source hash, and output hash. It is written
to `.profile-cache/overload-baseline/results.json`. The one-member and
256-member explicit-name programs also passed optimized runtime checks.

Run the baseline from the repository root:

```sh
python3 benchmarks/overload/measure.py
```

Measure the stage against the same compiler and generated inputs:

```sh
python3 benchmarks/overload/measure.py \
  --stage-compiler build/rmd-overload \
  --measure-stage-preparation \
  --output benchmarks/overload/performance.json
```

The candidate run includes the explicit-name controls through the overload
stage. It also measures each overload-name form. Keep native stage preparation
in a separate bucket. If a project must compile the stage before use, add
that complete preparation cost to the project's cold compilation cost.
The enabled stage also uses the RMD reader. Its total difference from the
baseline includes that reader change. Compare unique and shared names through
the same enabled stage to separate the cost of an overload choice.

## Decision rules

- Exact type tuples select one declaration. The result type does not select
  an ordinary call. A function type used as a parameter includes its result.
- Hash lookup must compare the complete key. A hash collision must not select
  another function. A native name must encode the complete source ABI key.
- Publish all signatures once. Index each family's parameter tuples once.
  Do not scan every member for every call or replay the ordinary checker.
- Compare enabled-stage cost with both the explicit-name compiler and the
  same explicit-name program through the stage. Report intervals, bytes, and
  memory. Do not choose an acceptable overhead percentage after the run.
- Stop expansion if the functional witness fails, if generated code adds
  dispatch, or if work grows with calls times family size. Identify that cost
  before another implementation layer is added.
- The disabled stage must leave the ordinary compiler path unchanged.

This baseline does not measure the overload stage. It also does not establish
C-level compilation speed. These inputs take only a few milliseconds, and
there is no matched C baseline here. The project-wide C-speed rule still
requires the candidate/C median ratio and the upper 95% confidence bound to
be at most 1.00 at each comparable boundary. See
[the timing contract](../../docs/exploration/language-exploration.md#103-define-the-timing-boundary).

Nominal record names form part of the proposed source ABI key. Separate
objects must use the same record definitions and ABI domain, preferably from
one shared interface. Mangling does not detect different layouts for the same
record name in separately compiled objects. This contract is explicit; the
experiment does not add a module identity or a layout compatibility system.
