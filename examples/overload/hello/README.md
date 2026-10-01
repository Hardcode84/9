# Overloaded hello

Build the optional stage, then run this source file:

```sh
make all overload-stage
build/crust examples/overload/hello/main.crs
build/overload-hello
```

The root selects an ordinary Crust compiler library. That library reads the
remainder of the same file. `hello` accepts a string or a repetition count.
The local function type also selects the string overload without a call.

Expected output:

```text
A typed function value.
Hello, overloads!
```
