<!-- SPDX-License-Identifier: Apache-2.0 -->

# Windows support plan

Status: phases 1 through 4 are implemented for the capabilities listed in the
[Windows guide](windows.md). Vulkan execution uses the separate
`check-windows-shader` gate with explicit tools and a compute driver.

Add native Windows x64 support in stages. First prove that the C99 seed can
build a compiler stage from source, load it, hand later compilation to it,
and produce a working application. Then extend backend and tool coverage.

The current contracts remain in the [language specification](crust0-spec.md),
[bootstrap guide](bootstrap.md), and [runner guide](source-runner.md).
Update those contracts with each implemented capability.

## Scope

Use MinGW-w64, GNU Make, Python, and libffi for the first Windows profile.
Keep the existing strict C99 checks. Select platform files through the build.
A build shell may provide Unix command utilities, but the resulting launcher
and applications must run as native Windows programs without WSL.

The first supported workflow must include:

- The seed launcher in both amalgamated and separate-file builds.
- Scalar foreign calls and callbacks through the Windows x64 ABI.
- Source-built compiler stages and native handoff.
- One backend that produces a native executable.
- Cache reuse with complete input capture and correct invalidation.
- Diagnostics and cleanup for failed compilation and failed library loading.

Add ASM, C, and LLVM parity after the first complete workflow. Track formatter,
parallel jobs, editor integration, and shader tooling as separate capabilities.
MSVC, Windows ARM64, and 32-bit Windows are outside the initial scope.
Reject unsupported profiles explicitly.

## Dependencies at the start of the port

| Area | Current implementation | Required change |
| --- | --- | --- |
| Build | [Makefile](../Makefile) accepts only `linux_x64` and selects POSIX objects | Add a Windows profile, file suffixes, platform objects, and linker options |
| Host layout | [Linux profile](../src/profile_linux_x64.c) requires LP64 and Linux allocation and locale APIs | Define Windows host assumptions and provide allocation and numeric parsing adapters |
| Native calls | [libffi adapter](../src/eval_ffi.c) uses the default host ABI | Validate Windows scalar calls, returns, and closures; share only demonstrated common code |
| Libraries | [POSIX runner](../src/run_posix.c) uses ELF loader inspection | Add DLL loading, export resolution, ABI validation, and unload operations |
| Memory | [Host allocation](../runtime/host_posix.c) uses `posix_memalign`; [host release](../runtime/host.c) uses `free` | Preserve matching allocation and release operations for every buffer owner |
| Source paths | [Host stage](../stages/host.crs) uses slash-based path rules | Define drive, UNC, relative path, and Unicode handling |
| Native stages | [Linux native operations](../stages/native/linux.crs) use POSIX processes and shared libraries | Add Windows process, temporary-file, link, and cleanup operations |
| Cache | [Cache operations](../stages/cache/linux.crs) and [input capture](../stages/cache/inputs_linux.crs) use Linux tools and loader data | Capture Windows toolchain and library inputs under a defined execution environment |
| ABI identity | [API generator](../tools/api.py) includes a Linux LP64 identity | Generate distinct profile identities and reject incompatible artifacts |
| C output | [C emitter](../stages/c/emit.crs) requires Linux GCC for its 64-bit output | Add a Windows output profile and audit GNU extensions, symbols, and C type assumptions |
| LLVM output | [LLVM emitter](../stages/llvm/program.crs) selects a Linux target triple | Add Windows target layout, ABI, exports, and toolchain configuration |
| Assembly output | [ASM stage](../stages/asm/README.md) emits System V ELF assembly | Implement Windows calling convention, COFF directives, relocations, and stack requirements |

Windows x64 keeps pointers at 64 bits but uses 32-bit C `long`. Audit foreign
declarations and generated layout assumptions. Do not infer C type widths from
pointer width. Regenerate API declarations from their C headers.

## Architecture constraints

