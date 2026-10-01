#include "rmd0.h"

#include <stdio.h>
#include <string.h>

static unsigned checks;
static unsigned failures;

static void check(bool condition, const char *name)
{
    ++checks;
    if (!condition) {
        ++failures;
        fprintf(stderr, "reader check failed: %s\n", name);
    }
}

static RmdSource source_text(const char *text, size_t size, uint64_t identity)
{
    RmdSource source;
    source.path = "reader-test";
    source.bytes = (const unsigned char *)text;
    source.size = size;
    source.identity = identity;
    return source;
}

static void syntax_case(const char *name, const char *text, size_t size, bool expected)
{
    RmdContext ctx;
    RmdSource source = source_text(text, size, 1);
    RmdUnit *unit;
    bool accepted;
    rmd_context_init(&ctx, NULL);
    accepted = rmd_read(&ctx, &source, &unit);
    check(accepted == expected, name);
    if (accepted != expected) fprintf(stderr, "diagnostic: %s\n", ctx.error);
    if (!accepted) {
        check(unit == NULL && ctx.units == NULL && ctx.last_unit == NULL &&
              ctx.failure == NULL && ctx.error_count == 1, "failure leaves no published unit");
    }
    rmd_context_destroy(&ctx);
}

#define SYNTAX(name, text, accepted) syntax_case(name, text, sizeof(text) - 1, accepted)

static void test_lexical_boundaries(void)
{
    SYNTAX("empty input", "", true);
    SYNTAX("maximal u64", "const n: u64 = 18446744073709551615u64;", true);
    SYNTAX("maximal hexadecimal u64", "const n: u64 = 0xffffffffffffffffu64;", true);
    SYNTAX("u64 decimal overflow", "const n: u64 = 18446744073709551616u64;", false);
    SYNTAX("u64 hexadecimal overflow", "const n: u64 = 0x10000000000000000u64;", false);
    SYNTAX("numeric suffix boundary", "const n: u64 = 12u64tail;", false);
    SYNTAX("numeric separator", "const n: u64 = 1_2u64;", false);
    SYNTAX("empty hexadecimal digits", "const n: u8 = 0xu8;", false);
    SYNTAX("uppercase prefix", "const n: u8 = 0Xffu8;", false);
    SYNTAX("reserved word boundary", "fn sizeof_buffer() -> unit {}", true);
    SYNTAX("reserved word identifier", "fn sizeof() -> unit {}", false);
    SYNTAX("high comment bytes", "// \xff\nfn f() -> unit {}", true);
    SYNTAX("high string bytes", "const s: *u8 = \"\xff\";", true);
    SYNTAX("high identifier byte", "fn f\xff() -> unit {}", false);
    SYNTAX("zero after declarations", "fn f() -> unit {}\0", false);
    SYNTAX("zero in comment", "// x\0y", false);
    SYNTAX("zero in string", "const s: *u8 = \"x\0y\";", false);
    SYNTAX("invalid escape", "const s: *u8 = \"\\q\";", false);
    SYNTAX("short hex escape", "const s: *u8 = \"\\xA\";", false);
    SYNTAX("unterminated escaped quote", "const s: *u8 = \"\\\"", false);
    SYNTAX("native symbol empty", "extern fn f() -> unit = \"\";", false);
    SYNTAX("native symbol embedded zero", "extern fn f() -> unit = \"a\\0b\";", false);
    SYNTAX("native symbol high byte", "extern fn f() -> unit = \"\xff\";", false);
    SYNTAX("comparison equality boundary", "fn f() -> bool { return a < b == c < d; }", true);
    SYNTAX("comparison boolean boundary", "fn f() -> bool { return a < b && c < d; }", true);
    SYNTAX("ordering cannot chain", "fn f() -> bool { return a < b < c; }", false);
    SYNTAX("equality cannot chain", "fn f() -> bool { return a == b != c; }", false);
    SYNTAX("typed count", "record R { x: [u8; 1usize]; }", false);
    SYNTAX("empty record", "record R {}", false);
    SYNTAX("empty parameter then comma", "fn f(,) -> unit {}", false);
}

