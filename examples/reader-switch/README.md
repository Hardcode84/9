# Replace the root reader

Run from the repository root after `make all`:

```sh
build/rmd examples/reader-switch/main.rmd
```

The root prints:

```text
Hello from a reader written in RMD!
These lines use the new grammar.
```

[main.rmd](main.rmd) first defines an RMD reader and executor. One root block
installs both callbacks and their state. The block's final semicolon ends the
RMD action. The new reader owns all bytes after it, including the line break.

The new grammar accepts lines that start with `> `. Empty lines are separators.
The executor writes each line's text, including its line break when present.
An invalid prefix produces a diagnostic at its original source position.

Both callback assignments belong in one action. Installing the reader in a
separate earlier action would give it the executor assignment as input.
The source bytes and callback state remain live until root completion.
