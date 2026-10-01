#include "rmd0_x64.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    RmdContext context;
    RmdSource source;
} Fixture;

static unsigned checks;
static unsigned failures;
static bool callback_returned;
static RmdExpr *watched_expression;
static unsigned expression_hits;
static unsigned place_hits;

static void check(bool condition, const char *name)
{
    ++checks;
    if (!condition) {
        ++failures;
        fprintf(stderr, "x64 check failed: %s\n", name);
    }
}

static void fixture_init(Fixture *fixture, const char *text)
{
    RmdUnit *unit;
    RmdDecl *declaration;
    rmd_context_init(&fixture->context, NULL);
    fixture->source.path = "x64-test";
    fixture->source.bytes = (const unsigned char *)text;
    fixture->source.size = strlen(text);
    fixture->source.identity = 1;
    if (!rmd_read(&fixture->context, &fixture->source, &unit) ||
        !rmd_collect(&fixture->context) || !rmd_resolve(&fixture->context) ||
        !rmd_check(&fixture->context)) {
        fprintf(stderr, "x64 fixture failed: %s\n", fixture->context.error);
        exit(1);
    }
    for (declaration = unit->declarations; declaration; declaration = declaration->next)
        if (declaration->kind != RMD_D_RECORD && !declaration->link_name)
            declaration->link_name = declaration->name->text;
}

static FILE *output_file(void)
{
    FILE *output = tmpfile();
    if (!output) {
        perror("tmpfile");
        exit(1);
    }
    return output;
}

static void abi_case(const char *text, bool expected, const char *name)
{
    Fixture fixture;
    RmdX64Program *program = NULL;
    bool accepted;
    fixture_init(&fixture, text);
    accepted = rmd_x64_prepare(&fixture.context, &program, NULL);
    check(accepted == expected, name);
    check(fixture.context.failure == NULL, "preparation restores failure frame");
    if (!accepted)
        check(program == NULL && strstr(fixture.context.error, "native ABI") != NULL,
              "native ABI conflict has a diagnostic and no result");
    rmd_context_destroy(&fixture.context);
}

static void test_native_contract(void)
{
    Fixture fixture;
    RmdDecl *first;
    RmdX64Program *program = NULL;
    abi_case("extern fn a(x: usize) -> isize = \"same\";"
             "extern fn b(x: u64) -> i64 = \"same\";", true,
             "pointer-sized integers share their selected native integer ABI");
    abi_case("record A { x: u8; } record B { y: u64; }"
             "extern fn a(x: *A) -> *u8 = \"same\";"
             "extern fn b(x: *B) -> **u8 = \"same\";", true,
             "data-pointer pointee types do not change the native scalar ABI");
    abi_case("extern fn a(x: i8) -> unit = \"same\";"
             "extern fn b(x: u8) -> unit = \"same\";", false,
             "signed and unsigned narrow native parameters conflict");
    abi_case("extern fn a(x: bool) -> unit = \"same\";"
             "extern fn b(x: u8) -> unit = \"same\";", false,
             "native bool and byte parameters conflict");
    abi_case("extern fn a(x: fn(usize) -> isize) -> unit = \"same\";"
             "extern fn b(x: fn(u64) -> i64) -> unit = \"same\";", true,
             "function-pointer native signatures compare recursively");
    abi_case("extern fn a(x: fn(i8) -> unit) -> unit = \"same\";"
             "extern fn b(x: fn(u8) -> unit) -> unit = \"same\";", false,
             "different nested native function signatures conflict");
    abi_case("extern fn a(x: *u8) -> unit = \"same\";"
             "extern fn b(x: fn() -> unit) -> unit = \"same\";", false,
             "data pointers and function values have distinct mapped signatures");
    fixture_init(&fixture, "fn a() -> unit {} fn b() -> unit {}");
    first = fixture.context.units->declarations;
    first->next->link_name = first->link_name;
    check(!rmd_x64_prepare(&fixture.context, &program, NULL), "distinct native definitions cannot share a name");
    check(strstr(fixture.context.error, "duplicate native definition") != NULL,
          "duplicate native definition has a precise diagnostic");
    check(!rmd_x64_prepare(&fixture.context, &program, first),
          "entry selection cannot conceal duplicate native definitions");
    rmd_context_destroy(&fixture.context);
    fixture_init(&fixture, "extern fn reference(x: usize) -> i64 = \"implementation\";"
                 "fn implementation(x: u64) -> isize { return x as isize; }");
    check(rmd_x64_prepare(&fixture.context, &program, NULL), "compatible native reference and definition agree");
    rmd_context_destroy(&fixture.context);
}

