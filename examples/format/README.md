<!-- SPDX-License-Identifier: Apache-2.0 -->

# Format Crust source

The formatter applies one style to compilation code and application code.
It is a Crust stage. The root selects the formatting service, and the shared
package code can compile and cache it.

## Use the formatter

Run these commands from the repository root:

```sh
make all
build/crust examples/format/main.crs examples/hello/main.crs
build/crust examples/format/main.crs --check examples/format/main.crs
build/crust examples/format/main.crs --write examples/format/main.crs
```

The first command with a source path writes formatted text to stdout. Use one
input file in this mode. `--check` lists files that need changes. `--write`
updates the specified files. These two modes accept several paths. Put `--`
before a path that starts with `-`. Paths are relative to the working directory.

| Exit status | Meaning |
| --- | --- |
| 0 | Formatting or writing succeeded; all checked files have the required format |
| 1 | At least one checked file needs formatting |
| 2 | Argument, input, service, allocation, or output error |

For repeated use, run the native tool package:

```sh
build/crust stages/build/run.crs stages/format/tool.crs examples/hello/main.crs
build/crust stages/build/run.crs stages/format/tool.crs --check examples/format/main.crs
```

The shared stage loader builds and caches this package. `make all` builds the
seed. The formatter reads the specified files as data. Only its selected root
and services execute.

## The style

Input:

```crs
fn identity!(Type)(value:Type)->Type{return value;}
```

Output:

```crs
fn identity!(Type)(value: Type) -> Type {
    return value;
}
```

The fixed rules are:

- Four spaces per block or wrapped group. Empty braces remain compact.
- LF line endings. Nonempty formatted output ends with a newline.
- Spaces between words and around binary operators. Commas and colons have
  a following space. Field access with `.` and indexing remain compact.
- Nonempty braces put their contents on separate lines. `else` follows the
  closing brace on the same line.
- Parenthesized and bracketed groups use block indentation when their estimated
  flat width exceeds the remaining space in a 100-byte line, or contains braces
  or comments. This is a wrapping target. Long expressions outside these
  groups, tokens, and comments can exceed it.
- At most one existing blank line remains at a structural line break.
- Token spelling, token order, and comment text stay intact. CRLF comment
  endings become LF. Strings, comment paragraphs, and numeric literals retain
  their spelling. Commas, parentheses, and other tokens stay in the source.

The same input produces the same output. A second pass leaves the output
unchanged. Validation covers lexical errors and balanced delimiters, with a
maximum nesting depth of 512. Run the selected compiler for grammar, name,
type, and ownership checks.

Ownership, generics, overloads, and unions use the same token rules and
whitespace conventions as raw Crust. Their files use this service directly.
A custom grammar with meaningful whitespace needs its own service.

## Select a service in your root

[main.crs](main.crs) is the complete interpreted formatter root. Its setup is:

```crs
host_source(run, "../../stages/build/load.crs");
host_source(run, "../../stages/format/load.crs");
if !format_setup(run, "../..") { return 1i32; };
return fm_program(run->argc, run->argv, fm_crust, null(*u8));
```

Adjust these three paths to the Crust source package when you put the root in
another directory. `format_setup` loads declarations. Its second argument is
the package directory, relative to the root. The shared `stage_path` helper
resolves the source paths. The final call selects `fm_crust` as the service.
Arguments passed to the root become the formatter's file arguments.

For a different grammar, replace that callback. For example:

```sh
build/crust examples/format/reader-switch.crs examples/reader-switch/main.crs
```

[reader-switch.crs](reader-switch.crs) loads [text.crs](text.crs) and selects
`format_document`. This document grammar starts its text section at the first
line with `> `. The callback formats the complete Crust prefix and copies the
text section unchanged. That choice preserves spaces and punctuation used by
the [reader-switch tutorial](../reader-switch/README.md).

Choose a service from the document's declared grammar. The tool has no automatic
service discovery through the input program. A different embedded grammar must
supply a formatter or an explicit copy policy for its region.

## Use the library

The [source manifest](../../stages/format/sources.crs) can be included in another
stage package. The [library package](../../stages/format/package.crs) exports
the formatter entry points. The [tool package](../../stages/format/tool.crs)
adds the command-line entry point. Both use ordinary package compilation.

For direct calls, initialize a `CrustContext`, a `CrustSource`, and `FmResult`:

```crs
var result: FmResult = uninit;
fm_init(&result, &context, &source);
if !fm_region(&result, 0usize, source.size, fm_crust, null(*u8)) {
    return false;
}
if !fm_finish(&result) { return false; }
// result.output.bytes and result.output.size contain the formatted source.
```

