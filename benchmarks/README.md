<!-- SPDX-License-Identifier: Apache-2.0 -->

# Benchmarks

This directory contains workloads, measurement tools, and instructions.
Keep generated inputs, reports, profiles, dependency lockfiles, and binaries
under ignored `build/` storage. Dependency downloads use `.profile-cache/`.
Do not commit archives or machine-specific timing tables.

Use a new report path for each run. Record source and tool hashes, build flags,
commands, input bytes, and raw samples. Keep a captured run unchanged when the
implementation changes. Historical captures remain in Git history; a capture
removed during cleanup also has an unchanged local copy under
`build/benchmark-cleanup/`.

| Area | Entry point |
| --- | --- |
| C, C++, and Rust frontend profiles | [Method and commands](../docs/exploration/compiler-profiles.md) |
| Seed checking, assembly, and memory use | [Bootstrap guide](../docs/bootstrap.md#validation-and-measurements) |
| C emission | [C backend guide](../docs/c-backend.md#compilation-measurements) |
| Root execution and native handoff | [Source-order measurements](source-order/README.md) |
| Independent module jobs and dependency chains | [Parallel measurements](parallel/README.md) |
| Backend preparation and artifact reuse | [Cache measurements](backend-cache/README.md) |
| Ownership and cleanup | [Resource measurements](resources/README.md) |
| Overload selection and field lookup | [Overload measurements](overload/README.md) |
| Highlighting and editor transport | [Highlight measurements](highlight/README.md) |

Run correctness checks before timing. Compare the same work at each endpoint.
Separate checking, lowering, emission, stage preparation, and target toolchain
costs. Exclude target GCC compilation and linking from frontend measurements.
Use an identified compiled backend for the main application gate. Record
backend construction and automatic cache validation separately. Include
project stage preparation when that is part of the stated request.

Run timed processes serially on an allowed CPU. Preserve paired samples and
report confidence intervals. Collect instrumented profiles separately because
the profiler changes the work. The [specification](../docs/crust0-spec.md#14-conformance-and-performance-gates)
defines the performance gate; these tools do not establish a result without a
run on the selected inputs and builds.
