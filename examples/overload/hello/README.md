<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: select a function by type

This example uses one source name for two operations: print a string, or
print a number of greetings. It also selects one of those functions as a
value. All selection occurs during compilation.

Read [Hello World](../../hello/README.md) first. Run these commands from the
repository root on Linux x86-64:

```sh
make all overload-stage
build/crust examples/overload/hello/main.crs
build/overload-hello
```

Expected output:

```text
A typed function value.
Hello, overloads!
```

## Select the compiler stage

Open [main.crs](main.crs). Its first actions load the build request interface,
the overload API, and `build/crust-overload-library.so`. The final root call is:

```crust
return overload_build((*run).source, (*run).cursor, 2i32, &arguments[0usize]);
```

The argument array selects `build/overload-hello` as the output. The cursor
points past this return statement. The stage reads the remaining declarations
with overload rules, then uses the C backend. Root setup needs no new syntax.

## Follow each selection

The two `hello` definitions take `*u8` and `u32`. Both return `i32` so they
can report a failed output call. The `u32` version loops and calls the string
version once per iteration.

The target entry contains:

```crust
var say: fn(*u8) -> i32 = hello;
if say("A typed function value.") != 0i32 { return 1i32; }
return hello(1u32);
```

The first line gives the resolver a complete function type. It selects the
string function and stores its address in `say`. The last line selects the
integer function because `1u32` has type `u32`. Return context does not select
a call overload. Arguments must match the parameter types exactly.

## Change the program

Change `hello(1u32)` to `hello(2u32)` and repeat the build and run commands.
The second greeting must print twice. Change it to `hello(1u64)` and build
again. Compilation must fail with `no overload matches the exact parameter
types`. Restore `1u32` after the exercise.

## Follow the implementation

The stage collects all signatures, selects calls by exact parameter keys,
and rewrites each function to a unique internal name. It also assigns a
stable native symbol for separate compilation. The next checker validates
the rewritten program. No runtime type test selects the call.

Continue with the [overload stage tutorial](../../../stages/overload/README.md)
for the resolver source, diagnostics, name encoding, and ownership hooks.
Then run the [separate-object example](../separate/README.md) to check that
independent caller and provider builds agree on those symbols.
