# Separate objects

```sh
make all overload-stage
build/crust examples/overload/separate/main.crust
build/overload-separate
nm -g build/overload-format.o
```

Expected output is `types: 42` followed by a newline.

The root first compiles the provider to an object. It then compiles its own
target source and links that object. Both compilations use `interface.crust`.
The provider's definitions complete the interface declarations. The caller
uses the same declarations as imports.

`format` has a string overload and an unsigned integer overload. Their native
names contain distinct parameter encodings. No runtime dispatcher is present.
The native names do not depend on the input file order or declaration order.
