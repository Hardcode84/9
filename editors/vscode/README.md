# Crust for VS Code

This extension gets source classifications from a program written in Crust.
It supports saved and unsaved `.crs` documents. The bundled service classifies
seed syntax. A trusted workspace can select another Crust service.

## Build and install

Run from the repository root on Linux x86-64:

```sh
make all highlight-stage vscode
code --install-extension build/crust-vscode.vsix
```

You can also use **Extensions: Install from VSIX...** and select that file.
The package contains the native highlighter built on this host. It uses the
host C library. In a remote workspace, install it on the Linux x86-64 host
where the extension runs.

The package builder uses Python. It does not require npm, a JavaScript
compiler, or downloaded build packages. The adapter runs in VS Code's
extension host.

Open a `.crs` file. The extension registers the Crust language and supplies
semantic tokens. The language default enables semantic highlighting. A user
setting can disable it. Use a theme with semantic token colors, such as a
built-in VS Code theme.

## Select a user service

The default service never executes the input program. It reads the editor's
text as data and classifies seed syntax. It does not discover syntax changes
by running the root. To select the tutorial's reader-switch service, open
this repository as a trusted workspace and set:

```json
{
  "crust.highlighter.path": "build/crust",
  "crust.highlighter.arguments": [
    "${workspaceFolder}/examples/highlight/reader-switch.crs"
  ]
}
```

Then open `examples/reader-switch/main.crs`. The final text lines have string
classification. This profile requires the first line with `> ` to start the
text section. Documents without that marker are marked unresolved. Remove
the two settings to restore the seed service for all documents.

A custom executable must accept its configured arguments followed by
`--tokens SNAPSHOT`. It must write the version 1 JSON result defined in the
[highlighting tutorial](../../stages/highlight/README.md). Diagnostics go to
standard error and failures return a nonzero status. A successful response
must leave standard error empty.

Relative executable paths with a directory separator use the workspace
folder. `${workspaceFolder}` is expanded in the path and arguments. Other
shell expressions are not expanded. A custom service can be a compiled
Crust program or the `crust` launcher with an analysis root as its argument.

Workspace Trust gates custom executables. Untrusted workspaces always use
the bundled seed service. Trust permits project code to run; it does not
sandbox that code. The analysis root must avoid target builds and other
effects that are not needed for classification.

## Transport and errors

The adapter captures the document version and text. It writes a private
temporary snapshot, starts the selected process without a shell, and
converts returned byte ranges to UTF-16 positions. It removes the snapshot
after the process stops. A service sees the snapshot path, not the original
file path. Supply project configuration through the service's arguments.

Requests are cancelled when superseded, closed, or disposed. Stale results
cannot color a later document version. The default process timeout is five
seconds; `crust.highlighter.timeoutMs` accepts 100 through 60000 milliseconds.
The adapter kills the direct process on cancellation or timeout. This is
not a process sandbox for custom services or their descendants.

The input limit is 4 MiB of UTF-8. The output limit is 128 MiB. The diagnostic
limit is 64 KiB. An unpaired UTF-16 surrogate is rejected. Input limits,
process failures, and malformed responses produce a diagnostic and a message
in the **Crust highlighting** output channel. The first invalid token and
first unresolved region each get a diagnostic; classification continues.

The default comment and bracket commands use seed syntax. A custom token
service changes colors; it does not change those editor commands.

Run `make check-vscode` with Bun to check the adapter and provider. These
checks include real Crust processes, Unicode, unsaved text, cancellation,
stale results, workspace trust, and malformed responses.
