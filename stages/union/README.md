<!-- SPDX-License-Identifier: Apache-2.0 -->

# External tagged unions

This stage adds `union`, `construct`, and `match` through the Crust reader hooks.
The [tutorial](../../examples/union/README.md) shows setup, definitions, and use.
Prepare this package with the [shared stage loader](../build/README.md). Run `make check-union` for
construction, layout, evaluation order, exhaustive matching, rejection tests,
and output from both backends. `make check-union-alloc` repeats these checks
with the stage, core, and evaluator built under ASan and UBSan.

## Source contract

```text
union Name { Variant: Type; ... }
construct Name.Variant(place [, payload]);
match Name(expression) { Variant[(binding)] { statements } ... }
```

These three words select extension productions when the stage reads a declaration
or statement. Names and types use the existing reader grammar. Each union must
have at least one variant, with distinct variant names. Each match must list all
variants exactly once. A binding is optional for a stored payload and forbidden
for `unit`. The seed checks the destination, payload, scrutinee, and arm bodies
after lowering. Every declared payload type is resolved, including payloads
in unused variants.

Construction evaluates the destination place once, then the payload once. It
copies the payload and writes the tag last. Matching copies the scrutinee once,
selects one arm, and copies that arm's payload into its local binding. Arm order
can differ from declaration order. Exhaustive returning arms satisfy the seed's
return-path check. `break` and `continue` keep their enclosing loop targets.

Union values use the seed's aggregate rules. Pass them through pointers; function
results are scalar or unit. Construct storage before reading or copying its
value. Reconstruction replaces the stored value. The caller must release any
external resource held by the old payload. Raw casts, invalid pointers, and
uninitialized reads can violate these preconditions. The stage adds no lifetime
analysis or cleanup. Composition with another checker requires that checker to
handle the generated storage casts and payload copies under its own contracts.

## Storage and lowering

A lowered union is an ordinary record. It contains overlapping payload storage
and a `u32` tag. Variant tags start at zero in declaration order. Storage has the
maximum payload size and alignment, rounded to at least four-byte alignment.
The carrier uses an array of `u32` or `u64`; the tag follows the carrier. The
record has ordinary trailing alignment padding. A union with only `unit`
variants contains just the tag.

Generated field and local names cannot be spelled as source identifiers. Payload
access uses existing address, cast, and dereference nodes. No allocation, side
table, or pointer validity check appears in the target program. The backend may
retain ordinary copies and tag comparisons. This representation is specific to
this stage and the current target profile; it is not a C union ABI.

The stage computes carrier sizes from payload syntax and the context's scalar
layouts. By-value dependencies use a per-context layout cache. A by-value cycle,
size overflow, or excess nesting produces a diagnostic. Pointer cycles are
permitted. Payload types must be seed types or union declarations in the same
stage. Layout and lowering recursion are bounded at 256 levels; generated
conditional nesting also counts toward the seed's depth bound.

## Checked implementation boundary

The package compiles its algorithms through the ownership and generics stage.
Four files have checked bodies:

| Source | Responsibility |
|---|---|
| [read_checked.crs](read_checked.crs) | Union grammar, variant limits, construction arguments, and match arms |
| [layout_checked.crs](layout_checked.crs) | Depth, cache state, cycle rejection, array sizes, layout folds, alignment, overflow, and storage selection |
| [lower_checked.crs](lower_checked.crs) | Operation dispatch, payload rules, evaluation order, arm coverage, branch order, and bounded statement traversal |
| [passes_checked.crs](passes_checked.crs) | Input iteration, layout and lowering passes, payload resolution, seed checks, and output mode selection |

These files are untrusted package inputs. Invalid field access, borrowed-value
consumption, cursor mutation through `read`, or insufficient edit authority
stops normal package preparation. The typed layout-cache lookup is a generic
function instantiated for the map's result type.

