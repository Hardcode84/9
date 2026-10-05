<!-- SPDX-License-Identifier: Apache-2.0 -->

# Generics stage

The optional [ownership composition](ownership/README.md) adds abstract payload
contracts, generic cleanup, and ownership-checked clients to the source interface.

The [generics tutorial](../../examples/generics/README.md) builds two typed pairs
from one source definition. Start there for a complete compilation program.

The stage reads generic declarations and creates concrete declarations for each
ordered type argument list. It uses the external reader and the public compiler
API. The C99 seed remains unchanged. Ownership checks and backend selection are
separate stages.

## Source declarations

Declare type parameters beside each record or function:

```crust
record Pair!(Element) { first: Element; second: Element; }
fn first!(Element)(pair: *Pair!(Element)) -> *Element {
    return &(*pair).first;
}
```

`Element` is an ordinary identifier bound by the declaration's `!(...)` list.
Use `Pair!(i32)` as a type and `first!(i32)(&pair)` as a call. Multiple parameters
use `!(Key, Value)`. Argument order must match parameter order. Each declaration
has its own parameter scope. Parameters must have distinct names and cannot
share the declaration name or a local value name. Fields have their own scope.

The grammar accepts explicit type arguments. Parentheses are required; a final
comma is permitted. Types include scalar, pointer, array, function, record, and
nested generic record types. A generic function application is a function value;
ordinary calls, indexing, and field selection follow the usual expression rules.
Default arguments, inferred arguments, value parameters, constraints, parameter
packs, generic extern functions, and overload selection receive diagnostics.

A source program is one explicit set of input files and imported bindings. All
input files share a top-level scope. Generic declarations are found by name in
that scope. The root selects inputs; each source declares its own generics.
Top-level names must be unique, and local names cannot hide them. Free names in
a generic body resolve in this fixed input environment.

## Compile source inputs

Build the library with `make generics-stage`. Load [source_model.crs](source_model.crs),
[source_api.crs](source_api.crs), and `build/crust-generics-library.so` in the root.

| Call | Contract |
| --- | --- |
| `gp_init(program, allocator, namespace)` | Initialize fresh storage. Reserve a distinct unit identity for generated declarations. |
| `gp_read(program, source)` | Copy and parse one complete source. Call once for each selected input before lowering. |
| `gp_lower(program)` | Close input and replace applications with ordinary concrete declarations. Repeated calls reuse that result. |
| `gp_check(program)` | Lower if needed, then collect, resolve, and check concrete declarations and all supplied type arguments. |
| `gp_find(program, name)` | Return a checked ordinary declaration. Report an error when absent. |
| `gp_destroy(program)` | Release parsed sources and generated declarations. Destroy consumers first. |

Use `program.context` for output declarations and backend input. Bind complete
external declarations into this context with `crust_bind` before lowering. Their
providers must remain immutable and live until all consumers are destroyed.
Source identities and imported identities must be distinct from `namespace`.
Input errors are retained in `program.syntax`; lowering and checking errors are
retained in `program.context`. Stop the build after either context reports an
error. Read all inputs before the first `gp_lower` or `gp_check` call.

Every ordinary declaration is checked. Each generic is instantiated when used.
An unused generic function contributes no target declaration. The seed checks
each instantiated body with its concrete types. An operation can therefore work
for one type and fail for another. Every supplied type argument is checked even
when its parameter is unused by the body. These checks establish concrete seed
typing; the standalone stage has no abstract ownership contract checker.

Forward references and pointer-recursive records use the seed's declaration and
layout rules. Inline layout cycles fail. Parsing, syntax traversal, type hashing,
and specialization dependencies have explicit depth bounds of 256. Each argument
list must expand to at most 65,536 type syntax nodes. This bound includes repeated
uses of shared subtypes and applies before seed type resolution.

The stage copies each input once. It records parameter lists during parsing and
substitutes types during lowering. Each new instance enters the reuse table
before its body is copied. A work list expands referenced instances. Recursive
references can then select an existing declaration. All output declarations
enter one seed context before type resolution.

The source cache key consists of the definition and its ordered normalized type
arguments. Record identity is nominal. Imported aliases of the same record select
one instance; distinct records with equal layout select different instances.
Hash matches receive an exact structural comparison. `program.requests`,
`program.hits`, and `program.specializations` report cache use. These tables and
type arguments exist only during compilation.

Generated functions have native names `crust_g_NAMESPACE_ORDINAL`. Ordinary
functions and constants start private, with empty link names. A driver can assign
native export names before emission. Extern declarations retain their specified
names. Pass the complete checked context and selected entry to either backend.
The tutorial emits one concrete translation unit.

## Procedural definitions

Compilation programs can also construct definitions and request instances through
ordinary calls. This interface accepts complete checked type facts and explicit
captures. It uses the same syntax-copy operations as the source interface.

### Load and call the procedural stage

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

### Definitions and type arguments

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

### Bind external names

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

### Reuse and lifetime

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

### Procedural output

The seed checker writes types, symbols, field offsets, and other resolved facts
into the AST. Each new instance therefore receives a syntax copy with fresh
checking state. Names are interned in the instance context. Substitution converts
argument types to ordinary concrete type syntax. Internal record aliases use
names that source code cannot spell, which prevents accidental name capture.
Source locations continue to identify the copied definition text.

The source interface exposes `program.clone_kind(clone, kind)`. When standard
cloning encounters an extension kind, this callback must return the kind
reserved for that extension in the destination context. Return zero for an
unhandled kind. A missing callback or an unhandled kind produces a diagnostic
at the source node. Seed kinds are copied directly. The callback covers type
syntax, expressions, and statements; declaration kinds remain seed kinds.
The ownership adapter uses it to map resource kinds between its source and
concrete contexts. Side tables must use the same mapping for retained modes.

Collection reserves record identities before layout resolution. Pointer-recursive
records and forward function references use the seed's existing rules. Inline
record cycles receive the seed diagnostic. Syntax and type traversal have an
explicit depth bound of 256.

An instance context contains ordinary checked declarations. Pass it to the
selected backend. A driver can emit one object per instance and link it with the client. Instance tables and type arguments remain in the
compilation program; the target contains concrete records and direct functions.

## Checks and measurements

Run `make check-generics` for behavior, type identity, bindings, diagnostics,
source lifetime, and allocation failure checks. The tutorial includes a
handwritten comparison program and C emission without target compilation.

Measure the compiled stage against the handwritten source with:

```sh
python3 tests/generics_cost.py --work build/generics-cost
```

The report separates source copy and parsing, lowering and instance reuse,
concrete seed checks, and cleanup. It compares the same work with the handwritten
tutorial source. Input file reads and native harness preparation are recorded
separately. Target emission, GCC compilation, and linking are outside these
measurements. Input copies, hashes, commands, and raw results stay in the selected
build directory.
