# Highlighting baseline

The [recorded baseline](baseline.json) measures the first highlighting
implementation. It records source and binary hashes, build commands, helper
preparation time, raw samples, medians, and 95th percentiles. The source
hashes identify the implementation; the base revision precedes this change.

The run used 21 samples per input and endpoint on Linux x86-64. Files were
warm in the filesystem cache. Processes had no CPU affinity or exclusive CPU.
The tool sandbox traced system calls. These are local measurements, not a
guarantee for other hosts or for the VS Code graphical interface.

| Input | Bytes | Scan CPU median | Complete HTML median | Complete token JSON median | Adapter request median |
| --- | ---: | ---: | ---: | ---: | ---: |
| Empty | 0 | 1 us | 0.534 ms | 0.497 ms | 1.007 ms |
| Hello example | 544 | 11 us | 0.533 ms | 0.559 ms | 1.055 ms |
| C emitter source | 24143 | 300 us | 1.529 ms | 1.278 ms | 3.480 ms |
| Generated functions | 1002780 | 13854 us | 45.677 ms | 36.964 ms | 102.116 ms |

Complete native requests include process startup, input, classification,
rendering, output to the null device, and cleanup. The adapter measurement
uses a persistent Bun process. It includes a fresh native process, temporary
snapshot I/O, JSON parsing, validation, and UTF-16 conversion. Its generated
input 95th percentile was 114.964 ms.

The CPU profiler measures scan and classification together, followed by HTML
rendering and JSON rendering in one process. Those phases use `clock()` on
the stated Linux x86-64 C library profile. They exclude process startup and
file I/O. HTML and JSON share the already classified spans in that profiler.

GCC compilation and linking occur only during helper preparation. The report
records that cost separately. No target compilation occurs during a request.
These measurements do not compare Crust frontend speed with C frontend speed.

The [input archive](inputs.tar.gz) preserves the measured source bytes.
The generator in [measure.py](measure.py) also reproduces the large input.
Use a new report path when repeating the measurement:

```sh
make all c-stage
python3 benchmarks/highlight/measure.py --output build/highlight-repeat.json
```

Do not overwrite the recorded baseline or its input archive when the
implementation changes.