The owning context keeps arena storage live until all compiler operations
finish. The provider exposes opaque handles under the `CompilerArena` domain.
A handle cannot escape its access scope. Cursor mutation requires `mut`;
observing a handle requires `read`. Allocation and AST writes require edit
authority. The native entry owns the context reference and driver frames across
the checked call. Destruction occurs after the call returns.

The explicitly trusted code has these responsibilities:

- [model.crs](model.crs) initializes raw state and allocates nodes.
- [read.crs](read.crs) adapts reader callbacks and token operations, allocates
  parse results, and links variants and arms.
- [layout_handles.crs](layout_handles.crs) and [layout.crs](layout.crs) adapt
  type lookup, arena maps, layout cursors, diagnostics, and storage fields.
- [nodes.crs](nodes.crs) allocates typed AST fragments and writes their fields.
- [lower.crs](lower.crs) adapts raw operations to checked calls, provides name
  lookup and cursors, and links the selected branches.
- [passes.crs](passes.crs) provides declaration cursors and seed API calls.
- [program.crs](program.crs) owns the native call frames, copies and releases
  file buffers, and calls the backend.

Reader and backend dependencies also have explicit raw-source trust. The
provider must keep every exposed address live, preserve node kinds and list
links, and retain allocation errors. Ownership checking cannot prove the
provider's pointer operations. The measurement counts all provider files and
raw model functions, including small adapters.

Declaration, layout, and location handles contain live non-null pointers.
A type cursor stays on a live syntax node. Its step advances to an array base
or reads a leaf. Field and variant layout steps return scalar snapshots;
zero alignment means exhaustion or failure, distinguished by the context
error. Checked code controls recursion, arithmetic, and storage selection.

AST fragment and parser result handles can be empty. Their operations remain
valid after allocation failure. Publication requires an error-free context.
The checked parser controls token order and limits; the reader provider handles
seed grammar atoms. Match coverage validates names and counts before branch
construction. Its cursor retains the current diagnostic location. Layout keeps
an arena-owned variant-name map for construction and match lookup. Declaration
cursors skip empty source units. The checked passes also resolve payloads in
unused variants.

These contracts add no runtime ownership metadata or validity checks. They do
add source interfaces and compiler work. The
[measurement harness](../../benchmarks/ownership-stage/README.md) counts that
cost and compares target bytes, diagnostics, and execution against the raw
control. It includes a compiled provider and the actual checked algorithms.

The package uses source-owned compiler selection and caching. Make builds the
seed and test fixtures. The checker and backend bootstrap through package
dependencies.

## Compilation API

[api.crs](api.crs) declares `union_program`. It accepts a `CrustBuild` with an
empty initialized context, an optional source range, and C-driver arguments.
Keep the source bytes live until context destruction. Diagnostics stay in the
context; the return value is the build status.

The library includes the C backend adapter. Its lower-level source interface is:

1. Include [sources.crs](sources.crs) in a package. It selects the checked
   checked sources, their trusted provider, and the ownership compiler.
   Export the `su_` entry points that your consumer requires.
2. Call `su_init` with stage storage and an empty context.
3. Call `su_read` for each declaration source range.
4. Call `su_check` once. This collects declarations, lays out union storage,
   lowers extension statements, resolves types, and checks bodies.
5. Pass the checked context to a backend or evaluator. Destroy the context after
   all consumers finish.

`SuStage.hooks` can participate in a reader-hook chain. Semantic composition
requires an adapter under the
[source-stage composition contract](../../docs/design.md#source-stage-composition-contract).
The supplied stage accepts seed payload types and other unions. There is no
supplied adapter for generic or ownership-checked payloads. Such an adapter must
normalize payload types before layout and check transfer, replacement, and
cleanup before lowering erases the active variant operations. Reader-hook order
alone cannot establish those contracts.

The C99 seed has no union-specific type, keyword, node, or backend rule. The stage
uses context-allocated extension kinds, reader hooks, maps, arenas, and ordinary
syntax nodes. [The token-layout measurement](../../benchmarks/tagged-union/README.md)
ports the production reader in an isolated build and compares behavior and cost.
