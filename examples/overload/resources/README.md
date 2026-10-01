# Overloads with ownership and cleanup

```sh
make all overload-stage
build/crust examples/overload/resources/main.crs
build/overload-resources
```

Expected output:

```text
Owned overloads.
Deferred overload.
```

The root selects a package that composes two Crust stages. Overload selection
runs before ownership checking and cleanup lowering.

`write` accepts a raw string or a shared view of owned text. The source type
selects the function. The two `release` functions close a file descriptor and
free allocated text. Resource declarations select these drop functions by
their exact `mut` parameter types. `move` transfers the text owner. `defer`
schedules the final write before the output descriptor is closed.

The native calls and raw pointer operations remain inside `unsafe` regions.
Overload selection does not change their safety rules.
