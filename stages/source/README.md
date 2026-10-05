<!-- SPDX-License-Identifier: Apache-2.0 -->

# Source query services

A source pass can need the type of an expression that another stage owns.
`CsHooks` lets the owning stage supply that answer. The caller selects an ordered
chain of providers. Each provider uses `CsQuery` to visit child nodes and query
source types through the active pass.

Load [model.crs](model.crs) after `api/crust0.crs`. Compile [base.crs](base.crs)
with a provider that needs its arena and key helpers. The interface is ordinary
Crust code. The [composition tutorial](../../examples/composition/README.md)
selects resource, ownership, and overload services from a root program.

## Dispatch

Set `next` to the next provider, or null at the end. The root owns the finite,
acyclic chain and keeps it and each provider's `user` state live during the pass.
For type, binding, expression, and statement queries, the first handled result
wins. A null callback skips that provider. An unhandled callback leaves its input
and output unchanged. A context diagnostic stops dispatch immediately.

| Callback | Result and obligation |
|---|---|
| `type_key` | Append a complete type payload to `CsText`; return true. Return false for an unhandled type. |
| `binding_type` | Return the value type of a binding. Return null when unhandled. The consumer then tries the next provider, and finally uses the declared type. |
| `expression` | Visit the complete expression and return its source type. Return null when unhandled. |
| `statement` | Visit the complete statement and return true. Return false when unhandled. |
| `contract` | Append this provider's declaration contract. Every selected contract callback runs, in chain order. |
| `references` | Resolve names held in provider metadata after all function signatures are collected and before body names change. |
| `published` | Receive each retained function declaration after names and linkage are assigned. The Boolean marks a bodyless source import. |

A consumer applies its standard rules after all providers return unhandled. It
reports unsupported syntax at its source location. Hooks can also handle seed
nodes when an extension changes their source meaning, such as a field access
through a borrowed value.

## Queries inside a callback

`CsQuery` is borrowed for one callback. Keep neither it nor its opaque `user`
and `scope` pointers. Use its operations for recursive work:

- `type_key` appends a complete child type encoding. Pass `depth + 1` for a child.
- `expression` and `statement` visit child nodes in the current body scope.
  They are available inside expression and statement callbacks.
- `field_type` returns a named record field's source type.
- `same` compares source types.
- `select` selects a function by its full source signature and returns its
  assigned internal name. All function signatures must already be collected.

Check `context.error_count` before using a failed query's result. Call
`cs_error` with an original source location to report an extension error.
The consumer retains the first diagnostic. It stops before the next provider
or output stage. Failure can leave the current context partly transformed;
destroy that context instead of retrying it.

## Keys and contracts

`CsText` is an arena-backed byte buffer. `cs_number` appends a decimal number
and `_`. `cs_part` appends the byte count with `cs_number`, then the bytes.
Use these helpers to make complete, unambiguous encodings. Type and contract
payloads use ASCII without NUL. Start each provider payload with a stable name.
Use structural source facts. Context addresses and allocated kind IDs belong
only to their context and must stay out of native names.

Contract callbacks must encode every condition that must match between a
function interface and its definition. `cs_parameter` converts a parameter
name to a one-based position; null has position zero. This permits different
parameter names in matching declarations. Ordered field paths retain their
order. The ownership provider also requires the written order of `modifies`
and native-effect entries to match.

The overload consumer starts a declaration key with `s`, then appends the
selected contracts. Provider order and contract encodings form part of the ABI.
Use the same provider order, definitions, and ABI domain in a caller and provider.
Change the ABI domain when those rules change. Type queries can make nested
queries; their temporary keys preserve the enclosing output prefix even when
the buffer grows.

## Pass order

The root calls the passes explicitly. For ownership with overloads:

1. Read source with ownership hooks and overload function endings.
2. Collect signatures and provider contracts; resolve provider references.
3. Select calls with source types and assign unique names.
4. Lower resource operations and check ownership contracts.
5. Emit with the resource cleanup callback.

This order preserves the difference between `read T` and `mut T` during overload
selection. A source import also needs an ownership interface verified against
its provider, or explicit root trust. A matching mangled name alone cannot
establish that the provider obeys the contract.

`make check-overload` tests the providers through native output and rejection
cases. `make check-overload-alloc` checks allocation failure with sanitizers.
