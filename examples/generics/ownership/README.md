<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: generics with ownership

A container can own a plain value or a resource that needs cleanup. Write its
storage and operations once, then supply the payload type at each use.

This example has an intrusive list with two independent memberships. A node
contains its links and payload. An owner controls the node allocation. Removing
an owner unlinks the node, drops its complete payload, and frees the allocation.
The list can stay live while individual nodes are destroyed and their storage
is reused.

## 1. Select the stage

Build the compiler and the combined external stage:

```sh
make all c-stage ownership-generics-stage
build/crust examples/generics/ownership/main.crs
build/generics-ownership
```

The program prints `HFBFOK`. The letters record resource cleanup. `OK` follows
the membership, payload, and removal checks.

For a program with checked generic helpers, load these interfaces in your
compilation program:

```crust
host_source(run, "../../../api/crust0_stage.crs");
host_source(run, "../../../stages/generics/ownership/api.crs");
host_source(run, "../../../stages/generics/ownership/build.crs");
host_link(run, "../../../build/crust-ownership-generics-library.so");

return ownership_generics_build(null(*CrustSource), 0usize,
    (*run).argc, (*run).argv, null(*CrustSource), 0usize);
```

These paths assume this tutorial's directory. The arguments select source files
and output options. Each source declares its own generic parameters.

The list example also selects [provider.crs](provider.crs) as a trusted pointer
implementation. [main.crs](main.crs) reads that source once and passes it to
`ownership_generics_build`. Every specialization retains that trust selection.
Keep checked application code in the other inputs.

## 2. Define an ownership-generic function

[checked.crs](checked.crs) defines two small operations:

```crust
fn transfer!(Payload)(value: Payload) -> Payload {
    return move value;
}

fn discard!(Payload)(value: Payload) -> unit {
    drop value;
}
```

`!(Payload)` declares the type parameter. Its name is local to the declaration.
Use any valid identifier, and separate multiple parameters with commas.

In this stage, each parameter means a sized, movable record with closed
ownership and cleanup that requires no domain access. A plain record satisfies
that contract. A resource with nested resources or exclusive owned storage can
also satisfy it. Native integer and pointer-shaped handles can be owned fields.

The checker follows nested fields and owned storage. It rejects a payload that
contains stored loans, opaque storage, a stable or scoped value, or a domain
identity. Put the payload's full cleanup contract on its ordinary resource and
function declarations.

Inside the generic body, a parameter is affine: use `move` to transfer it, `read`
or `mut` to borrow it, and `drop` to end its ownership. Scope exit also drops a
live parameter value. The body can query `sizeof(Payload)` and
`alignof(Payload)`. It has no declared payload fields to select or initialize.

For example, this definition fails its contract check:

```crust
fn duplicate!(Payload)(value: Payload) -> Payload {
    return value;
}
```

The error applies even when the only requested specialization uses a plain
record. The function promises to work for resource payloads too.

## 3. Use a generic function

[payloads.crs](payloads.crs) defines `Plain`, an ordinary record, and `Parcel`, a
resource that contains a file-handle resource. [program.crs](program.crs) uses
the same helpers for both:

```crust
var plain: Plain = make Plain { x: 10i32, y: 20i32 };
var copied: Plain = transfer!(Plain)(plain);
discard!(Plain)(copied);

var parcel: Parcel = parcel_new(72i32);
var forwarded: Parcel = transfer!(Parcel)(move parcel);
discard!(Parcel)(move forwarded);
```

`Plain` is copyable at the call boundary. The call gets an independent value.
`Parcel` transfers with `move`. Its old binding becomes unavailable. The
specialized `discard` runs the parcel destructor, drops its nested ticket,
and closes the ticket's handle.

The two payloads have the same size and alignment. Their cleanup obligations
still differ. Type identity and declared contracts select the specialization.

## 4. Store a payload in the intrusive container

The provider separates links from payload storage:

```crust
record Link { prev: *Link; next: *Link; } opaque;
record Node!(Payload) { ready: Link; active: Link; value: Payload; } opaque;
resource Owner!(Payload) { node: *Node!(Payload); }
    opaque drop owner_drop!(Payload);
```

Read the full annotations in [provider.crs](provider.crs). Its `Head` contains
only a `Link`. An empty list therefore needs no payload value or dummy resource.
The domain declaration names each record family once:

```crust
domain Graph(Link, Head, Node, Owner);
```

Both `Node!(Plain)` and `Node!(Parcel)` belong to that domain. Links can be
counted and unlinked without access to a payload. Payload access starts from
an owner and returns a loan with an explicit origin:

```crust
fn owner_value!(Payload)(owner: read Owner!(Payload)) -> read Payload
    access(read, Graph) from owner {
    return read (*owner.node).value;
}
```

A head or end link has no payload projection. The owner supplies the storage
and lifetime for each payload loan. A live loan prevents removal of that owner.

The trusted destructor unlinks both memberships, executes `drop *owner.node`,
and then releases the allocation. That `drop` includes the concrete payload's
complete recursive cleanup. The checker verifies clients against these
interfaces. Native tests and sanitizers exercise the trusted pointer operations.

## 5. Inspect the generated code

```sh
build/crust examples/generics/ownership/main.crs --emit-c \
  -o build/generics-ownership.c \
  examples/generics/ownership/payloads.crs \
  examples/generics/ownership/checked.crs \
  examples/generics/ownership/program.crs
```

Each specialization has concrete record layouts and direct function calls.
Cleanup expands for the concrete payload. Ownership facts and generic argument
tables stay in the compiler.

The tests compare this output with the explicit specializations in
[handwritten.crs](handwritten.crs) and
[trusted-handwritten.crs](trusted-handwritten.crs). They also check individual
storage reuse, client rejections, and independent provider imports. See the
[stage contract](../../../stages/generics/ownership/README.md) for the proof and
artifact interfaces.