Keep the seed limited to reading, checking, evaluation, and running root actions.
Keep bootstrap, caching, backend selection, and execution policy in ordinary
Crust stages. Make builds the seed and test fixtures; it must not acquire an
application stage source graph.

Put Windows API calls and OS headers in dedicated implementation files. Use
portable types in shared headers. Select Crust platform providers through the
shared package mechanism. Avoid scattered OS conditions and example-specific
paths. Preserve explicit dependencies and root action order.

Classify loader, process, cache, and file publication work as preparation or
error-path work. Treat foreign calls and generated target code as execution
paths. Measure before adding state, repeated scans, or optimization machinery.

## Phase 1 Establish the baseline and port the seed

Record a Linux baseline for the hello application, source bootstrap, native
handoff, and warm cache reuse. Preserve commands, inputs, tool versions, flags,
hashes, and reports under ignored `build/` storage. Measure frontend, stage
execution, emission, and target toolchain time separately.

Add the Windows build profile and C platform adapters. Cover root paths,
locale-independent float parsing, aligned allocation, DLL loading, and output
publication. Keep allocator ownership explicit across DLL boundaries. A host
file-read buffer and an aligned host allocation must both reach the correct
release operation.

Define the host symbol interface explicitly. Preserve the runner checks that
an export belongs to the selected library and that a library carries its own
compatible ABI marker. A dependency must not supply a missing marker on behalf
of the selected image. Do not replace these checks with unrestricted DLL search.

Acceptance:

- Build the seed with the existing strict flags in both build modes.
- Execute a root that reads a file and calls a host function.
- Exercise integer, pointer, float, and boolean calls and returns, including
  mixed arguments, stack arguments, and callbacks.
- Reject missing exports, incompatible ABI markers, and invalid library owners.
- Exercise allocation failure, load failure, and unload cleanup.
- Exercise paths with spaces, Unicode characters, drive roots, and UNC syntax.

## Phase 2 Prove source bootstrap and native handoff

Implemented with the C backend and the shared package builder. The
[Windows checks](../tests/windows_bootstrap.py) cover empty-directory bootstrap,
a native callback witness before successor compilation, a second backend
DLL, hello execution, process behavior, failed builds, and unload cleanup.
Phase 3 adds validated reuse to this bootstrap workflow.

The shared preparation graph selects native, build, and artifact providers
from the host profile. The Windows C bootstrap does not require the ASM backend.

Run a bounded experiment with the [hello application](../examples/hello/main.crs).
Start with only the seed, repository sources, and the selected host toolchain.
Build the backend from source, load its DLL, hand later compilation to native
code, and run the resulting application. Build a successive stage generation
through the same path.

Add Windows process execution with argument quoting, a defined environment,
exit-status handling, and output redirection. Add export and import handling
for generated DLLs. Retain loaded code until all calls and callbacks finish.
Order unload and temporary-file deletion so that loaded DLLs do not prevent
cleanup. Report cleanup failures.

Acceptance:

- The complete hello workflow succeeds from an empty stage cache.
- Native handoff is witnessed before later compilation work starts.
- A successive stage generation produces the same program behavior.
- Failed compilation and missing dependencies leave no usable partial artifact.
- Linux bootstrap and handoff checks continue to pass.

Stop this experiment before broader backend work if it requires a backend in
the seed, copied bootstrap sequences, or relaxed ABI checks. Record the exact
dependency and revise the stage boundary before continuing. Do not expand the
C evaluator solely to hide slow interpreted bootstrap.

## Phase 3 Make cache behavior correct on Windows

Implemented for the self-contained GCC toolchain described in the
[Windows guide](windows.md). External files use streamed SHA-256 hashes.
The input provider captures installation files, child environment, loaded
images, and tool-process image dependencies. The cache publishes complete
directories and verifies artifact checksums before reuse. Phase 4 adds distinct
Windows ownership object bundle formats.

