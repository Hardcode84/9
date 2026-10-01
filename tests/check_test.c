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
        fprintf(stderr, "checker check failed: %s\n", name);
    }
}

static RmdSource source_text(const char *text, uint64_t identity)
{
    RmdSource source;
    source.path = "checker-test";
    source.bytes = (const unsigned char *)text;
    source.size = strlen(text);
    source.identity = identity;
    return source;
}

static bool check_source(RmdContext *ctx, RmdSource *source, RmdUnit **unit)
{
    return rmd_read(ctx, source, unit) && rmd_collect(ctx) &&
           rmd_resolve(ctx) && rmd_check(ctx);
}

static void source_case(const char *name, const char *text, const char *error)
{
    RmdContext ctx;
    RmdSource source = source_text(text, 1);
    RmdUnit *unit;
    bool accepted;
    bool passed;
    rmd_context_init(&ctx, NULL);
    accepted = check_source(&ctx, &source, &unit);
    passed = error == NULL ? accepted : !accepted && strstr(ctx.error, error) != NULL;
    check(passed, name);
    if (!passed) fprintf(stderr, "diagnostic: %s\n", ctx.error);
    check(ctx.failure == NULL, "stage restores failure frame");
    rmd_context_destroy(&ctx);
}

static void test_witness_rules(void)
{
    source_case("direct signed minimum", "fn f() -> i8 { return -128i8; }", NULL);
    source_case("grouped positive signed overflow",
                "fn f() -> i8 { return -(128i8); }", "outside its type");
    source_case("by-value recursion", "record A { a: A; }", "by-value layout cycle");
    source_case("pointer recursion", "record A { a: *A; }", NULL);
    source_case("array behind recursive pointer", "record A { a: *[A; 1]; }", NULL);
    source_case("missing return", "fn f() -> i32 { if true { return 1i32; } }",
                "reach the end");
    source_case("call argument mismatch",
                "fn f(a: u32) -> unit {} fn g() -> unit { f(1u64); }", "type mismatch");
    source_case("unknown field",
                "record A { a: u8; } fn f(p: *A) -> u8 { return (*p).b; }", "no field");
    source_case("duplicate field", "record A { a: u8; a: u32; }", "duplicate field");
    source_case("pointer offset type", "fn f(p: *u8) -> *u8 { return p + 1usize; }",
                "offsets require isize");
    source_case("layout overflow", "record A { a: [u64; 1152921504606846976]; }",
                "exceeds the isize limit");
    source_case("disjoint local scopes",
                "fn f() -> unit { {var x: u8 = 1u8;} {var x: u8 = 2u8;} }", NULL);
    source_case("active local scope",
                "fn f() -> unit { var x: u8 = 1u8; {var x: u8 = 2u8;} }",
                "already visible");
    source_case("check unreachable statements",
                "fn f() -> i32 { return 0i32; return 1u32; }", "type mismatch");
}

static void test_shared_bindings(void)
{
    RmdContext provider;
    RmdContext consumer;
    RmdSource provided = source_text(
        "record Hook { prev: *Hook; next: *Hook; }"
        "record Node { value: u64; hook: Hook; }"
        "extern fn read_node(p: *Node) -> u64 = \"read_node\";", 11);
    RmdSource consumed = source_text(
        "fn value(p: *Node) -> u64 { return (*p).value; }"
        "fn pass(p: *Node) -> u64 { return read_node(p); }"
        "fn alias(p: *Alias) -> *Node { return p; }", 12);
    RmdName alias = { "Alias", 5, 0 };
    RmdUnit *provided_unit;
    RmdUnit *consumed_unit;
    RmdDecl *node;
    RmdDecl *function;
    RmdDecl node_before;
    RmdDecl function_before;
    RmdField field_before;
    RmdType type_before;
    rmd_context_init(&provider, NULL);
    rmd_context_init(&consumer, NULL);
    if (!check_source(&provider, &provided, &provided_unit)) {
        check(false, "provider resolves");
        goto done;
    }
    node = provided_unit->declarations->next;
    function = node->next;
    node_before = *node;
    function_before = *function;
    field_before = *node->fields;
    type_before = *node->type;
    check(node->type->size == 24 && node->type->align == 8 &&
          node->fields->next->offset == 8, "embedded hook layout");
    check(rmd_bind(&consumer, provided_unit->declarations->name,
                   provided_unit->declarations), "bind recursive record");
    check(rmd_bind(&consumer, node->name, node), "bind record in a second context");
    check(rmd_bind(&consumer, &alias, node), "two names share nominal identity");
    check(rmd_bind(&consumer, function->name, function), "bind function signature");
    check(check_source(&consumer, &consumed, &consumed_unit),
          "field access and calls use shared facts");
    check(memcmp(node, &node_before, sizeof(*node)) == 0 &&
          memcmp(node->fields, &field_before, sizeof(*node->fields)) == 0 &&
          memcmp(node->type, &type_before, sizeof(*node->type)) == 0 &&
          memcmp(function, &function_before, sizeof(*function)) == 0,
          "consumer does not modify published declarations");
    check(!rmd_bind(&consumer, node->name, node) &&
          strstr(consumer.error, "duplicate name") != NULL,
          "duplicate supplied name rejected");
done:
    rmd_context_destroy(&consumer);
    rmd_context_destroy(&provider);
}

