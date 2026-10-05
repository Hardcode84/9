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

Four controls must produce identical target C and symbol maps: the raw stage,
the stage with opaque records and all its bodies trusted, and the generic
lookup compiled by the standalone generic stage, and that lookup compiled by
the ownership adapter with explicit body trust. Each control builds and runs
the union runtime corpus and rejects the union error corpus. The stage,
dependency implementations, and generated target use ASan and UBSan.

The compiled measurement driver times source reading, semantic checks, and
emission separately. Samples use fresh processes and a randomized paired order
on one CPU. Input file I/O, context initialization, symbol naming, teardown,
target GCC compilation, and linking stay outside these intervals. The report
contains each sample, the median trust-only/raw ratio, and its bootstrap interval.
The trust-only control measures compiler work with union body checks bypassed.
It supplies no checked-port speed result.

## Contract repairs

The typed cache lookup passes the ownership adapter's indirect type-argument
contract. The report compares its output and cost with the other controls.
Its bodies retain explicit trust in this control.

The borrowed layout client and field-access probes retain their diagnostics.
Use these inputs to repair the arena interface and continue the checked port.
Accept the production port when client bodies pass, native behavior agrees,
and the trusted boundary and restructuring burden have been reviewed. Keep
checked-port timing separate from controls that bypass body checks.
