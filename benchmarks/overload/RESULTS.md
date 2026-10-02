# Overload stage results

The bounded overload witness passes. All 16 generated C files are
byte-identical to the explicit-name control. Selection adds compilation work
and longer native symbols. It adds no target dispatch on these inputs.

[performance.json](performance.json) contains the raw samples, commands,
source sizes, hashes, runtime checks, and stage preparation observation.
[BASELINE.md](BASELINE.md) defines the inputs and decision rules.

## Frontend cost

Each input has two source files and 4,096 calls. A family has 1, 16, 64, or
256 functions that accept distinct nominal pointer types. Explicit names
and shared names have equal source byte counts. The shorter-name controls
also remain in the report.

The run used 21 paired rounds on CPU 6 of an AMD Ryzen Threadripper PRO
7995WX. Commands ran in a randomized order within each round. Each command
started a fresh process. The operating system file cache was warm. Other
validation work used different CPUs; shared caches and system activity were
not isolated. Source and binary hashes were unchanged through the run.

`check` stops after semantic checks. `prepare` also constructs the complete C
text and symbol rename response in memory. Target GCC compilation, output
file writes, linking, and execution are outside these frontend samples.
The installed native stage is already available at this boundary.

The enabled stage uses the RMD reader before overload selection and the seed
checker. Its difference from the seed control includes this reader change.
Compare unique and shared names through the enabled stage to isolate the
effect of an overload choice more closely.

All entries below are median wall times in milliseconds.

| Members | Seed check | Stage, unique check | Stage, shared check | Seed prepare | Stage, unique prepare | Stage, shared prepare |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.725 | 5.145 | 5.133 | 6.026 | 7.480 | 7.440 |
| 16 | 3.804 | 5.309 | 6.091 | 6.272 | 7.707 | 8.482 |
| 64 | 4.031 | 5.718 | 6.503 | 6.918 | 8.628 | 9.408 |
| 256 | 4.817 | 7.287 | 7.953 | 8.194 | 10.760 | 11.418 |

Within the enabled stage, the extra check time is 0.781, 0.785, and 0.665 ms
for 16, 64, and 256 members. This fixed-call witness does not show a cost
that grows with calls times family size. The implementation indexes complete
parameter keys and checks the complete key when it interns a name. It does
not try the next checker once per candidate.

The table below gives shared-name/unique-name ratios within the enabled
stage. Intervals use 10,000 resamples of complete paired rounds.

| Members | Check ratio, 95% interval | Prepare ratio, 95% interval |
| ---: | ---: | ---: |
| 1 | 0.998 [0.994, 1.005] | 0.995 [0.989, 1.002] |
| 16 | 1.147 [1.138, 1.152] | 1.101 [1.098, 1.106] |
| 64 | 1.137 [1.129, 1.142] | 1.090 [1.079, 1.100] |
| 256 | 1.091 [1.086, 1.100] | 1.061 [1.056, 1.067] |

Total optional-stage cost is larger. At 256 members, shared-name checking is
1.651 times the seed control, with interval [1.632, 1.673]. Preparation is
1.393 times the seed control, with interval [1.381, 1.402]. The disabled path
uses the same `build/rmd-c` binary as the initial baseline; its SHA-256 is
`45b1e682b797a779dce1686e41e83f7d52ea33e56cc1ffad2bc220c608c9a136`.

The report includes child CPU time and raw `wait4` peak resident memory.
The small frontend processes all reported 21,704 KiB. This memory value
includes the controller memory inherited before `exec`. A `/bin/true` probe
reported 10,956 KiB, then 75,468 KiB after its Python parent allocated 64 MiB.
These values do not measure compiler-only allocations or establish equal
memory use between the two compilers.

## Generated output and native boundary

The padded-name inputs produced the following output sizes:

| Members | C bytes, both compilers | Seed rename bytes | Stage rename bytes |
| ---: | ---: | ---: | ---: |
| 1 | 1,012,860 | 101 | 186 |
| 16 | 1,038,282 | 662 | 1,440 |
| 64 | 1,086,891 | 2,501 | 5,472 |
| 256 | 1,242,116 | 10,148 | 21,759 |

The exact C hashes match for both name lengths and both stage source forms
at every family size. The native symbol encoding increases rename bytes.
That increase is included in `prepare`.

