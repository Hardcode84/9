<!-- SPDX-License-Identifier: Apache-2.0 -->

# Windows seed support

The `windows_x64` profile runs the C99 seed natively on Windows 10 or later,
on x86-64. It supports interpreted root actions, public compiler APIs, host
allocation and binary file operations, and explicit native DLL imports.
The host uses the Windows x64 scalar ABI and an LLP64 C data model.

Application backends, source bootstrap, cache providers, native parallel jobs,
and formatter file replacement remain Linux-only. A Windows seed build does
not establish support for those stages. Make rejects their check targets under
the Windows profile. The [support plan](windows-support-plan.md) defines the
remaining phases.

## Build and check

Use an MSYS2 UCRT64 shell with GNU Make, MinGW-w64 GCC, libffi, and native Python.
The CI job installs these packages: `make`, `mingw-w64-ucrt-x86_64-gcc`,
`mingw-w64-ucrt-x86_64-libffi`, and `mingw-w64-ucrt-x86_64-python`.
Run `make PROFILE=windows_x64 all check-windows`. Repeat with
`AMALGAMATION=0` to check the separate-file core.

The default output is `build/windows/crust.exe`. It runs from PowerShell or
another Windows process without WSL. The build shell is not a runtime dependency.
If libffi is linked dynamically, place its matching DLL beside the launcher
or make it available through the normal executable dependency search.

Use a separate `BUILD` directory for each host profile. The strict C99 flags
apply to all repository C files. `FFI_CFLAGS` and `FFI_LDFLAGS` supply a custom
libffi installation. Mark third-party headers as system headers, for example
with `-isystem/path/to/libffi/include`; this does not relax checks on Crust code.

A Linux cross-build can use `CC=x86_64-w64-mingw32-gcc` and a Windows libffi
installation. `check-windows` can execute those binaries through WSL interop
on a Windows host. A cross-build alone does not validate runtime behavior.

## Native interface

The host interface exposes the generated seed declarations from `crust0`,
`crust0_host`, `crust0_eval`, and `crust0_run`. It also exposes these C functions:
`puts`, `strlen`, `strcmp`, `strncmp`, `memcpy`, `memmove`, `memset`, `memcmp`,
`malloc`, `calloc`, `realloc`, `free`, `abort`, and `exit`.
Other externs require an explicit library binding. Loading a DLL does not add
its exports to the host interface.

Use the host release function for host allocations and file-read buffers.
Do not pass these buffers to a CRT `free`. The Windows host uses a matched
aligned allocation and release pair. Compiler arenas retain their own context
allocator. A DLL that supplies an allocator must remain loaded until all of
its allocations have been released.

Float literals use the system Universal CRT's locale-specific binary32 parser.
Locale creation, conversion, and release use the same CRT instance. Parsing
does not change process or thread locale. The legacy CRT's conversion through
binary64 is not used because it can round decimal boundary values incorrectly.

Windows API declarations and ABI markers are generated under
`build/windows/profile/`. Add its `include` directory before the repository's
`include` directory when compiling a Windows native provider. Export its own
`CRUST_ABI_crust0` marker with `CRUST_ABI_EXPORT` from `crust0_abi.h` and export
the declared functions. GNU linker option `--export-all-symbols` is sufficient
for the test providers. Production providers can use an explicit export list.
The Windows digest differs from Linux's. Use the generated Windows `api/`
files for explicit API imports into Windows roots.

The runner owns loaded libraries until destruction. Complete every call and
callback before destroying the runner. DLL dependency lookup uses the selected
library directory and the system directory. Forwarded exports and forwarded
ABI markers cannot satisfy ownership checks.

## Validation boundary

`check-windows` exercises scalar calls and callbacks, mixed and stack arguments,
file buffer release, allocation failures, runner ownership, missing and mismatched
ABI markers, forwarded exports, decimal rounding, Unicode command arguments,
root-relative paths, LF and CRLF reader switching, and output publication failure.
UNC syntax is checked
without requiring an external share. Access to a real UNC share depends on the
test environment and is not covered by the local suite.

Native test processes run serially in Windows jobs with a 512 MiB combined
memory limit per process tree. Closing a test job terminates its remaining
children. Allocation rejection tests use invalid inputs and injected context
allocator failures; they do not request large live allocations.

Run local Linux validation one job at a time with an aggregate memory limit.
For a host with systemd user scopes, use:

```sh
systemd-run --user --scope -p MemoryMax=536870912 -p MemorySwapMax=0 make check
```

This limits the process tree to 512 MiB and disables swap for that scope.
A check stopped by the limit is incomplete; retain its failure log.

The Windows output adapter is tested with an emitter fixture. This checks file
publication and cleanup independently of a target backend; it does not establish
Windows ASM emission. Linux checks and allocation sanitizers remain required for
changes to shared code.

## Linux baseline

Before changing the implementation, retain a source archive under ignored
`build/` storage. Extract it into a separate directory and build its seed and
test tools. Run `benchmarks/bootstrap/windows_baseline.py` with `--source`
set to that frozen checkout and `--output` set to a new ignored directory.
Select an allowed CPU with `--cpu`.

The tool records one cold and one warm hello build. It separates stage
preparation, target frontend work, C emission, and native toolchain processes.
The instrumentation uses ordinary Crust callbacks and includes their overhead.
The final program must print the expected greeting. Reports retain commands,
flags, tool and source hashes, generated inputs, and raw times. These samples
establish a reproducible baseline, not a performance ranking. Run timing samples
without other compilation jobs.

Also retain `check-native` and `check-cache` logs from the frozen checkout to
record the native handoff and successive-stage behavior. Keep the original
archive and reports when collecting later measurements.