Keep the source bytes live through the last use of the result. The context owns
all tokens, delimiter frames, and output buffers. Destroy the context after the
last result use. Each document can use a separate context.

`fm_region` requires consecutive regions that cover the source in order.
`fm_finish` checks complete coverage before publication. A null service copies
a region unchanged. A callback has this type:

```crs
fn service(result: *FmResult, begin: usize, end: usize, user: *u8) -> bool
```

Offsets are bytes in the original source. The callback receives a valid range.
It appends output through `fm_bytes`, reports failures through `fm_error`, and
returns success. A false return without a diagnostic becomes a formatter error.
Failure is retained; the caller must discard the partial output.

`fm_crust` formats a complete, balanced token region at indentation zero. Use
whole lines for region boundaries. `fm_copy` copies a valid source range.
Composite services can call these functions on validated subranges, as the
text example does. A custom service is responsible for its grammar and for
preserving its program's behavior.

## Implementation and file writes

The formatter reuses `hl_seed`, the lexical service from the
[highlighting stage](../../stages/highlight/README.md). That service retains
source spans for comments and literal spelling. The formatter uses its arena
allocator and output buffer too.

[tokens.crs](../../stages/format/tokens.crs) matches delimiters with an explicit
stack. It records cumulative widths and counts of tokens that require line
breaks. [layout.crs](../../stages/format/layout.crs) uses those records to select
spacing and indentation in one forward pass. Work is proportional to input and
output size. The stages use neither recursive delimiter walks nor repeated
parsing of nested groups.

[program.crs](../../stages/format/program.crs) handles arguments, input, and
publication. [linux.crs](../../stages/format/linux.crs) isolates the Linux
x86-64 file interface. Write mode accepts regular files with one link. It
rejects symbolic links and hard-linked inputs. It writes to a temporary file
in the same directory, closes it, checks that the input metadata is unchanged,
and renames the result over the input. Failed formatting keeps the original.
Unchanged files retain their inode and timestamps.

Replacement retains the ordinary permission bits. The new file gets the
creating user's ownership and the directory's default metadata. Use stdout
when you need a separate tool to retain ACLs, extended attributes, or special
mode bits. Use write mode in a trusted directory with no concurrent writers.
The metadata check detects changes before rename; it provides no lock against
a writer that changes the file after that check. With several paths, each
successful replacement is complete independently of errors on later paths.

## Other formatters

These tools informed the choices above:

| Tool | Relevant behavior | Crust choice |
| --- | --- | --- |
| [Rust style guide](https://doc.rust-lang.org/style-guide/) and [rustfmt](https://github.com/rust-lang/rustfmt/blob/main/README.md) | Four-space indentation, block indentation for wrapped lists, 100-column default, and a check mode | Four spaces, block wrapping, and check mode |
| [Zig formatter](https://github.com/ziglang/zig/blob/master/src/fmt.zig) | Parses through the language AST, rejects parse errors, supports file writes, stdin, and check mode | Shared language tooling, explicit writes, and check mode; Crust validation stops at tokens and delimiters |
| [D dfmt](https://github.com/dlang-community/dfmt) | A standalone formatter with stdout, in-place output, and configurable style through options and EditorConfig | Standalone stage and explicit output modes; one fixed style |
| [Go gofmt](https://pkg.go.dev/cmd/gofmt) | Stdout by default; `-l` lists changed files and `-w` updates them | Stdout by default; separate check and write modes |

Crust's extension point is the service selected by the root. Each service
owns the layout rules for its grammar. Keeping layout outside the compiler
core lets source tools support new readers through ordinary Crust code.

## Check the formatter

```sh
make check-format
python3 tests/tutorials.py --formatter build/format-tests/crust-format
```

The first command checks exact layouts, token and comment preservation,
idempotence over the stage/API/example corpus, interpreted/native parity,
custom services, malformed input, file replacement, and allocation failures
under ASan and UBSan. Inputs that contain a separate text grammar also have
an execution test through their explicit service.

The second command formats copies of the tutorial and stage sources in ignored
build storage. It compiles them through C and LLVM at O0 and O2, then checks
application outputs, rejection diagnostics, and native stage behavior. The
ordinary `make check-tutorials` matrix also compares C-built and LLVM-built
formatter tools with the interpreted root. See the
[backend setup instructions](../README.md#select-a-backend) for the pinned
LLVM toolchain and SQLite test input.