static void test_complete_forms(void)
{
    source_case("constant table and callback",
        "record Pair { first: u32; second: u32; }"
        "const widths: [u32; 3] = make [u32; 3] { 8u32, 16u32, 32u32 };"
        "fn increment(value: u32) -> u32 { return value + 1u32; }"
        "const callback: fn(u32) -> u32 = increment;"
        "const pair: Pair = make Pair { second: 2u32, first: 1u32 };"
        "fn apply() -> u32 {"
        "var item: Pair = pair; var f: fn(u32) -> u32 = callback;"
        "item.first = widths[1usize]; return f(item.first) + item.second; }", NULL);
    source_case("complete constant whitelist",
        "record R { a: i8; b: *u8; c: fn() -> unit; d: usize; }"
        "fn f() -> unit {}"
        "const a: i8 = (-128i8); const b: bool = (true);"
        "const c: *u8 = null(*u8); const d: fn() -> unit = null(fn() -> unit);"
        "const e: [usize; 3] = make [usize; 3] { sizeof(R), alignof(R), offsetof(R, d) };"
        "const r: R = make R { a: -1i8, b: \"x\", c: f, d: sizeof(R) };", NULL);
    source_case("nested array and aggregate places",
        "record R { data: [u8; 2]; }"
        "fn f(p: *R) -> u8 { var a: [R; 1] = make [R; 1] {"
        "make R { data: make [u8; 2] { 1u8, 2u8 } } };"
        "a[0usize].data[1usize] = (*p).data[0usize];"
        "var q: *u8 = &a[0usize].data[1usize]; return q[0usize]; }", NULL);
    source_case("temporary field and element reads",
        "record R { x: u8; } fn f() -> u8 {"
        "return make [R; 1] { make R { x: 1u8 } }[0usize].x; }", NULL);
    source_case("array initializer count",
        "const a: [u8; 2] = make [u8; 2] { 1u8 };", "every element");
    source_case("array initializer type",
        "const a: [u8; 1] = make [u8; 1] { 1u16 };", "type mismatch");
    source_case("record missing initializer",
        "record R { x: u8; y: u8; } const r: R = make R { x: 1u8 };", "every field");
    source_case("record duplicate initializer",
        "record R { x: u8; } const r: R = make R { x: 1u8, x: 2u8 };",
        "duplicate initializer");
    source_case("array index type",
        "fn f(p: *u8) -> u8 { return p[0u64]; }", "indexing requires usize");
    source_case("nonindexable value",
        "fn f() -> u8 { return 1u8[0usize]; }", "array or data pointer");
    source_case("temporary element has no address",
        "fn f() -> *u8 { return &make [u8; 1] { 1u8 }[0usize]; }",
        "address-taking requires a place");
    source_case("constant element cannot be assigned",
        "const a: [u8; 1] = make [u8; 1] { 1u8 };"
        "fn f() -> unit { a[0usize] = 2u8; }", "writable place");
    source_case("constant field cannot be assigned",
        "record R { x: u8; } const r: R = make R { x: 1u8 };"
        "fn f() -> unit { r.x = 2u8; }", "writable place");
    source_case("constant alias has raw write precondition",
        "const a: u8 = 1u8; fn f() -> unit { var p: *u8 = &a; *p = 2u8; }", NULL);
    source_case("constant arithmetic is excluded", "const a: u8 = 1u8 + 2u8;",
        "constant initializer");
    source_case("constant cast is excluded", "const a: u8 = 1u16 as u8;",
        "constant initializer");
    source_case("constant call is excluded",
        "fn f() -> u8 { return 1u8; } const a: u8 = f();", "constant initializer");
    source_case("constant reference is excluded", "const a: u8 = 1u8; const b: u8 = a;",
        "only function names");
    source_case("constant conditional is excluded", "const a: bool = true || false;",
        "constant initializer");
    source_case("group before constant negation is excluded", "const a: i8 = -(1i8);",
        "constant initializer");
    source_case("direct constant unsigned negation", "const a: u8 = -255u8;", NULL);
    source_case("duplicate extern parameter",
        "extern fn f(x: u8, x: u8) -> unit = \"native\";", "already visible");
    source_case("extern parameter shadows top level",
        "record X { x: u8; } extern fn f(X: u8) -> unit = \"native\";", "already visible");
    source_case("no aggregate parameter",
        "record R { x: u8; } fn f(r: R) -> unit {}", "scalar types");
    source_case("no aggregate result",
        "record R { x: u8; } fn f() -> R { trap; }", "scalar or unit");
    source_case("nested function type scalar restriction",
        "record R { x: u8; } record F { f: fn(R) -> unit; }", "scalar types");
    source_case("unit storage rejected", "fn f() -> unit { var x: unit = uninit; }",
        "not a storage type");
    source_case("unit pointer rejected", "record R { p: *unit; }", "pointer target");
    source_case("zero array rejected", "record R { data: [u8; 0]; }", "must be positive");
    source_case("pointer comparison ordering rejected",
        "fn f(a: *u8, b: *u8) -> bool { return a < b; }", "integer operation");
    source_case("function cast rejected",
        "fn f() -> unit {} fn g() -> *u8 { return f as *u8; }", "invalid cast");
    source_case("unit return value rejected",
        "fn f() -> unit {} fn g() -> unit { return f(); }", "without a value");
    source_case("conservative loop return",
        "fn f() -> i32 { while true { return 1i32; } }", "reach the end");
    source_case("loop exits and mutation",
        "fn f() -> i32 { var x: i32 = 0i32; while x < 10i32 {"
        "x = x + 1i32; if x == 2i32 { continue; } if x == 4i32 { break; } }"
        "return x; }", NULL);
    source_case("break outside loop", "fn f() -> unit { break; }", "outside a loop");
    source_case("trap terminates function", "fn f() -> i32 { trap; }", NULL);
}

