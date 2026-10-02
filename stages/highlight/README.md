<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tutorial: a highlighter written in Crust

This tutorial builds HTML output and editor tokens from the same source
classifications. It then selects a custom language service for part of a
file. The highlighter, service interface, and renderers are ordinary Crust
code. The C99 compiler has no special highlighting operation.

Run the commands from the repository root. The native tools target Linux
x86-64. GCC builds the optional native highlighter. Bun runs the editor
adapter tests. No JavaScript package installation is required.

## 1. Highlight a file with a compilation program

```sh
make all
build/crust examples/highlight/main.crs --html examples/hello/main.crs > build/hello.html
```

Open `build/hello.html` in a browser. Keywords, comments, strings, types, and
function declarations have distinct classifications. The source text keeps
its spaces and line breaks.

The [root program](../../examples/highlight/main.crs) loads the reader's
lexical definitions and the highlighting library through `host_source`.
Its final action selects the seed service:

```crs
return hl_program((*run).argc, (*run).argv, hl_seed, null(*u8));
```

`hl_program` reads the named input as data. It creates a context, calls the
selected service, renders its result, writes standard output, and releases
the context and input buffer. It does not execute the input program.
The root which selects this service does execute, as any compilation
program does.

The command works directly through the root evaluator. It does not build
the target in `examples/hello/main.crs` or invoke GCC while highlighting.

## 2. Inspect the intermediate result

Request tokens instead of HTML:

```sh
build/crust examples/highlight/main.crs --tokens examples/hello/main.crs > build/hello.tokens.json
python3 -m json.tool build/hello.tokens.json
```

The result has this shape:

```text
{
  "version": 1,
  "byteLength": source size,
  "tokenTypes": ordered type names,
  "tokenModifiers": ["declaration", "readonly"],
  "spans": [[begin, end, type index, modifier bits], ...]
}
```

Offsets count bytes in the exact input snapshot. Each range is `[begin,end)`.
Ranges are ordered, disjoint, non-empty, and inside the input. Whitespace
needs no token. The renderer copies text between tokens.

The type legend is `keyword`, `comment`, `string`, `number`, `operator`,
`type`, `variable`, `function`, `struct`, `property`, `invalid`, `unresolved`,
in that order. Modifier bit 0 means declaration; bit 1 means readonly.
This legend is fixed for protocol version 1. A syntax service selects these
classes; it does not supply arbitrary HTML or color values.

The seed service identifies lexical categories and declaration names. It
does not resolve references, types, or overloads. Names stay in their source
form; no symbol mangling runs. For example, `read` remains a variable name
in seed syntax. A resource-language service must select its own contextual
rules before treating that word as an operator or type qualifier.

## 3. Prepare a native service

The interpreted root is useful for composition. Compile the same library
once for repeated editor requests:

```sh
make highlight-stage
build/crust-highlight --html examples/hello/main.crs > build/hello-native.html
build/crust-highlight --tokens examples/hello/main.crs > build/hello-native.tokens.json
cmp build/hello.tokens.json build/hello-native.tokens.json
```

`cmp` must report no difference. `make highlight-stage` uses the Crust C
backend and system GCC to prepare `build/crust-highlight`. Each subsequent
highlight request runs that executable. It has no GCC dependency at run
time. Helper compilation is separate from highlighting measurements.

Both interfaces accept `[--html|--tokens] SOURCE`. HTML is the default.
Input paths are relative to the working directory. Prefix a path that
starts with `-` with `./`. Status 2 means invalid command arguments. Status
1 means an input, output, allocation, or service error. Invalid source
tokens are represented in the successful result so editing can continue.
Token mode permits at most 500000 spans. It fails with a diagnostic and no
JSON output if the service exceeds that budget. HTML mode has no span budget.

## 4. Select another grammar

The [reader-switch example](../../examples/reader-switch/README.md) changes
from seed syntax to a line language. A line in the new language starts with
`> `, followed by text. The seed lexer cannot know that these words are text.

Run its explicit highlighting profile:

```sh
build/crust examples/highlight/reader-switch.crs --html examples/reader-switch/main.crs > build/reader-switch.html
build/crust examples/highlight/reader-switch.crs --tokens examples/reader-switch/main.crs > build/reader-switch.tokens.json
```

Open the HTML file. The prefix `>` is an operator; the words after it form
one string span. The first part of the file retains seed highlighting.

The [profile](../../examples/highlight/text.crs) finds the first line with
the `> ` prefix. This is an explicit precondition of this example's profile,
not automatic reader discovery. It classifies the two ranges with ordinary
calls:

```crs
return hl_region(result, begin, split, hl_seed, null(*u8)) &&
       hl_region(result, split, end, text_highlight, null(*u8));
```

A service has this function type:

```crs
fn(*HlResult, usize, usize, *u8) -> bool
```

The parameters are the result, begin offset, end offset, and caller-owned
state. A service appends spans with `hl_add`. It can call other services
through `hl_region`. Its functions and state must remain live during the
call. The result and spans remain live until their context is destroyed;
the caller retains the source bytes until then.

`hl_region` validates its range and checks that the service's output stays
inside it. `hl_add` checks ordering, bounds, classes, and modifier bits.
A failed allocation or service sets `result.failed` and a context diagnostic.
Callers stop on failure. A null service emits an `unresolved` span.
`hl_init` sets `result.span_limit` to the largest `usize` value. Set this field
before adding spans to select a smaller budget. All services that append to
the same result share that budget. A budget failure retains the diagnostic;
the caller must reject the partial result.

If this profile cannot find its marker, it marks the document unresolved.
It does not execute the original program to guess which reader it selects.
Other projects can define different selection rules in their source. No
stage name or source filename is registered with the compiler.

Try changing `HL_STRING` to `HL_COMMENT` in `text_highlight`. Run the root
again and inspect the output. Only the text region changes classification.
Restore `HL_STRING` after the exercise. The editor can use this same root.

## 5. Handle a file while it is being edited

Create an incomplete string followed by a valid function:

```sh
printf '"unfinished\nfn after()->unit{}\n' > build/incomplete.crs
build/crust-highlight --html build/incomplete.crs > build/incomplete.html
```

The string has the `invalid` class. The function on the next line still
has normal highlighting. A malformed string stops at its closing quote,
line break, or EOF. A malformed number consumes its complete identifier-like
token. Other invalid source characters advance by one UTF-8 scalar, or one
byte if the sequence is invalid. Every step makes progress.

The [scanner](scan.crs) shares identifier tests, hexadecimal digit tests,
and the keyword table with the [strict reader](../reader/lex.crs). It scans
without allocating decoded strings or interning names. It retains comments
and reports invalid ranges instead of changing the strict reader's failure
rules. Tests compare token boundaries with the strict reader on repository
sources to detect divergence.

The [HTML renderer](output.crs) escapes markup characters. It displays
invalid UTF-8 and non-whitespace control bytes as `\xHH`. Its style sheet
belongs to the renderer. A different consumer can select another style.
Span and output buffers grow in the supplied context arena. No individual
token has a separate allocation and release operation.

## 6. Install in VS Code

```sh
make vscode
code --install-extension build/crust-vscode.vsix
```

Alternatively, use **Extensions: Install from VSIX...**. Open a `.crs`
document after installation. The package contains the native seed service
and a small JavaScript adapter. It targets the Linux x86-64 host on which
the package was built.

The adapter captures unsaved text and its version. It sends a private
snapshot to the service, validates the response, and converts byte ranges
to the UTF-16 positions required by VS Code. It splits ranges at line
breaks, cancels obsolete requests, and discards stale results. It reports
process and protocol failures through diagnostics and an output channel.

VS Code consumes semantic tokens from the adapter. A language server is
not required. The [extension guide](../../editors/vscode/README.md) gives
custom-service settings, workspace trust rules, input limits, and the
reader-switch configuration. The service selection is explicit; opening
a file does not run that file's compilation actions.

## Checks and measurements

```sh
make check-highlight
make check-vscode
python3 stages/highlight/test.py --build build --sanitize
```

The library checks cover source boundaries, rejected service output, span
budgets, arena allocation failures, HTML text preservation, and input/output
errors. The editor checks run actual Crust processes and check unsaved text,
Unicode, CRLF, stale results, cancellation, timeouts, trust, invalid responses, and
output and token budgets. A multiline span must fit the token budget after
line splitting.
The provider tests supply a VS Code API test double; they do not operate a
graphical editor.

The sanitizer command instruments the generated highlighter and its library
tests with ASan and UBSan. If a tracing sandbox prevents LeakSanitizer from
starting, run with `ASAN_OPTIONS=detect_leaks=0`. The allocator tests still
check that every injected allocation failure releases all arena blocks.

The [measurement method](../../benchmarks/highlight/README.md) separates scanning,
rendering, native process startup, and editor transport. Helper compilation
and GCC linking are outside request measurements.
