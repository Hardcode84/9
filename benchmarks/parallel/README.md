<!-- SPDX-License-Identifier: Apache-2.0 -->

# Parallel module compilation

Run the compiled-backend single-worker gate first:

```sh
make all c-stage parallel-stage
python3 benchmarks/source-order/gate.py --cpu 0 --rounds 20 --output build/application-gate.json
python3 benchmarks/parallel/measure.py --cpu 0 --rounds 20 --output build/parallel-gate.json
```

Select an allowed range of eight CPUs and a new report path. The script uses
1, 2, 4, and 8 CPUs and the same worker limit for Crust and C. It records tool,
source, library, and input hashes, commands, paired samples, CPU time, a
separate RSS observation, and confidence intervals. Timed processes run
serially with respect to other measured configurations. Keep reports under
ignored build storage.

The [driver](driver.crs) is ordinary compiled Crust code. A root loads it and
selects its worker count and inputs. The driver uses the existing module and
C backend APIs. Each module has its own context. Consumer modules borrow the
checked provider's record and function declarations. The provider stays live
through emission and consumer destruction.

The provider implements the direct list operations from the seed witness.
Consumers attach and detach stack hooks. Their functions also do arithmetic
and branch work. The target program calls every consumer and checks the
result. All requested bodies are checked and emitted. The final Crust and C
executables must print the same text.

The wide graph has independent consumers of one provider. The deep graph
also requires consumer `i - 1` before consumer `i`. This graph must remain
serial. Dependencies are driver policy; the job library does not infer them.
Function names and source identities are assigned before worker startup.
Output bytes and diagnostics must remain stable across worker counts.
Body and layout edits must change the affected output. A signature edit must
reject calls that use its old parameter list. Restoring the original source
must restore the original output. Each request checks fresh input; this test
does not use saved application results.

Check time includes the fresh root, library loading, inputs, bindings,
semantic checks, and cleanup. Handoff adds complete C and symbol files.
Compare checking with the fastest GCC or Clang syntax check. Compare handoff
with Clang frontend IR emission with LLVM passes disabled. Both handoff
routes include text serialization. The C controller starts a fresh compiler
for each translation unit. Its scheduling time is included; Python process
startup is excluded. This gives the C control no Python startup penalty.

Backend and driver compilation happen before samples and are recorded
separately. Final target compilation and linking also happen outside timing.
Automatic cache validation is measured by the
[cache harness](../backend-cache/README.md). No application result is reused.
This benchmark establishes the stated raw module and native job contracts.
It does not establish a memory-safety policy for stored list observers.
