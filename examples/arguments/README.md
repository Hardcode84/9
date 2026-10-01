# Compiler and program arguments

Run from the repository root after `make all c-stage`:

```sh
build/rmd examples/arguments/main.rmd -o build/arguments
build/arguments first 'two words'
```

The executable prints:

```text
Program arguments:
first
two words
```

[main.rmd](main.rmd) passes its root arguments to the C backend. Here `-o` sets
the executable path relative to the working directory. The target receives
`first` and `two words` when it runs. Its `argv[0]` is the executable name.

Use another backend operation through the same root file:

```sh
build/rmd examples/arguments/main.rmd --check
build/rmd examples/arguments/main.rmd --emit-c -o build/arguments.c --symbols build/arguments.rsp
```

`--check` creates no executable. C and symbol output are separate files. See
the [C backend guide](../../docs/c-backend.md) for their native build commands.
