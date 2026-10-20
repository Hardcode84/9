<!-- SPDX-License-Identifier: Apache-2.0 -->

# Artifact cache stage

This library reuses one complete output file from an explicit build function.
It is ordinary Crust code. The seed does not select a cache, discover inputs,
or skip root actions. The [backend tutorial](../../examples/cached-backend/README.md)
uses it to prepare and load native compiler stages.

Linux and Windows select separate platform providers. The Windows package
builder selects [artifact_windows.crs](artifact_windows.crs) and captures the
self-contained toolchain described in the [Windows guide](../../docs/windows.md).
Keep published files unchanged until their runners close.

## Contract

`CacheBuild` supplies ordered input snapshots, a build function, and user data.
`cache_artifact(context, directory, request, result)` returns a path and a hit
flag. The context owns the returned path. The caller owns the cache directory
and the published file. The producer receives the requested output path.

The caller must include every value that can affect output:

- Producer and helper code, frontend and ABI identity, and selected sources.
- Target settings, options, exports, and the meaning of user data.
- Tool executables, their libraries, and other external inputs.
- Presence or absence when a producer performs an optional file lookup.

The producer reads the captured source bytes. Native tools and loaded code
must remain unchanged while the request runs. A missing required input fails
before lookup. This API does not infer dependencies or observe arbitrary I/O.
A producer that cannot supply this contract must run without this cache.

The build function writes only its output and owned scratch files. It removes
scratch files before it returns. Unrelated effects belong outside the build
function and run on every invocation. Contexts, native pointers, reader state,
and execution results are not cache artifacts.

## Lookup and publication

The key is SHA-256 over a format tag and each input's length-delimited path and
bytes, in order. The Linux adapter invokes `sha256sum` without a shell. It does
not hash source bytes in an interpreted byte loop. Windows uses BCrypt SHA-256
with a fixed 64 KiB input buffer. Platform-specific format tags prevent reuse
between Linux x64 and Windows x64.

Every request uses a private temporary directory. A miss builds the file and
records its checksum. A directory rename publishes both together. Concurrent
producers can build independently; a losing producer verifies the winner and
removes its own output. Partial output is never a hit. Failures retain a
diagnostic and remove owned temporary files.

A hit checks the artifact bytes against its stored checksum. Corrupt entries
fail explicitly. Remove the affected entry before rebuilding it. The directory
must belong to the caller and must not have untrusted writers: this checksum
checks stored bytes, not the authority to execute them. Keep cache files live
while runners or later link operations need them. Eviction is a caller action.
Publication is atomic between processes; no power-loss durability is promised.

## Input providers

[inputs.crs](inputs.crs) captures files and the runner's retained source snapshots.
[inputs_linux.crs](inputs_linux.crs) captures the actual loaded native images.
Use the retained snapshots for producer code: a file edit after `host_source` does not change the code already checked.
The main executable comes from `/proc/self/exe`. Tool dependencies come from
`ldd`, under the same fixed environment as `cache_tool`. This provider requires
dynamic Linux ELF tools. Use another explicit provider for other tool formats.
The loaded-image provider includes loader-selected and explicitly loaded files.
Tool executables and their libraries are captured as named SHA-256 digests.
Their full bytes are not retained in compiler arenas. Source inputs still use
the captured bytes, and native tools must remain unchanged during the request.

[inputs_windows.crs](inputs_windows.crs) captures loaded process images and
tool-process images through Windows loader notifications. The Windows GCC
provider also hashes all files in its installation and captures its child
environment. File digests are retained as named snapshots; large tool files
are not retained in compiler arenas. Changes during a session are not supported.

The backend recipe uses only the assembler and linker. Its assembly contains
no file includes, and the link command supplies its libc file explicitly.
A different recipe must also capture its headers, link scripts, libraries,
configuration, environment, and other reads as applicable.

Run `make check-cache` for reuse, source and option edits, captured-byte use,
corruption, missing files, producer errors, partial output, concurrent
publication, allocation failures, and the native handoff witness.
Run `make PROFILE=windows_x64 check-cache` for the Windows provider.

On Linux with a systemd user session, run the extended checks serially with
a combined 512 MiB memory limit and no swap:

```sh
systemd-run --user --scope -p MemoryMax=536870912 -p MemorySwapMax=0 \
  make -j1 check-cache check-union-alloc check-llvm
```

The union sanitizer fixture keeps `-O1`, line debug information, ASan, and UBSan.
It omits local-variable debug records to reduce assembler memory use.
Its GCC options request earlier garbage collection to reduce peak memory.
The sanitizer build disables inlining of functions called once. This keeps
large helper frames out of recursive lowering calls and preserves stack space
for the depth-limit diagnostic. The ordinary union build still uses `-O2`.
The LLVM check builds three emitter generations and checks cache reuse and
invalidation. Retain measurement logs in the ignored `build/` directory.
