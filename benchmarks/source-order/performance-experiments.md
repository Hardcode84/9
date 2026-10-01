# Source-order performance experiments

Date: 2026-10-01. The final complete runner passed all three required speed
gates. The first result failed the 8,000-function gate. This file keeps that
failure and the bounded experiments that produced the final change.

The [first result](results-before-interposition.json) records all raw times and
hashes. The [profile and experiment record](profile-experiments.json) records
sample counts, commands, hashes, source changes, control results, and raw paired
times. `@REPO@` denotes the repository root in the recorded data. `@PYTHON@`
denotes the Python interpreter used to invoke the measurement script.

## Final complete-runner result

The [final result](results.json) records 225 timed samples across 25 paired
rounds. Compiler, library, source, and tool input hashes stayed fixed. The run
uses `-fno-semantic-interposition` for the prepared library and the one-byte
append change. Rejected changes are absent.

| Workload | Root through full C output, ms | Prepared C output, ms | Original C syntax, ms | Root/C 95% interval |
| --- | ---: | ---: | ---: | --- |
| Intrusive list | 2.460612 | 1.774322 | 7.016028 | [0.344523, 0.363075] |
| 1,000 functions | 14.018003 | 13.016581 | 18.640209 | [0.740432, 0.772590] |
| 8,000 functions | 109.335064 | 106.080140 | 111.386833 | [0.972778, 0.986766] |

Each upper bound is below 1.0. This result establishes the gate for these
inputs and this machine. It does not establish a speed bound for all programs.
The root endpoint has no prepared-root or execution-result cache. Generated
target GCC compilation and linking are outside the measured endpoints.

Untimed controls require identical C and rename bytes for root and prepared
routes. They also compile and execute the intrusive list and check that host
compiler symbols and library dependencies do not enter the target executable.
Normal validation passed 21,904 C unit checks, 398 x64 process checks, 348 C
backend process checks, and 141 source-order process checks. GCC ASan/UBSan
validation passed the 21,904 unit checks, 348 C backend checks, and 141 source
checks before this frozen run. The [sanitizer validation record](validation.json)
is separate from the performance samples.

A separate complete source-library preparation observation took 468.325237 ms:
455.788416 ms through the object and 12.536821 ms for shared linking. This is
one observation, not a median or interval. It includes all RMD library sources,
C generation, GCC compilation, and object symbol renaming. It uses the driver's
GCC `-O2` default without debug information, plus `-fPIC` and
`-fno-semantic-interposition`. The installed compiler and library use Make's
`-O2 -g` configuration. Thus the preparation observation is not the exact
installed debug-build recipe. It is excluded from the frontend samples; its
output does not replace the measured library.

From the repository root, with the normal build already prepared, rerun:

```sh
python3 benchmarks/source-order/measure.py --build-dir build --rounds 25 --warmup 1 --cpu 4 --prepare-library --output .profile-cache/source-order-final-after.json
```

Use an unused output path. Select an allowed CPU if CPU 4 is unavailable. Build
preparation occurs before the command; the script does not rebuild or replace
installed compiler artifacts. The raw local result remains unchanged. The
published copy substitutes the documented path tokens.

## First complete-runner result

| Workload | Root through full C output, ms | Prepared C output, ms | Original C syntax, ms | Root/C 95% interval |
| --- | ---: | ---: | ---: | --- |
| Intrusive list | 2.445 | 1.775 | 6.985 | [0.34215, 0.35466] |
| 1,000 functions | 14.867 | 13.253 | 18.572 | [0.78890, 0.81598] |
| 8,000 functions | 115.720 | 108.157 | 111.511 | [1.03238, 1.04419] |

Each endpoint starts a fresh process. The root endpoint includes the installed
prelude, root parsing and execution, source capture, library loading, foreign
calls, target checks, full C and rename output, and cleanup. It excludes final
target GCC compilation and linking. There are 25 paired rounds per workload,
with random endpoint order and one warmup. The interval is a paired-bootstrap
interval for the ratio of medians. The upper bound must be at most 1.0.

