<!-- SPDX-License-Identifier: Apache-2.0 -->

# Complete build time

Measure the time from compiler invocation through the finished executable.
Both paths use the same [intrusive-list program](../../examples/intrusive/raw.crs)
and prepared native backends. This program checks its list operations and prints
`intrusive: ok`.

Run from the repository root on Linux x86-64. Use an allowed CPU and a new
output directory under `build/`:

```sh
make all c-stage
python3 benchmarks/build-time/measure.py --cpu 4 --output build/build-time/run-1
```

The tool measures four endpoints:

| Endpoint | Included work |
| --- | --- |
| `c-emit` | Read and check source; emit C and native symbol mappings |
| `c-total` | Read and check source; emit C; GCC compilation; symbol renaming; linking; temporary-file cleanup |
| `asm-emit` | Read and check source; prepare and emit assembly |
| `asm-total` | Read and check source; prepare and emit assembly; assemble and link through the GCC driver |

Each total starts from source again. The C path uses the backend's
[default GCC flags](../../docs/c-backend.md#c-execution-rules), including `-O2`.
The assembly path has no optimizer. This compares two available build choices;
it does not compare equal optimization levels or target execution speed.

The tool uses the standalone `crust-c` and `crust0` drivers. Backend preparation,
source-root setup, artifact-cache validation, and target execution are outside
the timed intervals. The beginner examples call the same C backend through
`c_build` and also pay for their root setup.

Before timing, both executables must return zero and print the expected output.
Each sample runs fresh compiler and tool processes. Twenty paired rounds run
serially on one CPU with randomized endpoint order and a warm filesystem cache.
The report includes commands, source and tool hashes, environment, raw samples,
medians, and bootstrap confidence intervals. Inputs, outputs, and reports stay
in the selected ignored directory. Use a new directory for another run.

Compare the total endpoints to assess build wait time. The emission endpoints
show the work before the native toolchain. They are separate cumulative runs;
subtracting their medians does not measure an individual GCC phase. The
[frontend benchmark](../c-stage/measure.py) measures the frontend speed gate
with target compilation and linking excluded.
