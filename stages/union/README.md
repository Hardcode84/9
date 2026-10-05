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

The package checks [layout_checked.crs](layout_checked.crs) with the ownership
and generics stage. This code handles cache publication and cycle detection,
array traversal and size limits, field and variant loops, alignment, overflow,
storage carrier selection, and the final tag size. The package treats this file
as an untrusted input.
An invalid field access or borrow operation stops normal stage preparation.

[lower_checked.crs](lower_checked.crs) checks construction and match-arm rules.
Construction evaluates the destination once, writes the payload, then writes
the tag. A match binding copies its payload before the arm body starts. The
checked code rejects a payload for a unit variant, a missing required payload,
and a binding for a unit arm. It also builds each arm's tag comparison.

Before it builds match branches, checked code walks the arm names. Each name
must identify a declared variant and occur once. The final count must equal
the union's variant count. The checked lowering walk then visits each lowered
statement's body, alternative, and next sibling, with a depth limit of 256.

[layout_handles.crs](layout_handles.crs) and [layout.crs](layout.crs) are the
explicitly trusted provider. They handle arena pointers, cache lookup and
insertion, type lookup, cursor steps, diagnostics, and AST storage construction.
The typed cache helper is a generic function. [nodes.crs](nodes.crs) is the
trusted AST builder. [lower.crs](lower.crs) bridges raw syntax to checked
lowering and retains map access, operation dispatch, and branch linking.
Layout retains its variant-name map for construction and match lookup. The
map entries already belong to the arena; each union now keeps their map header.
The reader, driver, and backend also have explicit raw-source trust.

The owning context keeps arena storage live through a layout request. Opaque
scoped handles contain live declaration, layout, and location pointers.
Read and edit access permit allocation while excluding reclamation. Field and
variant steps return scalar size and alignment snapshots. Zero alignment ends
these cursors; the context diagnostic distinguishes failure from exhaustion.
A type cursor stays on a live syntax node. A step advances to an array's base
or reads a leaf type. Checked recursion controls depth and array multiplication.
Checked code selects diagnostics and computes the storage plan. The provider
attaches diagnostics to source locations and writes the planned AST fields.
The provider must preserve these contracts. These annotations add no runtime
ownership metadata or validity checks.

The AST builder uses scoped name, type, expression, and statement handles.
Each node handle contains one arena pointer. An empty handle represents an
absent fragment or a failed allocation. Constructors retain the context's
allocation diagnostic. The entry bridge publishes a statement only when the
context has no errors. The builder keeps pointer writes behind typed
interfaces. These interfaces add provider code; that code remains part of the
trusted implementation and is included in the measurement.

Match coverage uses a scoped arm cursor and a set of names seen in that match.
An arm step advances the cursor and keeps the arm's diagnostic location.
Statement handles also act as cursors: an empty statement has empty children
and remains empty when advanced. Advancing a cursor requires `mut`; reading
its children or testing exhaustion requires `read`. The pointer operations
stay in the provider. The checked functions control iteration and rejection.

The package uses the shared source-owned compiler selection and cache. Make
builds the seed and test fixtures. The checker and backend bootstrap through
package dependencies. The [measurement harness](../../benchmarks/ownership-stage/README.md)
compares generated target bytes, rejection behavior, and frontend costs.

## Compilation API

[api.crs](api.crs) declares `union_program`. It accepts a `CrustBuild` with an
empty initialized context, an optional source range, and C-driver arguments.
Keep the source bytes live until context destruction. Diagnostics stay in the
context; the return value is the build status.

The library includes the C backend adapter. Its lower-level source interface is:

1. Include [sources.crs](sources.crs) in a package. It selects the checked
   layout sources, their trusted provider, and the ownership compiler.
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
