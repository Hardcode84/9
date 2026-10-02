/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0.h"
#include "crust0_x64.h"

#include <stdio.h>
#include <stdlib.h>
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

static CrustSource source_text(const char *text, uint64_t identity)
{
    CrustSource source;
    source.path = "checker-test";
    source.bytes = (const unsigned char *)text;
    source.size = strlen(text);
    source.identity = identity;
    return source;
}

static bool check_source(CrustContext *ctx, CrustSource *source, CrustUnit **unit)
{
    return crust_read(ctx, source, unit) && crust_collect(ctx) && crust_resolve(ctx) &&
           crust_check(ctx);
}

static void source_case(const char *name, const char *text, const char *error)
{
    CrustContext ctx;
    CrustSource source = source_text(text, 1);
    CrustUnit *unit;
    bool accepted;
    bool passed;
    crust_context_init(&ctx, NULL);
    accepted = check_source(&ctx, &source, &unit);
    passed = error == NULL ? accepted : !accepted && strstr(ctx.error, error) != NULL;
    check(passed, name);
    if (!passed)
        fprintf(stderr, "diagnostic: %s\n", ctx.error);
    check(ctx.failure == NULL, "stage restores failure frame");
    crust_context_destroy(&ctx);
}

static void test_witness_rules(void)
{
    source_case("direct signed minimum", "fn f() -> i8 { return -128i8; }", NULL);
    source_case("grouped positive signed overflow", "fn f() -> i8 { return -(128i8); }",
                "outside its type");
    source_case("by-value recursion", "record A { a: A; }", "by-value layout cycle");
    source_case("pointer recursion", "record A { a: *A; }", NULL);
    source_case("array behind recursive pointer", "record A { a: *[A; 1]; }", NULL);
    source_case("missing return", "fn f() -> i32 { if true { return 1i32; } }", "reach the end");
    source_case("call argument mismatch", "fn f(a: u32) -> unit {} fn g() -> unit { f(1u64); }",
                "type mismatch");
    source_case("unknown field", "record A { a: u8; } fn f(p: *A) -> u8 { return (*p).b; }",
                "no field");
    source_case("duplicate field", "record A { a: u8; a: u32; }", "duplicate field");
    source_case("pointer offset type", "fn f(p: *u8) -> *u8 { return p + 1usize; }",
                "offsets require isize");
    source_case("layout overflow", "record A { a: [u64; 1152921504606846976]; }",
                "exceeds the isize limit");
    source_case("disjoint local scopes", "fn f() -> unit { {var x: u8 = 1u8;} {var x: u8 = 2u8;} }",
                NULL);
    source_case("active local scope", "fn f() -> unit { var x: u8 = 1u8; {var x: u8 = 2u8;} }",
                "already visible");
    source_case("check unreachable statements", "fn f() -> i32 { return 0i32; return 1u32; }",
                "type mismatch");
}

static void generated_scope_case(const char *text, bool expected)
{
    CrustContext ctx;
    CrustSource source = source_text(text, 1);
    CrustUnit *unit;
    CrustStmt *branch;
    bool accepted;
    crust_context_init(&ctx, NULL);
    if (!crust_read(&ctx, &source, &unit) || !crust_collect(&ctx) || !crust_resolve(&ctx))
        abort();
    branch = unit->declarations->body->body;
    branch->body = branch->body->body;
    if (branch->otherwise != NULL)
        branch->otherwise = branch->otherwise->body;
    accepted = crust_check(&ctx);
    check(accepted == expected && (expected || strstr(ctx.error, "unknown name") != NULL),
          "generated branch and loop bodies retain their lexical scope");
    crust_context_destroy(&ctx);
}

static void test_generated_scopes(void)
{
    generated_scope_case("fn f()->unit{if true {var x:u8=1u8;}else{var x:u8=2u8;}}", true);
    generated_scope_case("fn f()->u8{if true {var x:u8=1u8;}return x;}", false);
    generated_scope_case("fn f()->u8{if true {var x:u8=1u8;}else{return x;}return 0u8;}", false);
    generated_scope_case("fn f()->u8{while false {var x:u8=1u8;}return x;}", false);
    generated_scope_case("fn f()->unit{while false {var x:u8=1u8;}var x:u8=2u8;}", true);
}

