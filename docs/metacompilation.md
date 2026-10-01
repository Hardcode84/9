# Metacompilation and a small language core

Date: 2026-09-30. Updated: 2026-10-01. Status: source study and a proposed experiment.

This study extends the [language exploration](language-exploration.md).
It keeps C-level compilation speed as the first requirement. This study adds
source evidence, not new compiler timings. The earlier
[C, C++, and Rust profiles](compiler-profiles.md) remain separate measurements.

The [Crust0 specification](crust0-spec.md) now defines the bootstrap language and
its public construction contract. Module management is a library stage, along
with richer syntax, ownership policy, and backend adaptation. The candidate
features in this study are not additional seed requirements.

The [source metastage review](source-metastages.md) updates the selection model.
The user program selects its custom stages through ordinary library calls.
A separate build file is not required. Backend selection does not require
the proposed two-region file envelope. No new source syntax is adopted yet.

Reading guide: [Jai evidence](#2-what-public-jai-evidence-establishes),
[research](#3-research-that-applies),
[Forth and Factor](#36-forth-compiler-construction-through-ordinary-words),
[Lisp, Scheme, and Racket](#37-lisp-scheme-and-racket-language-features-as-libraries),
[public core and stages](#44-full-access-to-core-and-stages),
[language and backend replacement](compiler-extension-experiment.md),
[parallel stages](#5-parsing-and-parallel-stages),
[costs](#6-can-it-be-fast), [caching](#7-caching-without-changing-program-meaning),
[experiment](#8-a-bounded-experiment).

## 1. Finding

A small systems language can implement many features as libraries that run
during compilation. Terra is a direct example. Jai gives useful evidence that
extensive metaprogramming can coexist with short complete builds. Neither
establishes the required C-level frontend speed for this language.

Make the compiler a public library. Expose the core representations and every
compilation stage. Implement the standard compiler with that library. Let
compilation code in the user program inspect, replace, remove, and compose
its stages. A separately compiled driver is one execution mechanism, not the
required location of the user's stage override.
This includes complete base syntax replacement and the interface to LLVM or
another backend. The [compiler extension experiment](compiler-extension-experiment.md)
defines these interfaces and a C compiler witness.

Test a small bootstrap seed with compiled standard language libraries.
Implement ownership, cleanup, and unsafe policy in those libraries. Compile
them when the compiler is built. In the default driver, run project
generators over explicit inputs, then check their output as ordinary code.
Use a fixed default grammar and immutable interfaces between parallel tasks.

Investigate this staged extension model. Use the experiment in section 8 to
measure its benefits and costs before expanding the implementation.

Three different goals need separate names:

| Goal | Meaning | What it does not establish |
|---|---|---|
| Self-hosting | The compiler is written in its own language | A small language or a fast compiler |
| Language extension | A library translates added constructs into core constructs | New safety guarantees without a checker |
| Staging | Code runs at one stage to produce code or data for a later stage | Cheap execution or a valid persistent cache |

The desired result combines language extension with staging. Self-hosting can
support it, but is not the feature that makes it possible.

## 2. What public Jai evidence establishes

### 2.1 Mechanisms

Jai exposes a compiler control interface to programs written in Jai. Public
programs use it for build configuration, source generation, and inspection of
typed code. These programs are evidence of API use. They are not a specification
of every compiler state or an audit of the compiler implementation.

Tsoding's Jaibreak build program starts from a compile-time block. It creates
separate workspaces, selects build options, adds files and generated strings,
and waits for compiler messages. It reads configuration and translation files
to generate declarations. The program uses the language for build logic and
application code.
[Jaibreak build program, fixed revision](https://github.com/tsoding/jaibreak/blob/e7e206a66ae3140c5c588feb72591c2d641b0882/first.jai)

The public Developer_Only plugin receives type-check completion messages. When
its option disables developer code, it finds marked procedures, replaces their
statement lists, and calls the procedure-modification API. Thus the public
interface permits changes to procedure bodies after an initial type check.
This example alone does not establish which checks the compiler repeats.
[Developer_Only plugin, fixed revision](https://gist.github.com/alexover1/cbcb0fe1d735c96714c7c3426fdd02f6/17d8e8589ff4c2b9fccbedfef66e1fd024428699)

Alessio Marchetti's game example collects marked procedure names. It inserts
a generated table when the compiler reports that it has checked all code it
currently can. Insertion starts another round of messages. The example uses
a guard to prevent duplicate insertion.
[Marchetti, Examples of Metaprogramming, 12 April 2025](https://teiolass.gitlab.io/posts/metaprogramming_cards_1/)

These examples establish distinct facilities:

| Facility | Useful application | Cost or dependency to measure |
|---|---|---|
| Compile-time execution | Calculate constants or prepare data | Prepare and execute the code |
| Workspaces and build options | Build several targets with one program | Isolate target state and track input files |
| Generated source | Produce tables, bindings, and declarations | Construct, parse, and check the output |
| Typed-code messages | Find marked declarations and enforce project rules | Export compiler data and process messages |
| Procedure modification | Insert or remove application behavior | Re-establish the properties affected by each edit |
| Progress notifications | Generate code after dependencies become available | Additional rounds and possible serial dependencies |

The final row is important. A notification that no more current work can
progress is not proof that all possible generated declarations exist.
A generator that needs a complete type set needs a defined end to that set.
This is our scheduling inference from the examples, not a claim about an
undocumented Jai guarantee.

### 2.2 Speed evidence and its boundary

In the 2025 LambdaConf demonstration, Jonathan Blow reports a complete rebuild
of about 300,000 lines, including generated source, in about 2.3 seconds on his
laptop. He says this build does not use incremental compilation. This supports
the feasibility of rich metaprogramming in a fast complete-build workflow.

The report distinguishes external metaprogram execution, which can overlap
compilation, from inline compile-time values that block dependent work. It also
reports bytecode generation and specialization work. Reusing a specialization
still requires matching it. Type checking remains a major cost.
[Blow, Jai Demo and Design Explanation, LambdaConf 2025](https://www.youtube.com/watch?v=IdpD5QIVOKQ)

The talk demonstrates a replaceable default build metaprogram and an exported
typed AST interface. Relevant chapter starts are
[09:22, compiler control](https://www.youtube.com/watch?v=IdpD5QIVOKQ&t=562s),
[18:05, typed AST](https://www.youtube.com/watch?v=IdpD5QIVOKQ&t=1085s), and
[43:37, performance reports](https://www.youtube.com/watch?v=IdpD5QIVOKQ&t=2617s).
These are chapter starts, not exact statement times.

This is a creator demonstration, not a repeated measurement in this repository.
It does not isolate frontend time or provide an equivalent C baseline. The
review used a [public transcript](https://youtubetotranscript.com/transcript?current_language_code=en&v=IdpD5QIVOKQ).
The inspected sources do not establish Jai's persistent cache design.
Do not infer that the fast result came from caching.

The verified API does not establish public replacement of Jai's parser,
checker, or every compiler pass. The requested Crust interface goes further.

The [January 2026 Wookash interview](https://www.youtube.com/watch?v=1blhmslxkWg&t=4820s)
also has a metaprogramming chapter. Its publisher metadata was checked, but
the speech was not used as evidence here. The public subtitle requests did
not return a transcript. Claims from third-party summaries about new hooks
or hygiene need verification against the original audio.

### 2.3 What to take from Jai

Use the same ordinary language for generators and application code. Provide
visible generated output, useful diagnostics, and per-stage cost reports.
Make compiler services usable without an external text-processing language.

Separate these benefits from the exact live message protocol. Full IR access
can use explicit ownership and stage boundaries. Callback arrival order need
not affect meaning. That alternative is a design proposal, not a description
of Jai.

## 3. Research that applies

### 3.1 Terra: a close systems-language example

Terra combines a low-level typed language with Lua metaprograms. Its published
design uses libraries for conditional compilation, templates, namespaces, and
class systems. Saved target programs can run without Lua when they do not use
Lua services. This separates generation costs from the final program's runtime
support.
[Terra project description](https://terralang.org/)

The PLDI 2013 paper implements much of a Java-like class system in about
250 lines. A method-invocation microbenchmark is within 1% of analogous C++.
That result concerns runtime calls, not compilation speed. The system still
needs staging, binding, specialization, type checking, and code generation.
[DeVito et al., Terra, section 6.3.1](https://terralang.org/pldi071-devito.pdf)

Terra's exotypes expose a stronger option: the type checker calls user
functions to obtain type properties. The paper memoizes query results and
rejects query cycles, but property functions can still fail to terminate.
Order-sensitive side effects interfere with composition. This is direct
evidence for both the power and the dependency cost of type-directed callbacks.
[DeVito et al., Exotypes, PLDI 2014](https://terralang.org/pldi083-devito.pdf)

For Crust, first test generation from already available type signatures and
layouts. This retains useful reflection without arbitrary calls from the
middle of name or type resolution.

### 3.2 MetaOCaml: process only the staged parts

MetaOCaml provides typed quotation and splicing. It preserves intended binding
and detects scope escape during generation, including when open fragments are
stored in mutable cells. Its guarantee comes from the code operations and
their checks, not from attaching a type field to an arbitrary syntax tree.

Since version N114, quotation translation is integrated with type checking
and visits the quoted subtrees. Kiselyov reports that plain OCaml programs
activate no MetaOCaml-specific processing. This is a useful implementation
method for the unused-feature requirement. It is not a C-relative timing
result. Generated code still needs compilation.
[Kiselyov, MetaOCaml: ten years later, sections 3 and 4](https://okmij.org/ftp/meta-programming/design-10.pdf)

Use this selective processing idea. Keep full IR access available through the
compiler library; do not confuse the stronger guarantees of a quotation API
with the contract of an arbitrary compiler transformation.

### 3.3 Turnstile and Nanopass: expose the compiler itself

Turnstile expresses typing rules and rewrites through Racket macros. Its
examples include an ML-like language with local inference, data types, pattern
matching, and basic type classes. Expansion performs checking and translation
together to avoid duplicate work. The framework supplies binding and expansion
machinery. The author of each checker remains responsible for its rules.
[Chang, Knauth, and Greenman, Type Systems as Macros, POPL 2017](https://www.ccs.neu.edu/home/stchang/pubs/ckg-popl2017.pdf)

This supports the requirement that language features and checkers can be
ordinary compiler libraries. The default checker need not be a hidden,
privileged part of the seed compiler.

Nanopass gives transformations explicit input and output languages and
generates routine traversal code. The commercial Chez Scheme study reports
average complete-compilation ratios of 1.64 to 1.75 against its old compiler.
It also changes optimizations and register allocation. The result does not
isolate pass-framework overhead or frontend time.
[Keep and Dybvig, A Nanopass Framework for Commercial Compiler Development, section 4](https://www.cs.tufts.edu/comp/150FP/archive/icfp13.pdf)

Take the public representations and precise pass boundaries. Do not assume
that many small passes will meet the speed target. Exposed logical stages
can share a traversal or have a fused implementation when their contracts
permit it. A user can still select the separate implementations.

### 3.4 A formal staging boundary

Two-level type theory separates compile-time and runtime terms. Kovács proves
a staging algorithm that removes compile-time terms while preserving the
specified meaning. The prototype uses variable levels to avoid repeated
environment adjustment. Its production specialization cache is not implemented,
and the presented theory does not support compile-time effects.
[Kovács, Staged Compilation with Two-Level Type Theory, ICFP 2022](https://andraskovacs.github.io/pdfs/2ltt.pdf)

This supports explicit stage boundaries. It does not establish C-speed
compilation, mutable-pointer safety, or a reason to add dependent types to
the minimal core.

### 3.5 Fast native preparation is a separate problem

Copy-and-patch compilation prepares binary templates ahead of time, then copies
and patches them to produce executable code. Xu and Kjolstad report that their
C-like metaprogramming compiler generates native code from an AST faster than
that AST is constructed. Their database experiment reports much lower code
generation cost than LLVM.
[Xu and Kjolstad, Copy-and-Patch Compilation, 2021](https://arxiv.org/abs/2011.13127v3)

This could reduce the cost of executing substantial generators. It does not
remove parsing, type checking, ownership checks, or output construction.
It also adds machine-specific implementation work. Test it only if a simpler
runner fails because generator preparation or execution dominates.

### 3.6 Forth: compiler construction through ordinary words

Forth distinguishes a word's execution and compilation behavior. IMMEDIATE
makes a definition execute during compilation. POSTPONE composes compilation
behavior without requiring the caller to know whether a word is immediate.
The standard rationale also explains why assuming a particular threaded-code
representation prevents native-code implementations.
[Forth POSTPONE specification and rationale](https://forth-standard.org/standard/core/POSTPONE),
[Gforth interpretation and compilation semantics](https://gforth.org/manual/Interpretation-and-Compilation-Semantics.html)

CREATE and DOES> support defining words that create new definitions with
associated data and behavior. This is a compact example of language
construction being available to ordinary programs.
[Forth DOES>](https://forth-standard.org/standard/core/DOES)

Gforth's outer interpreter and compiler are largely written in Forth. Its
cross compiler builds the initial kernel and can produce images for another
architecture. This is direct evidence for a small bootstrap plus a compiler
library.
[Gforth cross compiler](https://gforth.org/manual/Cross-Compiler.html)

There is a cost to the traditional input model. The text interpreter looks up
a word before performing its compilation behavior. A word can parse further
input or change the input position. Thus independent parsing cannot assume
that every following token has a fixed role. The standard also does not
require data-type or program-construct checking.
[Forth usage requirements, sections 3.1 and 3.4](https://forth-standard.org/standard/usage)

The ordering conclusion is our inference from these input operations.
The Forth standard does not expose every implementation's internal IR or stages.
For Crust, take explicit compiler operations and a bootstrapped vocabulary.
The default driver gives a parser a fixed input region and known imports.
A custom Forth-like frontend can instead expose streaming parse operations;
its source-order dependencies remain part of its schedule and cache contract.

Fast Forth compilation is useful evidence with a measurement boundary.
Ertl and Maierhofer's 1995 translator hooks into compiler words to produce C.
They report that Forth compilation and translation were below their timing
resolution; reported compilation times cover GCC and linking. Their analysis
also identifies compile-time addresses that need relocation for the target.
This historical experiment does not measure a modern checked frontend against C.
[Ertl and Maierhofer, Translating Forth to Efficient C](https://www.complang.tuwien.ac.at/papers/ertl%26maierhofer95.pdf)

Do not equate a small threaded-code compiler with zero runtime overhead.
Measure native output, calls, and storage behavior separately. Keep host
pointers out of serialized target data and cache identities.

Factor adds a related lesson. Its compiler checks declared stack effects.
In 2006, Slava Pestov replaced complex inference for recursive words with
explicit declarations. Use explicit interface facts when inference adds
cost and ambiguity. Stack-effect checks alone do not prove pointer lifetimes.
[Factor stack checking](https://docs.factorcode.org/content/article-inference.html),
[Pestov, Formal stack effect declarations](https://blogs.factorcode.org/slava/2006/08/formal-stack-effect-declarations.html)

### 3.7 Lisp, Scheme, and Racket: language features as libraries

Common Lisp macro transformers are functions that produce program forms.
This makes control constructs and domain operations available as libraries.
Its compiler macros have a different role: they suggest optional transformations.
The compiler can decline to apply them. Required language semantics and safety
checks must therefore be independent of that optional optimization.
[Common Lisp DEFMACRO](https://www.lispworks.com/documentation/HyperSpec/Body/m_defmac.htm),
[compiler macro use](https://www.lispworks.com/documentation/HyperSpec/Body/03_bbac.htm)

Quotation makes code construction convenient, but names need more than text.
Common Lisp's GENSYM returns a fresh symbol whose identity is not its printed
name. Scheme's syntax objects preserve lexical context. Its syntax-case
library can implement the simpler syntax-rules interface. Thus a small public
syntax API can support both convenient patterns and general transformation
functions. Preserve helper bindings as well as fresh local names.
[GENSYM](https://www.lispworks.com/documentation/HyperSpec/Body/f_gensym.htm),
[R6RS syntax-case library](https://r6rs.org/final/html/r6rs-lib/r6rs-lib-Z-H-13.html)

Racket language packages can supply a reader and an expander. Module languages
can redefine implicit forms such as function application and the module body.
This closely matches a language built from public libraries. Lisp surface
syntax is not required.
[Racket language construction](https://docs.racket-lang.org/guide/languages.html),
[Racket module languages](https://docs.racket-lang.org/guide/module-languages.html)

Racket's reader produces syntax objects; expansion uses bindings to complete
the parse. It therefore does not establish that arbitrary extension preserves
name-independent parsing. The same reference describes a registry lock for
module visits and instantiation. That is a concrete coordination cost within
one registry, not evidence that all Racket compilation is serial.
[Racket syntax and module model](https://docs.racket-lang.org/reference/syntax-model.html)

Phase dependencies are a major lesson. Flatt's module work separates imports
for runtime use from imports needed to implement macros. This addresses
programs that work in a prepared interactive session but fail in a fresh
compiler process. Separate phase instances prevent one client's module-local
compilation state from changing another client's expansion. External effects
such as file writes still need their own dependency and ordering contract.
[Flatt, Composable and Compilable Macros, ICFP 2002](https://www-old.cs.utah.edu/plt/publications/macromod.pdf)

Prepared macro code still needs phase initialization and transformer execution.
Racket documents separate compile-time module instances for separate client
expansions. Share prepared code and immutable tables; give each job explicit
state. Do not mistake a compiled macro module for cached expansion results.
[Racket module visits and instantiation](https://docs.racket-lang.org/guide/macro-module.html)

Common Lisp's EVAL-WHEN makes compile, load, and execution effects explicit.
Its file compiler processes a top-level form before reading the next, which
permits reader changes to affect later forms. That useful control carries
a serial dependency. A custom Crust driver may choose it; the default driver
can prepare a reader once and parse independent modules separately.
[EVAL-WHEN](https://www.lispworks.com/documentation/HyperSpec/Body/s_eval_w.htm),
[Common Lisp top-level processing](https://www.lispworks.com/documentation/HyperSpec/Body/03_bca.htm)

Self-bootstrap is practical. Racket 7.0 replaced about one eighth of its previous
core implementation with an expander that bootstraps itself. The expander is
only part of the compiler.
[Racket 7.0 announcement, 2018](https://blog.racket-lang.org/2018/07/racket-v7-0.html)

SBCL's saved core images offer a different form of reuse: they preserve prepared
process state. External state such as open streams needs separate treatment.
For this study, a saved image containing project code is a warm configuration,
not evidence for an empty-project-cache build.
[SBCL saved images](https://www.sbcl.org/manual/index.html#Saving-a-Core-Image)

Expose representations as well as entry points. Chez provides callable
expansion operations, but its documented replacement hook still depends on
sc-expand because the required internal representation is not public.
Crust must publish the input and output forms and invariants of each stage.
Users must be able to construct valid input without calling an opaque predecessor.
[Chez system operations](https://cisco.github.io/ChezScheme/csug/system.html)

There is direct evidence of a compilation-cost failure. Wessel reports that
refactoring three macros in a Common Lisp system reduced a full build from
33 minutes 17 seconds to 5 minutes 30 seconds under ACL 10.1. Repeated insertion
of nested bodies caused exponential output growth. This is an author-reported
whole-build result, not an isolated frontend or C comparison.
[Wessel, Notes on Refactoring Exponential Macros, 2023](https://www.sri.com/wp-content/uploads/2023/05/Notes-on-Refactoring-Exponential-Macros-in-Common-Lisp.pdf)

Hygiene does not prevent this growth. A macro that inserts its body twice can
produce 2^n copies at nesting depth n. A pattern-only macro can also expand
back into itself forever. Track expansion size and generator time separately.
Reducing copied bodies must preserve binding, cleanup, and runtime cost.
Fresh names and a cache do not fix those issues.

### 3.8 Combined design direction

| Source family | Apply to Crust | Check explicitly |
|---|---|---|
| Jai | Ordinary-language compiler control, reflection, and visible output | Blocking generation and exported-AST cost |
| Terra | Small low-level core with substantial feature libraries | Type-directed callbacks and generated runtime behavior |
| Lisp and Scheme | Quotation, binding-aware syntax, and ordinary macro functions | Expansion size, phase imports, and initialization |
| Racket and Turnstile | Replaceable languages and checkers as libraries | Public representations and the selected rules |
| Forth | Exposed compilation operations and bootstrap through ordinary code | Stateful parsing and host/target separation |
| Nanopass | Explicit pass input and output languages | Repeated traversal and allocation |

Use these ideas together in the default driver. They do not require Lisp
syntax, a stack-based runtime, dynamic target types, or a target garbage
collector. The compile-time representation and execution model can differ from
the target's representation and runtime support.

## 4. A small core that can extend itself

### 4.1 Keep the semantic obligations visible

A small bootstrap implementation and a small trusted language are different
things. Moving a checker into a library reduces the bootstrap implementation.
It does not remove that checker's rules, maintenance cost, or compilation cost.

The candidate seed needs primitive values, storage, calls, control flow, and
enough type and layout operations to implement compiler libraries. It does
not need a borrow solver, resource cleanup policy, or an `unsafe` grammar rule.
Binding, source locations, and richer representations can be library facilities.

Standard language stages define the resource-lifetime contract. Their IR must
retain moves, borrows, resource operations, and source scopes until checking
and cleanup lowering finish. Those stages then produce low-level operations.
The seed does not reconstruct ownership from raw pointer instructions.
See the [ownership and unsafe stage contract](compiler-extension-experiment.md#ownership-and-unsafe-are-language-stages).

| Feature | Possible library implementation | Required contract |
|---|---|---|
| Enum names and dispatch tables | Read an enum descriptor and emit constants and functions | Stable type identity and explicit representation |
| Serialization | Generate field access and encoding calls | Defined field access and external-data validation |
| Container specialization | Generate concrete types and operations from explicit parameters | Layout, alias, and lifetime rules |
| Iteration syntax | Expand to loops and calls | Evaluation order, binding, and loop exits |
| Resource conveniences | Expand to owner operations and scope cleanup | Cleanup on every supported exit and valid moves |
| Ownership and unsafe policy | Standard language checker and resource IR | Explicit lifetime rules, permitted unchecked operations, and rejection cases |
| Intrusive-list conveniences | Generate ordinary hook access or repeated operations | Stable addresses and safe access after individual reuse |
| New type-system rules | Implement an additional checker or a compiler pass | That component joins the trusted implementation |

Do not require the list algorithm to be a compiler plugin. It must remain
ordinary safe user code. Metaprogramming does not prove the missing
persistent-alias lifetime contract. Generating unchecked pointer operations
behind a safe-looking wrapper does not meet that requirement.

A resource macro also cannot obtain correct cleanup from textual replacement
alone. It must use the standard library's cleanup operation or implement the
full exit transformation, including early return, loop exit, and partial initialization.
If that transformation carries a safety guarantee, its implementation is part
of the trusted language.

### 4.2 Bootstrap once, then use the result

An implementation can use this build sequence:

~~~text
small seed compiler
    -> compiler modules and standard extensions written in the seed language
    -> compiler distribution with compiled parser, checkers, and extensions
    -> application source and optional project extensions
    -> checked standard language IR
    -> cleanup lowering and low-level IR
    -> backend input
~~~

Standard extensions need not interpret their own source on each application
build. They can be compiled into the compiler or shipped as versioned compiled
components. This is still language extension through libraries. It does not
require every feature to be hard-coded in the seed implementation.

Record the dependency direction. An extension's implementation can use core
features and extensions from an earlier bootstrap stage. It cannot require
its own unfinished expansion to become executable.

Verify the bootstrap by rebuilding the compiler and standard extensions with
the resulting compiler. Compare canonical output and run the same language
tests. Disable project-result caches for this check. Self-reproduction checks
consistency; it does not prove the source compiler correct.

Compiler construction is outside application frontend timing, just as building
Clang is. Building a project's changed extension is inside that timing.
A prebuilt project extension is a separate prepared configuration and must be
labeled. Record application-result cache state independently: a prepared
extension can still process a cold application build. The
[C experiment](compiler-extension-experiment.md#5-cost-and-parallelism)
separates installed language components, project preparation, and full construction.

### 4.3 Extension code and generated code have different trust

The library offers both a convenient generation interface and the full
compiler interface. The default generation interface reads immutable
descriptors and produces code for ordinary checking. Compiler-stage authors
can also own and edit core or typed IR and replace the checkers.

The difference is the guarantee. Editing a checked body can invalidate its
type, ownership, control-flow, or layout facts. To retain those guarantees,
the driver must rerun the affected check or use a transformation whose contract
preserves those facts.
A user-supplied pass that promises preservation is part of that compiler's
trusted implementation. A copied checked flag is not evidence of preservation.

Typed quotation can prevent many generation errors. It must also preserve
binding: a generated local name must not capture an unrelated caller variable.
This property is called hygiene.

Hygiene is not resource safety. A quoted expression that consumes an owner
cannot be inserted twice merely because both copies have the same result type.
The final ownership check must reject the duplicate consumption, or the
quotation system must track captured owners itself. Use the standard language
checker rather than a second ownership system for quotations. That checker is
itself a replaceable compiled metastage, not a hidden seed operation.

Under the standard rules, unsafe operations in generated code retain their
unsafe contract. Hiding their spelling does not establish safety. A user can
replace those rules through the public checker interface, but the changed
compiler must state the guarantee its rules actually provide.

### 4.4 Full access to core and stages

Expose these facilities as ordinary library interfaces:

- Lexer, parser, source locations, and binding operations.
- Core and intermediate representations, constructors, editors, and traversal.
- Declaration collection, type layout, type checking, and ownership checking.
- Address-stability rules, unsafe syntax and policy, and resource representations.
- Cleanup, specialization, target lowering, and backend-input construction.
- Backend selection, target queries, backend passes, object emission, and linking.
- Stage dependencies, workspaces, scheduling, diagnostics, and cost reports.
- Cache lookup, validation, serialization, invalidation, and cache policy.

Use those same interfaces in the standard driver. Do not reserve essential
operations for an internal plugin class. A custom driver can replace the
parser, add an analysis, change the core rules, or stop at an intermediate
representation.

Document each representation and its invariants. A callback that still needs
an opaque internal producer does not provide full access. Version these APIs
with the compiler; the experiment does not need a stable binary plugin ABI.

The smallest model is ordinary calls with explicit input and output types.
This is illustrative driver code, not a completed API:

~~~text
syntax  = parse(inputs)
program = elaborate(syntax)
typed   = check_types(program)
checked = check_ownership(typed)
lowered = lower_cleanup(checked)
output  = lower_target(lowered, target)
~~~

Each function and representation is public. Generation stages can be inserted
where their inputs are available. Users can replace this sequence completely.
The standard sequence defines the standard language contract.

Start with explicit stage preconditions and postconditions. Do not build a
general proof or automatic pass-ordering system. A replacement checker changes
the trusted compiler. A removed check removes its guarantee unless another
stage establishes it.

Full access can use exclusive ownership of a work unit during mutation and
immutable publication to readers. Publish a new revision after an edit.
Keep shared nodes immutable and alive until all readers finish, including
queued or paused jobs. A new revision must not modify or reclaim nodes retained
by an earlier revision. This is the shared data contract, not a restriction
on which compiler operation users can access.

Configure the driver once per build. Public stage access must not require
dynamic dispatch for each token or syntax node. Count the selected driver's
setup, scheduling, and enabled passes in the same frontend timing boundary.

### 4.5 Replace a language or a backend

The user can replace the lexer and the whole grammar, including declarations,
operators, and whitespace rules. Select the reader before it reads the target
source. Source-defined compilation code makes this selection through ordinary
libraries. Its own reader must already be available. It cannot select a reader
retroactively for bytes already consumed. A custom reader can also define
explicit changes in parsing rules within a file. The
[source review](source-metastages.md) separates this early dependency from
backend replacement, which needs no change to the source grammar.

Syntax extensions that produce standard Crust code or IR use its checkers.
A complete C frontend supplies C binding, type, conversion, and pointer rules. It can use
its own syntax and semantic representations, then lower to shared low-level
operations. Do not require C source to satisfy Crust ownership rules.

The backend adapter is also a metastage: compiler code that runs during the
build. It can construct LLVM IR, set the LLVM pass pipeline, and request object
output. It can instead select another backend. It can be compiled with the
compiler distribution; metacompilation does not require repeated interpretation
or native compilation of unchanged stage code.

The [extension experiment](compiler-extension-experiment.md) specifies the
target contract, LLVM boundary, and timing rules. Its C benchmark tests full
frontend replacement. It does not replace the safe direct-list witness or
establish Crust ownership-checking speed.

## 5. Parsing and parallel stages

### 5.1 Fixed syntax can still support extensions

The default parser can recognize a small, fixed form for expansion sites.
For example, the following is illustrative syntax, not an adopted grammar:

~~~text
import meta enum_text;

enum Color: u8 { red, green, blue }
expand enum_text(Color);
~~~

The parser recognizes the import and expansion delimiters without resolving
Color. A later stage supplies its frozen enum descriptor to the generator.
The output contains ordinary declarations. The example does not require
user-defined operator precedence or a parser that asks the type checker what
a token means.

Quotation can use normal core syntax with explicit holes. Parse a quoted
template once when the extension is prepared. At each use, bind fresh local
identities and insert the supplied fragments. Check the completed output.

For a domain-specific syntax, use an explicit delimited region. Its parser
is selected for that region and its cost is charged to the extension. This
keeps the surrounding grammar fixed for the default frontend. A custom driver
can select a different parser or reader before parsing begins. Its complete
cost and resulting language rules must be measured and stated.

### 5.2 Make each dependency stage explicit

Use this default sequence for each module or declared group:

1. Parse source, imports, and explicit extension sites.
2. Run generators that need only files, constants, or syntax.
3. Collect base declarations and resolve required type signatures and layouts.
4. Run generators over those immutable type descriptors.
5. Merge and check generated declarations. Publish the completed interface.
6. Expand local bodies, then perform ordinary type and ownership checks.
7. Lower cleanup and construct backend input.

This sequence is public driver code, not a mandatory hidden scheduler.
Independent tasks at a stage can run in parallel. A dependent task waits for
its actual inputs. This does not require one global barrier between every
numbered step.

A generator that consumes another generator's declarations must name an
earlier stage or generated module. Diagnose cycles. Do not repeatedly scan the
whole program until callbacks happen to stop changing it.

An all-types registry must name its scope. A registry for one frozen module
can finish at that module's boundary. A registry for the whole program must
wait for the whole declared program set. This wait is a real serial dependency.
Modules may emit local registry fragments for an explicit final merge.

Reject duplicate generated definitions. Define merge order independently of
worker completion order. Bind identifiers by stable scope identity. Do not use
worker-local pointer values as semantic identities.

Roslyn provides a production example of generators that read a common input
compilation and produce additional source. Its standard generation phase does
not let generators consume each other's output; an experimental earlier phase
adds controlled visibility for generated declarations.
[Roslyn generator design and cookbook](https://github.com/dotnet/roslyn/blob/main/docs/features/incremental-generators.cookbook.md)

This is a useful scheduling example, not an instruction to copy C#'s extension
limits. The explicit stage edges above permit composition.

## 6. Can it be fast?

### 6.1 Count all required work

Use this cost model:

~~~text
frontend and handoff time =
    ordinary input, parse, binding, and checking work
  + extension loading and preparation
  + extension execution
  + generated output construction and checking
  + required cache validation
  + cleanup, specialization, and backend-input construction
~~~

If an extension must be compiled to native code before it can run, its native
code generation is part of this total. Calling that work a backend does not
move it outside the application's frontend boundary.

A generator that emits N distinct statements requires work to represent and
check those statements. A generator can also spend arbitrary time computing
one constant. Neither a small surface program nor a small language kernel
gives a universal C-speed guarantee for arbitrary user computations.

This does not make metaprogramming unsuitable. The acceptance question is
whether useful, explicit generators pass the same speed gate on fixed
production work. Compare the whole enabled pipeline with equivalent C.

### 6.2 Separate preparation from execution

| Execution method | Potential benefit | Cost to test |
|---|---|---|
| Compiled standard extension | No source compilation for the extension on each application build | Loading, calls, and output construction |
| Small bytecode interpreter | Cheap preparation for a short project generator | Dispatch and allocation during execution |
| Native compilation of a project generator | Faster long-running generation | Native compilation and linking before generation |
| Copy-and-patch or another simple native runner | Lower native preparation cost | Added compiler size, target support, and code quality |

Start with compiled standard extensions and one simple project runner.
Select the runner from measured preparation and execution costs. Do not build
a tiered execution engine before there is evidence that it is needed.

Use direct compiler data access at a defined interface. Avoid copying every
typed procedure into an exported representation when a generator only needs
the fields of one marked type. Avoid a callback or persistent-cache operation
for every ordinary syntax node.

### 6.3 Avoid work when an extension is absent

A build with no enabled extensions should not load project generators, create
expansion tasks, export typed ASTs, or maintain their incremental dependency
graph. An enabled whole-program pass may inspect ordinary modules within its
declared scope. Measure startup and memory effects as well as per-node work.

Generated ASTs can avoid parsing generated text, but they are not automatically
faster. Node allocation, immutable-tree copying, and serialization can cost
more than a simple text builder. Roslyn's cookbook recommends text generation
for its string-based API and identifies expensive syntax formatting.
Measure the actual representation used here.
[Roslyn generation guidance](https://github.com/dotnet/roslyn/blob/main/docs/features/incremental-generators.cookbook.md#use-an-indented-text-writer-not-syntaxnodes-for-generation)

Keep one ordinary check of generated core code for routine derivation.
The public interface also permits transformations of typed code. Recheck only
the affected units when their interfaces and the pass contract permit it.
Measure that cost instead of assuming that the first check remains valid.

## 7. Caching without changing program meaning

### 7.1 Cache different products separately

| Cached product | Avoided work on a valid hit | Work that remains |
|---|---|---|
| Prepared extension | Parsing and preparing the generator | Its execution and checking new output |
| Expansion result | Executing an unchanged generator | Dependency validation and checks not included in the artifact |
| Checked module interface | Rebuilding unchanged declarations | Loading it and checking changed consumers |
| Checked body or lowered unit | Rechecking unchanged code | Validating all semantic dependencies and preparing handoff |

A cached syntax tree is not a checked module. A cached generator executable
is not a cached result. Report these cases separately.

Build Systems a la Carte separates scheduling from the decision to rebuild.
It describes both static and dynamic dependencies and reuse after unchanged
results. This is a model for organizing cache decisions, not a claim that
dependency tracking is free.
[Mokhov, Mitchell, and Peyton Jones, Build Systems a la Carte](https://www.microsoft.com/en-us/research/wp-content/uploads/2018/03/build-systems-final.pdf)

### 7.2 Use explicit dependency values

For an extension invocation, record these inputs where observable:

- Extension code, its transitive libraries, and configuration.
- Compiler version, core rules, extension API, and artifact format.
- Selected driver, stage graph, pass code and order, checker rules, and options.
- Host execution environment and target ABI, layout, and language options.
- Input syntax, binding context, invocation identity, and relevant source locations.
- Actual input IR content or revision and the imported interface revisions.
- Required type descriptors, constants, and imported interface fingerprints.
- Files, environment values, directory membership, and lookup results.

Use a stable invocation key to locate a previous record. That record contains
the dependency queries and their values. Validate them before reusing the
result. A changed earlier query can change which later queries are relevant;
rerun the invocation when that happens. Do not guess that its previous read
set is still complete.

A checked artifact also records which rules and required passes established
its state for that input IR and its dependencies. A direct edit through the
public IR API changes this input even when source files are unchanged.
A custom pipeline cannot reuse a result checked under different
ownership rules merely because its input source is unchanged. Initially,
invalidate at the module boundary when a relevant stage or rule changes.
Include transitive pass helpers. Reordering or removing a checker changes
the pipeline identity. An assumed property is not a performed check.

Record the exact captured file and configuration values used by execution.
Use those values consistently within the build view. Do not hash a second
read that can contain different bytes and attach that hash to the old output.
Require unchanged inputs during capture, or detect relevant changes and
restart or fail with a diagnostic. Per-file capture is not an atomic snapshot
of the whole filesystem.

Rust's incremental query design describes ordered dependency validation and
stable fingerprints. Its guide also states that fingerprint computation can
make incremental compilation slower than a non-incremental build.
[Rust query validation](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation.html),
[Rust fingerprint costs](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation-in-detail.html)

Start with one cache unit per invocation or module. Allow a batch build path
that does not maintain a fine-grained persistent graph. Add finer units only
when measured edits justify their tracking and memory costs.

### 7.3 Absence and collection membership are inputs

These are correctness cases, not optional cache improvements:

| Query | Change that must invalidate its old result |
|---|---|
| Does config.toml exist? | The previously absent file appears |
| Is helper defined in this scope? | A declaration or import makes it visible |
| Which types have this marker? | A matching type is added or removed |
| Which files match this pattern? | Directory membership changes |
| What is the layout of T? | Target options or a contributing type change |

Hashing only files that were read successfully is insufficient. Hashing only
the types returned by the previous query is also insufficient. The query must
depend on the membership of its frozen input set.

Skyframe gives a concrete model of tracked file state, path resolution, and
directory-listing dependencies.
[Bazel Skyframe](https://bazel.build/reference/skyframe)

Do not include a generator's previous output in its new input set unless an
explicit earlier stage owns that output. Otherwise, a rule that emits a name
only when it is absent can alternate between two results on successive builds.

### 7.4 Preserve binding and effects

Serialized results must not contain process-local type pointers or scope IDs.
Store stable identities and remap them on load. A reused macro template needs
fresh local binding identities for each insertion. Include every source
property that the extension can inspect in its dependencies.

Compact value records help. Roslyn warns that cached compiler symbols can
retain old compilations, and that syntax-node identity does not give useful
equality across edits. Its guidance extracts the needed information into
value-comparable models.
[Roslyn pipeline guidance](https://github.com/dotnet/roslyn/blob/main/docs/features/incremental-generators.cookbook.md#pipeline-model-design)

Only cache a task when its observable effects have a defined reuse contract.
An execution interface can provide tracked file reads and explicit inputs.
Shared mutable generator globals, the clock, network replies, and arbitrary
native calls do not acquire deterministic behavior merely because the language
calls the program a generator.

Run an effectful build command as an explicit build action. Do not memoize it
as a pure expansion. A cached generator's outputs must be returned artifacts;
it cannot rely on hidden writes that a cache hit omits. Native extensions that
bypass the tracked interface cannot claim this cache contract.

Validate cache artifacts at the file boundary. Once the compiler has accepted
an artifact, its internal consumers use the established representation rules.
Do not repeat file-validation branches at every internal access.

## 8. A bounded experiment

Classify expansion and generated-code checks as compiler hot paths. Extension
installation and compiler bootstrap are build-time paths. Project-generator
preparation is part of an application build whenever its prepared result is
not supplied by the compiler distribution.

Use the existing [frontend measurement rules](language-exploration.md#103-define-the-timing-boundary)
and [source-derived systems requirements](systems-capabilities.md).
First establish the core SQLite and direct-list ownership boundaries.
Then test this small extension set:

| Witness | Required result |
|---|---|
| An unused-extension build | No extension execution, AST export, or generated-code checking |
| A standard loop or resource convenience | The same checked core operations and cleanup as the explicit form |
| Enum text and a tagged command table | Reflection over explicit types, useful diagnostics, and ordinary direct code |
| A schema-to-record generator followed by encoding generation | Two declared stages that compose without repeated global checking |
| A user driver with one replaced stage and one typed-code edit | Full public API access, correct rechecking, and cache invalidation |
| A quoted owner-consuming expression inserted twice | Rejection by the ownership contract |
| Nested resource macros and two client-module orders | Bounded output growth, correct cleanup, and no dependence on session history |
| Direct intrusive-list code used from an expansion | No new pool, hidden allocation, or escape from the pointer contract |

Use an existing command/schema consumer or the SQLite witness for final
application output. Synthetic tables can measure scale but cannot establish
the systems capability. The source-derived list still needs individual
destruction, exact-address reuse, and its forbidden-access tests.

Compare three forms: ordinary explicit core source, its extension-based form,
and frozen C with the same behavior. Handwritten or already materialized C is
the primary frontend baseline. An equivalent generator-plus-C build is useful
additional context; it cannot replace the hard C gate.

Measure cold application builds with empty project caches, valid warm builds,
and edits to bodies, signatures, layouts, generator code, and generator inputs.
Report prebuilt project extensions as a separate configuration.
Count extension preparation, execution, output size, checking, cache I/O,
memory, total CPU time, and backend-input construction.

Use at least 20 paired samples, the single-worker ratio and confidence rule
from the main study, then test 2, 4, and 8 workers where available. A warm win
does not waive a failed cold-build gate. A failed workload is not hidden by
averaging it with a faster one.

Compare cached results with cache-disabled builds after each invalidation
case in section 7.3. Also change binding context, extension/API version, target,
worker order, pass order, and pass helper code. Remove or replace a checker,
and edit a checked body directly through the IR API without a source edit.
No stale checked result may survive those changes.
Require equivalent output and diagnostics for equivalent pipelines. Verify
that two expansions with local bindings cannot capture each other's names.

Reproduce the standard driver through public calls. Replace one stage without
calling its supplied implementation. A pipeline that omits ownership checking
is callable, but its timing does not establish speed for the checked language.

Set explicit execution and output budgets for the experimental generator.
Exceeding a budget produces a diagnostic that names the invocation.
A budget limits damage from runaway generation; it is not evidence of C-level
speed.

Inspect final code and data for additional allocations, indirect calls,
runtime reflection metadata, cleanup, and representation changes. Apply the
main runtime gates. No result passes because an optimizer might remove its
cost.

Stop expansion of the design if these witnesses fail. Identify whether the
cause is preparation, execution, checking, output growth, or cache bookkeeping.
Change the failing mechanism and rerun the same witness before adding another
extension facility. The next decision needs these measurements, not a complete
plugin framework.
