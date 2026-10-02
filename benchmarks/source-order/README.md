<!-- SPDX-License-Identifier: Apache-2.0 -->

# Source-order measurements

The root endpoint includes process startup, source capture, interface checks,
root execution, stage loading, target frontend work, complete C and native-symbol
output, and cleanup. Target GCC compilation and linking are excluded. An installed
backend and a source-built backend are different configurations.

Run from the repository root after `make all c-stage`. Select an allowed CPU
and a new output path for each command:

```sh
python3 benchmarks/source-order/measure.py --build-dir build --cpu 0 \
  --prepare-library --output build/benchmarks/source-order.json
python3 benchmarks/source-order/gate.py --build build --cpu 0 \
  --output build/benchmarks/source-gate.json
python3 benchmarks/native/measure.py --cpu 0 \
  --output build/benchmarks/native.json
```

`measure.py` compares an installed stage with the prepared backend and original
C input. `gate.py` uses a compiled backend and a fresh root process for each
sample. It compares checks with GCC and Clang syntax checks. It compares
complete C emission with Clang frontend IR emission with LLVM passes disabled.
Both handoff measurements include text serialization. `native/measure.py`
measures bootstrap and continuation compilation before native target work.
Each script checks output equivalence
before using the timing result. Target executables run outside the timed interval.

The application gate covers the direct list, increasing function counts,
array operations, one large function with many branches, and repeated record
types and calls. It checks every requested body on both sides and records
complete emitted files. It does not establish a checked list lifetime policy.

Keep source and binary hashes fixed during each set of paired rounds. An
installed stage is an explicit prepared input. A stage that must be built in
the request contributes its full preparation cost to the cold total. Cache
measurements must state whether the artifact exists at request start.

## Controlled changes

Freeze the baseline before an optimization. Use `gate.py` for the main
application gate. Use the
[cold-build comparison](../../docs/source-runner.md#compare-cold-native-builds)
to study backend bootstrap separately. Use
[the plain compiler comparison](../bootstrap/compare.py)
to compare prepared assembly emitters without root execution.

The earlier source-order study identified two concrete mechanisms. A shared
library built with `-fPIC` can retain calls that the standalone compiler inlines;
`-Bsymbolic` at link time does not itself enable compiler inlining. The build
uses `-fno-semantic-interposition` under its local-binding contract. Small text
appends can also spend time in external copy calls. A direct one-byte append
must keep capacity, overlap, allocation-failure, and output-byte guarantees.

A table created for every function can trade shorter probes for more allocations
and retained arena storage. Measure both effects. Do not assume that a smaller
individual table reduces whole-program cost. Keep rejected experiment results
with their exact local inputs rather than adding timing tables to documentation.

The [reader-transfer proof](proof.md) tests the ownership and output boundary.
The production tests are `make check-stage`, `make check-native`, and
`make check-cache`. Passing these tests establishes behavior, not compilation
speed or the complete specification performance gate.