static void test_shared_bindings(void)
{
    CrustContext provider;
    CrustContext consumer;
    CrustSource provided = source_text("record Hook { prev: *Hook; next: *Hook; }"
                                       "record Node { value: u64; hook: Hook; }"
                                       "extern fn read_node(p: *Node) -> u64 = \"read_node\";",
                                       11);
    CrustSource consumed = source_text("fn value(p: *Node) -> u64 { return (*p).value; }"
                                       "fn pass(p: *Node) -> u64 { return read_node(p); }"
                                       "fn alias(p: *Alias) -> *Node { return p; }",
                                       12);
    CrustName alias = {"Alias", 5, 0};
    CrustUnit *provided_unit;
    CrustUnit *consumed_unit;
    CrustDecl *node;
    CrustDecl *function;
    CrustDecl node_before;
    CrustDecl function_before;
    CrustField field_before;
    CrustType type_before;
    crust_context_init(&provider, NULL);
    crust_context_init(&consumer, NULL);
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
    check(node->type->size == 24 && node->type->align == 8 && node->fields->next->offset == 8,
          "embedded hook layout");
    check(crust_bind(&consumer, provided_unit->declarations->name, provided_unit->declarations),
          "bind recursive record");
    check(crust_bind(&consumer, node->name, node), "bind record in a second context");
    check(crust_bind(&consumer, &alias, node), "two names share nominal identity");
    check(crust_bind(&consumer, function->name, function), "bind function signature");
    check(check_source(&consumer, &consumed, &consumed_unit),
          "field access and calls use shared facts");
    check(memcmp(node, &node_before, sizeof(*node)) == 0 &&
              memcmp(node->fields, &field_before, sizeof(*node->fields)) == 0 &&
              memcmp(node->type, &type_before, sizeof(*node->type)) == 0 &&
              memcmp(function, &function_before, sizeof(*function)) == 0,
          "consumer does not modify published declarations");
    check(!crust_bind(&consumer, node->name, node) &&
              strstr(consumer.error, "duplicate name") != NULL,
          "duplicate supplied name rejected");
done:
    crust_context_destroy(&consumer);
    crust_context_destroy(&provider);
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
                "item.first = widths[1usize]; return f(item.first) + item.second; }",
                NULL);
    source_case("complete constant whitelist",
                "record R { a: i8; b: *u8; c: fn() -> unit; d: usize; }"
                "fn f() -> unit {}"
                "const a: i8 = (-128i8); const b: bool = (true);"
                "const c: *u8 = null(*u8); const d: fn() -> unit = null(fn() -> unit);"
                "const e: [usize; 3] = make [usize; 3] { sizeof(R), alignof(R), offsetof(R, d) };"
                "const r: R = make R { a: -1i8, b: \"x\", c: f, d: sizeof(R) };",
                NULL);
    source_case("nested array and aggregate places",
                "record R { data: [u8; 2]; }"
                "fn f(p: *R) -> u8 { var a: [R; 1] = make [R; 1] {"
                "make R { data: make [u8; 2] { 1u8, 2u8 } } };"
                "a[0usize].data[1usize] = (*p).data[0usize];"
                "var q: *u8 = &a[0usize].data[1usize]; return q[0usize]; }",
                NULL);
    source_case("temporary field and element reads",
                "record R { x: u8; } fn f() -> u8 {"
                "return make [R; 1] { make R { x: 1u8 } }[0usize].x; }",
                NULL);
    source_case("array initializer count", "const a: [u8; 2] = make [u8; 2] { 1u8 };",
                "every element");
    source_case("array initializer type", "const a: [u8; 1] = make [u8; 1] { 1u16 };",
                "type mismatch");
    source_case("record missing initializer",
                "record R { x: u8; y: u8; } const r: R = make R { x: 1u8 };", "every field");
    source_case("record duplicate initializer",
                "record R { x: u8; } const r: R = make R { x: 1u8, x: 2u8 };",
                "duplicate initializer");
    source_case("array index type", "fn f(p: *u8) -> u8 { return p[0u64]; }",
                "indexing requires usize");
    source_case("nonindexable value", "fn f() -> u8 { return 1u8[0usize]; }",
                "array or data pointer");
    source_case("temporary element has no address",
                "fn f() -> *u8 { return &make [u8; 1] { 1u8 }[0usize]; }",
                "address-taking requires a place");
    source_case("constant element cannot be assigned",
                "const a: [u8; 1] = make [u8; 1] { 1u8 };"
                "fn f() -> unit { a[0usize] = 2u8; }",
                "writable place");
    source_case("constant field cannot be assigned",
                "record R { x: u8; } const r: R = make R { x: 1u8 };"
                "fn f() -> unit { r.x = 2u8; }",
                "writable place");
    source_case("constant alias has raw write precondition",
                "const a: u8 = 1u8; fn f() -> unit { var p: *u8 = &a; *p = 2u8; }", NULL);
    source_case("constant arithmetic is excluded", "const a: u8 = 1u8 + 2u8;",
                "constant initializer");
    source_case("constant cast is excluded", "const a: u8 = 1u16 as u8;", "constant initializer");
    source_case("constant call is excluded", "fn f() -> u8 { return 1u8; } const a: u8 = f();",
                "constant initializer");
    source_case("constant reference is excluded", "const a: u8 = 1u8; const b: u8 = a;",
                "only function names");
    source_case("constant conditional is excluded", "const a: bool = true || false;",
                "constant initializer");
    source_case("group before constant negation is excluded", "const a: i8 = -(1i8);",
                "constant initializer");
    source_case("direct constant unsigned negation", "const a: u8 = -255u8;", NULL);
    source_case("duplicate extern parameter", "extern fn f(x: u8, x: u8) -> unit = \"native\";",
                "already visible");
    source_case("extern parameter shadows top level",
                "record X { x: u8; } extern fn f(X: u8) -> unit = \"native\";", "already visible");
    source_case("no aggregate parameter", "record R { x: u8; } fn f(r: R) -> unit {}",
                "scalar types");
    source_case("no aggregate result", "record R { x: u8; } fn f() -> R { trap; }",
                "scalar or unit");
    source_case("nested function type scalar restriction",
                "record R { x: u8; } record F { f: fn(R) -> unit; }", "scalar types");
    source_case("unit storage rejected", "fn f() -> unit { var x: unit = uninit; }",
                "not a storage type");
    source_case("unit pointer rejected", "record R { p: *unit; }", "pointer target");
    source_case("zero array rejected", "record R { data: [u8; 0]; }", "must be positive");
    source_case("pointer comparison ordering rejected",
                "fn f(a: *u8, b: *u8) -> bool { return a < b; }", "integer operation");
    source_case("function cast rejected", "fn f() -> unit {} fn g() -> *u8 { return f as *u8; }",
                "invalid cast");
    source_case("unit return value rejected", "fn f() -> unit {} fn g() -> unit { return f(); }",
                "without a value");
    source_case("conservative loop return", "fn f() -> i32 { while true { return 1i32; } }",
                "reach the end");
    source_case("loop exits and mutation",
                "fn f() -> i32 { var x: i32 = 0i32; while x < 10i32 {"
                "x = x + 1i32; if x == 2i32 { continue; } if x == 4i32 { break; } }"
                "return x; }",
                NULL);
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
    source_case("flat expression depth is bounded", source, "semantic traversal depth limit");
    size = 0;
    for (i = 0; i < 300; ++i) {
        int count =
            snprintf(source + size, sizeof(source) - size, "record R%u { x: R%u; }", i, i + 1);
        if (count < 0 || (size_t)count >= sizeof(source) - size) {
            check(false, "layout depth fixture fits");
            return;
        }
        size += (size_t)count;
    }
    memcpy(source + size, "record R300 { x: u8; }", 23);
    source_case("by-value layout traversal is bounded", source, "semantic traversal depth limit");
    size = 0;
    memcpy(source, "record R300 { x: u8; }", 22);
    size = 22;
    for (i = 300; i != 0; --i) {
        int count =
            snprintf(source + size, sizeof(source) - size, "record R%u { x: R%u; }", i - 1, i);
        if (count < 0 || (size_t)count >= sizeof(source) - size) {
            check(false, "reverse layout depth fixture fits");
            return;
        }
        size += (size_t)count;
    }
    source_case("layout depth does not depend on declaration order", source,
                "semantic traversal depth limit");
}

