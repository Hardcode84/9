<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: tagged unions

An event can contain a position, a key code, or a request to quit. A tagged union
stores one of these values. A `match` statement selects the code for that variant.
The compiler checks that each match covers every variant.

## Load the stage

Run from the repository root:

```sh
make all c-stage union-stage
build/crust examples/union/main.crs
build/union
```

The program prints `union: OK`.

[main.crs](main.crs) selects the union stage and builds [program.crs](program.crs).
To use this setup, copy `main.crs`, adjust its relative paths, and select your
source file in `arguments`. The stage accepts the C backend's build options,
including `--check` and `--emit-c`.

The setup loads three small interfaces and one compiled library:

```crust
host_source(run, "../../api/crust0_stage.crs");
host_source(run, "../../stages/union/api.crs");
host_source(run, "../../stages/union/build.crs");
host_link(run, "../../build/crust-union-library.so");
```

`union_build` receives the source range and command-line arguments. This example
passes a null source range and supplies `program.crs` as an argument. To put the
setup and target program in one file, pass `run->source` and `run->cursor`, then
put the target declarations after the call that returns from the compilation
program. See the [hello-world tutorial](../hello/README.md) for this source-order
execution model.

## Define a union

```crust
record Position { x: i64; y: i64; }

union Event {
    Move: Position;
    Key: u32;
    Quit: unit;
}
```

Each variant has a name and a payload type. `unit` means that the variant has no
payload. Records, arrays, pointers, function values, scalar values, and other
unions can be payloads. A pointer can refer back to its own union type.

## Construct a value

Declare storage, then select a variant:

```crust
var event: Event = uninit;
construct Event.Move(event, make Position { x: 10i64, y: 20i64 });
construct Event.Key(event, 65u32);
construct Event.Quit(event);
```

`construct` takes a destination place and, when required, a payload. It evaluates
the destination once, then the payload, and writes the tag last. Reconstructing
an initialized union replaces its value. Release any owned external resource
before replacing it; this stage supplies value storage and variant checks.

## Read the active variant

```crust
match Event(event) {
    Move(position) {
        if position.x != 10i64 { trap; }
    }
    Key(code) {
        if code != 65u32 { trap; }
    }
    Quit {}
}
```

Write the union type before the expression. Each variant must appear exactly
once. The binding in parentheses is a local copy of its payload. You can omit
that binding when you only need to select an action. A `unit` variant has no
binding.

The match expression is evaluated once. The match takes a value snapshot before
it selects an arm. The binding remains valid if the arm replaces the original
union. Pointer payloads retain ordinary pointer-copy behavior: their targets
must remain live. See `handle` in [program.crs](program.crs) for a function whose
arms all return a result.

Construct a union before its first read. The seed's raw storage and pointer
rules still apply. This stage checks payload types and exhaustive dispatch;
resource lifetimes require a separately composed ownership checker.

See the [stage reference](../../stages/union/README.md) for the lowering contract
and the API used by compilation programs.
