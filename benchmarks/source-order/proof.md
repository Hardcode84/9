<!-- SPDX-License-Identifier: Apache-2.0 -->

# Reader-transfer implementation gate

Date: 2026-10-01. This bounded experiment passed the first source-order
implementation gate. It does not implement the full host evaluator.

The [proof sources](proof/) preserve the executable experiment. Reports record
commands, hashes, raw timings, diagnostics, and sanitizer configuration in the
ignored work directory. This probe does not implement the full host evaluator.

## Actual output and ownership

The root starts with ordinary calls to select a backend function and a reader
function. The initial reader stops at the second call's semicolon. The next
byte is NUL at offset 70. The initial grammar rejects that byte. The selected
reader, written in RMD, consumes it and reads `@include |path|` and `@emit`.

The new reader creates public call expressions. The runner checks each action
and uses libffi to call its imported implementation. Each action has a separate
temporary arena. The include operation retains the source in an owner arena
and reads the external intrusive-list program into a separate target context.
The emit operation queues an RMD function. This function runs after root EOF
and after the reader has returned.

The target context uses allocation and release callbacks written in RMD. The
runner destroys that context before it unloads either library. The witness
records two allocations and two releases. Error paths also require balanced
callbacks. Source buffers, target facts, and function pointers therefore cross
the reader-return boundary and reach an actual output consumer.

The C runner has no backend-name dispatch or C-backend option algorithm. It
resolves the exact external symbols declared by its interfaces. RMD code
constructs the output options and calls the selected backend function pointer.
The backend library has an arbitrary filename.

The generated C and symbol-renaming response match the prepared C backend
byte for byte. GCC, object symbol renaming, and native linking produce an
executable that prints `intrusive: ok`. It has no host compiler, libffi, or
reader-library dependency.

## Correctness checks

The verifier runs native checks and repeats them with GCC AddressSanitizer
and UndefinedBehaviorSanitizer. Checks cover reader selection, alternate syntax,
queued-work failure, callback signatures, unresolved names, invalid arguments,
host/target name separation, forward references, and the final executable.

The runner, core, reader library, and backend library are instrumented.
Stack-use-after-return detection is enabled. The verifier disables leak scanning
and checks target allocation/release balance explicitly. This is not a claim
of leak-detector coverage.

Clang's additional function-type check rejects calls from generated C with
erased data-pointer types to C functions declared with record-pointer types.
The RMD native contract maps those data pointers to one ABI category. The
record preserves that diagnostic. The passing sanitizer result uses GCC; it
does not claim Clang C function-type identity across this foreign boundary.

## Speed gate

Timing uses paired rounds of fresh processes with randomized endpoint order
and a warmup. Inputs and binaries must remain unchanged. Compare the complete
reader-changing route with a fixed-reader control, the prepared C backend, and
the matched original C input. A confidence interval that includes no change
does not establish a reader-change cost.

The measured source-order path includes interface source reads and checks,
root reads and actions, library loading, symbol lookup, libffi preparation,
reader transfer, target frontend work, complete C and rename output, and
cleanup. No per-form assembler or linker subprocess runs. Prepared compiler
and library construction, correctness checks, and final generated-target GCC
compilation and linking are excluded. Filesystem caches are warm; each timed
invocation creates its own process, module instances, and call interfaces.
This gate does not measure library source preparation cost.

## Reproduce

From the repository root, prepare the compiler once, build the proof, and run
its checks. `build.py` does not run timing samples.

```sh
make all c-stage
python3 benchmarks/source-order/proof/build.py --cpu 6
python3 benchmarks/source-order/proof/measure.py
```

The default work directory is `.profile-cache/source-order-proof-replay`.
`build.py` accepts `--build-dir`, `--workdir`, and `--cpu`. For a custom replay
directory or compiler build, set the corresponding `CRUST_PROOF_DIR` and
`CRUST_PROOF_BUILD` environment variables when running `measure.py`. The timing
script uses CPU 4. Select an allowed idle CPU before running the experiment.
Rebuilt artifacts describe the current source state. Save each report under
a new path and keep its source and tool hashes.

## Bound of the result

The initial grammar accepts calls with one or two names or plain strings as
arguments. The executor accepts checked foreign calls with pointer,
function-pointer, and string arguments and an `i32` result. Zero means action
success in this proof protocol. Other forms fail with a diagnostic. This is
not the result rule for arbitrary RMD expression statements.

The result establishes the reader, cursor, source ownership, callback,
host/target separation, and final-output boundary. It does not establish host
local variables, host function bodies, arithmetic, loops, interpreted
callbacks, closures, arbitrary action representations, or complete evaluator
speed. The production runner must test its required semantics and pass its
full workload gate before those claims apply.