static void test_grammar_corpus(void)
{
    SYNTAX("syntax: empty_unit",
           "", true);
    SYNTAX("syntax: empty_function",
           "fn test() -> unit {}", true);
    SYNTAX("syntax: return_unit",
           "fn test() -> unit { return; }", true);
    SYNTAX("syntax: trailing_parameter_comma",
           "fn test(a: u32,) -> u32 { return a; }", true);
    SYNTAX("syntax: record_fields",
           "record Pair { left: u8; right: *Pair; }", true);
    SYNTAX("syntax: forward_pointer_record",
           "record A { b: *B; } record B { a: *A; }", true);
    SYNTAX("syntax: typed_array_constructor",
           "fn test() -> unit { var a: [u32; 2] = make [u32; 2] { 1u32, 2u32, }; }", true);
    SYNTAX("syntax: nested_array_constructor",
           "fn test() -> unit { var a: [[u8; 1]; 1] = make [[u8; 1]; 1] { make [u8; 1] { 7u8 } }; }", true);
    SYNTAX("syntax: record_constructor",
           "record R { a: u8; } fn test() -> unit { var r: R = make R { a: 1u8, }; }", true);
    SYNTAX("syntax: record_condition_boundary",
           "record R { flag: bool; } fn test() -> unit { if make R { flag: true }.flag {} }", true);
    SYNTAX("syntax: foreign_symbol",
           "extern fn test(x: usize) -> *u8 = \"native_test\";", true);
    SYNTAX("syntax: function_value_constant",
           "const f: fn(u32) -> u32 = test; fn test(a: u32) -> u32 { return a; }", true);
    SYNTAX("syntax: function_type_trailing_comma",
           "fn test() -> unit { var f: fn(u8,) -> unit = null(fn(u8,) -> unit); }", true);
    SYNTAX("syntax: function_call_trailing_comma",
           "fn f(a: u32) -> unit {} fn test() -> unit { f(1u32,); }", true);
    SYNTAX("syntax: pointer_place",
           "record R { a: u8; } fn test(p: *R) -> unit { (*p).a = 1u8; }", true);
    SYNTAX("syntax: pointer_index",
           "fn test(p: *u8) -> u8 { return p[0usize]; }", true);
    SYNTAX("syntax: nested_blocks",
           "fn test() -> unit { { { var n: u8 = 0u8; } } }", true);
    SYNTAX("syntax: uninitialized_storage",
           "fn test() -> unit { var n: u8 = uninit; n = 1u8; }", true);
    SYNTAX("syntax: if_else",
           "fn test() -> unit { if true { return; } else { trap; } }", true);
    SYNTAX("syntax: nested_if",
           "fn test() -> unit { if true {} else { if false {} } }", true);
    SYNTAX("syntax: while_break_continue",
           "fn test() -> unit { while true { if false { break; } continue; } }", true);
    SYNTAX("syntax: trap",
           "fn test() -> unit { trap; }", true);
    SYNTAX("syntax: operators",
           "fn test(a: u32, b: u32) -> bool { return (a + b * 3u32 << 1u32) != 0u32 && !false || true; }", true);
    SYNTAX("syntax: bitwise_operators",
           "fn test(a: u32, b: u32) -> u32 { return ~a & b ^ 2u32 | 1u32; }", true);
    SYNTAX("syntax: signed_minimum_token_shape",
           "const n: i8 = -128i8;", true);
    SYNTAX("syntax: hexadecimal_upper_digits",
           "const n: u64 = 0xABCDEFu64;", true);
    SYNTAX("syntax: keyword_identifier_boundary",
           "fn sizeof_buffer() -> unit { var while_loop: bool = false; }", true);
    SYNTAX("syntax: removed_keywords_are_names",
           "fn module(import: u32, pub: u32) -> u32 { var unsafe: u32 = import; return unsafe + pub; }", true);
    SYNTAX("syntax: high_bytes_in_comment",
           "// \377\nfn test() -> unit {}", true);
    SYNTAX("syntax: high_bytes_in_string",
           "const text: *u8 = \"\377\";", true);
    SYNTAX("syntax: string_escapes",
           "const text: *u8 = \"\\\\\\\"\\n\\r\\t\\0\\x41\";", true);
    SYNTAX("syntax: null_function",
           "fn test() -> unit { var f: fn() -> unit = null(fn() -> unit); }", true);
    SYNTAX("syntax: null_pointer",
           "fn test() -> unit { var p: **u8 = null(**u8); }", true);
    SYNTAX("syntax: layout_queries",
           "record R { x: u8; } const n: usize = sizeof(R); const a: usize = alignof(R); const o: usize = offsetof(R, x);", true);
    SYNTAX("syntax: scalar_cast_chain",
           "fn test(a: u8) -> u64 { return a as u32 as u64; }", true);
    SYNTAX("syntax: postfix_chain",
           "record R { f: fn(u32) -> u32; } fn test(p: *R) -> u32 { return (*p).f(1u32); }", true);
    SYNTAX("syntax: pointer_arithmetic",
           "fn test(p: *u8) -> *u8 { return p + 1isize - 1isize; }", true);
    SYNTAX("syntax: cast_then_pointer_arithmetic",
           "fn test(p: *u8) -> *u32 { return (p as *u32) + 1isize; }", true);
    SYNTAX("syntax: carriage_return_whitespace",
           "fn\rtest()\t-> unit {\r\nreturn;\r\n}", true);
    SYNTAX("syntax: end_of_file_comment",
           "fn test() -> unit {} // last comment", true);
    SYNTAX("syntax error: removed_module_header",
           "module test;", false);
    SYNTAX("syntax error: removed_import",
           "import test;", false);
    SYNTAX("syntax error: removed_visibility",
           "pub fn test() -> unit {}", false);
    SYNTAX("syntax error: qualified_name",
           "fn test() -> unit { a::b(); }", false);
    SYNTAX("syntax error: missing_variable_semicolon",
           "fn test() -> unit { var x: u8 = 0u8 }", false);
    SYNTAX("syntax error: missing_const_semicolon",
           "const x: u8 = 0u8", false);
    SYNTAX("syntax error: missing_function_result",
           "fn test() {}", false);
    SYNTAX("syntax error: missing_parameter_type",
           "fn test(a) -> unit {}", false);
    SYNTAX("syntax error: missing_local_type",
           "fn test() -> unit { var x = 0u8; }", false);
    SYNTAX("syntax error: missing_initializer",
           "fn test() -> unit { var x: u8; }", false);
    SYNTAX("syntax error: unsupported_let",
           "fn test() -> unit { let x: u8 = 0u8; }", false);
    SYNTAX("syntax error: else_if_without_block",
           "fn test() -> unit { if true {} else if false {} }", false);
    SYNTAX("syntax error: empty_record",
           "record Empty {}", false);
    SYNTAX("syntax error: record_field_comma",
           "record R { x: u8, y: u8 }", false);
    SYNTAX("syntax error: record_trailing_semicolon",
           "record R { x: u8; };", false);
    SYNTAX("syntax error: unsuffixed_expression_integer",
           "fn test() -> unit { var x: u8 = 0; }", false);
    SYNTAX("syntax error: bad_suffix",
           "const x: u8 = 0u128;", false);
    SYNTAX("syntax error: malformed_hex",
           "const x: u8 = 0xu8;", false);
    SYNTAX("syntax error: uppercase_hex_prefix",
           "const x: u8 = 0X10u8;", false);
    SYNTAX("syntax error: numeric_identifier_tail",
           "const x: u8 = 1u8extra;", false);
    SYNTAX("syntax error: numeric_separator",
           "const x: u32 = 1_000u32;", false);
    SYNTAX("syntax error: floating_literal",
           "const x: u8 = 1.0u8;", false);
    SYNTAX("syntax error: unterminated_string",
           "const x: *u8 = \"abc;", false);
    SYNTAX("syntax error: unknown_escape",
           "const x: *u8 = \"\\q\";", false);
    SYNTAX("syntax error: short_hex_escape",
           "const x: *u8 = \"\\xA\";", false);
    SYNTAX("syntax error: invalid_hex_escape",
           "const x: *u8 = \"\\xGG\";", false);
    SYNTAX("syntax error: literal_line_feed",
           "const x: *u8 = \"a\nb\";", false);
    SYNTAX("syntax error: literal_carriage_return",
           "const x: *u8 = \"a\rb\";", false);
    SYNTAX("syntax error: zero_in_string",
           "const x: *u8 = \"\000\";", false);
    SYNTAX("syntax error: zero_in_comment",
           "// zero \000\n", false);
    SYNTAX("syntax error: non_ascii_identifier",
           "fn t\377() -> unit {}", false);
    SYNTAX("syntax error: block_comment",
           "/* comment */ fn test() -> unit {}", false);
    SYNTAX("syntax error: chained_ordering",
           "fn test() -> unit { 1u8 < 2u8 < 3u8; }", false);
    SYNTAX("syntax error: chained_equality",
           "fn test() -> unit { 1u8 == 2u8 == 3u8; }", false);
    SYNTAX("syntax error: compound_assignment",
           "fn test() -> unit { var x: u8 = 1u8; x += 1u8; }", false);
    SYNTAX("syntax error: assignment_expression",
           "fn test() -> unit { var x: u8 = (x = 1u8); }", false);
    SYNTAX("syntax error: two_return_values",
           "fn test() -> unit { return 1u8, 2u8; }", false);
    SYNTAX("syntax error: uninit_as_expression",
           "fn test() -> unit { uninit; }", false);
    SYNTAX("syntax error: unadorned_array_literal",
           "fn test() -> unit { var a: [u8; 1] = [1u8]; }", false);
    SYNTAX("syntax error: typed_array_count",
           "fn test() -> unit { var a: [u8; 1usize] = uninit; }", false);
    SYNTAX("syntax error: hex_array_count",
           "fn test() -> unit { var a: [u8; 0x1] = uninit; }", false);
    SYNTAX("syntax error: constructor_field_semicolon",
           "fn test() -> unit { make R { x: 1u8; }; }", false);
    SYNTAX("syntax error: generic_type",
           "fn test() -> unit { var a: Box[u8] = uninit; }", false);
    SYNTAX("syntax error: nested_function",
           "fn test() -> unit { fn inner() -> unit {} }", false);
    SYNTAX("syntax error: missing_final_brace",
           "fn test() -> unit {", false);
    SYNTAX("syntax error: trailing_comma_without_argument",
           "fn test(,) -> unit {}", false);
    SYNTAX("syntax error: unknown_punctuation",
           "fn test() -> unit { @; }", false);
    SYNTAX("semantic control: positive_signed_literal_out_of_range",
           "const n: i8 = 128i8;", true);
    SYNTAX("semantic control: parenthesized_signed_minimum",
           "const n: i8 = -(128i8);", true);
    SYNTAX("semantic control: unsigned_literal_out_of_range",
           "const n: u8 = 256u8;", true);
    SYNTAX("semantic control: zero_array_count",
           "const n: [u8; 0] = make [u8; 0] {};", true);
    SYNTAX("semantic control: unit_storage",
           "fn test() -> unit { var x: unit = uninit; }", true);
    SYNTAX("semantic control: missing_nonunit_return",
           "fn test() -> u32 {}", true);
    SYNTAX("semantic control: break_outside_loop",
           "fn test() -> unit { break; }", true);
    SYNTAX("semantic control: nonplace_assignment",
           "fn test() -> unit { 1u8 = 2u8; }", true);
    SYNTAX("semantic control: temporary_address",
           "record R { x: u8; } fn test() -> unit { &(make R { x: 1u8 }); }", true);
    SYNTAX("semantic control: type_name_as_value",
           "record R { x: u8; } fn test() -> unit { R; }", true);
    SYNTAX("semantic control: unit_return_expression",
           "fn f() -> unit {} fn test() -> unit { return f(); }", true);
    SYNTAX("semantic control: constant_arithmetic",
           "const n: u8 = 1u8 + 2u8;", true);
}

