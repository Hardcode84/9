# Multiple target files

Run from the repository root after `make all c-stage`:

```sh
build/crust examples/multiple-files/main.crust
build/multiple-files
```

The executable prints `Hello from another source file!` and returns zero.

[main.crust](main.crust) is the compilation program. It captures
[program.crust](program.crust) and supplies [greeting.crust](greeting.crust) as another
target input. The function in the first file can call `greeting`, whose
definition is in the second file. Both target units use one checked namespace.

The root selects the files and their order. No import keyword or file search
is required. `host_source` loads compiler code; `host_input` captures target
source. The C backend reads the additional target path given in its arguments.