static void test_resource_bounds(void)
{
    char source[24000];
    size_t size = 0;
    unsigned i;
    static const char prefix[] = "fn f() -> u8 { return 1u8";
    memcpy(source, prefix, sizeof(prefix) - 1);
    size = sizeof(prefix) - 1;
    for (i = 0; i < 2000; ++i) {
        memcpy(source + size, " + 1u8", 6);
        size += 6;
    }
    memcpy(source + size, "; }", 4);
    source_case("flat expression depth is bounded", source, "semantic nesting limit");
    size = 0;
    for (i = 0; i < 300; ++i) {
        int count = snprintf(source + size, sizeof(source) - size,
            "record R%u { x: R%u; }", i, i + 1);
        if (count < 0 || (size_t)count >= sizeof(source) - size) {
            check(false, "layout depth fixture fits");
            return;
        }
        size += (size_t)count;
    }
    memcpy(source + size, "record R300 { x: u8; }", 23);
    source_case("by-value layout traversal is bounded", source, "semantic nesting limit");
    size = 0;
    memcpy(source, "record R300 { x: u8; }", 22);
    size = 22;
    for (i = 300; i != 0; --i) {
        int count = snprintf(source + size, sizeof(source) - size,
            "record R%u { x: R%u; }", i - 1, i);
        if (count < 0 || (size_t)count >= sizeof(source) - size) {
            check(false, "reverse layout depth fixture fits");
            return;
        }
        size += (size_t)count;
    }
    source_case("layout depth does not depend on declaration order", source,
                "semantic nesting limit");
}