static void test_ast(void)
{
    static const char text[] =
        "const direct: i8 = -128i8;"
        "const grouped: i8 = -(128i8);"
        "const bytes: *u8 = \"A\\0\\xFF\\n\\\"\\\\\";"
        "fn f(a: fn(*u8,) -> unit,) -> u64 { return a + b * c - d; }"
        "const offset: usize = offsetof(Node, hook);";
    static const unsigned char decoded[] = {'A', 0, 255, '\n', '"', '\\', 0};
    RmdContext ctx;
    RmdSource source = source_text(text, sizeof(text) - 1, 19);
    RmdUnit *unit;
    RmdDecl *decl;
    RmdExpr *expr;
    rmd_context_init(&ctx, NULL);
    if (!rmd_read(&ctx, &source, &unit)) {
        check(false, "AST fixture parses");
        fprintf(stderr, "%s\n", ctx.error);
        rmd_context_destroy(&ctx);
        return;
    }
    check(unit->source == &source, "source retained");
    decl = unit->declarations;
    check(decl->unit_identity == 19 && decl->identity == 1, "declaration identity");
    expr = decl->init;
    check(expr->kind == RMD_E_UNARY && expr->op == RMD_OP_NEG &&
          expr->left->kind == RMD_E_INTEGER && expr->left->integer == 128 &&
          expr->left->literal_type == RMD_T_I8, "direct negative token preserved");
    check(expr->loc.source == &source && expr->loc.offset == 19,
          "source byte offset");
    decl = decl->next;
    check(decl->init->kind == RMD_E_UNARY &&
          decl->init->left->kind == RMD_E_GROUP &&
          decl->init->left->left->kind == RMD_E_INTEGER,
          "parentheses preserved for literal range checking");
    decl = decl->next;
    check(decl->init->byte_count == sizeof(decoded) &&
          memcmp(decl->init->bytes, decoded, sizeof(decoded)) == 0,
          "decoded bytes and trailing zero");
    decl = decl->next;
    check(decl->param_count == 1 && decl->params->syntax_type->kind == RMD_T_FUNCTION &&
          decl->params->syntax_type->param_count == 1 &&
          decl->params->syntax_type->params[0]->kind == RMD_T_POINTER &&
          decl->params->syntax_type->base->kind == RMD_T_UNIT,
          "nested function type and trailing commas");
    expr = decl->body->body->expr;
    check(expr->kind == RMD_E_BINARY && expr->op == RMD_OP_SUB &&
          expr->left->op == RMD_OP_ADD && expr->left->right->op == RMD_OP_MUL,
          "arithmetic precedence and left association");
    decl = decl->next;
    check(decl->init->kind == RMD_E_OFFSETOF &&
          strcmp(decl->init->syntax_type->name->text, "Node") == 0 &&
          strcmp(decl->init->field_name->text, "hook") == 0,
          "offsetof record and field");
    check(decl->identity == 5 && decl->next == NULL, "declaration order");
    rmd_context_destroy(&ctx);
}

