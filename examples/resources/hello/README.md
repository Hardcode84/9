# Resource hello

Run from the repository root:

```sh
make all resource-stage
build/rmd examples/resources/hello/main.rmd
build/resource-hello
```

The output is `Hello, resources!` and a newline. The compilation program and
target program share one file. The root loads the resource compiler as an
ordinary shared library. It gives the library its source and current cursor.

The target duplicates standard output and owns that descriptor in `Output`.
The move transfers its cleanup obligation. The deferred call holds an exclusive
loan until it writes the greeting. Automatic cleanup then closes the descriptor.
No reference count, resource pool, or target cleanup table is used.

Foreign calls and the descriptor field occur in explicit `unsafe` regions.
Failed writes end the process with status 1. Failed implicit close uses status 2.
Process termination does not run pending cleanup. Normal return does.
