<!-- SPDX-License-Identifier: Apache-2.0 -->

# Production-stage ownership gate

This experiment attempts a bounded port of the production union stage through
the ownership and generics checker. It preserves the stage's arena storage,
layout algorithm, reader callbacks, and generated target program.

Build the seed and native test tools. Select a CPU allowed by the host:

```sh
make all test-tools
python3 benchmarks/ownership-stage/measure.py \
    --cpu 4 --rounds 20 --output build/ownership-stage-run
```

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
5. The arena cache algorithm with its body checked.

Each build runs the union runtime corpus and rejects the union error corpus.
The stage, dependency implementations, and generated target use ASan and UBSan.

The compiled measurement driver times source reading, semantic checks, and
emission separately. Samples use fresh processes and a randomized paired order
on one CPU. Input file I/O, context initialization, symbol naming, teardown,
target GCC compilation, and linking stay outside these intervals. The report
contains each sample, the median trust-only/raw ratio, and its bootstrap interval.
The trust-only control measures compiler work with union body checks bypassed.
It supplies no checked-port speed result.

## Checked arena cache

[arena_checked.crs](arena_checked.crs) checks the depth limit, cache state,
publication order, recursive-call status, and final layout state.
[arena_provider.crs](arena_provider.crs) supplies its native boundary. The
harness replaces the production `su_layout_record` body and runs the normal
union compilation entry point with that replacement.

Native callers supply a valid stage and declaration from its context.
The owning context keeps arena allocations live through the whole call. The boundary creates opaque
scoped handles only after the existing null and allocation checks succeed.
Each handle has one pointer. Read and edit scopes permit cache growth while
excluding reclamation. The checked client reads scalar layout snapshots and
publishes updates through the provider. No pointer validity test or runtime
ownership state is added.

The raw entry retains the null-result ABI. A new layout starts with state zero;
the checked function sets state one before cache publication and recursion.
State one detects cycles; state two permits cache reuse. The recursive field
and variant algorithms call the same entry, so nested layout requests also
run the checked cache algorithm.

The checked source is a separate untrusted input. Three invalid variants must
fail: access to private fields, destruction of a borrowed parameter, and edit
calls from read authority. Runtime output must agree with the raw stage, and
the normal union error corpus must fail under ASan and UBSan.

The report separates checked source lines, provider lines, and remaining raw
functions. It times the checked cache path against the raw stage. The remaining
union algorithms still have explicit body trust; the full checked-stage timing
stays unset. Use their recorded diagnostics to continue the port.