static void test_identity_facts(void)
{
    CrustContext first;
    CrustContext second;
    CrustContext consumer;
    CrustSource first_source =
        source_text("record Inner { value: u32; } record Outer { inner: *Inner; }"
                    "extern fn good(p: *Inner) -> unit = \"native\";",
                    40);
    CrustSource second_source =
        source_text("record Inner { value: i32; } record Outer { inner: *Inner; }"
                    "extern fn bad(p: *Inner) -> unit = \"native\";",
                    40);
    CrustSource duplicate = source_text("record Different { x: u8; }", 40);
    CrustUnit *first_unit;
    CrustUnit *second_unit;
    CrustUnit *duplicate_unit;
    CrustName other = {"Other", 5, 0};
    CrustDecl *outer;
    CrustDecl *bad;
    size_t identities;
    size_t globals;
    crust_context_init(&first, NULL);
    crust_context_init(&second, NULL);
    crust_context_init(&consumer, NULL);
    if (!check_source(&first, &first_source, &first_unit) ||
        !check_source(&second, &second_source, &second_unit)) {
        check(false, "identity providers resolve");
        goto done;
    }
    outer = first_unit->declarations->next;
    bad = second_unit->declarations->next->next;
    check(crust_bind(&consumer, outer->name, outer), "record binding supplies dependency facts");
    identities = consumer.identities.count;
    globals = consumer.globals.count;
    check(!crust_bind(&consumer, &other, second_unit->declarations->next) &&
              strstr(consumer.error, "conflicting facts") != NULL,
          "conflicting nominal dependency rejected through matching pointer field");
    check(!crust_bind(&consumer, bad->name, bad) &&
              strstr(consumer.error, "conflicting facts") != NULL,
          "function binding checks nominal dependencies");
    check(consumer.identities.count == identities && consumer.globals.count == globals,
          "failed binding does not publish partial facts");
    check(crust_bind(&consumer, outer->next->name, outer->next),
          "correct binding succeeds after rejected facts");
    check(crust_read(&first, &duplicate, &duplicate_unit) && !crust_collect(&first) &&
              strstr(first.error, "share one identity") != NULL,
          "distinct source declarations cannot reuse identities");
done:
    crust_context_destroy(&consumer);
    crust_context_destroy(&second);
    crust_context_destroy(&first);
}

