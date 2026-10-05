<!-- SPDX-License-Identifier: Apache-2.0 -->

# Generics frontend comparison

Compare a candidate stage change with a captured implementation. The primary
workload is the plain/resource intrusive-container tutorial. The standalone pair
tutorial is a control. Both drivers use compiled stages and a compiled backend.

## Capture each implementation

Build the tools, then capture the baseline before editing stage sources:

```sh
make all c-stage
python3 benchmarks/generics/prepare.py --work build/generics-before
```

After the candidate change, capture it in a different directory:

```sh
python3 benchmarks/generics/prepare.py --work build/generics-after
```

Each capture records preparation commands and time, source and library hashes,
source snapshots, input files, and native measurement drivers. Keep the capture
unchanged. Use the same core libraries, compiler, flags, and target profile for
both sides. Check the recorded hashes when a preparation input differs.

## Inspect the profile

With Valgrind and `callgrind_annotate` installed:

```sh
python3 benchmarks/generics/profile.py \
    --prepared build/generics-before/ownership --work build/generics-profile
```

This rebuilds the captured stage sources with exported function names. Callgrind
collects instructions during the generic compilation. Read `self.txt` for local
cost and `inclusive.txt` for callees. Inclusive costs overlap; do not add them.
Exports and instrumentation can affect generated code. Use this run to locate
work, then use the ordinary drivers to measure elapsed time.

The phase clocks separate reading, abstract proof, specialization, seed checking
and cleanup lowering, argument checks, ownership verification, and C emission.
The call profile separates ordinary-declaration cloning, instance cloning, and
type normalization within these phases.

## Compare the candidate

Select an allowed CPU and run without concurrent builds:

```sh
python3 benchmarks/generics/compare.py \
    --before build/generics-before/ownership \
    --after build/generics-after/ownership \
    --pair-before build/generics-before/pair \
    --pair-after build/generics-after/pair \
    --cpu 4 --samples 30 --work build/generics-comparison
```

Each ownership sample starts a fresh process. Each standalone sample uses 500
fresh pairs of compiler contexts. Before/after order is randomized. Both drivers
read the same captured baseline inputs. The report retains all samples and
bootstrap confidence intervals for paired ratios.

`frontend_ns` ends after ownership checking. `emit_ns` measures complete C-buffer
emission. `process_wall_ns` includes startup, input reads, declaration binding,
C and symbol output files, reporting, and teardown. Use this last measure for
the complete driver handoff. Final target GCC compilation and linking run only
as untimed correctness checks. Preparation has its own report. This comparison
selects no artifact-cache lookup.

Before timing, both implementations must match the handwritten layouts and
function operations, preserve proof erasure, and run at O0 and O2. The candidate
must also emit byte-identical C and symbols to the baseline. Reports include
arena storage, specialization reuse, and abstract proof counts.

Accept a frontend optimization only when the median and upper 95% confidence
bound of its candidate/baseline ratio are below one on the ownership workload.
Investigate any demonstrated control or runtime regression. A smaller phase
cost alone is insufficient. Preserve the syntax-ownership boundary: parsed
source and checked output have separate mutable nodes, and retained generic
definitions remain valid for later instantiation and imports.

Keep reports, profiles, candidate patches, binaries, and archives under ignored
`build/` storage. Commit measurement tools and instructions only.
