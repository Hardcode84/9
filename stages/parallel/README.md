<!-- SPDX-License-Identifier: Apache-2.0 -->

# Independent native jobs

`parallel_run` executes a caller-supplied array of native functions. The caller
selects the jobs, worker count, and dependencies. This library adds no scheduler
or thread state to the C99 core.

```sh
make parallel-stage check-parallel
```

Load `model.crs`, `api.crs`, and the compiled library through ordinary root
calls. Include `model.crs` and `linux_x64.crs` when building the library from
source. The Linux implementation uses pthreads. Other profiles need a separate
implementation of the same interface.

Each job has an `execute` function and a `user` pointer. The function must be
native and non-null. Each job owns its mutable state. Jobs may borrow shared
immutable input. Retain that input, all job storage, and callback code until
`parallel_run` returns. Do not call one seed evaluator from several workers.
These are raw-library preconditions, not language ownership checks.

The call blocks until every started worker has finished. One worker executes
on the calling thread and allocates no worker storage. More workers use a
fixed assignment of job indices. An empty job array does no work. A zero worker
count is an error. Allocation or thread creation failure retains a diagnostic.
A failed thread start can leave some jobs complete; the call joins all started
threads before it reports failure. It does not retry or replay work.

Keep each worker's diagnostics in its own context. After completion, report
them in the caller's source order. Publish provider declarations before
starting consumers. Destroy consumers before the providers they borrow.

The [module graph benchmark](../../benchmarks/parallel/README.md) uses this
contract to compile consumers of a shared list interface. It checks final
executables and stable output and diagnostics at different worker counts.
