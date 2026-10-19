<!-- SPDX-License-Identifier: Apache-2.0 -->

# Windows support

The `windows_x64` profile runs the C99 seed natively on Windows 10 or later,
on x86-64. It supports interpreted root actions, public compiler APIs, host
allocation and binary file operations, and explicit native DLL imports.
The host uses the Windows x64 scalar ABI and an LLP64 C data model.

The C backend supports source bootstrap, native DLL handoff, and application
compilation. The shared package builder selects Windows providers in ordinary
Crust. Captured inputs select validated, reusable DLL artifacts. LLVM and ASM
package compilers, native jobs, formatter replacement, and ownership imports
also have Windows providers. The [support plan](windows-support-plan.md) records
the implementation gates.

## Build and check

Use an MSYS2 UCRT64 shell with GNU Make, MinGW-w64 GCC, libffi, and native Python.
The CI job installs these packages: `make`, `mingw-w64-ucrt-x86_64-gcc`,
`mingw-w64-ucrt-x86_64-libffi`, and `mingw-w64-ucrt-x86_64-python`.
Run `make PROFILE=windows_x64 all check-windows check-windows-bootstrap check-windows-cache`. Repeat with
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
`malloc`, `calloc`, `realloc`, `free`, `qsort`, `abort`, and `exit`.
The Windows process and file provider also uses the explicit Win32 host symbols
listed in [run_windows.c](../src/run_windows.c). They cover UTF conversion,
paths, files, handles, process creation and status, environment lookup, image
enumeration, loader notifications, random bytes, and BCrypt SHA-256 operations.
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

## Source bootstrap

Put native MinGW-w64 GCC and binutils in `PATH`. From the repository directory,
run `build/windows/crust.exe examples/hello/main.crs`, then `build/hello`.
The root builds the C backend, loads its DLL, and calls the native backend to
compile the rest of the root. No backend is linked into the seed.

Keep `crust.exe.a` and the generated `profile/` directory beside `crust.exe`.
The import library lets generated stage DLLs call the same seed instance.
Stage DLLs export their own ABI marker and selected package functions.
The normal loader ownership and ABI checks apply to each generation.

Tools run without a shell. Arguments use Windows quoting and UTF-16 conversion.
The child environment contains only the captured `PATH`, `SystemRoot`, `TEMP`,
`TMP`, and `LC_ALL=C`; the first four variables are required. Standard input is
`NUL`. Standard output is inherited or redirected to the selected file. Standard
error is inherited. Process and stream handles close after completion.
The Windows providers use the output directory as the tool working directory
and pass relative scratch filenames. This avoids ANSI conversion of absolute
Unicode paths in GCC child tools. User compiler and linker flags remain unchanged;
relative paths in those flags must refer to the output directory.

For a GCC installation path that contains non-ASCII characters, the provider
adds relative search prefixes through a temporary directory junction. The
junction points to the original installation and is removed after the command.
This requires a local toolchain and an output filesystem that supports directory
junctions. A failure to create or remove the junction is an error. The cache
captures the original files, not the temporary junction name.

Each Windows artifact request hashes its ordered input snapshots with a Windows
x64 format tag. A hit verifies the DLL checksum. A miss builds in a private
directory and publishes the DLL and checksum together with a directory rename.
A concurrent losing producer verifies the winner and removes its own files.
Failed builds remove owned scratch files. An interrupted process can leave a
private `.build-` directory; it is never a cache entry. The caller can remove
such directories after their producers stop. Publication does not promise
power-loss durability.

The default GCC provider requires one self-contained installation with `gcc`
and `objcopy` in its `bin` directory. Its headers, libraries, helper executables,
and configuration must stay inside that installation. Reparse points and
directory nesting deeper than 32 levels are rejected. Custom specs or plugins
that read external files need a separate toolchain provider with explicit inputs.
The provider hashes every installation file, including directory membership,
and captures the exact child environment. A compile, object-copy, and DLL-link
probe captures the actual executable and DLL images loaded by the tools and
their children. The probe requires Windows debugging APIs. Failure to capture
an input rejects the request before cache lookup.

The seed, its loaded images, the seed import archive, producer source snapshots,
package inputs, options, and export mappings also contribute to the key.
External file hashing uses a fixed 64 KiB buffer. Keep tools, configuration, and
loaded code unchanged during a session. Keep published files unchanged until
every runner that loaded them has been destroyed. Cache directories must be
caller-owned and must not have untrusted writers.