static void test_failure_boundary(void)
{
    RmdContext ctx;
    RmdSource first = source_text("fn a() -> unit {}", 17, 1);
    RmdSource broken = source_text("fn b() -> unit {} @", 19, 2);
    RmdSource last = source_text("fn c() -> unit {}", 17, 3);
    RmdUnit *first_unit;
    RmdUnit *last_unit;
    RmdUnit *rejected;
    rmd_context_init(&ctx, NULL);
    check(rmd_read(&ctx, &first, &first_unit), "first unit accepted");
    check(!rmd_read(&ctx, &broken, &rejected), "incomplete unit rejected");
    check(rejected == NULL && ctx.units == first_unit && ctx.last_unit == first_unit &&
          first_unit->next == NULL, "failed parse does not append partial declarations");
    check(rmd_read(&ctx, &last, &last_unit), "reader reusable after diagnostic");
    check(first_unit->next == last_unit && last_unit->next == NULL &&
          ctx.last_unit == last_unit && ctx.failure == NULL,
          "successful unit appends after failed read");
    rmd_context_destroy(&ctx);
}

static void test_read_range(void)
{
    static const char prefix[] = "\0@\xff\nignored\n";
    static const char text[] = "\0@\xff\nignored\n"
        "fn selected() -> u8 {\n    return 7u8;\n}\n" "\"\0@\xff";
    static const char broken[] = "\0@\xff\nignored\n"
        "fn broken() -> unit {\n    @\n}\n" "\0@\xff";
    static const char incomplete[] = "\0@\xff\nignored\nfn incomplete() -> unit {}";
    static const char string[] = "const s: *u8 = \"x\";";
    static const char number[] = "const n: u8 = 1u8;";
    static const char comment[] = "// bounded comment\0suffix";
    RmdContext ctx;
    RmdSource source = source_text(text, sizeof(text) - 1, 29);
    RmdSource bad_source = source_text(broken, sizeof(broken) - 1, 30);
    RmdSource incomplete_source = source_text(incomplete, sizeof(incomplete) - 1, 31);
    RmdSource string_source = source_text(string, sizeof(string) - 1, 32);
    RmdSource number_source = source_text(number, sizeof(number) - 1, 33);
    RmdSource comment_source = source_text(comment, sizeof(comment) - 1, 34);
    RmdUnit *unit;
    RmdUnit *rejected;
    RmdDecl *decl;
    size_t begin = sizeof(prefix) - 1;
    size_t end = begin + sizeof("fn selected() -> u8 {\n    return 7u8;\n}\n") - 1;
    size_t error_offset = begin + sizeof("fn broken() -> unit {\n    ") - 1;
    rmd_context_init(&ctx, NULL);
    if (!rmd_read_range(&ctx, &source, begin, end, &unit)) {
        check(false, "range excludes invalid prefix and suffix bytes");
        fprintf(stderr, "%s\n", ctx.error);
        rmd_context_destroy(&ctx);
        return;
    }
    check(unit->source == &source && source.bytes == (const unsigned char *)text &&
          source.size == sizeof(text) - 1,
          "range retains the complete original source");
    decl = unit->declarations;
    check(decl != NULL && decl->next == NULL && decl->unit_identity == 29 &&
          decl->identity == 1 && decl->loc.source == &source && decl->loc.offset == begin,
          "range declarations retain identity and absolute locations");
    check(decl->body->body->expr->loc.source == &source &&
          decl->body->body->expr->loc.offset ==
              begin + sizeof("fn selected() -> u8 {\n    return ") - 1,
          "range expression location includes preceding source lines");
    check(!rmd_read_range(&ctx, &bad_source, begin, sizeof(broken) - 4, &rejected) &&
          rejected == NULL && ctx.error_loc.source == &bad_source &&
          ctx.error_loc.offset == error_offset,
          "range diagnostic retains the original source and absolute offset");
    check(ctx.units == unit && ctx.last_unit == unit && unit->next == NULL &&
          ctx.failure == NULL, "failed range publishes no partial unit");
    end = sizeof(incomplete) - 2;
    check(!rmd_read_range(&ctx, &incomplete_source, begin, end, &rejected) &&
          ctx.error_loc.source == &incomplete_source && ctx.error_loc.offset == end,
          "range end is EOF even when the next original byte completes the declaration");
    check(!rmd_read_range(&ctx, &string_source, 0, sizeof(string) - 3, &rejected) &&
          strstr(ctx.error, "unterminated string") != NULL,
          "string scanning does not cross the range end");
    check(!rmd_read_range(&ctx, &number_source, 0, sizeof("const n: u8 = 1") - 1,
                          &rejected) && ctx.error_loc.source == &number_source &&
          ctx.error_loc.offset == sizeof("const n: u8 = ") - 1 &&
          strcmp(ctx.error, "expected an expression") == 0,
          "integer scanning does not use a suffix outside the range");
    check(rmd_read_range(&ctx, &comment_source, 0, sizeof("// bounded comment") - 1,
                         &rejected) && rejected->declarations == NULL,
          "comment scanning excludes the zero byte after the range");
    rmd_context_destroy(&ctx);
}

