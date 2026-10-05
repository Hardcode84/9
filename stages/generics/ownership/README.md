<!-- SPDX-License-Identifier: Apache-2.0 -->

# Generic ownership stage

This optional stage composes the source-generic reader and instantiator with
the ownership checker. The [tutorial](../../../examples/generics/ownership/README.md)
shows setup, definitions, and calls. The ordinary ownership stage and standalone
generic stage remain separate entry points.

This is a dedicated adapter under the
[source-stage composition contract](../../../docs/design.md#source-stage-composition-contract).
It combines reading, syntax substitution, ownership facts, and definition
receipts. Select this entry point for the combined rules. Loading the two
standalone packages does not perform this composition.

## Parameter contract

The declaration boundary determines each type parameter's contract:

- A parameter used by value requires an integer, `bool`, or a sized movable
  record with closed ownership. Its complete cleanup requires no domain access.
  Generic record parameters and unused parameters have this contract too.
- A function parameter used only through pointers, `read`, or `mut` requires
  a sized type. This permits opaque, stable, scoped, and domain-bound records.
  Access to a domain-bound specialization requires the function's declared
  domain permission.

Uses inside a generic type application require the value contract. Callback
parameter and result types contribute their uses too. The checker reads these
contracts from signatures before it checks bodies. Distinct parameters have
separate symbolic identities, even when a caller supplies the same type for both.

For a closed record, argument validation follows inline fields and
`owns(field: storage)` targets. A native owned scalar or pointer-shaped handle
ends that path. Stored loans, raw pointer fields, opaque storage, stable or
scoped values, and domain-bound records fail the closed-value contract.

An indirect parameter keeps its weaker contract in calls to other generics.
Passing it to a generic that requires closed ownership fails. Borrowing an
opaque value preserves its private representation and source lifetime. Raw
pointer use still requires the ordinary pointer contracts or root trust.

With a closed-value parameter, a generic body can transfer, borrow, return,
and drop its value. It can
store it in another declared record. Construction of an unknown parameter type,
field selection on it, arithmetic, casts, and `offsetof` on it fail. `sizeof`
and `alignof` produce a symbolic layout query whose value is supplied during
specialization. Owning arrays require aggregate ownership state; this profile
accepts record storage and rejects owning array interfaces.

## Compilation flow

```mermaid
flowchart TD
    A[Read source and annotations] --> B[Check each generic definition with symbolic parameters]
    B --> C[Instantiate concrete syntax and annotations]
    C --> D[Lower concrete resource cleanup and check seed types]
    D --> E[Validate argument contracts and check ordinary bodies]
    E --> F[Emit target code]
```

The abstract check operates on source types and ownership facts. Parameter
atoms have no seed declaration, field list, concrete type, size, or layout.
Each function body is checked once with fresh atoms for its parameters.
Callees contribute their substituted interfaces. Their bodies receive their
own independent checks.

The reader and clone callbacks preserve resource destructors, owned fields,
effects, return origins, native resource contracts, access blocks, and trust.
Domain membership can name a generic record family. All instances of that
family inherit the declared domain.

After argument validation, a concrete function instance receives the checked
definition's receipt. The checker validates each concrete borrow signature's
domain permissions. The concrete seed checker still checks its types, layout,
and lowered cleanup. Explicit trust and imported concrete interfaces use
separate maps. A failed body check cannot grant trust.

## Interfaces

`ownership_generics_program` uses the ordinary `CrustBuild` request and a list
of root-selected trusted sources. It supports a target suffix in the root
source and extra input paths. The compilation program selects input files;
generic declarations register themselves during reading.

The [lower-level interface](extension.crs) uses `OgProgram`. Load the reader,
resource, ownership, and generic model declarations, then this stage's
[model](model.crs) and interface:

1. Call `og_init` with an allocator and a fresh declaration namespace.
2. Call `og_read` or `og_read_range` for each source. The stage captures the
   source bytes. Select trust with that read operation.
3. Call `og_check`. The checked seed program is in `generics.context` and its
   cleanup plan is in `resources`.
4. Emit with the resource stage's body emitter. Call `og_destroy` after all
   consumers have finished.

`og_prove` checks generic definitions and records their receipts. It permits
additional source inputs before concrete lowering. Parsed declarations,
annotations, source snapshots, and recorded receipts must remain unchanged.
Domain membership becomes fixed with the receipt, including a record's
domain-free status. Additional sources must preserve that membership.
To transform a definition, supply new source and check it as a new definition.
Keep providers alive while the program uses their data.

## Independent libraries

`og_library_publish` checks a closed provider and writes an authenticated
source artifact. `og_library_import` restores it into a fresh program. Read
client sources afterwards; their payload types can be absent at publication.
The original provider paths are retained for diagnostics and are never opened
during import.

The artifact contains captured definition bytes, source identities, parameter
declarations, annotations, and per-declaration checked or trusted status. Its
receipt binds those bytes and the loaded checker image. Publication requires
every external source name to have a provider binding. Duplicate declarations
are rejected on import, so a client cannot replace a bound helper.

An import restores definition receipts and specializes new types without
repeating the generic body proof. The root retains the receipt and supplies a
trusted absolute cache directory, as for ordinary ownership libraries. Source
artifacts contain the definitions needed to generate new instances; they can
be used without a previously emitted specialization object.

## Validation

Run `make check-ownership-generics`. It covers generic body checks, concrete
argument validation, cleanup, loan origins, source-independent imports,
allocation failure, and native trusted-container behavior. Run the ordinary
`check-ownership` and `check-generics` targets for their separate interfaces.

Compiler preparation, frontend checks, emission, and target compilation have
separate measurement boundaries. Keep raw reports and captured inputs under
ignored `build/`.

```sh
python3 tests/ownership_generics_cost.py --work build/ownership-generics-cost
```

The harness compares the container with its handwritten specializations. It
records parsing, abstract proof, specialization, concrete lowering and checks,
argument validation, ordinary ownership checks, emission, and teardown. It also
records proof-body counts, instance reuse, retained arena storage, and separate
proof workspace storage. Preparation and input I/O have separate records.
Target GCC compilation and linking run outside the frontend measurements.

The comparison checks record layouts and emitted operations. Before-and-after
verification output must have identical C and symbol buffers. Captured inputs,
hashes, commands, and raw measurements remain in the selected build directory.
