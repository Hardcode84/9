<!-- SPDX-License-Identifier: Apache-2.0 -->

# Production-stage ownership gate

This experiment attempts a bounded port of the production union stage through
the ownership and generics checker. It preserves the stage's arena storage,
layout algorithm, reader callbacks, and generated target program.

Build the seed and native test tools. Select a CPU allowed by the host:

```sh
make all test-tools
python3 benchmarks/ownership-stage/measure.py \
    --cpu 4 --rounds 20 --output build/ownership-stage-run \
    --raw-layout build/raw-control/layout.crs
```

Select a preserved raw layout implementation as the control. Keep it under
`build/` with its capture metadata. The harness records its exact bytes and
hash. It uses current reader and backend dependencies for both candidates.
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
5. The production layout arithmetic and field/variant loops with their bodies checked.

Each build runs the union runtime corpus and rejects the union error corpus.
The stage, dependency implementations, and generated target use ASan and UBSan.

The compiled measurement driver times source reading, semantic checks, and
emission separately. Samples use fresh processes and a randomized paired order
on one CPU. Input file I/O, context initialization, symbol naming, teardown,
target GCC compilation, and linking stay outside these intervals. The report
contains each sample, the median trust-only/raw ratio, and its bootstrap interval.
The trust-only control measures compiler work with union body checks bypassed.
It supplies no checked-port speed result.

## Checked production layout

The harness compiles the production
[checked layout](../../stages/union/layout_checked.crs),
[handle provider](../../stages/union/layout_handles.crs), and
[pointer adapter](../../stages/union/layout.crs). The checked source is a
separate untrusted input. The normal union package uses the same sources and
trust selections through its source-selected compiler.

The checked code handles depth, cache state, publication order, array size,
field and variant loops, alignment, overflow, and tag size. The provider owns
raw arena access, type lookup, cursor steps, AST storage construction, and
native entry points. Other union functions retain explicit trust. The report
separates checked lines, provider lines, and raw functions outside layout.
Provider counts include the wrappers required to expose the arena operations.
A smaller checked function does not imply a smaller trusted implementation.

Three invalid checked clients must fail: private field access, destruction of
a borrowed parameter, and edit calls from read authority. Each compiler must
produce the same target C and symbol map, execute the union corpus, and reject
the error corpus under ASan and UBSan. The package tests also apply these
invalid edits to the production source and require normal bootstrap to fail.

The report gives the checked-layout/raw frontend ratio. The full-stage checked
timing stays unset because the reader, lowering, and provider bodies retain
explicit trust. Target GCC compilation and linking remain outside the timed
intervals. Package bootstrap and cache validation are separate from this
native frontend measurement.
