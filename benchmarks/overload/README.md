<!-- SPDX-License-Identifier: Apache-2.0 -->

# Overload measurements

[measure.py](measure.py) compares explicit names, explicit names through the
overload stage, and overload selection. It generates nominal record families
with a fixed call count. Padded names keep input lengths equal; short-name
controls separate spelling cost from selection cost. Runtime checks require
the same result and direct calls without runtime dispatch.

Run from the repository root with a new report path:

```sh
make all overload-stage
python3 benchmarks/overload/measure.py \
  --stage-compiler build/crust-overload --measure-stage-preparation \
  --output build/benchmarks/overload/selection.json
```

`--check` includes reading, selection, mangling, and seed semantic checks.
`--prepare` also constructs complete C and native-symbol buffers. Target GCC
compilation, linking, and execution remain outside the timed samples. Native
stage preparation is reported separately and must be included when comparing
cold requests. The enabled stage uses the Crust reader, so compare its explicit
and shared names to isolate selection cost.

[fields.py](fields.py) generates large record constructors and field reads. A
list scan per lookup can make this work quadratic. A field-name table built
once per record removes the repeated scan. Supply an explicit baseline binary;
the tool does not assume that a saved local executable still exists.

```sh
python3 benchmarks/overload/fields.py \
  --baseline build/before/crust-overload --candidate build/crust-overload \
  --output build/benchmarks/overload/fields.json
```

[type_keys.py](type_keys.py) varies type-name length and call count. It compares
a baseline, the current overload stage, and explicit names through the plain C
stage. It also compiles and runs each input outside the timed check interval.

```sh
python3 benchmarks/overload/type_keys.py \
  --before build/before/crust-overload \
  --output build/benchmarks/overload/type-keys.json
```

Build baseline and candidate binaries from identified revisions with the same
flags. Reports retain commands, hashes, samples, and comparison intervals.
The field and type-key comparisons have no C compiler baseline and cannot
establish the complete language performance gate.

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

These comparisons do not establish C-level compilation speed. There is no
matched C baseline in this harness. The project-wide C-speed rule still
requires the candidate/C median ratio and the upper 95% confidence bound to
be at most 1.00 at each comparable boundary. See
[the timing contract](../../docs/exploration/language-exploration.md#103-define-the-timing-boundary).

Nominal record names form part of the proposed source ABI key. Separate
objects must use the same record definitions and ABI domain, preferably from
one shared interface. Mangling does not detect different layouts for the same
record name in separately compiled objects. This contract is explicit; the
experiment does not add a module identity or a layout compatibility system.
