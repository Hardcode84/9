<!-- SPDX-License-Identifier: Apache-2.0 -->

# Combine ownership and overloads

This example selects ownership checking and function overloads in one
compilation program. `read Ticket` and `mut Ticket` select different functions.
The resource destructor and `defer` run when the target function returns.

## Run

From the repository root:

```sh
make all ownership-stage overload-stage
build/crust examples/composition/main.crs
build/composition
```

The output is `!B`, with no newline. `!` comes from the deferred call. `B` comes
from the destructor after the mutable overload changes the ticket value from
65 to 66.

## Select the stages

[main.crs](main.crs) is the compilation program. It loads [setup.crs](setup.crs),
calls `composition_stages(run)`, and loads [build.crs](build.crs). The setup
loads the public models and interfaces, then links the C backend, ownership,
and overload libraries. The build helper takes a context, source, and output
options. Call it once for the complete target source.

Keep the source descriptor and bytes live through context destruction. Check
the returned Boolean before using the target. On failure, the context retains
the diagnostic. The root copies that diagnostic to the runner before it destroys
the target context.

## Write the target

[program.crs](program.crs) contains only target declarations. It defines a
resource with an integer payload:

```crust
resource Ticket { value:i32; } drop finish;
fn finish(ticket:mut Ticket)->unit { emit(ticket.value); }
```

Two functions share the name `choose`:

```crust
fn choose(ticket:read Ticket)->i32 { return ticket.value; }
fn choose(ticket:mut Ticket)->i32 {
    ticket.value=ticket.value+1i32;
    return ticket.value;
}
```

The call states the access it needs:

```crust
var ticket:Ticket=make Ticket { value:65i32 };
if choose(read ticket)!=65i32 { return 1i32; }
if choose(mut ticket)!=66i32 { return 2i32; }
defer emit(33i32);
```

Each call's loan ends after that call. Moving `ticket` and then using it fails
ownership checking. Keeping a shared view alive while passing `mut ticket`
also fails. The [ownership tutorial](../../docs/ownership.md) explains those
rules. The [overload tutorial](../../stages/overload/README.md) explains exact
selection and typed function values.

## How the compilation program works

The build helper makes two caller-owned chains. The reader chain combines
ownership declarations with overload function endings. The source query chain
combines ownership contracts with resource type and traversal rules.

```crust
var resource_rules:CsHooks=uninit;
rs_source_hooks(&resources,&resource_rules,null(*CsHooks));
var ownership_rules:CsHooks=uninit;
os_source_hooks(&ownership,&ownership_rules,&resource_rules);
var overloads:OvStage=uninit;
ov_init(&overloads,context,"checked_x64_v1",&ownership_rules);

var interfaces:CrustReaderHooks=uninit;
ov_reader_hooks(&interfaces,null(*CrustReaderHooks));
var reader:CrustReaderHooks=uninit;
os_reader_hooks(&ownership,&reader,&interfaces);
```

`rr_read` tries reader callbacks in chain order. The first callback that handles
the syntax wins. An unhandled callback preserves the input. A diagnostic stops
the read.

After reading, the helper calls `ov_prepare`, `os_lower`, and `os_verify` in that
order. Overload selection needs the original `read` and `mut` types. Ownership
checking then validates the selected calls. The final backend call uses
`rs_c_body` to emit both the checked operations and their cleanup plans.

Each stage supplies its own rules through the shared
[source query interface](../../stages/source/README.md). The root selects the
providers and call order. The [build helper](build.crs) also chooses a single
`main` entry and gives generated helpers private linkage.

`make check-overload` checks the output, matching source declarations, ownership
errors, and contract mismatches. `make check-examples` runs this root from a
copied source tree and a different working directory.
