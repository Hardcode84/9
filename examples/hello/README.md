# Hello world in one file

Run from the repository root after `make all c-stage`:

```sh
build/crust examples/hello/main.crs
build/hello
```

The executable prints `Hello, world!` and returns zero.

[main.crs](main.crs) contains both the compilation program and the target
program. The root loads the C backend and sets the output path. Its final
`return c_build(...)` passes the captured source and current cursor to the
backend. That cursor is after the return statement's semicolon. The backend
therefore compiles the remaining declarations as the target program.

The root returns after compilation. It does not execute the target `main`.
Target diagnostics retain the line numbers of this complete file.
