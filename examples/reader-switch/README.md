<!-- SPDX-License-Identifier: Apache-2.0 -->

# Replace the root reader

Run from the repository root after `make all`:

```sh
build/crust examples/reader-switch/main.crs
```

The root prints:

```text
Hello from a reader written in CRUST!
These lines use the new grammar.
```

[main.crs](main.crs) first defines a Crust reader and executor. One root block
installs both callbacks and their state. The block's final semicolon ends the
Crust action. The new reader owns all bytes after it, including the line break.

The new grammar accepts lines that start with `> `. Empty lines are separators.
The executor writes each line's text, including its line break when present.
An invalid prefix produces a diagnostic at its original source position.

Both callback assignments belong in one action. Installing the reader in a
separate earlier action would give it the executor assignment as input.
The loop captures both callbacks and `run.user` before each read. Both callbacks
receive that user pointer as their second argument. Changes to the fields select
the next action's operations and state. The source bytes and callback state
remain live until root completion.
