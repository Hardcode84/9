<!-- SPDX-License-Identifier: Apache-2.0 -->

# Production-stage ownership gate

This experiment measures the production union stage through
the ownership and generics checker. It preserves the stage's arena storage,
layout algorithm, reader callbacks, and generated target program.

Build the seed and native test tools. Select a CPU allowed by the host:

```sh
make all test-tools
python3 benchmarks/ownership-stage/measure.py \
    --cpu 4 --rounds 20 --output build/ownership-stage-run \
    --raw-stage build/raw-control
```

Select preserved raw `layout.crs`, `nodes.crs`, `lower.crs`, `read.crs`, and
`program.crs` implementations as the control. Keep these files under `build/`
with their capture metadata.
The harness records their exact bytes and hashes. It uses current reader and
backend dependencies for both candidates.
Use a new output directory for each run. The script captures source bytes,
hashes, commands, toolchain identity, diagnostics, timings, and generated code
under that directory. Results stay outside version control.

## Boundary under test

The union stage stores AST pointers in records and hash tables. Its layout
pass publishes a cached layout before recursive calls, then completes that
layout and changes the declaration's storage fields. The owning context keeps
all of these allocations live.

The experiment obtains source lists from the production package. It uses the
seed reader to locate declarations and bodies. The reader and C backend stay
behind native interfaces, with their real implementations linked into the
test executable. Trust counts distinguish those dependencies from the union
stage being evaluated.

The generated candidates test these changes:

1. Check the source with its original record and function interfaces.
2. Mark records with pointer, function, or array fields as opaque. Explicitly
   trust those representations. Check each union function separately while
   trusting the remaining functions. Retain each first diagnostic.
3. Change `su_layout_record` to take `mut SuStage` and `read CrustDecl`.
   Preserve its control flow and adapt its raw call arguments. Check this
   function against the same native and stage interfaces. Also test access to
   the stage's scalar serial field through a shared borrow.
4. Replace the layout cache's pointer cast with a typed generic lookup. Check
   `SuLayout` as its type argument, including with explicit body trust.

The report counts opaque annotations, generic parameters and applications,
borrow parameters, and physical function-body lines covered by trust. It
records the attempted restructuring. The tutorial client budgets exclude
provider code; they supply no numerical budget for this compiler stage.
The per-function checks measure the selected interfaces. They do not establish
the minimum trust possible after a different API design.

## Controls and costs

Five builds must produce identical target C and symbol maps:

1. The raw stage.
2. Opaque records with all stage bodies trusted.
3. Typed cache lookup through standalone generics.
4. Typed cache lookup through ownership, with all stage bodies trusted.
5. The production stage with its grammar, layout, lowering, and pass bodies checked.

Each build runs the union runtime corpus and rejects the union error corpus.
The stage, dependency implementations, and generated target use ASan and UBSan.

The compiled measurement driver times source reading, semantic checks, and
emission separately. Samples use fresh processes and a randomized paired order
on one CPU. Input file I/O, context initialization, symbol naming, teardown,
target GCC compilation, and linking stay outside these intervals. The report
contains each sample, the median trust-only/raw ratio, and its bootstrap interval.
The trust-only control measures compiler work with union body checks bypassed.
It supplies no checked-port speed result.

## Checked production code

The production package selects four checked inputs: grammar, layout, lowering,
and pass control. The [stage reference](../../stages/union/README.md#checked-implementation-boundary)
lists each file and its contract. The harness uses these exact files as a
separate untrusted input. It selects the same provider implementations as the
normal package.

Opaque scoped handles keep arena addresses behind typed interfaces. Mutable
cursors express iteration; checked code controls token order, pass order,
recursion, layout arithmetic, construction, and match coverage. The retained
variant-name map serves layout, construction, and matching. The provider
performs reader calls, type adaptation, allocation, map access, AST writes,
cursor steps, native calls, and file-buffer release. Model initialization also
retains explicit trust. These responsibilities remain in the trust count.

The report separates checked source lines, borrow and effect annotations,
provider lines and functions, model lines, and dependency source lines. Small
pointer adapters increase source size. A checked algorithm count alone is
insufficient to assess this cost. The raw-interface rejection inventory and
the production port counts are separate report entries.

Invalid checked clients must fail for private representation access, destruction
of a borrowed value, mutation through a shared borrow, and insufficient edit
authority. Probes cover layout, AST building, parser state, branch chains,
declaration cursors, and the driver. The package tests apply invalid edits to
the actual checked files and require normal bootstrap to fail.

Every native control must emit the same target C and symbol map, execute the
union corpus, and reject the complete error corpus under ASan and UBSan.
The corpus includes many variants, reversed arm order, payload replacement,
recursive storage, malformed grammar, and excessive generated lowering depth.
The normal stage tests also cover multiple inputs, empty units, input errors,
library output, evaluator execution, and allocation failure.

The report includes the complete port's frontend time and its ratio to the raw
control. This measures the implementation with its explicit provider trust.
It does not assert that provider pointer operations were checked. Per-phase
medians separate reading, checking, and emission. GCC and linking remain outside
the intervals. Package bootstrap and cache validation are separate costs.

Use the measured source growth, trust burden, and frontend costs together when
assessing this design for another stage. The port establishes a working arena
boundary. A performance improvement requires its own measured comparison.

## Compare a frontend change

Keep the baseline capture. Run `measure.py` into a new candidate directory.
Then use both compiled drivers on the baseline's exact source bytes:

```sh
python3 benchmarks/ownership-stage/compare.py \
    --baseline build/ownership-stage-baseline \
    --candidate build/ownership-stage-candidate \
    --output build/ownership-stage-comparison --cpu 4 --rounds 40
```

The comparison verifies driver hashes, copies the input bytes, randomizes the
paired process order, and checks every emitted C file and symbol map against
the baseline. Its report includes phase medians, paired frontend ratios,
bootstrap intervals, commands, and hashes. This isolates a compiler change from
changes to the program being compiled. Use `measure.py` results for the native
execution and rejection checks.