static void test_identity_facts(void)
{
    RmdContext first;
    RmdContext second;
    RmdContext consumer;
    RmdSource first_source = source_text(
        "record Inner { value: u32; } record Outer { inner: *Inner; }"
        "extern fn good(p: *Inner) -> unit = \"native\";", 40);
    RmdSource second_source = source_text(
        "record Inner { value: i32; } record Outer { inner: *Inner; }"
        "extern fn bad(p: *Inner) -> unit = \"native\";", 40);
    RmdSource duplicate = source_text("record Different { x: u8; }", 40);
    RmdUnit *first_unit;
    RmdUnit *second_unit;
    RmdUnit *duplicate_unit;
    RmdName other = { "Other", 5, 0 };
    RmdDecl *outer;
    RmdDecl *bad;
    size_t identities;
    size_t globals;
    rmd_context_init(&first, NULL);
    rmd_context_init(&second, NULL);
    rmd_context_init(&consumer, NULL);
    if (!check_source(&first, &first_source, &first_unit) ||
        !check_source(&second, &second_source, &second_unit)) {
        check(false, "identity providers resolve");
        goto done;
    }
    outer = first_unit->declarations->next;
    bad = second_unit->declarations->next->next;
    check(rmd_bind(&consumer, outer->name, outer), "record binding supplies dependency facts");
    identities = consumer.identities.count;
    globals = consumer.globals.count;
    check(!rmd_bind(&consumer, &other, second_unit->declarations->next) &&
          strstr(consumer.error, "conflicting facts") != NULL,
          "conflicting nominal dependency rejected through matching pointer field");
    check(!rmd_bind(&consumer, bad->name, bad) &&
          strstr(consumer.error, "conflicting facts") != NULL,
          "function binding checks nominal dependencies");
    check(consumer.identities.count == identities && consumer.globals.count == globals,
          "failed binding does not publish partial facts");
    check(rmd_bind(&consumer, outer->next->name, outer->next),
          "correct binding succeeds after rejected facts");
    check(rmd_read(&first, &duplicate, &duplicate_unit) && !rmd_collect(&first) &&
          strstr(first.error, "share one identity") != NULL,
          "distinct source declarations cannot reuse identities");
done:
    rmd_context_destroy(&consumer);
    rmd_context_destroy(&second);
    rmd_context_destroy(&first);
}

static void test_constant_facts(void)
{
    RmdContext first;
    RmdContext second;
    RmdContext third;
    RmdContext consumer;
    RmdSource a = source_text("const a: u8 = -255u8;", 50);
    RmdSource b = source_text("const b: u8 = (1u8);", 50);
    RmdSource c = source_text("const c: u8 = 2u8;", 50);
    RmdUnit *ua;
    RmdUnit *ub;
    RmdUnit *uc;
    rmd_context_init(&first, NULL);
    rmd_context_init(&second, NULL);
    rmd_context_init(&third, NULL);
    rmd_context_init(&consumer, NULL);
    if (!check_source(&first, &a, &ua) || !check_source(&second, &b, &ub) ||
        !check_source(&third, &c, &uc)) {
        check(false, "constant providers resolve");
        goto done;
    }
    ua->declarations->link_name = "shared_constant";
    ub->declarations->link_name = "shared_constant";
    uc->declarations->link_name = "shared_constant";
    check(rmd_bind(&consumer, ua->declarations->name, ua->declarations),
          "constant facts bind");
    check(rmd_bind(&consumer, ub->declarations->name, ub->declarations),
          "equivalent constant values share identity");
    check(!rmd_bind(&consumer, uc->declarations->name, uc->declarations) &&
          strstr(consumer.error, "conflicting facts") != NULL,
          "different constant values cannot share identity");
done:
    rmd_context_destroy(&consumer);
    rmd_context_destroy(&third);
    rmd_context_destroy(&second);
    rmd_context_destroy(&first);
}

static void test_invalid_bound_layout(void)
{
    RmdContext consumer;
    RmdDecl decl;
    RmdField field;
    RmdType type;
    RmdName record_name = { "Recursive", 9, 0 };
    RmdName field_name = { "value", 5, 0 };
    memset(&decl, 0, sizeof(decl));
    memset(&field, 0, sizeof(field));
    memset(&type, 0, sizeof(type));
    decl.kind = RMD_D_RECORD;
    decl.name = &record_name;
    decl.unit_identity = 60;
    decl.identity = 1;
    decl.type = &type;
    decl.fields = &field;
    decl.field_count = 1;
    field.name = &field_name;
    field.type = &type;
    type.kind = RMD_T_RECORD;
    type.size = 8;
    type.align = 8;
    type.record_decl = &decl;
    rmd_context_init(&consumer, NULL);
    check(!rmd_bind(&consumer, &record_name, &decl) &&
          strstr(consumer.error, "by-value cycle") != NULL,
          "precomputed sizes cannot hide imported by-value recursion");
    check(consumer.identities.count == 0 && consumer.globals.count == 0,
          "invalid imported layout publishes nothing");
    rmd_context_destroy(&consumer);
}

int main(void)
{
    test_witness_rules();
    test_shared_bindings();
    test_complete_forms();
    test_resource_bounds();
    test_identity_facts();
    test_constant_facts();
    test_invalid_bound_layout();
    printf("checker: %u/%u checks passed\n", checks - failures, checks);
    return failures == 0 ? 0 : 1;
}
