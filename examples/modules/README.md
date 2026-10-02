<!-- SPDX-License-Identifier: Apache-2.0 -->

# Separate modules

Follow the [module tutorial](../../stages/modules/README.md) for the design,
source bindings, native names, and context lifetimes.

Run from the repository root:

```sh
make all c-stage
build/crust examples/modules/main.crs
build/modules
```

The output is `modules: 42`. The root reads `provider.crs` and `consumer.crs`
into separate contexts. It exports three provider names, imports them with
new names, emits `build/modules-provider.o`, and links `build/modules`.
Both source files contain a private function named `helper`.

Source and output paths are relative to `main.crs`. Run `make check-modules`
to check the tutorial and the module library's failure paths.