static void test_constant_facts(void)
{
    CrustContext first;
    CrustContext second;
    CrustContext third;
    CrustContext consumer;
    CrustSource a = source_text("const a: u8 = -255u8;", 50);
    CrustSource b = source_text("const b: u8 = (1u8);", 50);
    CrustSource c = source_text("const c: u8 = 2u8;", 50);
    CrustUnit *ua;
    CrustUnit *ub;
    CrustUnit *uc;
    crust_context_init(&first, NULL);
    crust_context_init(&second, NULL);
    crust_context_init(&third, NULL);
    crust_context_init(&consumer, NULL);
    if (!check_source(&first, &a, &ua) || !check_source(&second, &b, &ub) ||
        !check_source(&third, &c, &uc)) {
        check(false, "constant providers resolve");
        goto done;
    }
    ua->declarations->link_name = "shared_constant";
    ub->declarations->link_name = "shared_constant";
    uc->declarations->link_name = "shared_constant";
    check(crust_bind(&consumer, ua->declarations->name, ua->declarations), "constant facts bind");
    check(crust_bind(&consumer, ub->declarations->name, ub->declarations),
          "equivalent constant values share identity");
    check(!crust_bind(&consumer, uc->declarations->name, uc->declarations) &&
              strstr(consumer.error, "conflicting facts") != NULL,
          "different constant values cannot share identity");
done:
    crust_context_destroy(&consumer);
    crust_context_destroy(&third);
    crust_context_destroy(&second);
    crust_context_destroy(&first);
}

static void function_constant_case(const char *text, bool accepted, const char *message)
{
    CrustContext first;
    CrustContext second;
    CrustContext consumer;
    CrustSource a = source_text("const left:fn()->u8=first;"
                                "extern fn first()->u8=\"same\";"
                                "extern fn second()->u8=\"same\";",
                                51);
    CrustSource b = source_text(text, 51);
    CrustUnit *ua;
    CrustUnit *ub;
    bool bound;
    crust_context_init(&first, NULL);
    crust_context_init(&second, NULL);
    crust_context_init(&consumer, NULL);
    if (!check_source(&first, &a, &ua) || !check_source(&second, &b, &ub)) {
        check(false, "function constant providers resolve");
        goto done;
    }
    ua->declarations->link_name = "shared_callback";
    ub->declarations->link_name = "shared_callback";
    check(crust_bind(&consumer, ua->declarations->name, ua->declarations),
          "function constant facts bind");
    bound = crust_bind(&consumer, ub->declarations->name, ub->declarations);
    check(bound == accepted && (accepted || strstr(consumer.error, "conflicting facts") != NULL),
          message);
done:
    crust_context_destroy(&consumer);
    crust_context_destroy(&second);
    crust_context_destroy(&first);
}

static void test_function_constant_facts(void)
{
    function_constant_case("const right:fn()->u8=second;"
                           "extern fn first()->u8=\"same\";"
                           "extern fn second()->u8=\"same\";",
                           true, "native aliases are equal function constant values");
    function_constant_case("const right:fn()->u8=second;"
                           "extern fn first()->u8=\"same\";"
                           "extern fn second()->u8=\"different\";",
                           false, "different native symbols are unequal function constant values");
    function_constant_case("const right:fn()->u16=second;"
                           "extern fn first()->u8=\"same\";"
                           "extern fn second()->u16=\"same\";",
                           false, "native aliases cannot change the constant function signature");
}

static void test_invalid_bound_layout(void)
{
    CrustContext consumer;
    CrustDecl decl;
    CrustField field;
    CrustType type;
    CrustName record_name = {"Recursive", 9, 0};
    CrustName field_name = {"value", 5, 0};
    memset(&decl, 0, sizeof(decl));
    memset(&field, 0, sizeof(field));
    memset(&type, 0, sizeof(type));
    decl.kind = CRUST_D_RECORD;
    decl.name = &record_name;
    decl.unit_identity = 60;
    decl.identity = 1;
    decl.type = &type;
    decl.fields = &field;
    decl.field_count = 1;
    field.name = &field_name;
    field.type = &type;
    type.kind = CRUST_T_RECORD;
    type.size = 8;
    type.align = 8;
    type.record_decl = &decl;
    crust_context_init(&consumer, NULL);
    check(!crust_bind(&consumer, &record_name, &decl) &&
              strstr(consumer.error, "by-value cycle") != NULL,
          "precomputed sizes cannot hide imported by-value recursion");
    check(consumer.identities.count == 0 && consumer.globals.count == 0,
          "invalid imported layout publishes nothing");
    crust_context_destroy(&consumer);
}

typedef struct {
    CrustType types[256];
    CrustType *parameters[256][2];
} FunctionTypes;

