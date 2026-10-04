<!-- SPDX-License-Identifier: Apache-2.0 -->

# Crust

Core small. Default compilation fast. New feature requires a concrete program.
User-selected checks may cost more compilation time. Measure cost; cost alone
does not veto the selected capability.

## Design

- Before contract changes, read [spec](docs/crust0-spec.md),
  [bootstrap](docs/bootstrap.md), [runner](docs/source-runner.md).
  Research proposals are not implemented contracts or accepted syntax.
- Sources: `.crs`. Command: `crust main.crs`. Root selects inputs, stages,
  outputs through ordinary calls.
- C99 seed: reader, checker, evaluator, runner. Seed builds without a backend.
  Backends, caching, bootstrap, execution policy: ordinary Crust stages.
  Test source bootstrap and successive stage generations.
- Keep evaluator simple. Early explicit root action prepares selected backend
  and hands later compilation code to its executor. Preserve native handoff
  witness before expanding C99 evaluator for stage speed.
- Modules, ownership, cleanup, overloads, syntax extensions, backend adapters:
  user stages. General APIs. No stage-name, path, or example special cases.
- Root actions stay in source order. Dependencies explicit. Independent work
  may run in parallel. Shared mutation or global order needs a semantic reason.
- Unused features: zero runtime cost. Raw seed: no implicit allocation,
  reference counting, checks, or cleanup.
- Safety claims require enforcing-stage checks and final program behavior.
  Raw-pointer examples alone prove no memory safety.

## Ownership

- Follow [design](docs/ownership-design.md) and [contract](docs/ownership-model.md).
  User model complexity <= Rust, for application and container authors.
  No hidden proof scripts, ghost lemmas, or solver predicates.
- Bounded local rules. No Z3, general theorem prover, equivalent solver, or graph
  solver. No whole-program analysis. Check each body using function/field
  contracts and callee interfaces. Local flow analysis allowed. No callee
  expansion or caller inspection to recover missing safety conditions.
- Verify definitions against contracts before treating library code as checked.
  Imports distinguish checked bodies from explicitly trusted bodies.
- Generic rules must cover stored views, owning trees with parent references,
  one-way observers, and intrusive lists. No topology-specific keywords, roles,
  state, proof callbacks, or disguised container checkers. Specialized stages
  may exist; their results prove only their specialized claims.
- Root may explicitly trust a small container behind an opaque checked API.
  Trusted bodies obey retention/retirement contracts. Trust is not a verified
  pointer-body proof. Test native provider behavior and client rejections
  separately. Failed checks never grant implicit trust.
- Every invalidation path, including automatic cleanup, enforces destructor
  access requirements. Undeclared retainers and raw release cannot bypass
  retirement.
- Erase proof state. No runtime identity metadata, validity checks, reference
  counts, hidden cleanup flags. Allowed: null checks before release; debug
  bounds checks. Cheap profiles reject unsupported proofs; preserve guarantees.
