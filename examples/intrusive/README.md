# Intrusive list

Run from the repository root after `make all c-stage`:

```sh
build/crust examples/intrusive/main.crust
build/intrusive-from-root
```

The executable prints `intrusive: ok` and returns zero.

[main.crust](main.crust) builds [program.crust](program.crust) and links the host memory
and output functions. The target inserts and unlinks embedded hooks, destroys
individual nodes while the list remains live, and allocates replacement nodes.
This is a raw-memory bootstrap example. It has no ownership-checking stage.

With arguments, the root passes those arguments to the C backend instead of
using its default output and link arguments. For example:

```sh
build/crust examples/intrusive/main.crust --check
build/crust examples/intrusive/main.crust -o build/list --ldflag build/libcrust0_host.a
build/list
```

Run `make witness` to compare the seed assembly output with the C reference.
