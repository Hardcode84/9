<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: generics

Write the pair operations once. The compilation program selects the element
types and gives each instance names that the application can use.

| File | Purpose |
| --- | --- |
| [main.crs](main.crs) | Select the generic definition, arguments, and application names |
| [pair.crs](pair.crs) | Define the shared record and functions |
| [types.crs](types.crs) | Define the element types |
| [program.crs](program.crs) | Use the concrete pairs |
| [setup.crs](setup.crs), [build.crs](build.crs) | Load the libraries and run the build |

## 1. Include the stage

Start [main.crs](main.crs) with:

```crust
host_source(run, "setup.crs");
load_example_stages(run);
host_source(run, "build.crs");
```

[setup.crs](setup.crs) loads the libraries. Its generics-stage calls are:

```crust
host_source(root, "../../stages/generics/model.crs");
host_source(root, "../../stages/generics/api.crs");
host_link(root, "../../build/crust-generics-library.so");
```

[build.crs](build.crs) supplies the build helpers used below. It reads the input
files, reports errors, and passes the checked program to the C backend. These
helpers are ordinary code supplied by this example.

## 2. Define the shared code

The compilation program declares the parameter name explicitly:

```crust
generic_definition(build, "pair.crs", "T");
```

The last argument registers `T` as a type parameter for this definition. In
[pair.crs](pair.crs), use that name for the element type:

```crust
record Pair { first: T; second: T; }

fn pair_init(pair: *Pair, first: *T, second: *T) -> unit {
    (*pair).first = *first;
    (*pair).second = *second;
}

fn exchange(left: *T, right: *T) -> unit {
    var saved: T = *left;
    *left = *right;
    *right = saved;
}

fn pair_swap(pair: *Pair) -> unit {
    exchange(&(*pair).first, &(*pair).second);
}

fn pair_first(pair: *Pair) -> *T {
    return &(*pair).first;
}
```

The definition uses ordinary records, functions, pointers, and assignments.
The compilation program supplies the concrete type for `T` before the seed
checks the code.

Parameter names can contain multiple letters. For example, pass `"Element"`
to `generic_definition` and write `Element` in the shared source:

```crust
record Pair { first: Element; second: Element; }
```

Use any valid identifier and use the same spelling in both places. An
unregistered type name must resolve to a record declared in the definition or
to an explicitly captured external record. Otherwise, checking the instance
reports an unknown name. The example helper accepts one type parameter; the
stage's `gs_define` API accepts a list, such as `Key` and `Value`.

[types.crs](types.crs) defines the two element types:

```crust
record Position { x: i64; y: i64; }
record Sample { value: i32; tag: u8; }
```

## 3. Create instances and select names

Add this configuration after the loading calls in `main.crs`:

```crust
fn configure(build: *GenericBuild) -> bool {
    var pair: *GsDefinition = generic_definition(build, "pair.crs", "T");
    if pair == null(*GsDefinition) { return false; }
    var positions: *GsInstance = generic_instance(build, pair, "Position");
    if positions == null(*GsInstance) { return false; }
    var samples: *GsInstance = generic_instance(build, pair, "Sample");
    if samples == null(*GsInstance) { return false; }

    var target: *CrustContext = &(*build).target.context;
    return gs_bind(target, positions, "Pair", "PositionPair") &&
           gs_bind(target, positions, "pair_init", "position_pair_init") &&
           gs_bind(target, positions, "pair_swap", "position_pair_swap") &&
           gs_bind(target, positions, "pair_first", "position_pair_first") &&
           gs_bind(target, samples, "Pair", "SamplePair") &&
           gs_bind(target, samples, "pair_init", "sample_pair_init") &&
           gs_bind(target, samples, "pair_swap", "sample_pair_swap") &&
           gs_bind(target, samples, "pair_first", "sample_pair_first");
}

return generic_build(run, "types.crs", "program.crs", configure);
```

`generic_definition` reads the shared source with one named type parameter.
`generic_instance` selects an element type from `types.crs` and calls the
stage's `gs_apply` operation. The stage substitutes the type and checks the
resulting declarations. A repeated request for the same definition and type
reuses the instance.

`gs_bind` makes a selected declaration available to the application. Here the
two instances become `PositionPair` and `SamplePair`, with separate function
names. The shared helper `exchange` remains inside each instance.

`generic_build` loads the element types before it calls `configure`. It then
checks `program.crs` with the selected names and builds the executable.

## 4. Use the concrete types

The application calls ordinary functions. For example:

```crust
fn main(argc: i32, argv: **u8) -> i32 {
    var a: Position = make Position { x: 10i64, y: 20i64 };
    var b: Position = make Position { x: 30i64, y: 40i64 };
    var pair: PositionPair = uninit;
    position_pair_init(&pair, &a, &b);
    position_pair_swap(&pair);
    var first: *Position = position_pair_first(&pair);
    if (*first).x != 30i64 || pair.second.x != 10i64 { trap; }
    return 0i32;
}
```

[program.crs](program.crs) checks both element types and their pair layouts.
The helpers copy values through raw pointers. Supply valid addresses and keep
the pointed-to storage live. Ownership contracts require the ownership stage.

## 5. Build and run

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

To inspect the generated C without target compilation or linking, run:

```sh
build/crust examples/generics/main.crs --emit-c
```

The example writes C files and symbol maps under `build/`.
[handwritten.crs](handwritten.crs) contains the same operations written for
each element type, with the same value and layout checks.

See the [stage reference](../../stages/generics/README.md) for direct API use,
external bindings, supported type arguments, and provider lifetimes.
