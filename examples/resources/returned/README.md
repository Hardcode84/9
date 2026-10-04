<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: return a borrowed field

A function can return a view into its input without copying the record or
transferring its owner. The caller must keep that input available while the
view is live. This example uses a read view, then a mutable view, and prints
the updated value.

Run these commands from the repository root on Linux x86-64:

```sh
make all resource-stage
build/crust examples/resources/returned/main.crs
build/resource-returned
```

Expected output:

```text
42
```

## Declare the source of the result

Open [main.crs](main.crs). The root program loads the resource stage. That
stage reads the target declarations after the root returns.

```crust
fn current(counter:read Counter)->read i32 from counter {
    return read counter.value;
}
```

`from counter` ties the result to that borrow parameter. The stage checks
each return. A return cannot borrow new local storage, a different parameter,
or storage reached only through a raw pointer.

The call transfers its temporary input loan to the result. A named local view
ends at `drop` or scope exit. The loan remains live after `current` returns.

## End one loan before the next

The first block holds a read view. The second block holds an exclusive view
from `update`. Assigning to that view changes `counter.value`. The last call
passes a returned read view to `print_number` and releases it after the call.

The current checker borrows the whole source record. It does not permit a
write to another field while a read view remains live. The target uses
pointers for these views. It has no reference count or loan table.

## Check the rejection paths

Add `counter.value = 0i32;` after the declaration of `before`, inside its
block. Compilation fails with `access conflicts with an active borrow`.
Restore the source after this check.

Next, add `var local:i32 = 7i32;` inside `current` and replace its return
with `return read local;`. Compilation fails because that loan does not
come from `counter`. Restore the source again.

Functions with this result contract must be called directly. The stage
rejects storing them in function values: the function type syntax cannot
carry the `from` dependency. A mutable result also requires a mutable source
parameter. An `unsafe` block does not remove these checks.

The small `print_number` adapter contains the foreign calls. The returned
views themselves need no `unsafe` block. The [resource reference](../../../stages/resources/reference.md)
describes source imports and the programmatic `rs_return_from` interface.