static CrustType *function_types(CrustContext *ctx, FunctionTypes *graph, size_t count)
{
    size_t index;
    memset(graph, 0, sizeof(*graph));
    for (index = 0; index < count; ++index) {
        CrustType *type = &graph->types[index];
        type->kind = CRUST_T_FUNCTION;
        type->size = 8;
        type->align = 8;
        type->base = &ctx->builtins[CRUST_T_UNIT];
        type->params = graph->parameters[index];
        type->param_count = 2;
        type->params[0] = index == 0 ? &ctx->builtins[CRUST_T_U8] : &graph->types[index - 1];
        type->params[1] = type->params[0];
    }
    return &graph->types[count - 1];
}

static CrustDecl supplied_function(CrustName *name, uint64_t identity, CrustType *type)
{
    CrustDecl declaration;
    memset(&declaration, 0, sizeof(declaration));
    declaration.kind = CRUST_D_EXTERN;
    declaration.name = name;
    declaration.unit_identity = 700;
    declaration.identity = identity;
    declaration.link_name = "shared_callback";
    declaration.type = type;
    return declaration;
}

static void test_shared_function_types(void)
{
    CrustContext ctx;
    FunctionTypes left;
    FunctionTypes right;
    CrustName left_name = {"left", 4, 0};
    CrustName right_name = {"right", 5, 0};
    CrustDecl a;
    CrustDecl b;
    CrustSource source = source_text("fn same() -> bool { return left == right; }", 701);
    CrustUnit *unit;
    FILE *output;
    size_t bytes;
    unsigned index;
    bool equal = false;
    crust_context_init(&ctx, NULL);
    a = supplied_function(&left_name, 1, function_types(&ctx, &left, 40));
    b = supplied_function(&right_name, 2, function_types(&ctx, &right, 40));
    check(crust_try_type_equal(&ctx, a.type, b.type, &equal) && equal,
          "shared function type graphs compare by structure");
    bytes = ctx.arena.bytes_reserved;
    for (index = 0; index < 512; ++index)
        check(crust_try_type_equal(&ctx, a.type, b.type, &equal) && equal,
              "type comparison workspace can be reused");
    check(ctx.arena.bytes_reserved == bytes, "warm comparisons do not grow the arena");
    right.parameters[0][1] = &ctx.builtins[CRUST_T_U16];
    check(crust_try_type_equal(&ctx, a.type, b.type, &equal) && !equal,
          "comparison does not cache facts across unpublished type edits");
    right.parameters[0][1] = &ctx.builtins[CRUST_T_U8];
    check(crust_bind(&ctx, &left_name, &a) && crust_bind(&ctx, &right_name, &b) &&
              check_source(&ctx, &source, &unit),
          "a consumer checks against independently supplied shared type graphs");
    if (ctx.error_count == 0) {
        unit->declarations->link_name = "same";
        output = tmpfile();
        check(output != NULL, "native alias test opens output");
        if (output != NULL) {
            check(crust_x64_emit(&ctx, output, NULL),
                  "native aliases accept equivalent shared callback signatures");
            check(fclose(output) == 0, "native alias output closes");
        }
    }
    crust_context_destroy(&ctx);
}

static void test_shared_type_depth(void)
{
    CrustContext ctx;
    FunctionTypes graph;
    CrustType wrapper;
    CrustType root;
    CrustType *params[2];
    CrustName name = {"deep", 4, 0};
    CrustDecl declaration;
    crust_context_init(&ctx, NULL);
    params[0] = function_types(&ctx, &graph, 254);
    memset(&wrapper, 0, sizeof(wrapper));
    wrapper.kind = CRUST_T_POINTER;
    wrapper.size = 8;
    wrapper.align = 8;
    wrapper.base = params[0];
    params[1] = &wrapper;
    root = *params[0];
    root.params = params;
    declaration = supplied_function(&name, 1, &root);
    check(!crust_bind(&ctx, &name, &declaration) &&
              strstr(ctx.error, "semantic traversal depth limit") != NULL,
          "a reused type must fit the depth limit at every occurrence");
    check(ctx.identities.count == 0 && ctx.globals.count == 0,
          "a rejected shared type graph publishes nothing");
    crust_context_destroy(&ctx);
    crust_context_init(&ctx, NULL);
    declaration.type = function_types(&ctx, &graph, 4);
    declaration.type->params[1] = declaration.type;
    check(!crust_bind(&ctx, &name, &declaration) && strstr(ctx.error, "cyclic structural") != NULL,
          "structural cycles cannot masquerade as shared type facts");
    crust_context_destroy(&ctx);
}

typedef struct {
    size_t calls;
    size_t live;
    size_t fail_at;
} AllocationCounts;

static void *count_allocate(void *user, size_t size)
{
    AllocationCounts *counts = user;
    void *allocation;
    if (++counts->calls == counts->fail_at)
        return NULL;
    allocation = malloc(size);
    if (allocation != NULL)
        ++counts->live;
    return allocation;
}