Ownership and generic-ownership library formats use Windows x64 tags and
Windows cache providers. Ownership object bundles contain COFF objects.
Their trusted receipts retain the same authority and body-checking rules.
Imported objects use private scratch files beside the output so that GCC does
not need to decode absolute Unicode object paths. Linux bundles are rejected.
The Windows cache tag and generated native ABI digest are distinct from Linux's;
native DLL loading still checks the marker owned by each selected image.

The C driver creates temporary files beside the destination. It replaces existing
files through `ReplaceFileW` and publishes new files through `MoveFileExW`.
Windows ACLs control file access; POSIX mode bits do not apply. Paired text and
symbol outputs reject matching canonical paths and existing hard links.

## Validation boundary

### Backends and tools

Fetch LLVM explicitly. For a native Windows Python installation:

```sh
python3 tools/fetch_llvm.py release --profile windows_x64
```

Set `CRUST_LLVM_DIRECTORY` to the printed directory. Use `--locked` to reuse
its pin. Compilation never fetches LLVM. Clang emits Windows GNU COFF objects;
the self-contained MinGW-w64 toolchain remains responsible for linking.

Run these additional checks in both seed build modes:

```sh
make PROFILE=windows_x64 check-windows-llvm check-windows-asm
make PROFILE=windows_x64 check-windows-tools check-windows-ownership
```

The backend tests exercise mixed register and stack arguments, calls and
callbacks with native C, binary32 casts and NaNs, large frames, actual Windows
unwinding, cache reuse, and a successor compiler built with the selected backend.
The LLVM check also builds and runs a standalone executable.

The formatter rejects directories, reparse points, and files with more than
one hard link. It checks file identity, size, write time, and change time before
replacement. `ReplaceFileW` preserves the target ACL. A read-only target fails
without replacement. The caller must own the containing directory. The Python
formatter wrapper selects the Windows launcher when it runs on Windows.

Native jobs use `_beginthreadex`. Each job owns its mutable state; callbacks
must be native and remain loaded until all workers finish. Every started worker
is joined before return, including after a later start fails. Allocation failure
does not start a worker.

The editor adapter launches native executables without a shell or a console
window. A Windows VSIX uses `--platform win32-x64` and bundles
`bin/crust-highlight.exe`. To run from source, configure `crust.highlighter.path`
as the absolute seed path and `crust.highlighter.arguments` as the absolute path
to `stages/build/run.crs`, followed by `stages/highlight/tool.crs`.
Set `CRUST_JS_RUNTIME` to a native JavaScript runtime to include the editor
process test in `check-windows-tools`. That test covers UTF-8 token output,
cancellation, and launch failure.

The ownership check runs a trusted direct-pointer provider with a checked
client, imports it after removing the original provider sources, rejects invalid
moves and receipts, and compares emitted code before and after proof erasure.
It also checks independent generic imports, cleanup, and move rejection.
The existing client-budget audit remains required; the port changes no ownership
syntax or proof rules.

### Shader environment

Vulkan execution is a separate Windows gate. A Vulkan runtime alone is not
sufficient. Validation also needs Windows SPIRV-Tools, Vulkan SDK headers and
an import library, and the selected WGSL validator. The current execution harness
links `libvulkan.so.1` and its file ABI uses Linux `long`; that harness must use
Windows link and file adapters before its results can establish Windows parity.
The host backend port does not establish this shader execution claim.

`check-windows` exercises scalar calls and callbacks, mixed and stack arguments,
file buffer release, allocation failures, runner ownership, missing and mismatched
ABI markers, forwarded exports, decimal rounding, Unicode command arguments,
root-relative paths, LF and CRLF reader switching, and output publication failure.
UNC syntax is checked
without requiring an external share. Access to a real UNC share depends on the
test environment and is not covered by the local suite.

`check-windows-bootstrap` starts with an empty artifact directory. It checks the
native callback binding before successor compilation, builds a second backend,
and uses it to compile and run hello. It also checks Unicode paths, argument
quoting, redirection, the child environment, exit status, missing tools and import
libraries, failed linking, output preservation, paired output aliases, and DLL
deletion after runner destruction. Cleanup is also tested with a context
allocator that rejects every allocation.

`check-windows-cache` checks cold and warm native builds, input invalidation,
checksums, failed and interrupted builds, concurrent publication, and allocation
failures. Concurrent storage tests share one 512 MiB job; they do not compile
backends concurrently. Toolchain copies and timing evidence stay in `build/`.

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

The Windows output adapter also has an emitter fixture that checks publication
and cleanup independently of a backend. Native backend tests provide separate
ABI and execution evidence. Linux checks and allocation sanitizers remain
required for changes to shared code.

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
