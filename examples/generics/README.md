<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: generics

A pair stores two values of the same type. Write its record and operations once,
then use them with the types that your program needs.

This example uses pairs of positions and pairs of samples. The source selects
those types at each use. The compilation program loads the generics stage and
passes it the input files.

| File | Purpose |
| --- | --- |
| [main.crs](main.crs) | Select the stages and input files |
| [pair.crs](pair.crs) | Define the generic record and functions |
| [types.crs](types.crs) | Define the element types |
| [program.crs](program.crs) | Use the pairs and check their values and layout |
| [setup.crs](setup.crs), [build.crs](build.crs) | Load the libraries and run the build |

## 1. Load the stage

[main.crs](main.crs) is the compilation program:

```crust
host_source(run, "setup.crs");
if !load_example_stages(run) { return 1i32; };
host_source(run, "build.crs");

var inputs: [*u8; 3] = make [*u8; 3] { "types.crs", "pair.crs", "program.crs" };
return generic_build(run, &inputs[0usize], 3usize);
```

Keep [setup.crs](setup.crs) and [build.crs](build.crs) beside this file. They are
ordinary compilation code supplied by the example. `setup.crs` loads the C
backend and the generics stage. Its generics calls are:

```crust
host_source(root, "../../stages/generics/source_model.crs");
host_source(root, "../../stages/generics/source_api.crs");
host_link(root, "../../build/crust-generics-library.so");
```

`generic_build` reads the selected inputs into one module, checks the program,
and passes the resulting declarations to the backend. Names are visible across
these files, including references to declarations that appear later.

## 2. Define the generic code

Declare type parameters after the name with `!(...)`. In [pair.crs](pair.crs):

```crust
record Pair!(Element) { first: Element; second: Element; }

fn exchange!(Element)(left: *Element, right: *Element) -> unit {
    var saved: Element = *left;
    *left = *right;
    *right = saved;
}

fn pair_swap!(Element)(pair: *Pair!(Element)) -> unit {
    exchange!(Element)(&(*pair).first, &(*pair).second);
}
```

Each declaration owns its parameter list. `Element` names a type throughout that
record or function. `Pair!(Element)` refers to the pair for that type.
`exchange!(Element)` selects a function; the following parentheses supply its
ordinary arguments.

Parameter names can be any valid identifiers. A declaration can have more than
one parameter:

```crust
record Entry!(Key, Value) { key: Key; value: Value; }
```

Arguments are explicit types in parameter order. For example,
`Entry!(i32, *u8)` has an integer key and a pointer value.

The type must support the operations in the requested function. `exchange`
copies values. The source stage substitutes the selected type, then the seed
checks the concrete function. An unused generic function contributes no concrete
function body. Repeated uses of one declaration with the same types share an
instance.

## 3. Use the generic code

[types.crs](types.crs) defines ordinary element types:

```crust
record Position { x: i64; y: i64; }
record Sample { value: i32; tag: u8; }
```

Use `Pair!(Position)` as a type and `pair_swap!(Position)` as a function:

```crust
fn main(argc: i32, argv: **u8) -> i32 {
    var pair: Pair!(Position) = make Pair!(Position) {
        first: make Position { x: 10i64, y: 20i64 },
        second: make Position { x: 30i64, y: 40i64 }
    };
    pair_swap!(Position)(&pair);
    if pair.first.x != 30i64 || pair.second.x != 10i64 { trap; }
    return 0i32;
}
```

[program.crs](program.crs) also calls `pair_init` and `pair_first`, which
[pair.crs](pair.crs) defines with the same syntax. It checks both element types,
the pair sizes, alignments, and field positions. Each compiled pair has two
ordinary element fields. Each compiled operation is a direct function call.

The helpers use raw pointers. Supply valid addresses and keep the storage live
while a helper uses it. Their assignments copy values; resource transfer requires
ownership contracts and the ownership stage.

## 4. Build and run

Run from the repository root:

```sh
make all c-stage generics-stage
build/crust examples/generics/main.crs
build/generics
```

The program prints:

```text
generics: OK
```

To inspect the generated C, run:

```sh
build/crust examples/generics/main.crs --emit-c
```

This writes `build/generics.c` and its symbol map, `build/generics.rsp`.
[handwritten.crs](handwritten.crs) contains the same operations written for each
element type, with the same value and layout checks. The tests compile both
versions and compare their output. They also pass the generic program to the ASM
backend.

See the [stage reference](../../stages/generics/README.md) for the source API,
checking rules, and direct use from compilation code.