static void test_imported_definitions(void)
{
    Fixture first;
    Fixture second;
    Fixture consumer;
    RmdUnit *unit;
    RmdDecl first_function;
    RmdDecl second_function;
    RmdDecl first_constant;
    RmdDecl second_constant;
    RmdX64Program *program;
    RmdX64Alias *alias;
    size_t definitions = 0;
    size_t references = 0;
    RmdName left = { "left", 4, 0 };
    RmdName right = { "right", 5, 0 };
    RmdName left_number = { "left_number", 11, 0 };
    RmdName right_number = { "right_number", 12, 0 };
    const char *source = "fn use() -> u64 { return left() + right() + left_number + right_number; }";
    const char *provider = "const number: u64 = 3u64; fn provided() -> u64 { return 7u64; }";
    fixture_init(&first, provider);
    fixture_init(&second, provider);
    first_constant = *first.context.units->declarations;
    second_constant = *second.context.units->declarations;
    first_function = *first.context.units->declarations->next;
    second_function = *second.context.units->declarations->next;
    rmd_context_init(&consumer.context, NULL);
    consumer.source.path = "consumer";
    consumer.source.bytes = (const unsigned char *)source;
    consumer.source.size = strlen(source);
    consumer.source.identity = 2;
    if (!rmd_bind(&consumer.context, &left, first.context.units->declarations->next) ||
        !rmd_bind(&consumer.context, &right, second.context.units->declarations->next) ||
        !rmd_bind(&consumer.context, &left_number, first.context.units->declarations) ||
        !rmd_bind(&consumer.context, &right_number, second.context.units->declarations) ||
        !rmd_read(&consumer.context, &consumer.source, &unit) ||
        !rmd_collect(&consumer.context) || !rmd_resolve(&consumer.context) ||
        !rmd_check(&consumer.context)) {
        fprintf(stderr, "import fixture failed: %s\n", consumer.context.error);
        exit(1);
    }
    unit->declarations->link_name = "consumer_use";
    check(rmd_x64_prepare(&consumer.context, &program, NULL),
          "independent imported descriptor copies are references, not definitions");
    if (program) {
        for (alias = program->aliases; alias; alias = alias->next) {
            if (alias->definition)
                ++definitions;
            else
                ++references;
        }
        check(definitions == 1 && references == 4,
              "native definition roles come only from owned source units");
        check(program->functions && !program->functions->next &&
              program->functions->declaration == unit->declarations,
              "consumer emits only its own function body");
    }
    check(memcmp(&first_function, first.context.units->declarations->next, sizeof(first_function)) == 0 &&
          memcmp(&second_function, second.context.units->declarations->next, sizeof(second_function)) == 0 &&
          memcmp(&first_constant, first.context.units->declarations, sizeof(first_constant)) == 0 &&
          memcmp(&second_constant, second.context.units->declarations, sizeof(second_constant)) == 0,
          "native preparation preserves imported provider descriptors");
    rmd_context_destroy(&consumer.context);
    rmd_context_destroy(&second.context);
    rmd_context_destroy(&first.context);
}

static void test_plan_and_symbols(void)
{
    Fixture fixture;
    RmdX64Program *program;
    RmdX64Function *function;
    RmdX64Expr *plan;
    RmdExpr *value;
    RmdX64Slot replacement;
    RmdX64Function replacement_function;
    FILE *output;
    char text[16384];
    size_t count;
    fixture_init(&fixture, "extern fn first() -> unit = \".Lrmd_0_alias_1\";"
                 "extern fn second() -> unit = \".Lrmd_1_string_1\";"
                 "extern fn unusual() -> unit = \"line\\nquote\\\"back\\\\slash\";"
                 "fn value() -> u64 { return 7u64 + 3u64; }");
    check(rmd_x64_prepare(&fixture.context, &program, NULL), "prepare public backend plan");
    check(strcmp(program->label_prefix, ".Lrmd_2_") == 0,
          "internal labels avoid complete native symbol prefixes");
    function = program->functions;
    memset(&replacement_function, 0, sizeof(replacement_function));
    replacement_function.declaration = function->declaration;
    check(rmd_x64_try_prepare_function(program, &replacement_function) &&
          replacement_function.frame_size == function->frame_size && fixture.context.failure == NULL,
          "native scalar API can prepare one replacement function plan");
    value = function->declaration->body->body->expr;
    plan = rmd_map_get(&function->expressions, (uintptr_t)value);
    check(rmd_x64_try_reserve(&fixture.context, function, 8, 16, &fixture.source, 0, &replacement),
          "native scalar API can reserve a replacement scratch slot");
    plan->scratch = replacement;
    value->left->integer = 42;
    output = output_file();
    check(rmd_x64_emit_program(program, output), "emit a caller-modified public plan");
    rewind(output);
    count = fread(text, 1, sizeof(text) - 1, output);
    text[count] = '\0';
    check(!ferror(output), "read emitted assembly");
    check(strstr(text, "$0x000000000000002a") != NULL,
          "emission uses the caller's changed typed expression");
    check(strstr(text, "movq %rax, -32(%rbp)") != NULL,
          "emission uses the caller's replacement scratch slot");
    check(strstr(text, "line\\012quote\\\"back\\\\slash") != NULL,
          "native symbol bytes are escaped in assembler name directives");
    check(strstr(text, "\t.weakref .Lrmd_2_alias_") != NULL,
          "native references use the collision-free alias namespace");
    check(fclose(output) == 0, "close successful output");
    rmd_context_destroy(&fixture.context);
}

