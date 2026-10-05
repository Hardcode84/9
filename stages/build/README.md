<!-- SPDX-License-Identifier: Apache-2.0 -->

# Source-owned stage preparation

A compilation program prepares its stages from source. Make builds the C99
seed. The code in this directory selects source inputs, prepares the C backend,
and reuses validated native libraries through the [artifact cache](../cache/README.md).

## Use a stage

Build the seed once:

```sh
make all
```

A root at `examples/hello/main.crs` selects the C backend with these actions:

```crust
host_source(run, "../../stages/build/load.crs");
if !stage_setup(run, "../..") { return 1i32; };
var stages: *StageSession = stage_open(run, "../..", "../../build/stage-cache");
if stages == null(*StageSession) { return 1i32; };
host_source(run, "../../stages/c/build.crs");
```

`stage_setup` loads the shared preparation functions and their interfaces.
Call it once in a root. `stage_open` captures the toolchain inputs and obtains
native C backend code. Its first build interprets C emission. Later calls
reuse the cached library. A session keeps its code loaded until the root ends.
The C backend's consumer interface is available after setup.

Select another stage with the same session:

```crust
if !stage_load(stages, "stages/ownership/package.crs") { return 1i32; };
host_source(run, "../../stages/ownership/api.crs");
```

Load that stage's consumer declarations before calling its functions. The
stage's package selects its implementation inputs. The root selects its use.
Paths passed to `stage_load` start at the package base given to `stage_open`.
An absolute manifest path can select code outside that base.

`stage_library(stages, path)` returns the validated artifact path without
loading it. Use this form when another native image must link against the
stage. Call `crust_run_link` to load the returned path for root calls.

## Define a package

A package is an ordinary Crust compilation program. It receives
`stage: *StagePackage`. For example:

```crust
stage_include(stage, "sources.crs");
stage_export(stage, "my_program");
```

Its `sources.crs` can contain:

```crust
stage_include(stage, "../c/sources.crs");
stage_source(stage, "model.crs");
stage_source(stage, "program.crs");
```

`stage_source` captures one declaration unit. `stage_include` executes another
package file. Paths in these calls start at the current package file's directory.
Repeated canonical paths contribute one source. Include nesting has a limit of
64. An included package can add sources and exports to its caller. Package
declarations share the root namespace. Give helper functions distinct names
and include each helper definition once per root.

Keep reusable source lists in `sources.crs`. Keep the public native exports in
`package.crs`. A source dependency can then reuse implementation code without
publishing its functions. To publish another package's API as part of a combined
stage, include its `package.crs` explicitly.

`stage_export` selects a defined function or constant by its source name.
`stage_export_as(stage, source_name, native_name)` selects a different native
name. Conflicting native names for the same definition are errors.
`stage_interface` selects the native names from a consumer interface's external
function declarations. The selected definitions must exist in the package.
The producer exports the generated API digest constants as well.

## Select a package compiler

A package can select a compiler implemented by another package:

```crust
stage_compiler(stage, "../generics/ownership/compiler-package.crs", "og_stage_compile");
stage_source(stage, "program.crs");
```

The compiler package is built through the same loader. Its exported function
has type `fn(*StageCompile) -> bool`. The request in
[interface.crs](interface.crs) contains captured sources, source options,
exports, a diagnostic context, and paths for C text and a symbol map. The
callback must write both outputs on success. It must retain a diagnostic on
failure. It owns its parser and checker storage through emission and must copy
any diagnostic into the request context before it releases that storage.
The shared builder runs GCC and the linker and publishes the cached artifact.

The compiler receives captured bytes. It must include each selected export
and the native API digest constants that its output requires. The shared
`stage_names` helper assigns those names to a seed-compatible checked tree.
A compiler with another representation can assign them itself. Compiler
selection and source options are ordinary package calls. The loader has no
ownership or union rules.

`stage_source_option(stage, source, option)` attaches a compiler-defined string
to a captured source. Repeated equal options are accepted. Conflicting options
fail. The ownership compiler accepts these options:

| Option | Contract |
| --- | --- |
| Empty string, the default | Check ownership and generic contracts |
| `trusted` | Trust bodies; retain the source's explicit record contracts |
| `raw` | Trust bodies and expose records as opaque representations |

Select trust at the point where the package captures the source. For example,
a package that adds a new provider can use:

```crust
stage_source(stage, "provider.crs");
stage_source_option(stage, stage->sources.items[stage->sources.count - 1usize], "trusted");
stage_source(stage, "client.crs");
```

Use the source's existing entry when it was already captured. The
[union package](../union/sources.crs) uses these calls to check its layout
algorithms and select its pointer provider. It bootstraps its checker from
source on a cache miss. Compiler dependency nesting has a limit of 64; a cycle
produces a diagnostic.

To emit a package for a test or a measurement, use the shared emission root:

```sh
build/crust stages/build/emit.crs PACKAGE C-OUTPUT SYMBOLS-OUTPUT
```

This selects the package compiler and stops after C emission. Paths are
relative to `stages/build`; absolute paths also work. The caller can compile
and link this output with its selected test flags.

## Cache inputs and failures

A session captures the seed executable, loaded native libraries, preparation
sources, tools, and system header output. A library key includes these inputs,
all included package files, captured declaration units, selected exports, and
the compiled backend used to emit it. A selected compiler adds its native
image and entry name to the key. Source options are also key inputs. Changes to transitive sources invalidate
the library even when file modification times stay the same.

The build callback reads the captured declaration bytes. A source file change
after capture affects the next selection. It cannot replace bytes in a build
that already captured the source.

Package programs run with the root's authority. When a package reads another
configuration input, add its captured bytes to `stage.inputs` with `cache_add`.
Keep the installed toolchain fixed during preparation. The caller owns the cache
directory and its parent must exist. Keep cached files unchanged and live while loaded code
uses them. Do not share this directory with untrusted writers.

A failed check stops preparation. The loader checks artifact contents on a hit.
A damaged artifact produces a diagnostic. The cache publishes a completed
artifact atomically. It checks a concurrent publisher's result before reuse.

The provider uses GCC, GNU assembler, `objcopy`, and the system linker on Linux
x86-64. This policy is Crust code in this stage. The seed has no package names,
cache paths, or backend-selection rules.

## Run a command tool

A tool package includes its declaration sources and exports its `main` function
as `crust_tool_main`, with type `fn(i32, **u8) -> i32`. The shared root prepares that package
and passes the command arguments to it:

```sh
build/crust stages/build/run.crs stages/c/tool.crs --check examples/intrusive/raw.crs
build/crust stages/build/run.crs stages/ccn/tool.crs --CCN 15 examples/hello/main.crs
build/crust stages/build/run.crs stages/highlight/tool.crs --tokens examples/hello/main.crs
```

This uses the same cache and package API as compilation roots.

## Inspect and test

The source runner can execute package queries:

```sh
build/crust stages/build/main.crs sources stages/ownership/package.crs ../../build/stage-cache
build/crust stages/build/main.crs exports stages/ownership/package.crs ../../build/stage-cache
build/crust stages/build/main.crs library stages/ownership/package.crs ../../build/stage-cache
make check-cache
```

The cache argument of this command is relative to `stages/build`. Use an
absolute cache path or `../../build/stage-cache` for a repository build.
Source and export queries print one item per line. A library query prints its
validated artifact path. Tests use these same package files to prepare native
test drivers. `make test-tools` prepares those fixtures. Application roots use
the source API above.

Measure source bootstrap and cache validation separately from application
compilation with an installed backend. Exclude target GCC compilation and
linking from frontend measurements.