static void count_release(void *user, void *allocation)
{
    AllocationCounts *counts = user;
    --counts->live;
    free(allocation);
}

static void test_binding_publication_failure(void)
{
    CrustContext provider;
    CrustUnit *unit;
    char text[40000] = {0};
    CrustSource source = source_text(text, 750);
    size_t index;
    bool completed = false;
    source.size = 0;
    for (index = 0; index < 1000; ++index) {
        int size = snprintf(text + source.size, sizeof(text) - source.size,
                            "record R%zu { next: *R%zu; }\n", index, (index + 1) % 1000);
        if (size < 0 || (size_t)size >= sizeof(text) - source.size) {
            check(false, "binding allocation fixture fits its source buffer");
            return;
        }
        source.size += (size_t)size;
    }
    crust_context_init(&provider, NULL);
    if (!check_source(&provider, &source, &unit)) {
        check(false, "binding allocation provider checks");
        crust_context_destroy(&provider);
        return;
    }
    for (index = 1; index <= 64 && !completed; ++index) {
        AllocationCounts counts = {0, 0, index};
        CrustAllocator allocator = {&counts, count_allocate, count_release};
        CrustContext consumer;
        crust_context_init(&consumer, &allocator);
        completed = crust_bind(&consumer, unit->declarations->name, unit->declarations);
        if (!completed) {
            check(consumer.identities.count == 0 && consumer.globals.count == 0,
                  "allocation failure cannot publish provider facts");
            check(consumer.failure == NULL && strstr(consumer.error, "allocation") != NULL,
                  "binding allocation failure retains its diagnostic and restores the frame");
            counts.fail_at = 0;
            check(crust_bind(&consumer, unit->declarations->name, unit->declarations),
                  "a failed binding can be retried");
        }
        crust_context_destroy(&consumer);
        check(counts.live == 0, "binding failure and retry release all arena blocks");
    }
    check(completed, "binding allocation sweep reaches success");
    crust_context_destroy(&provider);
}

static void test_comparison_allocation_failure(void)
{
    enum { COUNT = 4096 };
    CrustType left[COUNT];
    CrustType right[COUNT];
    CrustType *left_params[COUNT];
    CrustType *right_params[COUNT];
    CrustType a;
    CrustType b;
    CrustContext provider;
    size_t index;
    bool completed = false;
    crust_context_init(&provider, NULL);
    memset(left, 0, sizeof(left));
    for (index = 0; index < COUNT; ++index) {
        left[index].kind = CRUST_T_FUNCTION;
        left[index].size = 8;
        left[index].align = 8;
        left[index].base = &provider.builtins[CRUST_T_U8];
        right[index] = left[index];
        left_params[index] = &left[index];
        right_params[index] = &right[index];
    }
    a = left[0];
    a.params = left_params;
    a.param_count = COUNT;
    b = a;
    b.params = right_params;
    for (index = 1; index <= 64 && !completed; ++index) {
        AllocationCounts counts = {0, 0, index};
        CrustAllocator allocator = {&counts, count_allocate, count_release};
        CrustContext ctx;
        bool equal = false;
        crust_context_init(&ctx, &allocator);
        completed = crust_try_type_equal(&ctx, &a, &b, &equal);
        if (!completed) {
            check(!equal && ctx.failure == NULL && strstr(ctx.error, "allocation") != NULL,
                  "type comparison failure preserves its output and restores the frame");
            counts.fail_at = 0;
            check(crust_try_type_equal(&ctx, &a, &b, &equal) && equal,
                  "comparison can retry after workspace allocation failure");
        }
        check(equal, "wide supplied function graphs compare equally");
        crust_context_destroy(&ctx);
        check(counts.live == 0, "comparison failure and retry release all arena blocks");
    }
    check(completed, "comparison allocation sweep reaches success");
    crust_context_destroy(&provider);
}

static bool check_stream(CrustContext *ctx, CrustRootScope *scope, CrustSource *source)
{
    size_t cursor = 0;
    for (;;) {
        CrustAction action;
        if (!crust_read_one(ctx, source, cursor, source->size, &action))
            return false;
        if (action.declaration != NULL) {
            CrustUnit unit = {source, action.declaration, NULL};
            if (!crust_collect_unit(ctx, &unit) || !crust_resolve_unit(ctx, &unit) ||
                !crust_check_unit(ctx, &unit))
                return false;
        } else if (action.statement != NULL) {
            if (!crust_check_root(ctx, scope, action.statement))
                return false;
        } else {
            return true;
        }
        cursor = action.end;
    }
}

static void root_case(const char *name, const char *text, const char *error)
{
    CrustContext ctx;
    CrustRootScope scope;
    CrustSource source = source_text(text, 71);
    bool accepted;
    bool passed;
    crust_context_init(&ctx, NULL);
    memset(&scope, 0, sizeof(scope));
    accepted = check_stream(&ctx, &scope, &source);
    passed = error == NULL ? accepted : !accepted && strstr(ctx.error, error) != NULL;
    check(passed, name);
    if (!passed)
        fprintf(stderr, "diagnostic: %s\n", ctx.error);
    check(ctx.failure == NULL, "root checking restores its failure frame");
    crust_context_destroy(&ctx);
}

