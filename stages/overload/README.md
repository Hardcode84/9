# Function overload stage

This optional stage is an RMD program. The seed has one function per name.
The stage selects a function and replaces its source name before the next
checker runs. Generated calls have no runtime dispatch.
The standalone package retains the RMD0 scalar function ABI. The resource
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
uses the same header and a body. A matching import and definition can occur
in one compilation. Two definitions are an error.

`extern fn name(parameters) -> Result = "native_name";` retains the explicit
native name. This declaration uses the native ABI rules of the next stage.

Source functions get a structural native name. The name contains a version,
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
has no ownership-specific type or syntax cases. The resource adapter uses
these callbacks and preserves source import, unsafe, and drop contracts.

The implementation passes a separate caller and provider test that formats
typed values, links by generated symbols, and produces the required output.
Resource tests check cleanup and reject invalid ownership across that boundary.
The [baseline](../../benchmarks/overload/BASELINE.md) fixes the experiment and
the measurement rules. Frontend measurements stop before target C compilation
and linking. The seed and the default compilation path have no overload pass.

## Use from a compilation program

```sh
make all overload-stage
build/rmd examples/overload/hello/main.rmd
build/overload-hello
build/rmd examples/overload/separate/main.rmd
build/overload-separate
build/rmd examples/overload/resources/main.rmd
build/overload-resources
make check-overload
make check-overload-alloc
```

The [hello root](../../examples/overload/hello/main.rmd) loads `api.rmd` and an
ordinary compiled RMD library. It calls `overload_build` with the unread range
of its own source. The seed has no package-name check or overload syntax.
The [separate-object root](../../examples/overload/separate/main.rmd) controls
both compiler calls and the link input. The
[resource root](../../examples/overload/resources/main.rmd) selects the composed
package through `resource_api.rmd`.

`build/rmd-overload` and `build/rmd-overload-resource` are command wrappers for
these same libraries. They accept the C stage's input and output options.
`--check` stops after semantic checking. `--prepare` also constructs C text in
memory. `--library --object` emits a native object without a hosted entry.
Source definitions are visible under their mangled names in that object.
`--entry name` selects a defined `fn(i32, **u8) -> i32` from the named family.

`--export name` replaces the native name of one defined function or constant
with its plain source name. An overloaded family is ambiguous for this option.
Use a separately named wrapper when a native caller needs one family member.
A plain export changes that declaration's linkage contract; source imports
must use the normal mangled definition or an explicit native interface.
Explicit native names with the `rmd_ov1_` prefix are rejected. That prefix
belongs to source ABI imports and definitions.

## Native name format

`N(value)` is decimal `value` followed by `_`. `S(bytes)` is `N(length)` followed
by the bytes. The supplied ABI domain and contract encodings must use ASCII.
Use letters, digits, and underscores for portable domain names.

| Source type | Encoding |
| --- | --- |
| Builtin | `b N(kind)` with the RMD0 builtin kind number |
| Named record | `n S(name)` |
| Pointer | `p Type` |
| Array | `a N(count) Type` |
| Function value | `f N(arity) Parameters r Result` |
| Extension type | `x N(kind) Payload` from the type callback |

`Parameters` is the concatenation of the encoded parameter types.
The selection key is `a N(arity) Parameters`.
The native name is:

```text
rmd_ov1_d S(domain) n S(source_name) SelectionKey r Result c S(contract)
```

Spaces in this notation are separators; they are not emitted.
The standalone package uses domain `rmd0_x64_v1` and contract `s`.
The resource package uses domain `resources_x64_v1` and contract `safe` or
`unsafe`. Its extension type payload is the encoded base type. Thus `read T`
and `mut T` keep distinct names even when both lower to machine pointers.
The encoding contains complete keys. Native names do not use a truncated hash.
Interning compares all key bytes when hashes collide.

For example, `fn twice(value:i32)->i32` has this native name in the standalone
package:

```text
rmd_ov1_d11_rmd0_x64_v1n5_twicea1_b4_rb4_c1_s
```

## Public composition API

`model.rmd` and `extension.rmd` expose the stage state and operations.
`ov_init` takes a context, an ABI domain, and optional hooks. Call `ov_read`
for each source range, then `ov_prepare`. That last call runs `ov_collect`,
`ov_resolve`, and `ov_mangle` in order. The individual operations are also
public. After successful preparation, run the next checker and backend.
Keep the context, source bytes, stage, and hooks live through their use.
Operations on one context are serial; they share its arena and key buffer.
Keep source signatures and record fields unchanged between collection and
mangling. Lower their type representations after overload preparation.
Record field lookups use a name index built during collection. A constructor
does not scan the complete record once per initializer.

| Hook | Contract |
| --- | --- |
| `type_key` | Append a self-delimiting ASCII type payload without NUL after the extension kind tag; return false for an unknown type |
| `binding_type` | Return the value type produced by reading a binding; return the input type when no change is needed |
| `expression` | Visit a complete expression and return its source type; return null without changing an unhandled expression |
| `statement` | Visit a complete statement; return false without changing an unhandled statement |
| `contract` | Return a declaration contract interned in this context; equal parameter lists must have equal contracts |

Expression and statement hooks run before the standard visitor. Standard
visitor helpers bypass the current hook and retain hooks on child nodes.
Distinct extension types must have distinct payloads. Use `ov_part` for a
variable-length payload, or encode a fixed number of complete child types.
Unknown syntax fails with a source diagnostic. `ov_error` records the first
failure. Allocation failures and new context diagnostics from a hook also stop
the operation. Type, expression, and statement traversal have bounded depth.

The resource adapter supplies these callbacks. It selects each drop function
by `fn(mut Resource)->unit`, then publishes source ABI imports through
`rs_source_import`. The resource checker retains all move, borrow, cleanup,
unsafe-call, and function-cast rules. A cast does not bypass those rules.
Source signatures and their imported safety contracts remain distinct from
the lowered pointer signatures used by the C backend.

## Validation and cost

`make check-overload` checks exact type selection, function values, diagnostics,
native symbols, separate objects, source roots, and resource composition.
It also loads an ordinary copied library with a custom non-resource type and
checks all five hook diagnostic paths. `make check-overload-alloc` injects
arena backing allocation failures with AddressSanitizer and UndefinedBehaviorSanitizer.

The [measurement report](../../benchmarks/overload/RESULTS.md) separates the
explicit-name baseline, the enabled stage with explicit names, and overload
selection. The [field lookup experiment](../../benchmarks/overload/FIELDS.md)
checks large record constructors. These reports state the tested boundaries;
they do not establish the project's general C-speed requirement.
