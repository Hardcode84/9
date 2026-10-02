<!-- SPDX-License-Identifier: Apache-2.0 -->

# Bootstrap native compilation in one file

[main.crs](main.crs) starts with the C99 seed, loads the external assembly
stage, and builds its selected executor and C stage from Crust sources. It then runs two native compilation functions and builds the
target program from the unread tail of the same file.

```sh
make all
build/crust examples/native/main.crs
build/native-hello
```

The program prints `Hello from a bootstrapped native stage!`. `make all` builds
the selected assembly library. The example uses GNU assembler and GCC.
Use the [cache tutorial](../cached-backend/README.md) for source-only startup
and reuse of the prepared native stages.

The first function selects the C backend for the second function. Both access
the same earlier state and callback. The root checks that the state address
and callable identities survive the handoff, and that setup ran once.

To emit target C without target compilation or linking:

```sh
build/crust examples/native/main.crs --emit-c -o build/native-hello.c --symbols build/native-hello.rsp
```

Trailing arguments go to the C target driver. Source and temporary paths use
the root directory. An explicit `-o` path uses the working directory.

Continue with the [native stage tutorial](../../stages/native/README.md) for
the compilation flow, action contract, ownership rules, and backend selection.
