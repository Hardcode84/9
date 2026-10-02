<!-- SPDX-License-Identifier: Apache-2.0 -->

# Check function complexity

Follow the [CCN tutorial](../../stages/ccn/README.md) for the counting rule,
AST walk, allocation contract, build integration, and comparison with Lizard.

Run from the repository root:

```sh
make all
build/crust examples/ccn/main.crs examples/ccn/program.crs
make c-stage
build/crust examples/ccn/build.crs
build/ccn-example
```

The report gives CCN 4 for `score` and CCN 2 for `main`. The build root uses a
limit of 4. It checks the parsed target before type checking and C emission.
The executable returns status 0.

| File | Purpose |
| --- | --- |
| [main.crs](main.crs) | Select the checker and inspect file arguments as data |
| [build.crs](build.crs) | Check an already parsed unit before backend emission |
| [program.crs](program.crs) | Provide a target with two measured functions |

The report command takes input paths relative to the working directory.
The build root resolves its input and output relative to itself. Its output
is `build/ccn-example`. It uses the existing C backend library.

Use `make ccn-stage` to build the native `build/crust-ccn` command. Run
`make check-ccn` to check both commands and the compilation example.
