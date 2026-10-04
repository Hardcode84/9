<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ownership compilation cost

Measure a compiled stage in fresh processes. The driver separately records
source reading, resource lowering, local ownership checking, and C emission.
Target GCC compilation and linking are excluded. No application artifact cache
is used. Backend construction and automatic cache validation are separate costs.

```sh
make build/ownership-cost
python3 benchmarks/ownership/measure.py --work build/ownership-cost-run
```

Run without concurrent builds or checks. On Linux, prefix the Python command
with `taskset -c CPU` to pin both sides to the same permitted CPU. The report
records affinity. Use a new output directory for each capture. The script retains source hashes,
driver hash, commands, raw samples, and bootstrap intervals. It compares paired
runs of the same input with and without ownership verification. The unchecked
path exists only in this measurement driver and does not provide a safety claim.

The four workloads use the intrusive client, owning tree, native handles, and
stored views. The script repeats independent function bodies at three sizes.
It randomizes each pair and reports the verification pass separately. The
selected gate is a median total frontend ratio at most `2.0` for each workload
and size. This budget is not a C-level speed claim.

The report records the build command, compiler version, flags, and hashes of
stage sources. Keep machine-specific results under ignored `build/` storage.
Do not overwrite earlier captures or commit timing numbers. The script also publishes a trusted provider and measures a source-free client.
It reports artifact capture and validation separately. Provider publication
includes native object compilation and is reported outside the frontend gate.
