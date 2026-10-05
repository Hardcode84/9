<!-- SPDX-License-Identifier: Apache-2.0 -->

# Function overload stage

This optional stage is a Crust program. The seed has one function per name.
The stage selects a function and replaces its source name before the next
checker runs. Generated calls have no runtime dispatch.
The standalone package retains the Crust0 scalar function ABI. The resource
package also supports aggregate value calls under that stage's rules.

## Selection rules

- Functions can share a name when their parameter type lists differ.
- Calls require exact argument types and arity. Use a cast for a conversion.
- The result type does not select a call. Declarations with equal parameter
  types and different result types are errors.
- A typed variable, assignment, return, or known function parameter can select
  a function value by its complete function type.
- Arguments to an overloaded call must have types without candidate search.
  Bind an overloaded function value to a typed local before such a call.
- Source names retain the scope rules of the next checker. Mangling does not
  permit a local to hide a global name.

## Separate compilation

`fn name(parameters) -> Result;` declares a source ABI import. A definition
uses the same header and a body. A matching bodyless declaration selects that
definition for source ABI export, regardless of declaration order. Other
definitions are private. Two definitions are an error. Put public declarations
in an interface source and compile it with both provider and caller.

`extern fn name(parameters) -> Result = "native_name";` retains the explicit
native name. This declaration uses the native ABI rules of the next stage.

Source ABI imports and exports get a structural native name. The name contains a version,
an ABI domain, the source name, the parameter types, the result type, and the
declaration contract. Input order, paths, and allocation addresses have no
effect on this name. Function types include their result type. Record types
use their declared names in the current flat source namespace.

Caller and provider must use the same record definitions and ABI domain.
Use a shared interface source for this contract. A mangled name does not
check record layout drift. Separate libraries that use different types with
the same source names must use different ABI domains.

## Stage boundary

The resolver publishes all signatures before it visits function bodies.
It looks up exact parameter keys in a table. It does not run the checker
once per candidate. The next checker validates expressions, effects, and
ownership after selection.

Optional callbacks supply type encodings, binding value types, expression
and statement traversal, and declaration contracts. The standalone resolver
has no ownership-specific type or syntax cases. The resource provider supplies
these callbacks and preserves source import, unsafe, and drop contracts.

The implementation passes a separate caller and provider test that formats
typed values, links by generated symbols, and produces the required output.
Resource tests check cleanup and reject invalid ownership across that boundary.
The [measurement guide](../../benchmarks/overload/README.md) defines equivalent
inputs and comparison rules. Frontend measurements stop before target C
compilation and linking. The seed and the default compilation path have no overload pass.

## Use from a compilation program

```sh
make all overload-stage
build/crust examples/overload/hello/main.crs
build/overload-hello
build/crust examples/overload/separate/main.crs
build/overload-separate
build/crust examples/overload/resources/main.crs
build/overload-resources
make check-overload
make check-overload-alloc
```

The [hello root](../../examples/overload/hello/main.crs) loads `api.crs` and an
ordinary compiled Crust library. It calls `overload_build` with the unread range
of its own source. The seed has no package-name check or overload syntax.
The [separate-object root](../../examples/overload/separate/main.crs) controls
both compiler calls and the link input. The
[resource root](../../examples/overload/resources/main.crs) selects the composed
package through `resource_api.crs`.

`build/crust-overload` and `build/crust-overload-resource` are command wrappers for
these same libraries. They accept the C stage's input and output options.
`--check` stops after semantic checking. `--prepare` also constructs C text in
memory. `--library --object` emits a native object without a hosted entry.
Source definitions with a matching bodyless declaration are visible under
their mangled names in that object. Private definitions cannot collide with
helpers in another object or be replaced by another shared library's helper.
`--entry name` selects a defined `fn(i32, **u8) -> i32` from the named family.
Selection uses source types. A borrow with the same lowered pointer type does
not match this entry signature.

`--export name` replaces the native name of one defined function or constant
with its plain source name. An overloaded family is ambiguous for this option.
Use a separately named wrapper when a native caller needs one family member.
A plain export changes that declaration's linkage contract; source imports
must use the normal mangled definition or an explicit native interface.
Explicit native names with the `crust_ov1_` prefix are rejected. That prefix
belongs to source ABI imports and definitions.

## Native name format