Add Windows providers for hashing, tool identity, dependency capture, temporary
directories, and atomic artifact publication. Capture the actual compiler,
linker, libraries, and configuration used by the selected toolchain. Preserve
the cache contract when replacing `ldd` and loaded ELF image inspection.

Include platform and ABI identity in artifact compatibility. Reject Linux
artifacts on Windows. Audit ownership and generic ownership artifact identities
as well as native library markers.

Acceptance:

- A second identical build reuses the cached result.
- Source, tool, dependency, and relevant configuration changes invalidate it.
- Interrupted writes and concurrent builders cannot publish partial output.
- Paths with spaces and Unicode work for both tools and cache directories.
- Cleanup works after cache failure and after native code unload.

## Phase 4 Extend backends and tools

Implemented: native LLVM emission and acquisition, Windows ASM package compilation,
formatter replacement, native jobs, editor launch, and ownership imports.
The native checks cover callbacks, unwind records, successive compiler generations,
checked clients, trusted providers, and proof erasure. The Windows guide records
the supported toolchain and the separate shader environment requirements.

Add LLVM Windows emission and linking after the complete workflow passes.
Validate target layout, scalar ABI behavior, DLL exports, and native callbacks.
Extend LLVM acquisition separately. The release fetch now accepts Linux x64
and Windows x64 profiles.

Port ASM calling conventions and object format together. Cover integer and
floating-point argument placement, shadow space, preserved registers, stack
alignment, large stack frames, and required unwind information. Replace ELF
symbol directives and relocations with COFF forms. Test external calls in both
directions and successive ASM stage generations.

Port formatter file replacement and metadata handling, native parallel jobs,
and editor process launch. Validate ownership stages with both checked clients
and native trusted providers. Preserve proof erasure and the measured client
budget. Assess Vulkan and shader tool acquisition as a separate Windows test
environment.

## Validation and release gates

Add Windows CI beside Linux CI. Use the [repository check matrix](../AGENTS.md)
for every implementation change. Core or shared API changes require the full
matrix. Any capability not yet supported on Windows must have an explicit
rejection and a recorded gate; skipped tests do not establish parity.

| Change | Principal checks |
| --- | --- |
| Core and build | `make all`, `check`, both amalgamation modes, regenerated amalgamation |
| Runner and bootstrap | `check-stage`, `check-reader`, `check-native`, `check-cache` |
| Backends | `check-c`, `check-llvm`, `check-llvm-fetch`, `check-asm` |
| Language stages | Ownership, resources, imports, generics, overload, union, and module checks from the full matrix |
| User workflows | `check-examples`, `check-tutorials`, `check-format`, `check-parallel`, `check-highlight`, `check-vscode` |
| Shared APIs | `make api`, generated API check, updated stage consumers |

Run applicable allocation and lifetime sanitizers. If a sanitizer is unavailable
on the selected Windows toolchain, record that coverage gap and retain Linux
sanitizer coverage. Keep Windows allocation-failure and cleanup tests mandatory.

Compare the baseline and Windows implementation with identical program behavior.
Record compilation costs by phase. Set numerical performance gates from the
baseline before optimization; this proposal makes no performance claim.

For each completed phase, update the affected specification and guides in the
same commit as the implementation. Preserve Linux support. Run hooks and link
checks, and keep raw measurements in ignored storage.

## Effort and sequencing

These provisional estimates assume one developer familiar with the project.
They include implementation and tests. Re-estimate after the source bootstrap
experiment; no Windows build measurement supports a tighter schedule yet.

| Cumulative scope | Estimated effort |
| --- | --- |
| Seed, simple roots, and foreign calls | 1 to 3 weeks |
| One complete backend workflow with bootstrap, handoff, and cache | 4 to 8 weeks |
| Broad backend and tool parity | 2 to 4 months |

The main schedule risks are DLL symbol ownership, allocation across library
boundaries, the bootstrap dependency graph, complete cache input capture, and
the ASM ABI port. Complete phases 1 through 3 before broadening the supported
toolchain set.
