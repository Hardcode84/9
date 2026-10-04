<!-- SPDX-License-Identifier: Apache-2.0 -->

# Generics through compilation programs

Date: 2026-10-04. Status: design with a standalone implementation.
The [generics stage](../../stages/generics/README.md) implements source capture,
type substitution, isolated concrete checking, and instance reuse. The
[tutorial](../../examples/generics/README.md) gives its current API.
The ownership composition and abstract-checking APIs below remain proposals.
The [seed specification](../crust0-spec.md) and
[ownership contract](../ownership-model.md) define their current behavior.

## Decision

Make a generic definition a value in the compilation program. Ordinary Crust
functions construct definitions, inspect available types, select implementations,
and request instances. The root selects the generics stage and its checking
policy through ordinary calls.

A definition contains source declarations, explicit parameters, and bound
external names. Freeze these inputs before checking. A checked definition can
then be instantiated with arguments that satisfy its parameter contracts.
Specialization substitutes those arguments and produces concrete declarations.

Keep three responsibilities separate:

| Component | Responsibility |
| --- | --- |
| Generics stage | Parameter binding, definition identity, substitution, instance reuse, and generated names |
| Ownership stage | Initialization, moves, loans, cleanup, and permission requirements |
| Composition library | Check ownership under abstract parameters; validate arguments; preserve contracts and proof origin through specialization |

All three are ordinary Crust libraries. Basic ownership checking can run without
loading generics. The C99 seed keeps its concrete type system. Existing backends
receive concrete declarations.

The root's calls establish this flow for an ownership-checked configuration:

```mermaid
flowchart LR
    Root[Ordinary compilation code] --> Definition[Fixed definition and bindings]
    Definition --> Policy[Abstract checking or explicit provider trust]
    Policy --> Arguments[Argument contract checks]
    Arguments --> Instance[Reuse or specialize]
    Instance --> Seed[Concrete layout and seed checks]
    Seed --> Backend[Selected backend]
```

## What the language studies establish

### D

