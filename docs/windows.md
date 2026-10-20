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
Run `make PROFILE=windows_x64 all check check-native check-cache`. Repeat with
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
installation. Run the shared checks from a native MSYS2 UCRT64 shell.
A cross-build alone does not validate runtime behavior.

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
Its exports come from the generated Crust host declarations. CRT entry
points are not exported. Each DLL must use its own CRT registration functions
so that its exit callbacks run before the DLL is unloaded.
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

The default GCC provider captures the selected `gcc` and `objcopy` executables
and the exact child environment. It does not scan the installation, hash system
headers, inspect loaded DLLs, or run dependency probes.

The seed executable, seed import archive, producer source snapshots, package
inputs, options, and export mappings also contribute to the key. External file
hashing uses a fixed 64 KiB buffer. Keep the host and toolchain installations
fixed while reusing the cache. Use a fresh cache after changing untracked
libraries, headers, helper tools, or configuration. Add other required file
inputs explicitly. Keep published files unchanged until every runner that loaded
them has been destroyed. Cache directories must be caller-owned and must not
have untrusted writers.

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
make PROFILE=windows_x64 check-llvm check-asm
make PROFILE=windows_x64 check-format check-parallel check-vscode check-ownership
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
process test in `check-vscode`. That test covers UTF-8 token output,
cancellation, and launch failure.

The ownership check runs a trusted direct-pointer provider with a checked
client, imports it after removing the original provider sources, rejects invalid
moves and receipts, and compares emitted code before and after proof erasure.
It also checks independent generic imports, cleanup, and move rejection.
The existing client-budget audit remains required; the port changes no ownership
syntax or proof rules.

### Shader environment

Vulkan execution uses the shared `check-shader` target. Install a Vulkan compute driver,
Windows SPIRV-Tools, Vulkan headers, and a MinGW-compatible Vulkan import library.
Select a Windows LLVM build with the SPIR-V target. Check that
`llc.exe --version` lists `spirv`; a host-only LLVM distribution is insufficient.
The MSYS2 UCRT64 LLVM package includes this target.

```sh
UCRT64_PATH=$(cygpath -m /ucrt64)
make PROFILE=windows_x64 check-shader \
  LLVM_DIRECTORY="$UCRT64_PATH" SPIRV_TOOLS="$UCRT64_PATH/bin" \
  VULKAN_INCLUDE="$UCRT64_PATH/include" \
  VULKAN_LIBRARY="$UCRT64_PATH/lib/libvulkan-1.dll.a" \
  WGSL_VALIDATOR="$(cygpath -m build/tools/naga.exe)"
```

The command converts MSYS paths for native Windows Python. Set the validator
path to its installed location. `WGSL_VALIDATOR` adds validation of generated
WGSL; omit it only when that separate validation is not required. The test runs native tools
and dispatches directly, including paths with spaces and non-ASCII text.
Repeat with `AMALGAMATION=0` to test the separate-file seed.

The Vulkan runner uses UTF-16 file opening and signed 64-bit file offsets.
The shader package selects Windows tool names and runs tools with relative
temporary file arguments. ABI checks compare the Crust bindings with C headers.
The execution suite checks shader results, status buffers, allocation failures,
rejected programs, and output preservation after tool failure. Linked wrappers
inject enumeration and descriptor-pool failures on Windows. The Linux test
uses its existing interposition library. See the
[shader tutorial](../examples/shader/README.md) for the device requirements.

`check` exercises scalar calls and callbacks, mixed and stack arguments,
file buffer release, allocation failures, runner ownership, missing and mismatched
ABI markers, forwarded exports, decimal rounding, Unicode command arguments,
root-relative paths, LF and CRLF reader switching, and output publication failure.
UNC syntax is checked
without requiring an external share. Access to a real UNC share depends on the
test environment and is not covered by the local suite.

`check-native` starts with an empty artifact directory. It checks the
native callback binding before successor compilation, builds a second backend,
and uses it to compile and run hello. It also checks Unicode paths, argument
quoting, redirection, the child environment, exit status, missing tools and import
libraries, failed linking, output preservation, paired output aliases, and DLL
deletion after runner destruction. Cleanup is also tested with a context
allocator that rejects every allocation.

`check-cache` checks cold and warm native builds, input invalidation,
checksums, failed and interrupted builds, concurrent publication, and allocation
failures. Concurrent storage tests do not compile backends concurrently.
Toolchain copies and timing evidence stay in `build/`.

Linux and Windows use one CI suite matrix and the same Make test targets.
CI runs Make targets in parallel with one job per available CPU. Shared fixture
preparation builds each target's prerequisites. Platform contract cases run from
the corresponding shared targets. Test processes run directly, without a job
wrapper or a test-wide memory cap. Allocation rejection tests use invalid inputs
and injected context allocator failures; they do not request large live allocations.

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
