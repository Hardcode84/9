<!-- SPDX-License-Identifier: Apache-2.0 -->

# AST layout experiment

This tool tests whether a smaller seed expression node can reduce frontend
memory use enough to justify an API change. It builds two compiler copies
under `build/`. The production compiler and stage API stay unchanged.

Run from the repository root on Linux x86-64. Install Python 3.10 or later,
GCC, Clang 20, GNU Make, and GNU time. Select a CPU in your allowed affinity set
and a new output directory:

```sh
python3 benchmarks/ast-layout/measure.py --cpu 4 --output build/ast-layout/run-1
```

The tool returns status 2 if a measurement or migration gate fails. A build,
validation, or tool failure stops the run with a diagnostic. Use a new output
directory for each run. Keep captured reports and sources unchanged.

## Candidate

The baseline uses the current seed layout. The candidate puts expression
location, type, kind, and place flags in a common header. Four named C99 unions
hold the remaining fields. Fields that coexist in one expression kind occupy
different unions. Nodes retain one fixed allocation size; payload access has
no extra allocation, pointer lookup, or kind test.

`layout.py` checks the field set and expression kinds against the header.
Clang supplies C member reference locations for the source rewrite. Only the
copied core, reader, checker, and test driver use the changed layout. Other
node families retain their baseline layouts.

## Inputs and checks

The tool generates the ordinary-function scaling inputs from
[the bootstrap benchmark](../bootstrap/measure.py), from 1,000 through 64,000
functions. It also captures the actual `C_STAGE` source list from the Makefile.
That case reads and checks the C backend stage as a program.

Both copies must pass these checks before measurement:

- Pedantic C99 builds with the production warning flags.
- Reader tests and checking of the runtime and raw intrusive-list examples.
- Separate-file builds, in addition to the amalgamated builds.
- AddressSanitizer and UndefinedBehaviorSanitizer checks on the smallest
  scaling input and the C backend stage.
- Equal node counts for each kind in both copies.

The candidate stops at seed checking. It does not emit or execute a backend.
The migration probe tests the boundary with unchanged stage source.

## Measurement boundary

Each timed process loads source, reads it, collects declarations, resolves
types, checks bodies, and releases its context. Elapsed time also includes
process startup and the GNU time launcher. Backend execution, emission, target
GCC compilation, and linking are outside this interval.

The tool runs at least 20 paired rounds on one CPU. It randomizes workload and
baseline/candidate order. Processes are fresh; the filesystem cache is warm.
GNU time records maximum process RSS. The report contains raw samples, paired
median ratios, and 95% bootstrap confidence intervals from 10,000 resamples.
Short processes can have wide time intervals because startup costs vary.

Histograms run separately from timing. They count unique reachable nodes after
checking in four families: expressions, statements, declarations, and type
syntax. `node-bytes.json` gives counts and bytes for each named kind.
Arena reservation also includes other node families, tables, arrays, and
unused arena space. RSS includes memory outside the arena. These are separate
measurements.

## Gates and outputs

All three gates must pass:

1. The median paired RSS ratio must be at most 0.60 on both the largest scaling
   input and the real C backend stage.
2. The upper 95% confidence bound for the paired time ratio must be at most
   1.02 on every input. This permits a 2% noise margin. A wider interval does
   not establish the time gate.
3. Stage migration must fit within API generator changes. The probe runs the
   generator against the candidate header. A second probe supplies a nested
   Crust header and a payload of the candidate size to unchanged C-stage source.
   This checks whether the client field accesses survive a representable
   layout. The payload in that probe is a layout witness, not a backend.

Stop when a gate fails. Record the evidence and retain the production ABI.
Passing measurements require a source and API review before integration.

The output directory contains compiler and experiment source copies, input
bytes, build commands, tool versions and hashes, input/source/binary hashes,
raw samples, histograms, and migration diagnostics. `report.json` contains
the gate results; `migration/` contains the API and client probes. Generated
binaries and machine-specific results stay under ignored `build/` storage.
