<!-- SPDX-License-Identifier: Apache-2.0 -->

# Pointer-field syntax

Measure the source cost of explicit pointer dereference in compiler stages.
The rewriter replaces `(*pointer).field` with `pointer->field`. It keeps
parentheses when the pointer operand requires them, such as `(*pointer)` in
`(*pointer)->field`.

Run from the repository root with prepared native backends and a new directory:

```sh
make all c-stage
python3 benchmarks/pointer-fields/measure.py --output build/pointer-fields/run-1
```

The C tool uses the actual seed lexer and root-action reader. It finds eligible
expressions in the parsed tree and preserves comments and strings. It measures
every `.crs` file under `stages/`, including compilation roots. A second parse
and token count check each rewritten file. C backend and reader-library builds
must produce identical assembly before and after rewriting.

`report.json` contains per-file and total token counts, rewrite counts, source
and tool-source hashes, the build command, and assembly hashes. Rewritten source
and captured tools stay in the selected ignored directory. The tool does not
replace production stage source.

To compare a seed implementation change, first save its baseline executable and
revision in ignored storage. Build the candidate with the same flags, then run:

```sh
python3 benchmarks/bootstrap/compare.py \
    --before build/pointer-fields/baseline/crust0 --before-revision BASELINE_REVISION \
    --after build/crust0 --cpu 4 --rounds 25 \
    --output build/pointer-fields/compare.json
python3 benchmarks/source-order/gate.py --build build --cpu 4 --rounds 20 \
    --output build/pointer-fields/gate.json
```

Select an allowed CPU and unused report paths. The comparison measures plain
source through complete assembly and verifies identical output. The second
command runs the compiled-backend application gate against C frontends.
Both exclude target assembly, GCC compilation, and linking. Keep raw samples
and confidence intervals with the captured binaries and inputs.
