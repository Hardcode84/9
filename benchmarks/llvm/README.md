<!-- SPDX-License-Identifier: Apache-2.0 -->

# LLVM emission cost

Build the native test driver and select a local LLVM release:

```sh
make all build/resource-backends
make fetch-llvm-release
python3 benchmarks/llvm/measure.py
```

The tool compares the C and LLVM emitters on the same checked intrusive
client and SQLite resource wrapper. Each sample starts a fresh native
process. It includes source reading, checks, cleanup lowering, complete target
text construction, output writes, and process teardown. Both routes use the
same executable and source inputs. The C route stops at emitted C text.

The report measures LLVM parse/verification and Clang optimization/code
generation in separate commands. It excludes these commands, GCC compilation,
and linking from the frontend result. It does not measure compiler bootstrap,
automatic package-cache validation, or linking. Run package checks separately
with `make check-llvm`; these measurements start with compiled emitters.

`build/llvm-measure/result.json` retains all commands, samples, input/output
hashes, emitter hash, and LLVM tool hashes. The generated C and IR stay beside
it. Use `--llvm` for another explicit installation, `--build` for another
compiled driver, and `--runs` to change the sample count. Run on an idle host.
Machine timings remain in ignored storage.

For behavior comparisons, run `make check-resources check-llvm`. Timing
results alone do not establish equivalent program behavior or the full
language compilation-speed gate.