static void test_invalid_ranges(void)
{
    static const char text[] = "@\0@";
    static const size_t invalid[][2] = {
        {1, 0}, {0, sizeof(text)}, {sizeof(text), sizeof(text)}, {0, SIZE_MAX},
        {SIZE_MAX, SIZE_MAX}
    };
    RmdContext ctx;
    RmdSource source = source_text(text, sizeof(text) - 1, 1);
    RmdUnit *unit;
    RmdUnit *previous;
    size_t index;
    rmd_context_init(&ctx, NULL);
    for (index = 0; index <= source.size; ++index) {
        check(rmd_read_range(&ctx, &source, index, index, &unit) &&
              unit->declarations == NULL && unit->source == &source,
              "empty range accepts no source bytes");
    }
    previous = ctx.last_unit;
    for (index = 0; index < sizeof(invalid) / sizeof(invalid[0]); ++index) {
        check(!rmd_read_range(&ctx, &source, invalid[index][0], invalid[index][1], &unit) &&
              unit == NULL && ctx.last_unit == previous && previous->next == NULL &&
              ctx.failure == NULL && ctx.error_count == index + 1 &&
              ctx.error_loc.source == &source && ctx.error_loc.offset <= source.size &&
              strstr(ctx.error, "source range") != NULL,
              "invalid range is a diagnostic without a published unit");
    }
    check(rmd_read_range(&ctx, &source, 1, 1, &unit) && previous->next == unit,
          "reader accepts a valid range after range errors");
    rmd_context_destroy(&ctx);
}

