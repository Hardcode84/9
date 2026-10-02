<!-- SPDX-License-Identifier: Apache-2.0 -->

# Artifact cache stage

This library reuses one complete output file from an explicit build function.
It is ordinary Crust code. The seed does not select a cache, discover inputs,
or skip root actions. The [backend tutorial](../../examples/cached-backend/README.md)
uses it to prepare and load native compiler stages.

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
not hash source bytes in an interpreted byte loop.

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

[inputs.crs](inputs.crs) captures files, the runner's retained source snapshots,
and the actual loaded native images. Use the retained snapshots for producer
code: a file edit after `host_source` does not change the code already checked.
The main executable comes from `/proc/self/exe`. Tool dependencies come from
`ldd`, under the same fixed environment as `cache_tool`. This provider requires
dynamic Linux ELF tools. Use another explicit provider for other tool formats.
The loaded-image provider includes loader-selected and explicitly loaded files.

The backend recipe uses only the assembler and linker. Its assembly contains
no file includes, and the link command supplies its libc file explicitly.
A different recipe must also capture its headers, link scripts, libraries,
configuration, environment, and other reads as applicable.

Run `make check-cache` for reuse, source and option edits, captured-byte use,
corruption, missing files, producer errors, partial output, concurrent
publication, allocation failures, and the native handoff witness.
