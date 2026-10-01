# Record field lookup experiment

The overload pass must find a field's source type before the seed checker runs.
The first implementation scanned the record's field list for each lookup. A
constructor with N fields, followed by one read of each field, caused
N × (N + 1) field-name comparisons in that pass. This count excludes the reader,
seed checker, and other overload operations.

The change adds one field-name table per record. Collection fills the table and
rejects duplicate field names. Type synthesis uses the table for constructors
and field access. The [three-file patch](field-index.patch) records this change.
It adds no source feature or runtime operation.

## Method

[fields.py](fields.py) generates one record with 64, 256, 1,024, or 4,096 fields.
The program initializes every field, reads each field through an overloaded
call, and checks the sum. Separate statements keep expression depth constant.

Each endpoint is a fresh compiler process with `--check`. It includes the RMD
reader, overload selection and mangling, and the seed semantic checks. It does
not emit C. Native compiler preparation and all target GCC work are excluded.
The run used CPU 6, two warmups per endpoint, and 25 paired rounds. Each pair
had randomized endpoint order. The operating system file cache was warm.

The interval uses 10,000 bootstrap resamples of complete pairs. All input and
binary hashes stayed fixed during the run. CPU affinity does not control shared
caches or other machine activity. [fields.json](fields.json) retains all commands,
samples, CPU time, peak resident memory, hashes, and the measurement scope.

## Results

| Fields | Source bytes | Scan median, ms | Index median, ms | Index / scan | 95% interval |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 5,685 | 0.569 | 0.595 | 1.046 | 0.989–1.081 |
| 256 | 22,163 | 1.052 | 0.948 | 0.901 | 0.874–0.948 |
| 1,024 | 88,237 | 4.506 | 2.466 | 0.547 | 0.544–0.551 |
| 4,096 | 355,502 | 43.071 | 8.688 | 0.202 | 0.199–0.204 |

The large inputs show a material reduction. At 4,096 fields, the pass no longer
performs the 16,781,312 list comparisons required by the scan. The 64-field
interval includes a small increase or decrease; this run does not establish
a benefit at that size.

This experiment measures the field lookup change. It has no C compiler
baseline and does not establish general C-level compilation speed. It also does
not measure resource checking or emitted-output cost.

## Provenance and repetition

The saved scan executable has SHA-256
`18759e1f2223a1e99238cd8444385fd60fe873e679bcd7e471c778be02487fc1`.
No source manifest was captured at that executable's build. The report therefore
does not claim a verified baseline source hash. It retains the saved binary
hash, the exact field-index delta, and the candidate's source manifest.

After measurement, one blank context line was removed from the patch and its
first hunk counts were adjusted. The edited source lines did not change.
`fields.json` retains the measured artifact hash in `frozen_sha256` and records
the current patch hash and this adjustment in `field_change.patch_artifact`.

The measured index executable has SHA-256
`07eb9dd94349b5f23ca04e2596feeaf2c2df717b7944770229ddc3cea8069caf`.
This identifies the executable used for these pairs, not a later rebuild.
The candidate hashes for the three changed files are in `fields.json`.

Run from the repository root with the retained scan executable and an installed
index executable:

```sh
python3 benchmarks/overload/fields.py \
  --baseline .profile-cache/overload-validation/rmd-overload-field-scan \
  --candidate build/rmd-overload --cpu 6 --rounds 25 \
  --output .profile-cache/overload-fields/results.json
```

For a new baseline build, reverse `field-index.patch` in a separate checkout and
build the overload compiler there. Build the candidate from the matching source
with the patch applied. Pass both binary paths to the script. The script does
not rebuild or modify compiler sources.

The resource composition tests also execute a 512-field constructor with
overload-selected field reads. Separate cases reject duplicate fields in an
ordinary record and a resource record. These three cases passed six process
checks. They check output and diagnostics; they are not timing samples.