Six optimized executables passed the generated checksum test: seed,
enabled-stage unique names, and enabled-stage shared names, for 1 and 256
members. Their required output was:

```text
overload 1: 4096 calls, checksum 4096
overload 256: 4096 calls, checksum 1048576
```

The separate [functional suite](../../tests/overload.py) passed 18 runtime,
25 rejection, and 8 native-boundary cases, with 155 process checks. It covers
a separately compiled formatter, stable native symbols, exact native extern
names, function values, source prototypes, entry selection, field lookup,
scope rules, and excessive nesting. Three copied example packages select
their backend from source and load a library renamed to
`selected backend.plugin`. Their targets produce the required output and
contain no host compilation entry points. The source-order launcher cost
is not part of this frontend measurement.

## Native stage preparation

One separate observation built the overload, reader, and C backend library
from 192,848 bytes of RMD source with the installed RMD C compiler. It used
GCC 13.3 with `-O2 -g -fPIC -fno-semantic-interposition`, then a shared link
with `-Bsymbolic`, `-z text`, `-z relro`, and `-z now`.

| Operation | Wall time, ms |
| --- | ---: |
| RMD translation, target GCC, assembly, and symbol renaming | 1,683.207 |
| Shared library link | 17.889 |
| Total | 1,701.096 |

This is one observation, with no confidence interval. It is separate from
the frontend table. A project that must construct or change this stage must
add its complete native preparation cost to the cold compilation path.

## Scope and replay

This run establishes the bounded selection and code-generation result. It
does not establish C-level frontend speed. No matched C compiler workload
was measured here, and these small processes have a material startup cost.
The project rule still requires a candidate/C median ratio and upper 95%
confidence bound at most 1.00 at every comparable boundary. The missing
comparison requires equivalent C declarations and bodies, the same work
boundary, and the full stage preparation cost when a project needs it.

Run from the repository root:

```sh
make all overload-stage
python3 tests/overload.py --build build
python3 benchmarks/overload/measure.py \
  --stage-compiler build/rmd-overload \
  --measure-stage-preparation \
  --output benchmarks/overload/performance.json
```

The final measured overload compiler SHA-256 is
`999cc56affe5744b8653e05e3313208aa898de1d81faa33c03a945056a2a63c5`.
The report lists the exact compiled RMD inputs, C core inputs, archive hashes,
tool hashes, generated output hashes, and all commands. The initial and
provisional timing reports remain separate; their medians are not mixed
with this final paired run.

## Long type keys, 2026-10-02

[type-keys-2026-10-02.json](type-keys-2026-10-02.json) records 20 shuffled paired
samples on CPU 0, after two warmups. Each sample starts a fresh process and
runs `--check`. The baseline is commit `51bdc97`. Both compilers use the default
`make all overload-stage` build with `CFLAGS='-O2 -g'`. The report retains the
binary, generator, and input hashes and each command.
The native toolchain is GCC 13.3.0, Ubuntu package `13.3.0-6ubuntu2~24.04.1`.

The changed lookup uses interned type identities within a compiler context.
Native symbol names retain the same structural encoding. It removes the copy
and hash of a long type name for each call.

| Type name bytes | Calls | Before, ms | After, ms | Plain Crust check, ms |
| ---: | ---: | ---: | ---: | ---: |
| 8 | 20,000 | 15.598 | 15.148 | 8.972 |
| 8,192 | 20,000 | 278.376 | 16.317 | 9.533 |
| 2,000 | 2,000 | 9.434 | 3.109 | 2.376 |
| 8,000 | 8,000 | 106.827 | 7.155 | 4.688 |
| 32,000 | 32,000 | 1,640.543 | 24.790 | 14.454 |

The plain variant gives the scalar function a separate name and uses
`crust-c --check`. It measures the cost without overload selection; it is not
a GCC or Clang baseline. These results do not establish the complete C-speed
gate. All five measured programs also compile and run with the changed driver.
Each verifies that its counter equals its call count. Target GCC compilation
and execution are excluded from the timing samples.

To repeat with a separately built baseline:

```sh
git worktree add --detach build/type-key-before 51bdc97
make -C build/type-key-before all overload-stage
make all overload-stage
python3 benchmarks/overload/type_keys.py \
  --before build/type-key-before/build/crust-overload \
  --output build/type-key-repeat.json
```
