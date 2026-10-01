# Resource-stage measurements

The SQLite application passes the required output and error checks. The cleanup
stress test has linear emitted-code growth at the three measured sizes. These
results do not establish the complete language speed requirement.

Run from the repository root after preparing the pinned SQLite source:

```sh
make all resource-stage
python3 benchmarks/resources/verify.py --output .profile-cache/resources-baseline/replay.json
python3 examples/resources/sqlite/verify.py --sanitizers
python3 benchmarks/resources/measure.py
```

The [application report](../../examples/resources/sqlite/validation.json) records
21 process checks, six ownership rejections, and three decimal-format boundary
checks. The two normal entry paths and the sanitized target have the same output
as the frozen C application. The formatter initializes only the emitted decimal
suffix. Its optimized code has no mandatory buffer-zeroing stores.

[performance.json](performance.json) records 21 paired samples per endpoint on
CPU 6 of an AMD Ryzen Threadripper PRO 7995WX. The run uses one worker, fresh
processes, warm filesystem data, and no compiler cache. Endpoint order is shuffled
with a fixed seed. The report includes raw wall time, CPU time, peak resident
memory, input and tool hashes, commands, and 95% bootstrap intervals. Other work
can still affect shared caches and system load.

Median wall time, in milliseconds:

| Input | GCC syntax | Clang syntax | Resource check | Complete C buffers | Source-order root and C buffers |
|---|---:|---:|---:|---:|---:|
| SQLite direct C / resource source | 9.747 | 22.554 | 1.237 | 1.525 | 2.201 |
| 16 owners and 16 early exits | 4.987 | 17.279 | 0.696 | 0.784 | 1.406 |
| 64 owners and 64 early exits | 5.222 | 17.626 | 1.069 | 1.337 | 1.974 |
| 256 owners and 256 early exits | 6.247 | 19.041 | 2.853 | 3.573 | 4.223 |

The callback C SQLite version takes 9.897 ms with GCC and 22.909 ms with Clang.
GCC is the fastest eligible C compiler in each measured case.

Resource check includes source checks, ownership checks, cleanup plans, scalar
ABI lowering, and seed checks of the lowered program. Complete C buffers add all
C text and native-symbol rename construction. The source-order endpoint also
includes the runner prelude, root program, API input, ordinary shared-library
loading and calls, and destruction of compilation state. Target GCC optimization,
object emission, linking, and application execution are outside these samples.

The SQLite inputs differ. RMD reads 9,557 source bytes and declares only the C
functions that it uses. GCC reads 904,181 bytes including the direct C source and
all headers; Clang reads 931,718 bytes. Their preprocessed sizes are 58,442 and
60,824 bytes. The callback source adds more code. This header difference prevents
a general speed claim from the SQLite ratio.

The generated C stress baseline uses explicit shared cleanup labels. It has the
same number of owner creations and early exits as the resource source. Both
executables test every early exit and normal completion. Across all three sizes,
they check 678 paths and 70,896 destructor calls. All checks pass at `-O2`.

| Owners | Generated C bytes | Static drop call sites | Drop calls in each executable's runtime test |
|---:|---:|---:|---:|
| 16 | 23,259 | 32 | 152 |
| 64 | 71,988 | 128 | 2,144 |
| 256 | 274,233 | 512 | 33,152 |

The strict hypothesis of one static drop call site per owner failed. Early
returns share a cleanup chain that ends at the function epilogue. Normal block
completion uses a second chain that ends at a scope continuation. The generated
code therefore has two call sites per owner. Each runtime path executes the
required one. Four times as many owners produces 3.10 and 3.81 times as many C
bytes. This measured growth passes the separate bound of at most five times as
many bytes.

The check-time ratio rule passes for the three small generated inputs: both the
median ratio and the upper 95% confidence bound are below 1.00 against GCC. The
largest check ratio is 0.457, with an upper bound of 0.465. Process startup is a
large part of these samples. This result applies to these inputs. A matching C
frontend handoff measurement is absent, so the complete handoff gate remains
unestablished. The full profile in the language exploration also requires other
production inputs and runtime checks.

Native preparation of the resource, reader, and C-stage shared library takes
2,359.816 ms in one separate observation. It compiles 263,631 source bytes with
an installed RMD C compiler, includes GCC optimization and object emission, and
links the shared library. The final source-order samples load that prepared
library. A project that must construct this stage adds this preparation cost to
its cold critical path. The observation is not a median or confidence interval.
