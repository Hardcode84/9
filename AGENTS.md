# Crust

Crust is a small systems language with a C99 bootstrap compiler. Compilation
speed through backend handoff is the first requirement. Keep the core small.
Do not add a feature before a concrete program requires it.

## Design

- Read the [language specification](docs/crust0-spec.md),
  [bootstrap guide](docs/bootstrap.md), and
  [runner contract](docs/source-runner.md) before changing their contracts.
  Research documents contain proposals, not additional implemented features.
- Source files use `.crs`. The command is `crust main.crs`. The root program
  selects inputs, stages, and outputs through ordinary calls.
- Keep module management, ownership, cleanup, overloads, syntax extensions,
  and backend adapters in user stages. Compiler interfaces must be general.
  Do not add special cases for a stage name, source path, or example.
- Keep root actions in source order. Allow independent work to run in
  parallel. Make dependencies explicit; do not add shared mutable state or
  global ordering without a semantic requirement.
- Unused features must have no runtime cost. Do not add implicit allocation,
  reference counting, checks, or cleanup to the raw seed.
- Raw-pointer examples do not prove memory safety. Validate a safety claim
  through the stage that enforces its rules and the final program behavior.

## Communication and documentation

- Use short, direct, factual language in replies, comments, and commit
  messages. Dry humor is welcome. Omit praise, filler, and unsupported claims.
- Lead with the result. State what changed, why it changed, and what was
  checked. Identify any check that was not run and the reason.
- For a concrete question, give concrete failure points: the operation,
  location, violated contract, and observed effect. Do not substitute a
  general architecture description for an explanation.
- Complete authorized work. Do not stop at a plan or ask again for permission
  that the user already gave. Report a blocker with its exact cause and the
  action needed to remove it.
- Write technical documentation in ASD-STE100. Use repository-relative
  links. Do not put local absolute paths or issue tracker IDs in repo docs.
- Do not create review reports or review documents unless the user requests
  them. Record actionable findings in Beads and report results in the reply.
  Keep necessary scratch files and generated test outputs in the ignored
  build directory. Do not commit temporary investigation artifacts. Correct
  existing product documentation when its claims or contracts need a change.
- Function and type documentation describes user-visible behavior and
  preconditions and postconditions. Local comments explain non-obvious
  intent or invariants. Do not repeat the code in comments.
- When a reviewer cannot understand an important decision, fix the code or
  add a useful comment at that location. A reply alone does not fix the code.
- Update affected specifications and guides in the same commit as a contract
  change. Before replacing a design document, write the new version and
  compare it with the old version. Remove the old text only after that check.

## C code and platform boundaries

- Use pedantic ISO C99. The build uses `-std=c99 -pedantic-errors -Wall
  -Wextra -Werror -Wstrict-prototypes -Wmissing-prototypes -Wshadow -Wvla`.
  Do not weaken these checks.
- Do not use non-standard C syntax, including `typeof`, `__attribute__`,
  statement expressions, zero-length arrays, or inline assembly. Platform
  adapters must also compile as pedantic C99.
- Minimize platform-specific code. All OS-, architecture-, and ABI-specific
  code must be isolated in separate implementation files. Use private
  platform headers only where necessary.
- Keep OS headers, feature-test macros, filesystem extensions, process
  control, dynamic loading, and native ABI adaptation in those files. Keep
  target-specific code generation in dedicated backend files.
- Shared headers expose portable C99 types. Portable compiler algorithms
  and command-line policy must not contain platform calls or OS conditionals.
  Select platform implementations in the build, not with scattered `#ifdef`
  branches. Reject unsupported profiles explicitly.
- Use the existing Makefile. Add only the platform operations that a current
  implementation needs. Do not build a portability framework for hypothetical
  ports.
- Use arenas for compiler-owned nodes, types, names, and temporary tables.
  Allocate arena blocks through the context allocator. Do not allocate and
  free individual compiler objects. Give external buffers and native
  resources an explicit owner and release path.
- No global state in the language C99 core. Keep mutable compiler state in
  explicit contexts or caller-owned objects. Do not use mutable file-scope
  variables, mutable function-local statics, or thread-local storage. Immutable
  constant tables are allowed. Separate contexts must remain safe to use
  from separate threads.