static void test_constructors(void)
{
    static const char text[] =
        "const table: Outer = make Outer {"
        " right: make [Pair; 2] {"
        "  make Pair { second: 2u8, first: 1u8 },"
        "  make Pair { first: 3u8, second: 4u8, },"
        " },"
        " left: make [u8; 0] {},"
        "};"
        "fn f() -> unit { if make Flag { set: true }.set {}"
        " while make [bool; 1] { true }[0usize] { break; } }";
    RmdContext ctx;
    RmdSource source = source_text(text, sizeof(text) - 1, 1);
    RmdUnit *unit;
    RmdExpr *expr;
    RmdInit *init;
    RmdStmt *stmt;
    rmd_context_init(&ctx, NULL);
    if (!rmd_read(&ctx, &source, &unit)) {
        check(false, "constructor fixture parses");
        fprintf(stderr, "%s\n", ctx.error);
        rmd_context_destroy(&ctx);
        return;
    }
    expr = unit->declarations->init;
    check(expr->kind == RMD_E_RECORD && expr->syntax_type->kind == RMD_T_NAME &&
          strcmp(expr->syntax_type->name->text, "Outer") == 0,
          "record constructor type");
    init = expr->inits;
    check(strcmp(init->name->text, "right") == 0 &&
          strcmp(init->next->name->text, "left") == 0 && init->next->next == NULL,
          "record constructor preserves source field order");
    expr = init->value;
    check(expr->kind == RMD_E_ARRAY && expr->arg_count == 2 &&
          expr->syntax_type->kind == RMD_T_ARRAY && expr->syntax_type->count == 2 &&
          strcmp(expr->syntax_type->base->name->text, "Pair") == 0,
          "array constructor type and elements");
    check(strcmp(expr->args[0]->inits->name->text, "second") == 0 &&
          expr->args[0]->inits->value->integer == 2 &&
          expr->args[1]->inits->value->integer == 3,
          "nested record construction preserves element and field order");
    check(init->next->value->kind == RMD_E_ARRAY && init->next->value->arg_count == 0,
          "empty constructor is retained for semantic checking");
    stmt = unit->declarations->next->body->body;
    check(stmt->kind == RMD_S_IF && stmt->expr->kind == RMD_E_FIELD &&
          stmt->expr->left->kind == RMD_E_RECORD && stmt->body->kind == RMD_S_BLOCK,
          "record constructor before condition block");
    stmt = stmt->next;
    check(stmt->kind == RMD_S_WHILE && stmt->expr->kind == RMD_E_INDEX &&
          stmt->expr->left->kind == RMD_E_ARRAY && stmt->body->kind == RMD_S_BLOCK,
          "array constructor before condition block");
    rmd_context_destroy(&ctx);
    SYNTAX("pointer constructor rejected", "const x: *R = make *R {};", false);
    SYNTAX("scalar constructor rejected", "const x: u8 = make u8 {};", false);
    SYNTAX("function constructor rejected", "const x: fn() -> unit = make fn() -> unit {};", false);
    SYNTAX("record field missing colon", "const x: R = make R { a 1u8 };", false);
    SYNTAX("record field missing comma", "const x: R = make R { a: 1u8 b: 2u8 };", false);
    SYNTAX("array element missing comma", "const x: [u8; 2] = make [u8; 2] { 1u8 2u8 };", false);
    SYNTAX("record stray comma", "const x: R = make R {,};", false);
    SYNTAX("array stray comma", "const x: [u8; 1] = make [u8; 1] {,};", false);
    SYNTAX("record empty constructor", "const x: R = make R {};", true);
}

