<!-- SPDX-License-Identifier: Apache-2.0 -->

# Highlighting measurements

[measure.py](measure.py) measures scan and classification, HTML and JSON
rendering, complete native requests, and editor adapter requests. It generates
empty and large inputs and also reads the hello example and C emitter source.
Each report records the input hashes, implementation hashes, commands, helper
preparation cost, raw samples, medians, and percentiles.

Run from the repository root with a new report path:

```sh
make all c-stage
python3 benchmarks/highlight/measure.py --output build/benchmarks/highlight.json
```

Complete native requests include startup, input, classification, output to the
null device, and cleanup. The editor measurement uses a persistent Bun process
and a fresh native process per request. It includes snapshot I/O, JSON parsing,
validation, and UTF-16 conversion. It does not measure the VS Code graphical
interface.

The phase profiler uses `clock()` on the Linux x86-64 host profile. It measures
scan and classification, then HTML and JSON over the same classified spans.
These phase times exclude process startup and file I/O. Complete-request times
include those costs. The script does not pin a CPU or clear filesystem caches.

Helper GCC compilation and linking are recorded separately and excluded from
request timings. No target compilation occurs during a highlighting request.
These measurements do not compare Crust compilation speed with C compilation.
Keep generated inputs and reports in ignored storage, separate from the source
workloads. The large input is reproducible from the generator; no input archive
is needed in the repository.
