# RMD reader library

This library reads the RMD0 declaration grammar. All lexer and parser code is
ordinary RMD. It calls the public arena, name, and diagnostic APIs. It does not
call the seed reader.

Load these files after `api/rmd0.rmd`:

1. `model.rmd`
2. `lex.rmd`
3. `parse.rmd`

Call `rr_read(context, source, begin, end, hooks)`. A null hook pointer selects
the standard grammar. Success returns a unit and appends it to the context.
Failure returns null, retains the first diagnostic, and publishes no unit.
Keep the source descriptor and bytes live until context destruction.

The public `RmdReaderToken` exposes kind, original offset, raw text and length,
interned name, numeric value and type, and decoded string bytes. Single-byte
punctuation uses its ASCII value. The `RR_*` constants describe other tokens.
`rr_init` starts a reader over a source range. `rr_next`, `rr_take`, `rr_expect`,
`rr_name`, and `rr_is_name` provide token access. `rr_expect` takes a complete
error message. `rr_error` retains a diagnostic at an original source offset.

`RmdReaderHooks` supplies an optional function for a declaration, statement,
prefix expression, or type. Each function receives the reader and `user`.
A null result means unhandled and must leave the token and cursor unchanged.
A handled hook consumes its complete production. A new context diagnostic or
`reader.failed` stops reading. Hooks return one unlinked declaration or
statement; use a block to return several statements.

The `rr_standard_declaration`, `rr_standard_statement`, `rr_standard_prefix`,
and `rr_standard_type` functions bypass the hook for that production. Nested
productions still use their hooks. `rr_record` consumes `RR_RECORD`, the name,
the fields, and the closing brace. `rr_function` consumes a complete ordinary
or extern function. `rr_block` consumes both braces. `rr_expression` reads a
full expression; `rr_prefix` reads one complete unary operand. Each helper
leaves the next token current.

`rr_alloc` returns zeroed context storage. `rr_new_expr`, `rr_new_stmt`,
`rr_new_type`, and `rr_new_decl` take a kind and original offset. These helpers
do not impose extension syntax or semantic policy.

The nesting limit is 256. The default token budget is the range size plus one.
Every lexical step uses one token from that budget. Failed readers are sticky.

Run the differential tests with:

```sh
python3 stages/reader/test.py
python3 stages/reader/test.py --backend c --cflag=-O3
```

The tests compare acceptance, AST fields, source offsets, and diagnostics with
the seed reader. They also exercise all four hooks, hook contract failures,
source ranges, nesting and token limits, and allocation failure. The seed
compiler checks the reader source before each test build.