static void test_root_checks(void)
{
    CrustContext ctx;
    CrustRootScope scope;
    CrustSource source = source_text("var x: i32 = 1i32; x = x + 2i32; "
                                     "{ var y: i32 = x; }; { var y: i32 = x; }; return x;",
                                     72);
    CrustAction action;
    CrustSymbol *variable;
    CrustSymbol *first_nested;
    size_t cursor;
    root_case("persistent root variable", "var x: i32 = 1i32; x = 2i32; return x;", NULL);
    root_case("root return type", "return 1u32;", "type mismatch");
    root_case("root return needs a value", "return;", "requires a value");
    root_case("root loop exit needs a loop", "break;", "outside a loop");
    root_case("root continue needs a loop", "continue;", "outside a loop");
    root_case(
        "root loops retain ordinary nested syntax",
        "var x: i32 = 0i32; while x < 3i32 { x = x + 1i32; if x == 2i32 { continue; } break; };",
        NULL);
    root_case("root variables need earlier definitions", "var x: i32 = x;", "unknown name");
    root_case("root calls need earlier definitions", "later(); fn later() -> unit {}",
              "unknown name");
    root_case("declared functions do not capture root variables",
              "var x: i32 = 1i32; fn read() -> i32 { return x; }", "unknown name");
    root_case("declared function parameters are independent of root locals",
              "var x: i32 = 1i32; fn read(x: i32) -> i32 { return x; } x = read(x);", NULL);
    root_case("ordinary function return rules stay in effect",
              "fn f() -> unit { return; } f(); return 0i32;", NULL);
    root_case("root duplicate local", "var x: i32 = 0i32; var x: i32 = 1i32;", "already visible");
    root_case("root local cannot shadow a visible declaration",
              "const x: i32 = 1i32; var x: i32 = 2i32;", "already visible");
    root_case("nested locals leave scope", "{ var x: i32 = 0i32; }; x = 1i32;", "unknown name");
    root_case("nested locals cannot shadow active root locals",
              "var x: i32 = 0i32; { var x: i32 = 1i32; };", "already visible");
    root_case("root checks both branches", "if true { return 0i32; } else { return 1u32; };",
              "type mismatch");
    root_case("root declaration checks its whole body", "fn f() -> unit { return; absent(); }",
              "unknown name");
    root_case(
        "root function self recursion",
        "fn f(x: i32) -> i32 { if x == 0i32 { return x; } return f(x - 1i32); } return f(2i32);",
        NULL);
    root_case("earlier constants and function values remain visible",
              "const k: i32 = 7i32; fn f() -> i32 { return k; } const callback: fn() -> i32 = f; "
              "return callback();",
              NULL);
    root_case("root does not bind an unread later record",
              "record A { b: *B; } record B { a: *A; }", "unknown name");
    crust_context_init(&ctx, NULL);
    memset(&scope, 0, sizeof(scope));
    if (!crust_read_one(&ctx, &source, 0, source.size, &action) ||
        !crust_check_root(&ctx, &scope, action.statement)) {
        check(false, "root symbol witness begins");
        goto done;
    }
    variable = action.statement->symbol;
    cursor = action.end;
    check(crust_read_one(&ctx, &source, cursor, source.size, &action) &&
              crust_check_root(&ctx, &scope, action.statement) &&
              action.statement->expr->symbol == variable &&
              action.statement->value->left->symbol == variable,
          "later root actions use the same resolved local symbol");
    cursor = action.end;
    if (!crust_read_one(&ctx, &source, cursor, source.size, &action) ||
        !crust_check_root(&ctx, &scope, action.statement)) {
        check(false, "first nested root block checks");
        goto done;
    }
    first_nested = action.statement->body->symbol;
    check(crust_map_get(&scope.locals, (uintptr_t)first_nested->name) == NULL &&
              scope.scope == variable,
          "nested root bindings do not persist");
    cursor = action.end;
    check(crust_read_one(&ctx, &source, cursor, source.size, &action) &&
              crust_check_root(&ctx, &scope, action.statement) &&
              action.statement->body->symbol != first_nested,
          "separate root blocks use distinct local symbols");
    cursor = action.end;
    check(crust_read_one(&ctx, &source, cursor, source.size, &action) &&
              crust_check_root(&ctx, &scope, action.statement) &&
              action.statement->expr->symbol == variable,
          "root return keeps the persistent symbol identity");
done:
    crust_context_destroy(&ctx);
}