D executes ordinary functions at compile time after semantic checking. Its CTFE
rules restrict what those functions can do. D also retains a separate template
system: template bodies receive semantic analysis at instantiation. Equal
normalized arguments identify the same template instance, including across
modules. Take ordinary compilation functions and predictable instance reuse.
Crust's source runner already supplies the place where those functions execute.
[D CTFE](https://dlang.org/spec/function.html#interpretation),
[D templates](https://dlang.org/spec/template.html#common_instantiation).

D template mixins can acquire bindings from their insertion scope. Crust should
bind a definition's free names when it is constructed. An external dependency
must be captured explicitly or declared as a parameter. This makes the meaning
independent of unrelated names at an instantiation site.
[D template mixins](https://dlang.org/spec/template-mixin.html).

### Rust

Rust checks generic code with the bounds declared for its parameters, then
monomorphizes code for concrete arguments. A destructor cannot require stronger
bounds than its containing generic type. These are useful boundaries for Crust:
parameter facts must justify the body, and a container must account for payload
cleanup. Use explicit facts and bindings for the first implementation.
[Rust bounds](https://doc.rust-lang.org/reference/trait-bounds.html),
[parameter environments](https://rustc-dev-guide.rust-lang.org/typing-parameter-envs.html),
[monomorphization](https://rustc-dev-guide.rust-lang.org/backend/monomorph.html),
[destructor bounds](https://doc.rust-lang.org/stable/error_codes/E0367.html).

### Zig

Zig functions can accept and return types, including constructed record types.
Its compile-time parameters support ordinary control flow. Generic calls use
compile-time duck typing: the compiler checks operations for concrete arguments.
The reference also shows repeated type-factory calls producing the same type.
This is useful programming style, but it supplies a different checking boundary
from a reusable abstract ownership proof.
[Zig 0.15.2 reference](https://ziglang.org/documentation/0.15.2/#Compile-Time-Parameters),
[generic data structures](https://ziglang.org/documentation/0.15.2/#Generic-Data-Structures).

Zig's compiler keeps function-instance interning separate from memoized
compile-time calls. Crust needs the same conceptual distinction: instance reuse
has a defined key; root functions can perform visible I/O and must retain their
ordinary execution behavior.
[Zig instance implementation](https://github.com/ziglang/zig/blob/0.15.2/src/InternPool.zig#L9007).

### Jai

Jonathan Blow's LambdaConf 2025 demonstration shows a replaceable compiler
control program, workspaces, compiler messages, and execution during compilation.
He distinguishes external metaprograms that can overlap compiler work from
embedded execution that blocks dependent work. His specialization report also
distinguishes finding an existing instance from generating a new one: matching
still costs time.
[Original demonstration](https://www.youtube.com/watch?v=IdpD5QIVOKQ),
[transcript used for inspection](https://youtubetotranscript.com/transcript?current_language_code=en&v=IdpD5QIVOKQ).

This is evidence from a public demonstration, not a complete Jai specification.
It does not establish reusable ownership proofs or persistent specialization
cache rules. For Crust, keep compiler control in ordinary source and expose the
cost of definition checking, instance lookup, and specialization separately.
No compilation-speed result is inferred from the demonstration.

### Related work

Terra makes types ordinary values in its host language and uses explicit
memoization for type factories. Its API also supports incomplete recursive
records. Crust can use ordinary descriptor values and instance interning within
its existing language.
[Terra types and memoization](https://terralang.org/api.html).

Research on ML modules explains why type identity must account for the inputs
and effects of a factory. A function that creates fresh state cannot safely be
reused merely because its visible type argument is unchanged. Crust avoids that
question for automatic reuse: only frozen definitions have interned instances.
Arbitrary root calls retain source-order effects.
[Rossberg, Russo, and Dreyer, F-ing Modules](https://people.mpi-sws.org/~rossberg/f-ing/).

## The programming model

### Proposed source syntax

Status: selected syntax design. The implemented standalone stage currently
exposes the procedural API in the [stage reference](../../stages/generics/README.md).
The reader and application lowering described here require implementation.

Declare parameters at each generic declaration:

```crust
record Pair!(Element) {
    first: Element;
    second: Element;
}

fn pair_swap!(Element)(pair: *Pair!(Element)) -> unit {
    var saved: Element = (*pair).first;
    (*pair).first = (*pair).second;
    (*pair).second = saved;
}
```

The declaration's `!(Element)` list binds `Element` as a type parameter in that
declaration. Parameter names are ordinary identifiers: `T`, `Element`, and
`Payload` follow the same rule. `record Entry!(Key, Value)` declares two ordered
parameters. Names must be distinct within the parameter list. Reject a parameter
that collides with another name declared in the same declaration scope.

The record and function have separate parameter scopes. The function's
`Pair!(Element)` refers to the provider's `Pair` definition with the function's
current type argument. Instance identity is the definition plus ordered type
arguments, so this reference selects the same record as other `Pair!(Element)`
requests. Free names resolve in the definition's environment.

Use the same application spelling in types and expressions:

```crust
var pair: Pair!(i32) = make Pair!(i32) {
    first: 10i32, second: 20i32
};
pair_swap!(i32)(&pair);
```

`Pair!(i32)` selects a concrete record type. `pair_swap!(i32)` selects a
concrete function; the following `(&pair)` supplies its runtime arguments.
The provider declares the parameter names. The user supplies concrete arguments
at each use. The root selects the stage and source inputs; it needs no central
parameter list or `configure` callback.

The grammar extends the seed productions:

```text
TypeParameters = "!" "(" Identifier ("," Identifier)* ","? ")" ;
TypeArguments  = "!" "(" Type ("," Type)* ","? ")" ;

RecordDeclaration = "record" Identifier TypeParameters? RecordBody ;
FunctionDeclaration = "fn" Identifier TypeParameters? FunctionParameters
                      "->" Type FunctionBody ;

NamedType      = Identifier TypeArguments? ;
NameExpression = Identifier TypeArguments? ;
```

The declaration header is the binder position. Each other occurrence of `!(...)`
is an argument list. Existing expression postfix rules supply calls, indexing,
and field access after `NameExpression`. `Type` includes the seed types and
recursively includes applied named types. `Pair!(Pair!(i32))` is a nested type
application. The same type production applies in `make`, `null`, casts,
`sizeof`, `alignof`, and `offsetof`.

The first grammar accepts one or more type parameters and requires the exact
number of explicit type arguments. Parentheses are mandatory; a trailing comma
follows the seed's list convention. Defaults, parameter packs, inference, value
parameters, constraints, and specialized overload declarations are outside this
grammar. Unsupported forms receive a diagnostic. Ordinary compilation functions
remain available for conditions, loops, reflection, and constructing new
definitions.

Each source generic declaration has its own definition and instance cache.
Referencing a generic record alone requests that record's instance. A generic
function is specialized when requested. The procedural API can still construct
a definition containing several declarations when a factory needs that result.
The source syntax needs no separate generic-group construct or namespace.

### Parsing rules and cost

The existing lexer already supplies `!`, `(`, `)`, and `,`. After a declaration
name, `!` selects a type-parameter list. After a name in a type or expression,
`!` selects a type-argument list. The parser then requires `(`. Prefix `!`
retains logical negation; `!=` remains a distinct token. Whitespace and comments
follow the ordinary token rules.

Parsing requires fixed token lookahead. The declaration parser reads names in
binder lists; the application parser reads types in argument lists. Neither
queries a symbol table to choose a production. Reading tokens runs no factory
and computes no layout. Comparisons, shifts, indexing, and ordinary calls keep
their existing grammar. In particular:

```crust
pair_swap!(i32)(&pair);   // Specialization, then call.
value != other;          // Inequality.
!flag;                   // Logical negation.
value < other;           // Comparison.
value >> 1u32;           // Shift.
items[index];            // Indexing.
```

Nested applications close with `)`, so the lexer has no generic-specific `>>`
rule. Each token is consumed once, apart from bounded lookahead. These
properties support linear parsing; elapsed time still needs measurement.
Specialization and type checking remain separate costs.

### Syntax lessons from other languages

| Language | Useful mechanism | Crust decision |
| --- | --- | --- |
| D | Declaration-local parameters and explicit `Name!(Args)` application | Use the explicit marker and require parentheses |
| Rust | Explicit binders; `::<...>` separates expression arguments from comparison | Use one marked application spelling in types and expressions |
| Zig | Generic construction uses ordinary functions and compile-time type values | Keep construction and compiler control in ordinary Crust functions |
| Jai | Public demonstrations expose compiler control and specialization work | Keep the compiler interface programmable; distinguish public evidence from a complete grammar |

D's grammar distinguishes explicit instantiation with `!`. Rust's reference
states that `::` before `<` removes ambiguity with comparison in expression
paths. Rust also restricts unbraced constant arguments. This supports an explicit
delimiter and a type-only argument grammar for the initial stage.
[D grammar](https://dlang.org/spec/template.html#explicit_template_instantiation),
[Rust path grammar](https://doc.rust-lang.org/reference/paths.html#paths-in-expressions).

Zig's ordinary generic calls rely on its compile-time type values and unified
expression model. Crust's current seed has separate type syntax and value
expressions; its compilation program uses explicit type descriptors. The
chosen syntax lowers to those ordinary stage operations. Conditions and
reflection retain the host language's expression rules.
[Zig compile-time parameters](https://ziglang.org/documentation/0.15.2/#Compile-Time-Parameters).

The inspected Jai keynote supplies evidence about compiler control and
specialization costs. A complete current grammar was not established from
author-controlled sources, so the syntax choice does not depend on a claim
about Jai's precise parameter spelling.
[Jonathan Blow, LambdaConf 2025](https://www.youtube.com/watch?v=IdpD5QIVOKQ).

### Syntax implementation boundary

Implement this reader and lowering in Crust. Keep the C99 seed unchanged.
Source loading must freeze a provider once and let its definitions share that
snapshot. Calling the current `gs_define` separately on every range copies
whole source bytes per definition; that path must change before reading a file
with many generic declarations.

The reader records parameterized declarations and applications. A later stage
resolves argument types, requests instances, and replaces applications with
ordinary concrete bindings. Preserve definition-scope references and source
locations. Forward dependencies and active instance requests require explicit
resolution state; parsing must stay independent of that state.

The current external reader has declaration, type, and prefix hooks. Use its
declaration hooks for the parameter list. Extract the expression postfix loop
into a general helper so a specialized function expression can receive normal
calls, indexing, and field selection. These changes stay in the external reader
library. Retain generic nodes as stage-owned data until lowering. Only ordinary
concrete AST nodes may reach seed checking.

The current `gs_define` invokes the seed reader, and `gs_apply` checks its clone
immediately. Source syntax requires a parsed-definition entry point and a
normalization step before concrete checking. The function's `Pair!(Element)`
already requires that step; a definition-local parameter list alone is
insufficient. Same-unit argument types can require dependency resolution before
`gs_apply`, which accepts complete type facts. These are concrete implementation
requirements; the procedural stage alone does not implement the surface grammar.

Validate source-local `Element` and `Key, Value` binders, repeated application,
nested applications, same-unit forward references, definition-scope capture,
and pointer-recursive records. Include every named-type position, malformed
delimiters, and ordinary comparison, shift, negation, call, and indexing
expressions. Measure many declarations in one source to detect repeated source
copies. Report parsing, resolution, instance construction, and instance lookup
separately.

### Compilation-program values

Types, definitions, and instances are handles to stage-owned data. A handle is
an ordinary pointer or record in compilation code. It represents a target type;
it has no target value representation. The seed needs no first-class `type`
primitive or implicit compile-time evaluator.

Use normal source to describe a generic body. For example, a source unit can
contain:

```crust
fn transfer(value: T) -> T {
    return move value;
}

fn discard(value: T) -> unit {
}
```

The compilation program supplies `T` as a parameter binding when it reads this
unit. The ownership composition gives `T` its declared value and cleanup
contract. `discard` performs the ordinary cleanup of its parameter.

This uses the existing function, type-name, move, and scope syntax. The reader
can parse `T` as a name without knowing its concrete type. Binding happens in
the external stage. Files can be separate captured inputs or explicit source
ranges; the root remains an ordinary `crust main.crs` program.

The proposed API sequence is:

```text
parameters = declare the type parameter T
requirements = describe the ownership requirements for T
definition = read(source, parameters, explicit external bindings)
checked = ownership.check_definition(definition, requirements)
plain = ownership.instantiate(checked, PlainPayload)
resource = ownership.instantiate(checked, ResourcePayload)
bind selected instance exports into the target's input scope
compile the target with the selected backend
```

These are library operations. An ordinary Crust wrapper can perform the last
argument-binding step. For example, with proposed library types and functions:

```crust
fn container_for(g: *GenericStage, ownership: *OwnershipStage,
                 definition: *OwnershipDefinition,
                 payload: *GenericType) -> *GenericInstance {
    return ownership_instantiate_type(ownership, g, definition, payload);
}
```

The root can call this function in a loop, keep results in an array, or choose
between definitions with an ordinary `if`. There is no second expression
language for these decisions. Source discovery and exported-name policy stay
with the root or its selected module library.

For example, an ordinary function can select one of two checked definitions:

```crust
fn select_container(compact: bool, small: *OwnershipDefinition,
                    general: *OwnershipDefinition) -> *OwnershipDefinition {
    if compact { return small; }
    return general;
}
```

The compilation program can compute `compact` from a build option or from
complete target type facts. Each selected definition still checks its argument
contract. A factory that instead builds a new body submits that body for checking.

Start with explicit type arguments and existing source syntax. Type-position
calls, angle-bracket application, implicit argument deduction, and quotation
syntax are not needed for this witness. A reader facade would have to lower
to the same library operations and preserve their contracts.

## Construction, checking, and instantiation

A definition has a fixed parameter list, declaration graph, external bindings,
and checking contracts. Its source locations remain available for diagnostics.
The definition is immutable after publication. An edit creates a new definition.
The selected compiler stages remain responsible for preserving this contract.
Public AST access permits a stage replacement; it does not make a previous
checking receipt valid for changed output.

An ordinary factory can inspect a concrete type and generate different code.
The resulting definition must be checked. Calling the factory once with a dummy
payload cannot prove its outputs for all payloads. Selecting between already
checked definitions can reuse their checks.

Checking a parameterized definition must establish the types of expressions
and the ownership effects of each operation under its abstract environment.
Use symbolic type identities for parameters. A parameter is not an empty
record, an `i64`, a pointer, or a seed type with a fabricated size.

The symbolic environment belongs to the external stages. Reuse the source AST
and the existing local ownership rules where their contracts permit it. Extract
type-fact queries needed by those rules instead of copying the whole ownership
checker. The current concrete checker does not provide abstract checking for
free; the first implementation must demonstrate this path with `transfer` and
`discard` before expanding it to the container.

Instantiation performs these operations:

1. Validate argument identities and the required contracts.
2. Find or create the instance under its canonical key.
3. Substitute type and declaration identities while preserving bound names.
4. Resolve concrete layout and cleanup operations.
5. Lower to ordinary seed declarations and run concrete seed validation.
6. Publish the instance and its exact definition and checking provenance.

An instance can still fail because its concrete layout is invalid, a target
limit is exceeded, or allocation fails. Checking once means that the unchanged
abstract body does not undergo ownership analysis for each specialization.
Concrete layout, seed checks, and emission still require work.

Specialization may substitute declared parameters and lower the resulting
operations. A new type-reflection branch, an arbitrary body rewrite, or a
changed ownership annotation beyond the declared parameter substitution requires
a new check. A checking receipt cannot be copied onto independently generated
syntax.

## Ownership parameter contract

The first ownership composition accepts one payload parameter with these
requirements:

- A sized, movable record.
- Closed ownership: its complete contents retain no loans or domain identities.
- Its complete cleanup tree requires no domain access.

Plain value records and resource records can satisfy this contract. The check
must inspect nested fields, owning storage, and cleanup requirements. A plain
pointer hidden in a record or a nested borrowed view cannot satisfy it by hiding
behind `T`. The first profile rejects opaque records anywhere in the owned value
or storage graph: the current opaque interface has no closed-ownership contract.
Follow `owns(field: storage)` edges when checking that graph. Native handle fields
with declared ownership and foreign contracts are terminal resources, including
pointer-shaped handles; their representation does not grant pointee access.

These are requirements of the first container and ownership profile. Other
checking profiles can use the same generics stage with different parameter
contracts. General scalar parameters do not require a seed feature, but are
outside the first two-record witness.

Inside a checked body, treat `T` as an affine value: a move consumes its source.
Permit whole-value transfer, return, temporary `read T` and `mut T` loans, and
scope cleanup. A borrowed parameter must still be initialized when the function
returns. Its loan cannot escape except through a declared result origin.

The body has no permission to copy `T`, select unknown fields, manufacture an
arbitrary `T`, or use arithmetic on it. A concrete plain-record argument does
not make an invalid abstract copy acceptable. Similarly, a machine copy emitted
for a plain-record move does not restore the source's abstract ownership.

Cleanup resolves through the ownership/resource stage. It includes the user
destructor and recursive field cleanup in the defined order. For a plain record
with no resources, cleanup emits no operation. `drop_access = none` means that
cleanup needs no domain authority; cleanup can still print, release storage,
or close a handle.

The container's destructor contract must cover the payload cleanup contract.
A resource that needs reclamation authority for another domain fails the initial
argument contract. Silently granting that authority would invalidate the body
proof. Adding domain-dependent payloads would require explicit effect and domain
parameters at this boundary.

The first implementation needs no trait search or arbitrary boolean constraint
solver. A user function may select a definition, but a successful user predicate
cannot replace the ownership facts required to check it.

## Bindings, identity, and layout

Bind every free reference to its definition environment or to a declared
parameter. Generated local names have fresh internal identities. A name in the
client cannot capture a helper in the generic body. Export aliases are a separate
root-controlled mapping.

The logical instance key contains the definition identity and the ordered
argument identities. Definition identity includes its fixed bindings and
contracts. Two nominal records with equal size and fields remain different
arguments. Two aliases of the same nominal record denote the same argument.
Repeated requests reuse one instance within the selected program context.
Use exact key comparison after a hash lookup; a hash collision is not type equality.

Keep logical type identity separate from the artifact cache key. The latter
also includes target layout and ABI, checker and stage versions, options, and
captured dependencies. Arena addresses and worker completion order are never
persistent identifiers. Symbol spelling can use the stable instance key while
diagnostics retain readable source names.

Pointers can refer to an instance while its record layout is being completed.
An inline cycle that requires a record to contain itself has no finite layout
and must fail. Reserve identities before resolving fields; publish complete
facts only after resolution succeeds. Bound expansion depth and instance count
with explicit diagnostics. Do not hide an expansion cycle by inventing a type.

`sizeof(T)` and offsets into a record containing `T` remain symbolic until its
instance has a layout. Trusted container code may use these target-layout
operations. It must use the declared fields and types; size equality does not
justify treating two nominal types as interchangeable. The first checked helper
needs no pointer-layout proof.

## Trust and independent imports

A root selects trust for a fixed generic provider definition. Specializations
inherit that selection together with its identity. They do not require repeated
trust declarations. This is still an explicitly trusted pointer implementation.
Its parameter checks and client checks do not constitute a proof of its links.

Keep checked generic definitions and trusted generic definitions distinct in
receipts and diagnostics. A generated instance is not an ordinary bodyless
import merely because ownership analysis should be skipped. Its provenance must
identify the source definition, checked parameter environment, substitution,
and selected implementation.

A generic library artifact needs the definition representation for new
specializations, its bound dependencies, parameter contracts, and checking or
trust receipt. The current concrete interface plus native object cannot produce
code for an argument that was absent at publication. Store captured generic
source or a versioned external-stage representation with its bindings. Imports
can specialize that representation without recovering local source files or
repeating its ownership proof. Concrete bodies remain subject to seed checks.

The existing artifact cache can store the resulting files. Receipt validation
must bind all representation bytes and participating stages. Untrusted interface
text cannot set a checked flag or grant trust to a body. Library consumers need
only the declared argument and function contracts to check their own code.

## Scheduling and costs

Root calls retain source order, including file reads and visible effects.
Automatic reuse applies to definition instances; it does not memoize arbitrary
root functions. A factory that reads changing external state must capture that
state in a new definition before requesting reusable instances.

After definitions and interfaces are fixed, independent body checks and
specializations can use separate contexts. Pass immutable input data to those
jobs. Use explicit declaration dependencies and a deterministic identity map.
A task waiting for its own complete inline layout reports a cycle. Pointer
recursion uses the already reserved declaration identity.

The initial implementation runs with one worker and an in-memory instance table.
Parallel execution and persistent reuse must not conceal cold checking or
specialization costs. Avoid repeated source parsing per use, repeated ownership
proofs, and scans of all instances at every request. Use the existing captured
artifact cache only when there is an actual artifact to reuse.

Count definition reads, abstract body checks, argument checks, specialization
requests, reuse hits, and emitted bodies. Many requests for one instance should
add lookups and argument checks. New argument types should add concrete
specialization work. Neither case should re-check an unchanged abstract body.

## First implementation witness

Use one intrusive membership-container definition with a plain payload record
and a resource payload record. The resource must include nested cleanup so a
test can distinguish complete destruction from calling only its user destructor.
The root selects trust once for the provider definition. A separate untrusted
`transfer`/`discard` definition demonstrates abstract ownership checking.

Use link-only sentinels. The current intrusive heads embed a full node and use a
zero integer payload. A generic resource need not have a dummy value or a default
constructor. Keep links in a `Link` record and the payload in allocated `Node`
records. Preserve the two independent memberships used by the current example.

The initial public operations construct an owner from a payload, borrow the
payload through that owner, insert into heads, count membership, and destroy an
owner while heads remain live. Test unlinking, individual release, and storage
reuse. A trusted destructor unlinks the node, executes `drop *owner.node`, then
releases the allocation. The existing resource lowerer can recursively drop
record fields through this operation.

A link sentinel contains no payload. Therefore this witness must not export the
old unconditional `cursor_value` operation for cursors that can denote the end.
A prose precondition would let checked clients violate the safety claim. Keep
the current nongeneric cursor tests as regressions. The generic witness tests
loans and reclamation through valid owner handles.

If payload traversal becomes necessary, the smallest additional experiment is
an explicit compilation-time function binding with the contract
`fn(read T) -> unit` and no domain or retention effects. The trusted traversal
checks the sentinel before projecting a node and calls that bound function
directly. Its identity and contract become definition arguments. This requires
function-parameter binding and interface matching; the type-only slice must
not claim to have implemented it. A general end-cursor refinement system is
outside this witness.

Test the following properties before expanding the implementation:

| Case | Required result |
| --- | --- |
| Plain and resource payloads | Same provider definition; correct native output at O0 and O2 |
| Nested payload cleanup | Every destructor runs once, after unlinking and before release |
| Move then use in generic helper | Rejected at definition checking, including for a plain-record instance |
| Borrowed or domain-dependent payload | Rejected at argument validation; its obligations cannot disappear inside T |
| Stronger nested destructor permission | Rejected at argument validation |
| Borrow versus owner destruction | Existing ownership conflict reported in the client |
| Repeated request | Same instance and exported nominal identities |
| Equal-layout nominal arguments | Distinct instances |
| Definition-site helper versus client names | Original helper binding retained |
| Edited body or annotation | Previous receipt cannot authorize it |
| Independent import | New payload instance generated from the artifact with preserved provenance |
| Allocation failure and invalid layout | Diagnostic; no partially published instance |
| Emission and sanitizers | Same operations as handwritten specializations; no ownership metadata or hidden generic dispatch |

Freeze the two handwritten specializations before implementation. Measure root
setup, reading, abstract checking, argument checking, specialization, concrete
lowering, emission, and memory use. Exclude final target GCC compilation and
linking. Record cold stage preparation and cache validation separately. Keep raw
measurements under ignored build storage.

Compare concrete layouts and emitted C or assembly against those specializations.
Normalize only generated symbol identities; retain every operation in the
comparison. Also compare emission before and after ownership verification of
the same instance. Diagnostics must identify the definition, the failed parameter
requirement, and the instantiation site. A nested cleanup failure must name the
field path and required permission.

Measure one instance, repeated uses of that instance, and many distinct
instances. The first profile adds an optional check; report that cost honestly.
The basic compilation path and the optional ownership path retain their separate
speed requirements from the [specification](../crust0-spec.md#14-conformance-and-performance-gates).
No speed claim follows from the language comparisons in this document.

## Implementation boundaries in the current code

| Location | Required change or reusable mechanism |
| --- | --- |
| [Reader hooks](../../stages/reader/model.crs) | Compose parameter-name bindings with the ownership reader; preserve source locations |
| [Ownership pipeline](../../stages/ownership/program.crs) | Check abstract definitions before concrete resource lowering and seed validation |
| [Ownership facts](../../stages/ownership/model.crs) | Supply abstract parameter facts through an explicit environment; preserve annotations keyed by node identity |
| [Move checking](../../stages/ownership/places.crs) | Treat abstract T as affine; ordinary concrete plain-record checking currently rejects explicit owner moves |
| [Resource lowering](../../stages/resources/expr.crs) and [drop lowering](../../stages/resources/drop.crs) | Existing delegated lowering supports plain-record transfers and empty cleanup; keep source ownership proof attached |
| [Recursive cleanup](../../stages/resources/cleanup.crs) | Reuse full record cleanup for the instantiated payload |
| [Trust selection](../../stages/ownership/trust.crs) | Retain definition-level trust and instance provenance |
| [Interface emission](../../stages/ownership/interface.crs) | Serialize substituted declarations and contracts; copying original source spans would retain stale T and names |
| [Library artifacts](../../stages/ownership/artifact.crs) | Bind the generic representation and its dependencies to the receipt |
| [Concrete API boundary](../bootstrap.md#core-and-storage) | Publish only complete seed facts; keep unresolved parameters in external-stage data |

Implement the checked helper, then the two-payload container, then its independent
import. Review this complete slice before adding another generic facility. Stop
if it needs core changes, per-instance trust selection, caller inspection,
solver machinery, or runtime proof state. Record the exact missing contract.
A factory experiment that only emits two working concrete programs does not
satisfy the abstract-checking requirement.
