<!-- SPDX-License-Identifier: Apache-2.0 -->

# Generics stage

The [generics tutorial](../../examples/generics/README.md) builds two typed pairs
from one source definition. Start there for a complete compilation program.

This stage supplies type parameters through ordinary Crust calls. It parses a
definition once and creates concrete declarations for each distinct argument
list. It uses the public compiler API and has no ownership or backend dependency.

## Load and call the stage

Build the library with `make generics-stage`. A root loads
[model.crs](model.crs), [api.crs](api.crs), and the resulting
`build/crust-generics-library.so`. The model contains ordinary compilation-time
records. The API exposes these calls:

| Call | Contract |
| --- | --- |
| `gs_init(stage, allocator, namespace)` | Initialize fresh storage. Reserve a unit identity for generated declarations. |
| `gs_define(stage, source, begin, end, parameters, count, captures, capture_count)` | Copy and parse a source range. Copy parameter names and capture names. Return a definition handle. |
| `gs_apply(definition, arguments, count)` | Check or reuse a concrete instance. Arguments are pointers to complete, immutable `CrustType` facts. |
| `gs_find(instance, name)` | Return an owned declaration. Report an error if the name is absent. |
| `gs_bind(consumer, instance, name, alias)` | Bind an instance declaration under a consumer name through `crust_bind`. |
| `gs_destroy(stage)` | Release the definitions and all instance contexts. Destroy consumers first. |

Pointer/count pairs follow the C API convention: a nonzero count requires that
many valid elements. Source descriptors and type descriptors must satisfy their
public API contracts. Null type arguments and unresolved record arguments receive
diagnostics. The stage retains an error in `stage.context`; consumer binding
errors remain in the consumer context. Stop that build after an error.

The root must reserve a distinct `namespace` across all source units and other
generics stages in the linked program. Each generated declaration receives a
unique ordinal within that namespace. Defined functions and constants receive
native names of the form `crust_g_NAMESPACE_ORDINAL`. Explicit native names on
`extern` declarations remain unchanged.

## Definitions and type arguments

A definition contains ordinary seed declarations. Supply type parameter names
as strings, such as `"T"` and `"Element"`. Use these names wherever the seed
accepts a type name: record fields, parameter types, local declarations, casts,
record initializers, and layout queries. The source reader accepts these names
before their concrete types are available.

Arguments can be scalar, pointer, array, function, or record types. The seed
checks whether each use is valid after substitution. For example, `unit` can
be a function result, but a field with type `unit` is rejected. A function with
a record argument by value is rejected by the seed ABI; use a pointer argument
for that operation. Type parameters supply types; values and arbitrary source
generators remain ordinary compilation-program code.

`gs_define` copies the source bytes and parameter lists. Treat its returned
data as immutable. Construct a new definition when its source, parameters, or
captures change. Each call creates a distinct definition, even if the source
bytes match another definition.

The standalone stage checks concrete instances. It supplies no abstract
ownership proof. A definition that works for one argument can fail for another:
an addition on `T` can work for `i32` and fail for a record type. Ownership syntax
and annotations need a separate composition with the ownership reader and
checker.

## Bind external names

Each `GsBinding` supplies a source name and a complete declaration:

```crust
var capture: GsBinding = make GsBinding {
    name: "transform", declaration: transform_declaration
};
var definition: *GsDefinition = gs_define(stage, source, 0usize, (*source).size,
    &parameter, 1usize, &capture, 1usize);
```

Here `parameter` is a `*u8` containing a type parameter name. The declaration
must meet the [binding contract](../../docs/bootstrap.md#core-and-storage).
Captured functions need native link identities. The root supplies the matching
provider object or library when it links the result.

The definition owns its local names. Its external names come from explicit
captures. Each instance uses a separate context, so client aliases and helper
names cannot change those bindings. An absent external name is diagnosed when
the concrete instance is checked.

## Reuse and lifetime

The instance key contains the definition and the ordered concrete type
identities. Scalar and compound types use the seed's type equality rules.
Records use nominal declaration identities. Two aliases of one record reuse an
instance; distinct records with identical fields create separate instances.
Hash collisions receive an exact type comparison. Across the build, one nominal
identity must denote the same immutable declaration facts, including its fields
and layout. The caller supplies those facts under the core binding contract.

`stage.requests`, `stage.hits`, and `stage.specializations` expose lookup counts.
The stage caches instances within one stage lifetime. Native names follow the
root's request order. The root controls source order, backend options, and any
artifact cache. The seed currently supplies one target profile; all instances
use that profile's concrete type facts.

Definitions own their source copies. Argument types and captured declarations
remain borrowed from their providers. Keep those providers unchanged and alive
until the stage and all consumers are destroyed. An instance may use a type from
an earlier instance in the same stage. Stage destruction releases instance
contexts in reverse creation order.

## Implementation and output

The seed checker writes types, symbols, field offsets, and other resolved facts
into the AST. Each new instance therefore receives a syntax copy with fresh
checking state. Names are interned in the instance context. Substitution converts
argument types to ordinary concrete type syntax. Internal record aliases use
names that source code cannot spell, which prevents accidental name capture.
Source locations continue to identify the copied definition text.

Collection reserves record identities before layout resolution. Pointer-recursive
records and forward function references use the seed's existing rules. Inline
record cycles receive the seed diagnostic. Syntax and type traversal have an
explicit depth bound of 256.

An instance context contains ordinary checked declarations. Pass it to the
selected backend. The tutorial emits one object per instance, then links these
objects with the client. Instance tables and type arguments remain in the
compilation program; the target contains concrete records and direct functions.

Run `make check-generics` for behavior, type identity, bindings, diagnostics,
source lifetime, and allocation failure checks. The tutorial includes a
handwritten comparison program and C emission without target compilation.

Measure the compiled stage against the handwritten source with:

```sh
python3 tests/generics_cost.py --work build/generics-cost
```

The report separates definition reading, new instances, client checking,
repeated requests, and cleanup. New instances pay for syntax copies, context
storage, and concrete checks. Input file reads precede the timed phases. Native
harness preparation is recorded separately; target GCC compilation and linking
are outside these measurements. Input copies, hashes, commands, and raw results
stay in the selected build directory.
