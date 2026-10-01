<!-- SPDX-License-Identifier: Apache-2.0 -->

# Highlight source with a Crust program

Follow the [highlighting tutorial](../../stages/highlight/README.md) for the
design, implementation, custom reader service, editor adapter, and checks.

Run from the repository root:

```sh
make all highlight-stage
build/crust examples/highlight/main.crs --html examples/hello/main.crs > build/hello.html
build/crust-highlight --tokens examples/hello/main.crs > build/hello.tokens.json
build/crust examples/highlight/reader-switch.crs --html examples/reader-switch/main.crs > build/reader-switch.html
```

Open the HTML files in a browser. The first command uses the source runner.
The native executable uses the same seed service. The last command selects
a user service for the line language in the reader-switch example.

| File | Purpose |
| --- | --- |
| [main.crs](main.crs) | Select the seed highlighter through ordinary root calls |
| [reader-switch.crs](reader-switch.crs) | Select the mixed-language service |
| [text.crs](text.crs) | Classify the seed prefix and the following text lines |

The source under inspection is data. These programs do not execute it.
Run `make check-highlight` to check both roots and the native executable.
