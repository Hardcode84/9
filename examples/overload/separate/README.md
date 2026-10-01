# Separate objects

This example checks the boundary that a single-file overload example cannot:
two independent compilations must produce the same native symbol for a
source declaration. Read [overloaded hello](../hello/README.md) first.
Run from the repository root:

```sh
make all overload-stage
build/crust examples/overload/separate/main.crs
build/overload-separate
nm -g build/overload-format.o
```

Expected output is `types: 42` followed by a newline.

The root first compiles the provider to an object. It then compiles its own
target source and links that object. Both compilations use `interface.crs`.
The provider's definitions complete the interface declarations. The caller
uses the same declarations as imports.

`format` has a string overload and an unsigned integer overload. Their native
names contain distinct parameter encodings. No runtime dispatcher is present.
The native names do not depend on the input file order or declaration order.

Read the inputs in this order:

1. [interface.crs](interface.crs) declares `Output` and both `format` signatures.
   The bodyless declarations are source ABI imports.
2. [provider.crs](provider.crs) defines those signatures. It handles partial
   native writes and converts `u64` values to decimal digits.
3. [main.crs](main.crs) builds the provider with `--library --object`, checks
   its status, then passes that object as a link argument for the caller.

Find the two defined symbols containing `n6_format` in the `nm` output.
The integer and pointer parameter encodings differ. The caller uses the
same encoding from the shared interface; it does not need the provider's
function bodies during selection.

Both builds must share the record definitions and ABI domain. The mangled
name includes the record name, not a complete record layout. A symbol match
alone cannot detect two incompatible definitions of `Output`.

The [overload tutorial](../../../stages/overload/README.md) explains the
name encoding and implementation. The next [composition example](../resources/README.md)
keeps ownership and borrow contracts through the same selection step.