static bool failing_expression(RmdX64Emitter *emitter, RmdExpr *expression)
{
    rmd_set_error(emitter->program->context, expression->loc.source,
                  expression->loc.offset, "custom expression rejected");
    callback_returned = true;
    return false;
}

static bool silent_failure(RmdX64Emitter *emitter, RmdExpr *expression)
{
    (void)emitter;
    (void)expression;
    callback_returned = true;
    return false;
}

static bool counted_place(RmdX64Emitter *emitter, RmdExpr *expression)
{
    if (expression == watched_expression)
        ++place_hits;
    return rmd_x64_try_emit_place(emitter, expression);
}

static bool replaced_value(RmdX64Emitter *emitter, RmdExpr *expression)
{
    if (expression == watched_expression) {
        ++expression_hits;
        return rmd_x64_write(emitter, "\tmovq $42, %rax\n");
    }
    return rmd_x64_try_emit_expression(emitter, expression);
}

static void test_place_and_group_operations(void)
{
    static const char *const sources[] = {
        "fn read(x: u64) -> u64 { return x; }",
        "fn read(p: *u64) -> u64 { return *p; }",
        "record Box { x: u64; } fn read(p: *Box) -> u64 { return (*p).x; }",
        "fn read(p: *u64) -> u64 { return p[1usize]; }",
        "record Box { x: u64; } fn read() -> u64 { return make Box { x: 7u64 }.x; }"
    };
    static const char *const groups[] = {
        "fn read(x: u64) -> u64 { return x; }",
        "fn read(x: u64) -> u64 { return (x); }"
    };
    Fixture fixture;
    RmdX64Program *program;
    RmdX64Ops operations = { NULL, counted_place, NULL };
    size_t index;
    FILE *output;
    for (index = 0; index < sizeof(sources) / sizeof(*sources); ++index) {
        fixture_init(&fixture, sources[index]);
        check(rmd_x64_prepare(&fixture.context, &program, NULL), "prepare a place-read hook fixture");
        watched_expression = program->functions->declaration->body->body->expr;
        place_hits = 0;
        output = output_file();
        check(rmd_x64_emit_program_with_ops(program, output, &operations), "emit a custom place read");
        check(place_hits == 1, "each stored-value read invokes its place operation once");
        check(fclose(output) == 0, "close place-read output");
        rmd_context_destroy(&fixture.context);
    }
    operations.expression = replaced_value;
    for (index = 0; index < sizeof(groups) / sizeof(*groups); ++index) {
        fixture_init(&fixture, groups[index]);
        check(rmd_x64_prepare(&fixture.context, &program, NULL), "prepare a grouped expression override");
        watched_expression = program->functions->declaration->body->body->expr;
        if (watched_expression->kind == RMD_E_GROUP)
            watched_expression = watched_expression->left;
        expression_hits = 0;
        place_hits = 0;
        output = output_file();
        check(rmd_x64_emit_program_with_ops(program, output, &operations), "emit an expression override with both hooks installed");
        check(expression_hits == 1 && place_hits == 0,
              "grouping preserves an expression override without an added storage read");
        check(fclose(output) == 0, "close grouped override output");
        rmd_context_destroy(&fixture.context);
    }
    watched_expression = NULL;
}

