<!-- SPDX-License-Identifier: Apache-2.0 -->

# Backend bootstrap and cache measurements

Run from the repository root. Use the same C compiler and flags for both
checkouts. Preserve the baseline before changing the implementation.

```sh
mkdir -p build/backend-before
git archive HEAD | tar -x -C build/backend-before
make -C build/backend-before all
make all c-stage
python3 benchmarks/backend-cache/measure.py --before build/backend-before --rounds 20 --output build/backend-cache.json
```

`--before` is optional. `--cpu` pins the process and its children to an allowed
CPU. The output path must be new. Keep reports under the ignored build directory.

Each case uses paired fresh processes in random order. A miss has an empty
artifact cache. A hit has a completed entry. OS file caches are warm. The report
retains raw samples, commands, inputs, hashes, flags, output checks, and the
paired hit/miss interval. Source and tool files must remain unchanged during
measurement.

The endpoint includes root capture, input hashing, backend preparation or
lookup, loading, native continuation compilation, target checks, complete C
and symbol output, and cleanup. Final target GCC compilation and linking run
outside the samples. The final intrusive-list program must execute correctly.
The prepared assembly comparison verifies identical output from the frozen
and current compilers. Do not combine prepared and source-bootstrap timings.

The intrusive case also records GCC syntax checking of its C reference. The
other cases measure cache and backend costs; they do not establish the full
language performance gate. A hit result cannot replace the cold result.
