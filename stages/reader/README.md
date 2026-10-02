<!-- SPDX-License-Identifier: Apache-2.0 -->

# Crust reader library

This library reads the Crust0 declaration grammar. All lexer and parser code is
ordinary Crust. It calls the public arena, name, and diagnostic APIs. It does not
call the seed reader.

Load these files after `api/crust0.crs`:

1. `model.crs`
2. `lex.crs`
3. `parse.crs`

Call `rr_read(context, source, begin, end, hooks)`. A null hook pointer selects
the standard grammar. Success returns a unit and appends it to the context.
Failure returns null, retains the first diagnostic, and publishes no unit.
Keep the source descriptor and bytes live until context destruction.

The public `CrustReaderToken` exposes kind, original offset, raw text and length,
interned name, numeric value and type, and decoded string bytes. Single-byte
punctuation uses its ASCII value. The `RR_*` constants describe other tokens.
`rr_init` starts a reader over a source range. `rr_next`, `rr_take`, `rr_expect`,
`rr_name`, and `rr_is_name` provide token access. `rr_expect` takes a complete
error message. `rr_error` retains a diagnostic at an original source offset.

`CrustReaderHooks` supplies an optional function for a declaration, statement,
prefix expression, or type. Each function receives the reader and `user`.
A null result means unhandled and must leave the token and cursor unchanged.
A handled hook consumes its complete production. A new context diagnostic or
`reader.failed` stops reading. Hooks return one unlinked declaration or
statement; use a block to return several statements.

The `rr_standard_declaration`, `rr_standard_statement`, `rr_standard_prefix`,
and `rr_standard_type` functions bypass the hook for that production. Nested
productions still use their hooks. `rr_record` consumes `RR_RECORD`, the name,
the fields, and the closing brace. `rr_function` consumes a complete ordinary
or extern function. `rr_function_header` consumes `fn` or `extern fn`, the
name, the parameters, and the result type. It returns a declaration without a
body or native symbol and leaves the next token current. A hook can inspect
this token and consume its own suffix. To use the standard suffix, pass a
successful header result to `rr_function_end`: it consumes the function body
or the extern `= "native";` suffix. `rr_function` calls both helpers.

`rr_block` consumes both braces. `rr_expression` reads a full expression;
`rr_prefix` reads one complete unary operand. Each helper leaves the next
token current.

`rr_alloc` returns zeroed context storage. `rr_new_expr`, `rr_new_stmt`,
`rr_new_type`, and `rr_new_decl` take a kind and original offset. These helpers
do not impose extension syntax or semantic policy.

The reader has a traversal budget of 256 levels. Recursive productions and
active hooks use that budget. It does not permit 256 arbitrary nested blocks.
The seed checker has a separate 256-level traversal budget. A stage that adds
syntax nodes must also satisfy that check.

For `main(argc:i32,argv:**u8)->i32`, the following limits count blocks inside
the function body. The return fixture contains only `return 0i32;` in its
innermost block. The assignment fixture contains `argc=argc+1i32;` there,
then `return 0i32;` after the nested blocks.

| Driver | Return fixture | Assignment fixture |
|---|---:|---:|
| `crust0`, `crust-c` | 253 | 252 |
| `crust-overload` | 252 | 252 |
| `crust-resource`, `crust-overload-resource` | 250 | 249 |

The overload declaration hook uses one reader level while it reads a function.
Resource lowering adds levels to the checked tree. Other expressions and hooks
can use more levels. Each stage rejects exhausted traversal with a diagnostic.
[The boundary test](../../tests/nesting.py) checks each listed limit and the
first rejected depth. `make check-overload` runs this test for all five drivers.

The default token budget is the range size plus one. Every lexical step uses
one token from that budget. Failed readers are sticky.

Run the differential tests with:

```sh
python3 stages/reader/test.py
python3 stages/reader/test.py --backend c --cflag=-O3
```

The tests compare acceptance, AST fields, source offsets, and diagnostics with
the seed reader. They also exercise all four hooks, hook contract failures,
source ranges, nesting and token limits, and allocation failure. The seed
compiler checks the reader source before each test build.
Generated inputs and outputs go in `BUILD/reader-tests`, where `--build`
selects `BUILD`. Use `--work` to select a different test output directory.