`N(value)` is decimal `value` followed by `_`. `S(bytes)` is `N(length)` followed
by the bytes. The supplied ABI domain and contract encodings must use ASCII.
Use letters, digits, and underscores for portable domain names.

| Source type | Encoding |
| --- | --- |
| Builtin | `b N(kind)` with the Crust0 builtin kind number |
| Named record | `n S(name)` |
| Pointer | `p Type` |
| Array | `a N(count) Type` |
| Function value | `f N(arity) Parameters r Result` |
| Extension type | `x Payload` from the type callback, including its stable extension name |

`Parameters` is the concatenation of the encoded parameter types.
The `NativeParameters` encoding is `a N(arity) Parameters`.
Local selection uses `a N(arity)` followed by `N` of each interned type key's
address. These keys are exact within their context. They must not be saved or
used across contexts. Calls reuse cached type keys without copying their text.
Native names use only structural encodings; they contain no addresses.
The native name is:

```text
crust_ov1_d S(domain) n S(source_name) NativeParameters r Result c S(contract)
```

Spaces in this notation are separators; they are not emitted.
The standalone package uses domain `crust0_x64_v1` and contract `s`.
The resource package uses domain `resources_x64_v1`. Its contract is
`s S(resources) N(unsafe) N(return_source_position)`, where the position is
one-based, or zero for no returned loan. Its extension type payload starts with `S(resource_read)` or
`S(resource_mut)`, followed by the encoded base type. Thus `read T`
and `mut T` keep distinct names even when both lower to machine pointers.
The encoding contains complete keys. Native names do not use a truncated hash.
Interning compares all key bytes when hashes collide.

For example, `fn twice(value:i32)->i32` has this native name in the standalone
package:

```text
crust_ov1_d13_crust0_x64_v1n5_twicea1_b4_rb4_c1_s
```

## Public composition API

Load the reader and [source query models](../source/model.crs), then
`model.crs` and `extension.crs`. `ov_init` takes a context, an ABI domain, and
an optional `CsHooks` chain. Keep the context, sources, stages, and hook sets
live through their use. Operations on one context are serial.

For overload syntax alone, call `ov_read` for each range. To combine readers,
call `ov_reader_hooks` to construct its hook set, add other sets with `next`,
and pass the head to `rr_read`.

After reading, call `ov_prepare` once. It runs these public operations:

1. `ov_collect` collects signatures and all provider contracts, then calls each
   provider's `references` service.
2. `ov_resolve` visits bodies and selects calls using source types.
3. `ov_mangle` assigns names, retains one matching declaration, and calls each
   provider's `published` service.

The [source query contract](../source/README.md) defines forwarding, failure,
keys, and callback lifetimes. Expression and statement providers run before
standard traversal. The first handled result wins. Unhandled nodes reach the
next provider, then the standard visitor. Unsupported syntax gets a diagnostic.
Every selected contract callback contributes to declaration and native-name
identity. Caller and provider must use the same provider order and encodings.

Keep source signatures and record fields unchanged until mangling completes.
Lower types after overload preparation. Record field lookups use the index
built during collection. Nested type queries preserve the enclosing output
prefix, including when the key buffer grows. Queries release their temporary
byte ranges on return. Type, expression, and statement traversal is bounded.

The resource stage supplies `rs_source_hooks`. Its reference callback selects
each drop by `fn(mut Resource)->unit`. Its publication callback marks source
imports through `rs_source_import`. The resource checker then enforces move,
borrow, cleanup, unsafe-call, and function-cast rules.

The ownership stage supplies `os_source_hooks` for field and function contracts.
Select it together with the resource provider, then call `os_lower` and
`os_verify` after `ov_prepare`. The
[composition tutorial](../../examples/composition/README.md) shows the root
setup, target code, and complete pass sequence.

## Validation and cost

`make check-overload` checks exact type selection, function values, diagnostics,
native symbols, separate objects, source roots, and resource and ownership composition.
It also loads an ordinary copied library with a custom non-resource type and
checks provider diagnostic paths. `make check-overload-alloc` injects
arena backing allocation failures with AddressSanitizer and UndefinedBehaviorSanitizer.

The [measurement method](../../benchmarks/overload/README.md) separates the
explicit-name baseline, the enabled stage with explicit names, and overload
selection. Its field-lookup workload checks large record constructors. Each
result applies to its measured inputs, builds, and endpoint.
