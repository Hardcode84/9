# Tutorial: own a descriptor and defer a call

This example writes through an owned file descriptor. A move transfers the
descriptor's cleanup obligation. A deferred call borrows it until scope exit.
The owner then closes it exactly once on normal return.

Read [Hello World](../../hello/README.md) first. Run these commands from the
repository root on Linux x86-64:

```sh
make all resource-stage
build/crust examples/resources/hello/main.crs
build/resource-hello
```

Expected output:

```text
Hello, resources!
```

## Select the ownership rules

Open [main.crs](main.crs). The root loads the resource API and its ordinary
compiled Crust library. Its final call is:

```crust
return resource_build((*run).source, (*run).cursor, 2i32, &arguments[0usize]);
```

The stage reads the remaining target declarations. It adds the resource
syntax, checks owners and loans, and sends cleanup plans to the C backend.
The seed does not recognize the stage's name or implement its ownership rules.

## Follow the descriptor

`Output` is a resource record with a declared `output_drop` function.
`output_open` calls `dup(1)` to obtain a separate descriptor for standard
output. Its successful result creates one owner. It does not transfer the
process's original descriptor into the resource.

The target entry contains:

```crust
var first: Output = output_open();
var output: Output = move first;
defer hello(mut output);
return 0i32;
```

The move makes `first` unavailable and gives its obligation to `output`.
The defer captures an exclusive loan now. At return, the program saves zero,
invokes `hello`, closes `output` through its drop, and returns the saved value.
`hello` handles partial writes until all 18 greeting bytes have been written.
No reference count, resource pool, or target cleanup table is used.

## See which mistakes are rejected

Temporarily replace `move first` with `first`, then repeat the build command.
Compilation must fail with `copy of a resource requires an explicit move`.
A copy would create two cleanup obligations for the same descriptor.

Restore the move. Add `hello(mut output);` after the defer and build again.
Compilation must fail with `access conflicts with an active borrow`. The
deferred call holds its exclusive loan until invocation. Restore the source
after the exercise.

## Keep the adapter contract explicit

Foreign calls and the descriptor field occur in explicit `unsafe` regions.
Failed writes end the process with status 1. Failed implicit close uses status 2.
Process termination does not run pending cleanup. Normal return does.

The stage checks source moves and loans. The small native wrappers remain
responsible for descriptor validity and the write buffer's bytes. The drop
returns `unit`; this example chooses a fatal close policy. An API that needs
to return close errors must handle them explicitly before automatic cleanup.

Continue with the [resource stage tutorial](../../../stages/resources/README.md)
for a visible drop trace, checker state, branch joins, and C cleanup labels.
The [SQLite example](../sqlite/README.md) applies those rules to connections,
statements, borrowed bytes, and failure paths.
