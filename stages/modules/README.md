<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: modules as ordinary Crust code

Two files can use the same private function name. A consumer can import a
record under another name without changing its type. This tutorial builds
those cases with separate compiler contexts and separate native objects.

Module policy belongs to the compilation program. The seed supplies a name
binding operation, `crust_bind`. The [module library](library.crs) selects
which declarations reach that operation. It also owns source snapshots and
sets native link names. No module keywords or compiler registration are used.

## 1. Build and run two modules

Run these commands from the repository root:

```sh
make all c-stage
build/crust examples/modules/main.crs
build/modules
```

The program prints:

```text
modules: 42
```

The [root program](../../examples/modules/main.crs) loads the module library
as source and the C backend as native code. Its `prepare_modules` function
selects two inputs:

| Input | Role |
| --- | --- |
| [provider.crs](../../examples/modules/provider.crs) | Defines `Value`, `increment`, `answer`, and a private `helper` |
| [consumer.crs](../../examples/modules/consumer.crs) | Uses selected imports and defines its own `helper` |

The root emits `build/modules-provider.o`. It then emits and links
`build/modules` with that object. The target contains no module library or
compiler context. Modules have no target runtime cost.

Paths in this root use `host_path`, so they are relative to the root file.
`module_read` itself opens the exact path supplied by its caller. The root
can select another file with an ordinary condition or function call.

## 2. Select names and native symbols

The root initializes one `CrustModule` per namespace. It reads and checks
the provider before it publishes these exports:

```crs
module_export(provider, "Value", "");
module_export(provider, "answer", "tutorial_answer");
module_export(provider, "increment", "tutorial_increment");
```

The complete example checks every result. Functions and constants start
private after `module_check`. An export gives them an explicit nonempty
native name. A record export requires an empty native name because a type
has no native symbol. Exports must be checked definitions owned by the
module. The library rejects duplicate exports and imported reexports.

Inspect the provider object:

```sh
nm -g --defined-only build/modules-provider.o
```

Only `tutorial_answer` and `tutorial_increment` are global definitions.
Both inputs contain `helper`, but each helper is private to its own object.
Choose distinct native names for distinct public definitions that will be
linked together. Changing a source alias does not change its native name.

## 3. Import facts with local names

Before reading and checking the consumer, the root supplies these bindings:

```crs
module_import(consumer, provider, "Value", "Number");
module_import(consumer, provider, "answer", "calculate");
module_import(consumer, provider, "increment", "step");
```

The consumer constructs `Number`, then calls `calculate`:

```crs
var value: Number = make Number { number: step };
if calculate(&value) != helper() { return 1i32; }
```

`Number` denotes the provider's `Value` declaration. It is not a new record
or a structural copy of a record type. The seed validates the imported
layout, signature, constant facts, and identities at `crust_bind`.
The module library does not run another type checker.

The names `Value`, `answer`, and `increment` are absent from the consumer's
namespace. For example, changing `calculate(&value)` to `answer(&value)`
produces `unknown name 'answer'`. Importing `helper` produces
`module name is not exported`. Restore the original call to build again.

Visibility controls which names a consumer can use. It is not a security
sandbox for the compilation program, which can inspect public compiler data.
An exported record exposes its layout and fields.

## 4. Own facts through their last use

`CrustModule` contains a context and an export table. The context arena owns
captured paths, source bytes, syntax, types, and export entries. The file
reader releases its temporary native buffer after copying the bytes.

An import borrows declaration facts from its provider. It does not copy the
provider tree. Use this order:

```text
initialize provider and consumer
read provider -> check provider -> select all exports
                                -> bind consumer imports
read consumer -> check consumer
emit provider object -> emit and link consumer
destroy consumer -> destroy provider
```

Finish all export selection before the first consumer borrows facts. Keep
provider facts and stage code unchanged and live through every consumer.
The export lookup reads the provider table without interning a new name in
its context. Separate consumers can therefore read the same provider facts.

The root assigns source identities `1` and `2`. Each input unit needs a
distinct identity across owned and imported declarations. An alias retains
the provider identity. Reusing an identity for a different declaration fails
at the binding or collection boundary.

The library has no hidden scheduler. This root expresses a dependency order
with ordinary calls. It completes a provider before preparing its consumer;
this policy does not admit import cycles. It does not resolve packages or
search directories. Those choices remain code in the root program.

Stop after an operation fails. Its context retains a diagnostic. The example
reports diagnostics before it destroys either context, then destroys the
consumer first. There is no phase flag to permit a second check or later
export mutation while consumers still use old facts.

## 5. Derive a real library's export list

The build uses [exports.crs](exports.crs) to derive the C backend's exports
from its consumer interfaces:

```sh
build/crust stages/modules/exports.crs stages/c/api.crs stages/c/extension.crs
```

The root reads every supplied path, then emits one `--export NAME` argument
for each external function declaration. It checks all names before it writes
output. The Makefile uses this output to select the C backend library exports.
Changing a consumer declaration changes the next library build's exports.
The library also exports the generated public API digest constants. The root
loader checks these constants when it loads the library.

This operation reads syntax; it does not resolve interface types or prove
ABI compatibility with the implementation. The C backend CLI checks that each
selected export names a definition. Tests check the requested names, the API
digest constants, and the library's consumers.

The CLI's export option uses one name for both source lookup and native
linkage. Thus this helper rejects interfaces whose source and native names
differ. The module API itself supports distinct names, as step 2 shows.
Argument paths for this command are relative to the working directory.

## 6. Check the boundaries

```sh
make check-modules
```

The checks run the unchanged tutorial from a directory with spaces and a
different working directory. They inspect native exports, check alias type
identity, compare provider facts before and after consumer checks, and reject
private names, duplicate exports, conflicting identities, and reexports.
They also check file and output failures and inject failure at each arena
backing allocation while preparing a larger provider and its consumer.

For the underlying contracts, read the
[module design](../../docs/crust0-spec.md#module-management-is-a-metastage),
[C backend tutorial](../c/README.md), and
[source runner guide](../../docs/source-runner.md).
