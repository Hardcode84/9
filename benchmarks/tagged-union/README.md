<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tagged reader-token measurement

This bounded experiment compares the production reader's flat token with an
external tagged payload. It changes the actual reader and its test harness in
an isolated directory. It keeps the production reader unchanged.

Run from the repository root, with an allowed CPU number:

```sh
make all c-stage union-stage check-union check-reader ccn-stage
python3 benchmarks/tagged-union/measure.py \
    --cpu 4 --rounds 20 --output build/tagged-token-run
```

Use a new output directory for each run. The report records source hashes,
commands, source bytes and lines, token size, lowered CCN, paired timings, and a
bootstrap confidence interval. Generated sources, executables, and reports stay
under `build/`.

`port.py` replaces the token's independent name, integer, type, and string fields
with one tagged payload. It retains the lexical token kind. Small accessors keep
the flat reader's zero values for inactive fields, including the hook contract's
comparison of token snapshots. All writes construct variants. All payload reads
use exhaustive matches. This isolates the representation change; it does not
claim that the accessors are the smallest possible parser design.

The harness compares the complete parsed trees and diagnostics against the seed
reader on the reader test corpus. It also runs the reader's hook, allocation,
range, and evaluator tests. A separate compiled driver repeatedly reads and
checks `tests/runtime.crs`. Target GCC compilation and linking happen before the
timed runs. Each sample includes process startup and one hundred passes through
the reader, collection, resolution, and checking.

CCN uses the existing Crust counter on lowered function bodies. Thus, generated
match branches count as decisions. Source counts include the accessors. Use the
behavior results and all cost measures when deciding whether to replace the
production token layout. A smaller token alone is insufficient evidence.