- Keep [validation gate](docs/ownership-design.md#9-validation) as a
  regression: trusted direct-pointer provider + checked client; individual
  destruction/reuse; rejected lifetime errors; independent imports; identical
  emitted code; compilation-cost budget.

## Communication and docs

- Short, direct, factual replies, comments, commits. Result first. State change,
  reason, checks, skipped checks and reasons. Dry humor allowed. No praise,
  filler, unsupported claims.
- Concrete question: name operation, location, broken contract, observed effect.
- Finish authorized work. No plan-only stop or repeated permission request.
  Blocked: exact cause + action needed.
- Technical docs: ASD-STE100; repo-relative links; no local absolute paths or
  tracker IDs. Correct stale claims and contracts.
- Review docs only on user request. Findings go in Beads; results in reply.
  Scratch/test output goes in ignored `build/`. Never commit investigation junk.
- Function/type docs: public behavior, preconditions, postconditions. Local
  comments: non-obvious intent/invariants. No comments that repeat code.
- Unclear decision: fix code or comment at that location. Reply alone is insufficient.
- Contract change: update specs/guides in same commit. Design-doc replacement:
  write candidate, compare old/new, then remove old text. Lose no requirements.

## Implementation

- Core edits: `src/`. Regenerate `crust0_amalg.c` with `make amalgamate` after core
  edits. Inspect/stage generated changes, including hook edits. Never hand-edit
  the amalgamation. Private shared helpers: `CRUST_STATIC`. Helpers called by
  separate platform/runner files: external linkage.
- Default: amalgamated core/reader/checker. Keep runner/platform adapters
  separate. Core/build changes: test default and `AMALGAMATION=0`.
- All C, including platform adapters: pedantic ISO C99. Keep flags:
  `-std=c99 -pedantic-errors -Wall -Wextra -Werror -Wstrict-prototypes
  -Wmissing-prototypes -Wshadow -Wvla`. No GNU syntax, `typeof`, `__attribute__`,
  statement expressions, zero-length arrays, inline assembly. Never weaken checks.
- Isolate OS/architecture/ABI code in separate implementation files. Keep OS
  headers, feature-test macros, filesystem/process/loading operations, native
  ABI adapters there. Private platform headers only when needed. Target code
  generation stays in dedicated backend files.
- Shared headers: portable C99 types. Portable algorithms and CLI policy:
  no platform calls or OS conditionals. Build selects platform files. No
  scattered `#ifdef`. Reject unsupported profiles.
- Use existing Makefile. Add platform operations only for current needs.
  No framework for hypothetical ports.
- Struct/record members: decreasing size; equal sizes in logical order.
  Foreign ABI mirrors: exact ABI order.
- Nodes/types/names/temporary tables: arenas. Arena blocks use context allocator.
  No individual compiler-object allocation/free. External buffers/native
  resources need explicit owners and release paths.
- C99 core: no mutable globals, mutable function-local statics, or thread-local
  storage. Mutable state belongs to contexts/caller-owned objects. Immutable tables
  allowed. Separate contexts must support concurrent use on separate threads.
- Source-controlled recursion: enforce depth limit or iterate. Host stack size
  is not a bound.
- CCN <= 15. Lizard: `src/`, `include/`, `runtime/`. Crust CCN stage:
  `api/`, `stages/`, `tests/`. Split responsibilities. No exclusions/counting tricks.
- Never install Node.js or npm.
- Source/config/docs: one `SPDX-License-Identifier: Apache-2.0` comment at file
  start, after shebang if present. Change generators for generated headers.
  Preserve archived benchmark bytes.

## Engineering

- Before machinery: classify hot, cold, test, compatibility, shutdown/error,
  or experiment path. Match cost/complexity to role.
- Design for performance, layout, caches, synchronization, security. Frequent
  scans of all allocated state require demonstrated need and measurements.
- Validate external input at parsing/API boundaries. Internal consumers trust
  verified state. Fix broken producers instead of repeating validation.
- Infallible internal operations return value/`void`. Status requires a possible
  input/allocation/I/O/platform failure. Assertions only for non-obvious invariants.
- Minimize valid states. Every flag/branch/retry/fallback needs a named invariant.
  No duplicate facts in flags or side tables.
- Handle failures completely or reject with diagnostic. No swallowed errors,
  invented fallbacks, partial success.
- Investigate every discovered failure, regardless of age. Fix it or explain
  exact mechanism and required fix. No "known limitation"/"future work" dismissal.
- Before major optimization/architecture: real program, controlled baseline,
  measurable success criterion. Unproven idea: bounded experiment + stop condition.
- Before extending/landing replacement architecture: prove hardest ownership
  boundary and final output in a real program. Review evidence before next layer.
  Performance claims require measurements.
- Measure frontend, stage execution, emission, target toolchain separately.
  Exclude target GCC compilation/linking from frontend. Record commands, inputs,
  flags, baseline.
- Preserve measured inputs/reports and hashes in ignored storage. Before removing
  tracked capture, retain and verify an identical local copy. New implementation:
  new evidence; preserve old captures.
- Commit benchmark tools/instructions. Raw results stay in ignored `build/`.
  Never commit binaries/archives. No machine-specific timing numbers in docs.
  Under `benchmarks/`: no generated reports, profiler logs, downloaded dependency
  trees, or third-party lockfiles.

## Checks

Test production contracts. Cover success and relevant rejection/allocation/cleanup
paths. Never weaken interfaces for tests or write tests that mirror implementation.

Code changes: `make all`, then applicable checks:

| Area | `make` targets |
|---|---|
| Core/reader/checker/evaluator/x86 | `check` |
| C backend | `check-c` |
| ASM self-compilation | `check-asm` |
| Cache/source bootstrap | `check-cache` |
| Root/reader extensions | `check-stage check-reader` |
| Native bootstrap/handoff | `check-native` |
| Ownership/RAII/defer | `check-resources check-resource-alloc` |
| Ownership/field contracts | `check-ownership check-ownership-alloc` |
| Verified ownership imports | `check-ownership-imports` |
| Overloads/resource composition | `check-overload check-overload-alloc` |
| Compilation examples | `check-examples` |
| Modules/bindings/exports | `check-modules` |
| Native jobs | `check-parallel` |
| Highlight/editor | `check-highlight check-vscode` |
| Crust CCN | `check-ccn` |

- Core/shared API changes: full table. Allocation/native-call/lifetime changes:
  relevant sanitizers. Repeat passed checks only after changes, failures, or
  new concerns. Docs-only: hooks + links; compiler rebuild unnecessary.
- Executable doc changes: run consuming tests. Specification examples:
  `make check check-c`.
- C API authority: `include/`. API changes: `make api`, then
  `python3 tools/api.py --check`; update stage consumers. Never hand-edit
  generated API declarations or prelude.

## Beads and commits

Use `br` (beads_rust) from repo. Database: `../.beads`. Never create/commit
repo-local `.beads`.

1. `git status`; `br ready`. Preserve others' work.
2. `br update <issue> --status=in_progress`. Create focused issue if none matches.
   Track newly found defects.
3. Implement; run required checks.
4. Stage intended files. `pre-commit run`; `git diff --cached --check`.
   Hooks edit files: inspect, restage, rerun. All hooks must pass.
5. `br close <issue>` for completed work; `br sync --flush-only`.
6. `git commit -s`. One logical change per commit; descriptive subject.
7. `git status`. Report commit, validation, remaining checkout changes.