static void test_unit_checks(void)
{
    CrustContext ctx;
    CrustSource first = source_text("fn first(v: i32) -> i32 { return v; }", 81);
    CrustSource second = source_text(
        "record A { b: *B; } record B { a: *A; }"
        "fn second(v: i32) -> i32 { if v == 0i32 { return first(v); } return third(v - 1i32); }"
        "fn third(v: i32) -> i32 { return second(v); }",
        82);
    CrustSource later = source_text("fn invalid() -> unit { missing(); }", 83);
    CrustUnit *first_unit;
    CrustUnit *second_unit;
    CrustUnit *later_unit;
    CrustSymbol *parameter;
    size_t bindings;
    crust_context_init(&ctx, NULL);
    if (!crust_read(&ctx, &first, &first_unit) || !crust_collect_unit(&ctx, first_unit) ||
        !crust_resolve_unit(&ctx, first_unit) || !crust_check_unit(&ctx, first_unit)) {
        check(false, "initial host unit checks");
        goto done;
    }
    parameter = first_unit->declarations->params->symbol;
    if (!crust_read(&ctx, &second, &second_unit) || !crust_read(&ctx, &later, &later_unit)) {
        check(false, "later host units parse");
        goto done;
    }
    bindings = ctx.globals.count;
    check(crust_collect_unit(&ctx, second_unit) && ctx.globals.count == bindings + 4 &&
              later_unit->declarations->symbol == NULL,
          "unit collection does not scan later linked units");
    check(crust_resolve_unit(&ctx, second_unit) && later_unit->declarations->type == NULL,
          "unit resolution preserves forward references within the selected unit");
    check(crust_check_unit(&ctx, second_unit) && second_unit->declarations->next->next->checked &&
              second_unit->declarations->next->next->next->checked,
          "loaded host units support mutual recursion and earlier declarations");
    check(first_unit->declarations->params->symbol == parameter &&
              first_unit->declarations->body->body->expr->symbol == parameter,
          "checking a new unit does not recheck old function bodies");
    check(later_unit->declarations->symbol == NULL && !later_unit->declarations->checked,
          "checking a unit leaves a later unit untouched");
    check(crust_collect_unit(&ctx, later_unit) && crust_resolve_unit(&ctx, later_unit) &&
              !crust_check_unit(&ctx, later_unit) && strstr(ctx.error, "unknown name") != NULL,
          "checking the selected unit diagnoses every body");
    check(ctx.failure == NULL, "unit checks restore the failure frame");
done:
    crust_context_destroy(&ctx);
}

static void test_injected_root_local(void)
{
    CrustContext ctx;
    CrustRootScope scope;
    CrustSymbol *injected;
    CrustType *pointer;
    CrustSource source;
    CrustSource returned = source_text("return *run + x0 + x79;", 85);
    CrustAction action;
    char text[4096];
    size_t size = 0;
    size_t index;
    crust_context_init(&ctx, NULL);
    memset(&scope, 0, sizeof(scope));
    injected = crust_try_alloc(&ctx, sizeof(*injected), CRUST_ALIGNOF(CrustSymbol));
    pointer = crust_try_pointer_type(&ctx, &ctx.builtins[CRUST_T_I32]);
    if (injected == NULL || pointer == NULL) {
        check(false, "injected root symbol allocation");
        goto done;
    }
    injected->kind = CRUST_SYM_LOCAL;
    injected->name = crust_try_intern(&ctx, (const unsigned char *)"run", 3);
    injected->type = pointer;
    scope.scope = injected;
    if (injected->name == NULL ||
        !crust_try_map_set(&ctx, &scope.locals, (uintptr_t)injected->name, injected)) {
        check(false, "injected root symbol publication");
        goto done;
    }
    for (index = 0; index < 80; ++index) {
        int written = snprintf(text + size, sizeof(text) - size, "var x%zu: i32 = *run;", index);
        if (written < 0 || (size_t)written >= sizeof(text) - size) {
            check(false, "root growth fixture fits its storage");
            goto done;
        }
        size += (size_t)written;
    }
    source = source_text(text, 84);
    check(check_stream(&ctx, &scope, &source) && scope.locals.count == 81 &&
              crust_map_get(&scope.locals, (uintptr_t)injected->name) == injected,
          "injected root symbols survive growth of persistent local storage");
    check(crust_read_one(&ctx, &returned, 0, returned.size, &action) &&
              crust_check_root(&ctx, &scope, action.statement) &&
              action.statement->expr->left->left->left->symbol == injected,
          "checked actions retain the caller's injected symbol identity");
done:
    crust_context_destroy(&ctx);
}

int main(void)
{
    test_witness_rules();
    test_generated_scopes();
    test_shared_bindings();
    test_complete_forms();
    test_resource_bounds();
    test_identity_facts();
    test_constant_facts();
    test_function_constant_facts();
    test_invalid_bound_layout();
    test_shared_function_types();
    test_shared_type_depth();
    test_binding_publication_failure();
    test_comparison_allocation_failure();
    test_root_checks();
    test_unit_checks();
    test_injected_root_local();
    printf("checker: %u/%u checks passed\n", checks - failures, checks);
    return failures == 0 ? 0 : 1;
}