static void test_callback_failure(void)
{
    Fixture fixture;
    RmdX64Program *program;
    RmdX64Ops operations = { failing_expression, NULL, NULL };
    FILE *output;
    fixture_init(&fixture, "fn value() -> u64 { return 7u64; }");
    check(rmd_x64_prepare(&fixture.context, &program, NULL), "prepare callback fixture");
    callback_returned = false;
    output = output_file();
    check(!rmd_x64_emit_program_with_ops(program, output, &operations), "custom callback can reject emission");
    check(callback_returned, "failure reaches the callback return before C propagation");
    check(strcmp(fixture.context.error, "custom expression rejected") == 0 &&
          fixture.context.error_count == 1 && fixture.context.failure == NULL,
          "callback diagnostic and failure-frame ownership survive propagation");
    check(fclose(output) == 0, "close callback output");
    callback_returned = false;
    operations.expression = silent_failure;
    output = output_file();
    check(!rmd_x64_emit_program_with_ops(program, output, &operations), "silent callback failure is rejected");
    check(callback_returned && strstr(fixture.context.error, "without a diagnostic") != NULL,
          "a failed custom operation cannot reuse a stale diagnostic");
    check(fclose(output) == 0, "close silent-failure output");
    output = output_file();
    check(rmd_x64_emit_program_with_ops(program, output, &rmd_x64_default_ops),
          "nonthrowing default callback wrappers can emit a full function");
    check(fclose(output) == 0, "close default-callback output");
    rmd_context_destroy(&fixture.context);
    fixture_init(&fixture, "fn value(x: u64) -> u64 { return x; }");
    check(rmd_x64_prepare(&fixture.context, &program, NULL), "prepare custom-place fixture");
    operations.expression = NULL;
    operations.place = failing_expression;
    callback_returned = false;
    output = output_file();
    check(!rmd_x64_emit_program_with_ops(program, output, &operations) && callback_returned,
          "scalar local reads preserve a caller's place operation");
    check(fclose(output) == 0, "close custom-place output");
    rmd_context_destroy(&fixture.context);
}

static void test_failure_boundaries(void)
{
    Fixture fixture;
    RmdX64Program *program;
    RmdX64Emitter emitter;
    RmdX64Function function;
    RmdX64Slot slot = { 123, 45, 8 };
    RmdDecl *constant;
    FILE *output;
    fixture_init(&fixture, "const number: u64 = 7u64; fn value(x: u64) -> u64 { return x; }");
    check(rmd_x64_prepare(&fixture.context, &program, NULL), "prepare output-failure fixture");
    memset(&function, 0, sizeof(function));
    check(!rmd_x64_try_reserve(&fixture.context, &function, 8, 3, &fixture.source, 0, &slot),
          "invalid frame alignment returns failure through scalar API");
    check(slot.offset == 123 && slot.size == 45 && function.frame_size == 0 &&
          fixture.context.failure == NULL, "failed slot reservation changes neither output nor frame");
    function.declaration = program->functions->declaration;
    function.frame_size = INT64_MAX;
    check(!rmd_x64_try_prepare_function(program, &function) && fixture.context.failure == NULL,
          "function preparation contains frame-allocation failure");
    output = fopen("/dev/full", "w");
    if (!output || setvbuf(output, NULL, _IONBF, 0) != 0) {
        perror("/dev/full");
        exit(1);
    }
    memset(&emitter, 0, sizeof(emitter));
    emitter.program = program;
    emitter.function = program->functions;
    emitter.output = output;
    check(!rmd_x64_write(&emitter, "output"), "non-variadic output returns I/O failure without jumping");
    check(strstr(fixture.context.error, "assembly output failed") != NULL,
          "I/O failure retains a concrete diagnostic");
    check(!rmd_x64_try_emit_expression(&emitter, program->functions->declaration->body->body->expr),
          "expression wrapper contains native output failure");
    check(!rmd_x64_try_emit_place(&emitter, program->functions->declaration->body->body->expr),
          "place wrapper contains native output failure");
    check(!rmd_x64_try_emit_statement(&emitter, program->functions->declaration->body),
          "statement wrapper contains native output failure");
    constant = fixture.context.units->declarations;
    check(!rmd_x64_try_emit_constant(&emitter, constant), "constant wrapper contains native output failure");
    check(!rmd_x64_try_emit_constant_value(&emitter, constant->init),
          "constant-value wrapper contains native output failure");
    check(!rmd_x64_try_emit_function(&emitter, program->functions),
          "function wrapper contains native output failure");
    check(fixture.context.failure == NULL, "all nonthrowing wrappers restore the outer failure boundary");
    check(fclose(output) == 0, "close the unbuffered failed output sink");
    rmd_context_destroy(&fixture.context);
}

int main(void)
{
    test_native_contract();
    test_imported_definitions();
    test_plan_and_symbols();
    test_callback_failure();
    test_place_and_group_operations();
    test_failure_boundaries();
    printf("x64: %u/%u checks passed\n", checks - failures, checks);
    return failures != 0;
}
