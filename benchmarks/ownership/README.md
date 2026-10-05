<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership compilation cost

Measure a compiled stage in fresh processes. The driver separately records
source reading, resource lowering, local ownership checking, and C emission.
Target GCC compilation and linking are excluded. No application artifact cache
is used. Backend construction and automatic cache validation are separate costs.

```sh
make build/ownership-cost
python3 benchmarks/ownership/measure.py --pairs 20 --work build/ownership-cost-run
```

Run without concurrent builds or checks. On Linux, prefix the Python command
with `taskset -c CPU` to pin both sides to the same permitted CPU. The report
records affinity. Use a new output directory for each capture. The script retains source hashes,
driver hash, commands, raw samples, and bootstrap intervals. It compares paired
runs of the same input with and without ownership verification. The unchecked
path exists only in this measurement driver and does not provide a safety claim.

The six workloads use the intrusive client, tree with parent links, one-way
index, native handles, stored views, and exclusive heap owners. The script
repeats independent function bodies at three sizes.
It randomizes each pair and reports the verification pass separately. The
selected gate is a median total frontend ratio at most `2.0` for each workload
and size. This budget is not a C-level speed claim.

The report records the build command, compiler version, flags, and hashes of
stage sources. Keep machine-specific results under ignored `build/` storage.
Do not overwrite earlier captures or commit timing numbers. The script also publishes a trusted provider and measures a source-free client.
It reports artifact capture and validation separately. Provider publication
includes native object compilation and is reported outside the frontend gate.

The report also measures each tutorial through a fresh compilation root. These
samples include interface input, explicit trust selection, library loading,
checking, and complete C and symbol files. The emitted programs must run at
`-O0` and `-O2`. The erasure check must produce identical C before and after
ownership verification. These root costs have no independent C-speed claim.

A separate stress case puts 32, 64, and 128 live loans and branches in one
function. It measures branch-join growth rather than independent-body scaling.
The checker visits all visible slots and objects at each join. When both paths
retain the incoming slot value, the join reuses that binding. When both paths
consume the value, the join must replace the incoming binding. This prevents
unchanged slot facts from extending the lookup chains at each branch. Object,
loan, and initialization checks still run. The report records this cost
separately and does not classify it as C-level.

All samples include child CPU time. A separate observation records peak RSS
for each route. At least 20 paired samples are required. The source-free client
also contributes to the acceptance result.

To compare a stage change, save the compiled `ownership-cost` driver, its
revision, and its build flags before the change. Build the candidate with the
same flags. Run the comparison on an idle machine:

```sh
python3 benchmarks/ownership/compare.py \
    --baseline build/ownership-baseline/ownership-cost \
    --baseline-revision BASELINE_REVISION \
    --work build/ownership-comparison
```

This compares candidate and baseline verification on identical inputs, at three
sizes. It reports the ownership-pass and total-frontend ratios separately.
Each ratio has paired samples and a bootstrap interval. The report records
source and driver hashes, flags, commands, and CPU affinity. Keep it under
ignored `build/` storage.