## Profile result and first change

The prepared executable and the loaded backend library came from the same RMD
sources. Their optimization differed. With ordinary `-fPIC`, GCC retained
calls between exported RMD functions. The link command already used
`-Bsymbolic`, but that link option did not restore compiler inlining. In
`c_buffer_text`, the library called `c_length`; the prepared executable inlined
the loop.

The selected library now uses `-fno-semantic-interposition`. Its internal
bindings remain local, as required by its existing `-Bsymbolic` link contract.
The controlled change reduced the 8,000-function root median from 115.454 ms
to 110.990 ms. The candidate/control interval was [0.95140, 0.96787]. Its
candidate/GCC interval was [0.99045, 1.00264], so this experiment did not pass
the required speed gate by itself.

The profile used `perf` 7.0.12, `cpu-clock:u`, 997 Hz, and 40 fresh endpoint
processes per recording. Original root and prepared recordings had 2,529 and
2,265 samples. Optimized recordings had 2,357 and 2,286 samples. All four
recordings had zero lost samples. Flat percentages describe recorded user CPU
samples, including the launcher. They are not wall-time phase percentages.

With the optimized library, root and prepared `--check` times did not show a
resolved difference: their paired median difference was 0.084 ms, with interval
[-0.116, 0.657] ms. The root `--prepare` endpoint added 1.678 ms, with interval
[1.042, 2.227] ms. Here `--prepare` includes complete C buffer construction;
it is not only semantic checking. Full C output added 1.092 ms, with interval
[0.166, 1.700] ms. These are endpoint differences from separate processes.

## Further bounded changes

The buffer and map experiments used the optimized library as their control.
The `-fno-plt` experiment retained the original library as its control, as the
table states. Each kept the same target and runner and collected 25 paired
rounds on CPU 4. Candidate output and symbol-renaming bytes had to match the
control before timing.

| Change | Candidate/control 95% interval | Candidate/GCC 95% interval | Decision |
| --- | --- | --- | --- |
| Add `-fno-plt` | [0.95419, 0.96766] | [0.99757, 1.00755] | Reject; the control here was the original library, so this does not establish an additional gain over `-fno-semantic-interposition` |
| Compute buffer end before the copy call | [0.99456, 1.00749] | [0.98962, 1.00170] | Reject; no measured gain |
| New local-symbol map for each function | [1.01444, 1.03080] | [1.01797, 1.02670] | Reject; slower |
| Copy a one-byte text append directly | [0.97431, 0.98278] | [0.97110, 0.97935] | Adopt; full validation and final gate passed |

The map experiment kept the symbol counter unchanged and matched all output
bytes. It passed a 32,768-local function before and after 8,000 tiny functions.
It also passed the complete runtime fixture and intrusive-list execution.
For the ordinary workload, its initial 64-entry table per function requested
8,192,000 bytes across 8,000 table allocations. The original growing map
requested 2,096,128 bytes across 11 table allocations. These byte counts follow
from the three checked symbols per function and the table growth rules; they
are not allocator timing measurements.

The one-byte change keeps all capacity and failure checks. After the existing
capacity check, a one-byte append uses a byte store. Other lengths retain the
copy call. The profile identified text append and external copy calls as major
costs. The candidate median was 108.626 ms, against 111.070 ms for its control
and 111.397 ms for GCC. Exact output controls cover the ordinary workload,
intrusive list, and full runtime fixture. A foundation control appends from its
own buffer through the capacity boundary, grows the buffer, checks retained
old storage, and compiles and runs the generated all-byte C string test.

## Plain seed control

The [plain seed comparison](plain-results.json) uses the saved pre-runner seed
and the new seed. Generated assembly bytes are identical. The 8,000-function
ratio interval was [0.98375, 1.00655]. The intrusive interval was
[0.92403, 1.02198]. The 1,000-function median ratio was 1.09665, with interval
[0.98515, 1.11652]. That smaller workload is inconclusive; these samples do not
prove that every plain workload has unchanged speed.