static void *reject_allocation(void *user, size_t size)
{
    (void)user;
    (void)size;
    return NULL;
}

static void reject_release(void *user, void *allocation)
{
    (void)user;
    (void)allocation;
    check(false, "failed allocator must not release absent allocation");
}

static void test_limits(void)
{
    RmdAllocator allocator;
    RmdContext ctx;
    RmdSource source = source_text("", 0, 1);
    RmdUnit *unit;
    char nested[512];
    size_t size = 0;
    unsigned index;
    allocator.user = NULL;
    allocator.allocate = reject_allocation;
    allocator.release = reject_release;
    rmd_context_init(&ctx, &allocator);
    check(!rmd_read(&ctx, &source, &unit) && unit == NULL && ctx.units == NULL &&
          ctx.failure == NULL && ctx.error_count == 1,
          "allocation failure is reported without a published unit");
    rmd_context_destroy(&ctx);
    memcpy(nested, "const x: i8 = ", 14);
    size = 14;
    for (index = 0; index < 300; ++index) nested[size++] = '-';
    memcpy(nested + size, "1i8;", 4);
    size += 4;
    syntax_case("excessive prefix nesting is a diagnostic", nested, size, false);
}

int main(void)
{
    test_lexical_boundaries();
    test_grammar_corpus();
    test_ast();
    test_constructors();
    test_failure_boundary();
    test_read_range();
    test_invalid_ranges();
    test_limits();
    printf("reader: %u/%u checks passed\n", checks - failures, checks);
    return failures == 0 ? 0 : 1;
}