- Bound recursion on source-controlled input. Enforce the depth bound or use
  iteration. Do not rely on the host stack size.
- Keep function cyclomatic complexity at CCN 15 or less in `src/`,
  `include/`, and `runtime/`. Split functions by responsibility. Do not bypass
  Lizard with exclusions or altered counting rules.
- Never install Node.js or npm on this machine.

## Engineering discipline

- Classify the path before adding machinery: hot path, cold path, test
  helper, compatibility path, shutdown or error path, or experiment. Match
  its costs and complexity to that role.
- Treat performance, memory layout, cache behavior, synchronization, and
  security as design properties. Do not add a scan over all allocated state
  inside a frequent operation without a demonstrated need and measurements.
- Establish the trust boundary. Validate external input at public parsing
  and API boundaries. Internal consumers can trust verified compiler state.
  Fix a producer that breaks its contract instead of adding repeated checks.
- An infallible internal operation returns a value or `void`, not a failure
  status. A status must represent a possible input, allocation, I/O, or
  platform failure. Use assertions only for non-obvious invariants.
- Prefer fewer valid states. Each flag, branch, retry, or fallback must serve
  a named invariant. Do not add flags or side tables to carry facts that are
  already available in the program representation.
- Handle failures explicitly. Do not discard errors or invent fallback
  behavior. Handle a case completely or reject it with a diagnostic.
- Investigate every failure found during the task. Its age is not a reason
  to ignore it. Fix it or explain the exact mechanism and required fix.
  Do not use "known limitation" or "future work" as a substitute.
- Before substantial optimization or architecture work, establish a real
  program, a controlled baseline, and a measurable success criterion. Bound
  an unproven idea as an experiment with a stop condition.
- Before extending or landing a replacement architecture, demonstrate its
  hardest ownership boundary and final output in a real program. Review the
  evidence before adding another layer. Passing tests alone do not prove a
  performance benefit.
- Keep frontend, stage execution, emission, and target toolchain costs
  separate in measurements. Exclude target GCC compilation and linking from
  frontend results. Record the commands, inputs, build flags, and baseline.
- Preserve recorded benchmark inputs and reports. Their hashes identify the
  measured bytes. Write new evidence separately when the implementation
  changes.

## Validation

Tests must exercise production contracts. Do not weaken an interface to make
a test easier. Cover successful behavior and relevant rejection, allocation,
and cleanup paths. Do not add tests that only repeat the implementation.

Build with `make all`. Use the checks that cover the change:

| Area | Checks |
|---|---|
| Core, reader, checker, evaluator, x86 backend | `make check` |
| C backend | `make check-c` |
| Root execution and reader extensions | `make check-stage check-reader` |
| Ownership, RAII, and defer | `make check-resources check-resource-alloc` |
| Overloads and resource composition | `make check-overload check-overload-alloc` |
| Compilation program examples | `make check-examples` |
| Highlighting and editor integration | `make check-highlight check-vscode` |

A core or shared API change requires the full matrix. Run the relevant
sanitizer checks when allocation, native calls, or resource lifetimes change.
Once the required checks pass, repeat them only after a change, failure, or
new concern. A documentation-only change needs the applicable hooks and link
checks; it does not require a compiler rebuild.

The headers in `include/` define the C API. After an API change, run `make api`
and `python3 tools/api.py --check`. Do not edit generated API declarations or
the generated prelude by hand. Update stage consumers with their API changes.

## Issues and commits

The project uses `br` from beads_rust. Its data is in `../.beads`, outside this
repository. Run `br` from the repo; do not create or commit a local `.beads`.

1. Run `git status` and `br ready`. Preserve other work in the checkout.
2. Claim a matching issue with `br update <issue> --status=in_progress`.
   Create a focused issue if none matches. Track defects found during work.
3. Implement the change and run its checks.
4. Stage the intended files, then run `pre-commit run` and
   `git diff --cached --check`. If a hook changes files, inspect and stage
   them again. All hooks must pass before the commit.
5. Close completed issues with `br close <issue>` and run
   `br sync --flush-only`.
6. Commit the completed work with `git commit -s`. Keep each commit focused
   on one logical change. Use a descriptive subject.
7. Check `git status` and report the commit and validation results. Identify
   any remaining checkout changes accurately.
