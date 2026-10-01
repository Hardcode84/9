#include "rmd0_eval.h"

#include <dlfcn.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

int32_t eval_native_reenter(int32_t (*callback)(int32_t), int32_t value);
void eval_native_save(int8_t (*callback)(int8_t));
int8_t eval_native_saved(int8_t value);
void eval_native_write32(void *address, uint32_t value);

static int8_t (*saved_callback)(int8_t);
static unsigned checks;
static unsigned failures;

typedef struct {
    RmdContext *context;
    bool enabled;
    unsigned lookups;
} Resolver;

typedef struct {
    bool fail;
    size_t live;
    size_t calls;
    size_t fail_at;
} AllocatorState;

int32_t eval_native_reenter(int32_t (*callback)(int32_t), int32_t value)
{
    return callback(value) + callback(value);
}

void eval_native_save(int8_t (*callback)(int8_t)) { saved_callback = callback; }
int8_t eval_native_saved(int8_t value) { return saved_callback(value); }
void eval_native_write32(void *address, uint32_t value) { memcpy(address, &value, sizeof(value)); }

static void check(bool condition, const char *message)
{
    ++checks;
    if (!condition) {
        ++failures;
        fprintf(stderr, "evaluator check failed: %s\n", message);
    }
}

static void *test_allocate(void *user, size_t size)
{
    AllocatorState *state = user;
    void *allocation;
    ++state->calls;
    if (state->fail || state->calls == state->fail_at) return NULL;
    allocation = malloc(size);
    if (allocation != NULL) ++state->live;
    return allocation;
}

static void test_release(void *user, void *allocation)
{
    AllocatorState *state = user;
    --state->live;
    free(allocation);
}

static bool resolve_native(void *user, RmdDecl *declaration, void **address)
{
    Resolver *resolver = user;
    const char *error;
    ++resolver->lookups;
    if (!resolver->enabled) {
        rmd_set_error(resolver->context, declaration->loc.source,
                       declaration->loc.offset, "native lookup disabled by test");
        return false;
    }
    (void)dlerror();
    *address = dlsym(RTLD_DEFAULT, declaration->link_name);
    error = dlerror();
    if (error != NULL) {
        rmd_set_error(resolver->context, declaration->loc.source, declaration->loc.offset, error);
        return false;
    }
    return true;
}

static RmdEval *new_eval(RmdContext *context, Resolver *resolver)
{
    RmdEvalOptions options;
    resolver->context = context;
    resolver->enabled = true;
    resolver->lookups = 0;
    options.resolve = resolve_native;
    options.user = resolver;
    return rmd_eval_create(context, &options);
}

static bool parse(RmdContext *context, RmdSource *source, RmdUnit **unit)
{
    bool success = rmd_read(context, source, unit) && rmd_collect(context) &&
        rmd_resolve(context) && rmd_check(context);
    if (!success) fprintf(stderr, "test source diagnostic: %s\n", context->error);
    return success;
}

static RmdSource source_text(const char *text)
{
    RmdSource source = {"eval-test", (const unsigned char *)text, 0, 1};
    source.size = strlen(text);
    return source;
}

static RmdDecl *named(RmdUnit *unit, const char *name)
{
    RmdDecl *declaration;
    for (declaration = unit->declarations; declaration != NULL; declaration = declaration->next)
        if (strcmp(declaration->name->text, name) == 0) return declaration;
    abort();
}

static bool prepare_all(RmdEval *eval, RmdUnit *unit)
{
    RmdDecl *declaration;
    for (declaration = unit->declarations; declaration != NULL; declaration = declaration->next)
        if (!rmd_eval_prepare(eval, declaration)) return false;
    return true;
}

static unsigned char *read_file(const char *path, size_t *size)
{
    FILE *file = fopen(path, "rb");
    unsigned char *bytes;
    long length;
    if (file == NULL || fseek(file, 0, SEEK_END) != 0 || (length = ftell(file)) < 0 ||
        fseek(file, 0, SEEK_SET) != 0) abort();
    bytes = malloc((size_t)length + 1);
    if (bytes == NULL || fread(bytes, 1, (size_t)length, file) != (size_t)length ||
        fclose(file) != 0) abort();
    bytes[length] = 0;
    *size = (size_t)length;
    return bytes;
}

static void test_runtime(void)
{
    RmdContext context;
    RmdSource source = {"tests/runtime.rmd", NULL, 0, 1};
    RmdUnit *unit;
    RmdEval *eval = NULL;
    Resolver resolver;
    int32_t argc = 1;
    const char *text = "eval-test";
    const char **argv = &text;
    void *arguments[2] = {&argc, &argv};
    int32_t result = -1;
    source.bytes = read_file(source.path, &source.size);
    rmd_context_init(&context, NULL);
    if (!parse(&context, &source, &unit)) { check(false, "runtime source checks"); goto done; }
    eval = new_eval(&context, &resolver);
    check(eval != NULL && prepare_all(eval, unit), "runtime declarations prepare");
    check(resolver.lookups == 0, "preparation does not resolve native symbols");
    check(rmd_eval_call(eval, named(unit, "main"), arguments, 2, &result) && result == 0,
          "full runtime witness: scalar ABI, aggregates, alias copies, order, loops, callbacks");
    if (result != 0) fprintf(stderr, "runtime result: %d, diagnostic: %s\n", result, context.error);
    check(context.failure == NULL, "runtime leaves no failure frame");
done:
    rmd_eval_destroy(eval);
    rmd_context_destroy(&context);
    free((void *)source.bytes);
}

static void test_reentry(void)
{
    const char *text =
        "extern fn twice(f:fn(i32)->i32,n:i32)->i32=\"eval_native_reenter\";"
        "extern fn save(f:fn(i8)->i8)->unit=\"eval_native_save\";"
        "extern fn saved(n:i8)->i8=\"eval_native_saved\";"
        "extern fn write(p:*u8,n:u32)->unit=\"eval_native_write32\";"
        "fn recurse(n:i32)->i32 {var preserved:i32=n;if n==0i32{return 0i32;}"
        "return twice(recurse,n-1i32)+preserved;}"
        "fn narrow(n:i8)->i8{return n-1i8;}"
        "fn keep()->unit{save(narrow);}"
        "fn use()->i8{return saved(-127i8);}"
        "fn alias()->u64{var x:u64=18446744069414584320u64;write(&x as *u8,42u32);return x;}"
        "fn direct(n:u32)->u32{if n==0u32{return 1u32;}return direct(n-1u32)+1u32;}";
    RmdSource source = source_text(text);
    RmdContext context;
    RmdUnit *unit;
    RmdEval *eval = NULL;
    Resolver resolver;
    int32_t n = 5;
    int32_t result = 0;
    int8_t narrow = 0;
    uint64_t wide = 0;
    uint32_t depth = 50;
    uint32_t direct = 0;
    void *argument = &n;
    void *depth_argument = &depth;
    int8_t (*callback)(int8_t) = NULL;
    int8_t (*again)(int8_t) = NULL;
    size_t reserved;
    rmd_context_init(&context, NULL);
    if (!parse(&context, &source, &unit)) { check(false, "reentry source checks"); goto done; }
    eval = new_eval(&context, &resolver);
    check(eval != NULL && prepare_all(eval, unit), "reentry declarations prepare");
    check(rmd_eval_call(eval, named(unit, "recurse"), &argument, 1, &result) && result == 57,
          "native callback recursion keeps each live frame separate");
    reserved = context.arena.bytes_reserved;
    check(rmd_eval_call(eval, named(unit, "recurse"), &argument, 1, &result) && result == 57 &&
          context.arena.bytes_reserved == reserved, "completed frames are reused");
    check(rmd_eval_call(eval, named(unit, "keep"), NULL, 0, NULL), "native retains interpreted callback");
    check(rmd_eval_call(eval, named(unit, "use"), NULL, 0, &narrow) && narrow == INT8_MIN,
          "retained narrow callback remains callable after the original call");
    check(rmd_eval_function(eval, named(unit, "narrow"), &callback) && callback(-127) == INT8_MIN,
          "native function pointer has the exact narrow return ABI");
    check(rmd_eval_function(eval, named(unit, "narrow"), &again) && again == callback,
          "function pointer identity is stable");
    check(rmd_eval_call(eval, named(unit, "alias"), NULL, 0, &wide) &&
          wide == UINT64_C(18446744069414584362), "native alias store is visible in a wide local read");
    check(rmd_eval_call(eval, named(unit, "direct"), &depth_argument, 1, &direct) && direct == 51,
          "direct interpreted recursion");
    saved_callback = NULL;
done:
    rmd_eval_destroy(eval);
    rmd_context_destroy(&context);
}

static void test_native_identity(void)
{
    const char *text =
        "extern fn a(p:*u8)->u64=\"shared\";"
        "extern fn b(p:*i32)->usize=\"shared\";"
        "extern fn bad(p:*u8)->u8=\"shared\";"
        "extern fn identity(n:i32)->i32=\"native_i32\";"
        "fn owned(n:i32)->i32{return n+1i32;}";
    RmdSource source = source_text(text);
    RmdContext context;
    RmdUnit *unit;
    RmdEval *eval = NULL;
    Resolver resolver;
    int32_t (*external)(int32_t) = NULL;
    int32_t (*owned)(int32_t) = NULL;
    RmdDecl copy;
    rmd_context_init(&context, NULL);
    if (!parse(&context, &source, &unit)) { check(false, "native identity source checks"); goto done; }
    eval = new_eval(&context, &resolver);
    resolver.enabled = false;
    check(rmd_eval_prepare(eval, named(unit, "a")) && rmd_eval_prepare(eval, named(unit, "b")),
          "native aliases accept matching pointer and integer ABI types");
    check(!rmd_eval_prepare(eval, named(unit, "bad")) && strstr(context.error, "conflicting native ABI") != NULL,
          "native aliases reject incompatible ABI before lookup");
    check(resolver.lookups == 0, "ABI validation needs no loaded native library");
    check(rmd_eval_prepare(eval, named(unit, "identity")), "extern prepares before a link is available");
    resolver.enabled = true;
    check(rmd_eval_function(eval, named(unit, "identity"), &external) && external(42) == 42,
          "first function value resolves the linked native symbol");
    named(unit, "owned")->link_name = "native_i32";
    check(!rmd_eval_prepare(eval, named(unit, "owned")) && strstr(context.error, "already published") != NULL,
          "late definition cannot replace a published extern identity");
    rmd_eval_destroy(eval);
    eval = new_eval(&context, &resolver);
    check(rmd_eval_prepare(eval, named(unit, "identity")) && rmd_eval_prepare(eval, named(unit, "owned")),
          "owned function and extern alias register before publication");
    check(rmd_eval_function(eval, named(unit, "identity"), &external) &&
          rmd_eval_function(eval, named(unit, "owned"), &owned) && external == owned && owned(41) == 42,
          "extern and owned aliases share one interpreted callable");
    check(resolver.lookups == 0, "owned native identity needs no external lookup");
    copy = *named(unit, "owned");
    check(rmd_eval_function(eval, &copy, &external) && external == owned,
          "shared declaration identity reuses the same closure");
done:
    rmd_eval_destroy(eval);
    rmd_context_destroy(&context);
}

static void test_callback_types(void)
{
    const char *text =
        "fn i8_value(n:i8)->i8{return n;}fn u8_value(n:u8)->u8{return n;}"
        "fn i16_value(n:i16)->i16{return n;}fn u16_value(n:u16)->u16{return n;}"
        "fn i32_value(n:i32)->i32{return n;}fn u32_value(n:u32)->u32{return n;}"
        "fn i64_value(n:i64)->i64{return n;}fn u64_value(n:u64)->u64{return n;}"
        "fn isize_value(n:isize)->isize{return n;}fn usize_value(n:usize)->usize{return n;}"
        "fn bool_value(n:bool)->bool{return !n;}"
        "fn pointer_value(n:*u8)->*u8{return n;}"
        "fn unit_value(n:*u8)->unit{*n=42u8;}"
        "fn function_value()->fn(i8)->i8{return i8_value;}";
    RmdSource source = source_text(text);
    RmdContext context;
    RmdUnit *unit;
    RmdEval *eval = NULL;
    bool (*boolean)(bool) = NULL;
    void *(*pointer)(void *) = NULL;
    void (*procedure)(uint8_t *) = NULL;
    int8_t (*(*function)(void))(int8_t) = NULL;
    uint8_t byte = 0;
    rmd_context_init(&context, NULL);
    if (!parse(&context, &source, &unit)) { check(false, "callback scalar source checks"); goto done; }
    eval = rmd_eval_create(&context, NULL);
#define CHECK_CALLBACK(TYPE, NAME, VALUE) do { \
    TYPE (*callback)(TYPE) = NULL; \
    check(rmd_eval_function(eval, named(unit, NAME), &callback) && callback(VALUE) == (VALUE), \
          "native callback parameter and result: " NAME); \
} while (0)
    CHECK_CALLBACK(int8_t, "i8_value", INT8_MIN);
    CHECK_CALLBACK(uint8_t, "u8_value", UINT8_MAX);
    CHECK_CALLBACK(int16_t, "i16_value", INT16_MIN);
    CHECK_CALLBACK(uint16_t, "u16_value", UINT16_MAX);
    CHECK_CALLBACK(int32_t, "i32_value", INT32_MIN);
    CHECK_CALLBACK(uint32_t, "u32_value", UINT32_MAX);
    CHECK_CALLBACK(int64_t, "i64_value", INT64_MIN);
    CHECK_CALLBACK(uint64_t, "u64_value", UINT64_MAX);
    CHECK_CALLBACK(intptr_t, "isize_value", INTPTR_MIN);
    CHECK_CALLBACK(uintptr_t, "usize_value", UINTPTR_MAX);
#undef CHECK_CALLBACK
    check(rmd_eval_function(eval, named(unit, "bool_value"), &boolean) &&
          boolean(false) && !boolean(true), "native bool callback");
    check(rmd_eval_function(eval, named(unit, "pointer_value"), &pointer) &&
          pointer(&byte) == &byte, "native pointer callback");
    check(rmd_eval_function(eval, named(unit, "unit_value"), &procedure), "native unit callback prepares");
    procedure(&byte);
    check(byte == 42, "native unit callback writes its argument");
    check(rmd_eval_function(eval, named(unit, "function_value"), &function) &&
          function()(INT8_MIN) == INT8_MIN, "native callback returns a callable function pointer");
done:
    rmd_eval_destroy(eval);
    rmd_context_destroy(&context);
}

static void test_root(void)
{
    const char *text =
        "var total:i32=1i32;"
        "var p:*i32=&total;"
        "{var nested:i32=2i32;total=total+nested;};"
        "while total<10i32 {total=total+1i32;if total==5i32{continue;}if total==8i32{break;}};"
        "if total==8i32 {*p=*p+34i32;} else {trap;};"
        "return total;";
    RmdSource source = source_text(text);
    RmdContext context;
    RmdRootScope scope = {{NULL, 0, 0}, NULL};
    RmdAction action;
    RmdEval *eval;
    size_t begin = 0;
    int32_t status = 0;
    bool returned = false;
    unsigned actions = 0;
    rmd_context_init(&context, NULL);
    eval = rmd_eval_create(&context, NULL);
    while (begin < source.size && !returned) {
        if (!rmd_read_one(&context, &source, begin, source.size, &action) ||
            action.statement == NULL || !rmd_check_root(&context, &scope, action.statement) ||
            !rmd_eval_statement(eval, action.statement, &returned, &status)) {
            fprintf(stderr, "root diagnostic: %s\n", context.error);
            check(false, "root stream executes");
            break;
        }
        begin = action.end;
        ++actions;
    }
    check(returned && status == 42 && actions == 6, "root variables and addresses survive later actions");
    {
        RmdSymbol symbol;
        RmdExpr expression;
        int32_t borrowed = 17;
        int32_t other = 18;
        int32_t result = 0;
        memset(&symbol, 0, sizeof(symbol));
        memset(&expression, 0, sizeof(expression));
        symbol.kind = RMD_SYM_LOCAL;
        symbol.type = &context.builtins[RMD_T_I32];
        expression.kind = RMD_E_NAME;
        expression.type = symbol.type;
        expression.symbol = &symbol;
        expression.place = true;
        expression.writable = true;
        check(rmd_eval_bind(eval, &symbol, &borrowed) && rmd_eval_bind(eval, &symbol, &borrowed),
              "borrowed root storage binds once or repeats its address");
        check(rmd_eval_expression(eval, &expression, &result) && result == 17,
              "expression API reads bound host storage");
        borrowed = 42;
        check(rmd_eval_expression(eval, &expression, &result) && result == 42,
              "bound host writes remain visible");
        check(!rmd_eval_bind(eval, &symbol, &other), "bound root address cannot change");
    }
    rmd_eval_destroy(eval);
    rmd_context_destroy(&context);
}

static uint64_t width_mask(unsigned width)
{
    return width == 64 ? UINT64_MAX : (UINT64_C(1) << width) - 1;
}

static void test_arithmetic(void)
{
    const char *types[] = {"i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "isize", "usize"};
    const unsigned widths[] = {8, 8, 16, 16, 32, 32, 64, 64, 64, 64};
    const char *ops[] = {"+", "-", "*", "&", "|", "^", "<<", ">>", "/", "%"};
    uint64_t state = UINT64_C(0x8cb92baa6ed4315f);
    size_t type_index;
    size_t op_index;
    for (type_index = 0; type_index < sizeof(types) / sizeof(types[0]); ++type_index) {
        unsigned width = widths[type_index];
        uint64_t mask = width_mask(width);
        uint64_t sign = UINT64_C(1) << (width - 1);
        bool signed_type = type_index % 2 == 0;
        for (op_index = 0; op_index < sizeof(ops) / sizeof(ops[0]); ++op_index) {
            char text[256];
            RmdSource source;
            RmdContext context;
            RmdUnit *unit;
            RmdEval *eval;
            unsigned index;
            (void)snprintf(text, sizeof(text), "fn f(a:%s,b:%s)->%s{return a%s b;}",
                           types[type_index], types[type_index], types[type_index], ops[op_index]);
            source = source_text(text);
            rmd_context_init(&context, NULL);
            if (!parse(&context, &source, &unit)) abort();
            eval = rmd_eval_create(&context, NULL);
            for (index = 0; index < 100; ++index) {
                uint64_t a;
                uint64_t b;
                uint64_t expected = 0;
                uint64_t result = 0;
                void *arguments[2] = {&a, &b};
                state ^= state << 13; state ^= state >> 7; state ^= state << 17;
                a = state & mask;
                state ^= state << 13; state ^= state >> 7; state ^= state << 17;
                b = state & mask;
                if (op_index == 6 || op_index == 7) b %= width;
                if (op_index >= 8 && (b == 0 || (signed_type && a == sign && b == mask))) b = 1;
                switch (op_index) {
                case 0: expected = a + b; break;
                case 1: expected = a - b; break;
                case 2: expected = a * b; break;
                case 3: expected = a & b; break;
                case 4: expected = a | b; break;
                case 5: expected = a ^ b; break;
                case 6: expected = a << (unsigned)b; break;
                case 7:
                    expected = a >> (unsigned)b;
                    if (signed_type && (a & sign) != 0 && b != 0)
                        expected |= mask ^ width_mask(width - (unsigned)b);
                    break;
                default:
                    if (signed_type) {
                        uint64_t extended_a = (a & sign) != 0 ? a | ~mask : a;
                        uint64_t extended_b = (b & sign) != 0 ? b | ~mask : b;
                        int64_t signed_a;
                        int64_t signed_b;
                        int64_t answer;
                        memcpy(&signed_a, &extended_a, sizeof(signed_a));
                        memcpy(&signed_b, &extended_b, sizeof(signed_b));
                        answer = op_index == 8 ? signed_a / signed_b : signed_a % signed_b;
                        memcpy(&expected, &answer, sizeof(expected));
                    } else expected = op_index == 8 ? a / b : a % b;
                    break;
                }
                check(rmd_eval_call(eval, unit->declarations, arguments, 2, &result) &&
                      result == (expected & mask), "dynamic integer operation matches its width");
            }
            rmd_eval_destroy(eval);
            rmd_context_destroy(&context);
        }
    }
}

static void test_conversions_and_comparisons(void)
{
    const char *types[] = {"i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "isize", "usize"};
    const unsigned widths[] = {8, 8, 16, 16, 32, 32, 64, 64, 64, 64};
    size_t from;
    size_t to;
    for (from = 0; from < 10; ++from) {
        uint64_t mask = width_mask(widths[from]);
        uint64_t sign = UINT64_C(1) << (widths[from] - 1);
        uint64_t inputs[5] = {0, 1, sign - 1, sign, mask};
        char text[512];
        RmdSource source;
        RmdContext context;
        RmdUnit *unit;
        RmdEval *eval;
        size_t a;
        size_t b;
        (void)snprintf(text, sizeof(text),
            "fn f(a:%s,b:%s)->u8{return ((a==b) as u8)|(((a!=b) as u8)<<1u8)|"
            "(((a<b) as u8)<<2u8)|(((a<=b) as u8)<<3u8)|"
            "(((a>b) as u8)<<4u8)|(((a>=b) as u8)<<5u8);}", types[from], types[from]);
        source = source_text(text);
        rmd_context_init(&context, NULL);
        if (!parse(&context, &source, &unit)) abort();
        eval = rmd_eval_create(&context, NULL);
        for (a = 0; a < 5; ++a) for (b = 0; b < 5; ++b) {
            uint8_t result = 0;
            uint8_t expected;
            void *arguments[2] = {&inputs[a], &inputs[b]};
            if (from % 2 == 0) {
                uint64_t extended_a = (inputs[a] & sign) != 0 ? inputs[a] | ~mask : inputs[a];
                uint64_t extended_b = (inputs[b] & sign) != 0 ? inputs[b] | ~mask : inputs[b];
                int64_t x;
                int64_t y;
                memcpy(&x, &extended_a, sizeof(x));
                memcpy(&y, &extended_b, sizeof(y));
                expected = (uint8_t)((x == y) | ((x != y) << 1) | ((x < y) << 2) |
                                      ((x <= y) << 3) | ((x > y) << 4) | ((x >= y) << 5));
            } else {
                uint64_t x = inputs[a];
                uint64_t y = inputs[b];
                expected = (uint8_t)((x == y) | ((x != y) << 1) | ((x < y) << 2) |
                                      ((x <= y) << 3) | ((x > y) << 4) | ((x >= y) << 5));
            }
            check(rmd_eval_call(eval, unit->declarations, arguments, 2, &result) && result == expected,
                  "ordered comparisons include signed extrema");
        }
        rmd_eval_destroy(eval);
        rmd_context_destroy(&context);
        for (to = 0; to < 10; ++to) {
            (void)snprintf(text, sizeof(text), "fn f(a:%s)->%s{return a as %s;}",
                           types[from], types[to], types[to]);
            source = source_text(text);
            rmd_context_init(&context, NULL);
            if (!parse(&context, &source, &unit)) abort();
            eval = rmd_eval_create(&context, NULL);
            for (a = 0; a < 5; ++a) {
                uint64_t result = 0;
                uint64_t expected = inputs[a];
                void *argument = &inputs[a];
                if (from % 2 == 0 && (inputs[a] & sign) != 0) expected |= ~mask;
                expected &= width_mask(widths[to]);
                check(rmd_eval_call(eval, unit->declarations, &argument, 1, &result) && result == expected,
                      "integer cast extends signed source before destination truncation");
            }
            rmd_eval_destroy(eval);
            rmd_context_destroy(&context);
        }
    }
}

static void test_registration_failures(void)
{
    char text[32768];
    size_t used = 0;
    size_t index;
    size_t failures_to_test = 0;
    size_t failure;
    for (index = 0; index < 200; ++index) {
        int length = snprintf(text + used, sizeof(text) - used,
                               "fn f%zu(n:i32)->i32{return n+1i32;}\n", index);
        if (length < 0 || (size_t)length >= sizeof(text) - used) abort();
        used += (size_t)length;
    }
    for (failure = 0; failure <= failures_to_test; ++failure) {
        RmdSource source = source_text(text);
        RmdContext context;
        RmdUnit *unit;
        RmdDecl *declaration;
        RmdEval *eval;
        AllocatorState state = {false, 0, 0, 0};
        RmdAllocator allocator = {&state, test_allocate, test_release};
        size_t initial_calls;
        int32_t (*callbacks[200])(int32_t);
        size_t callback_count = 0;
        bool failed = false;
        rmd_context_init(&context, &allocator);
        if (!parse(&context, &source, &unit)) abort();
        initial_calls = state.calls;
        if (failure != 0) state.fail_at = initial_calls + failure;
        eval = rmd_eval_create(&context, NULL);
        if (eval == NULL) {
            failed = true;
            state.fail_at = 0;
            eval = rmd_eval_create(&context, NULL);
        }
        if (eval == NULL) abort();
        for (declaration = unit->declarations; declaration != NULL; declaration = declaration->next) {
            int32_t (*callback)(int32_t) = NULL;
            declaration->link_name = declaration->name->text;
            if (!rmd_eval_function(eval, declaration, &callback)) {
                failed = true;
                state.fail_at = 0;
                check(strstr(context.error, "allocation") != NULL && context.failure == NULL,
                      "registration allocation failure returns through local C frames");
                check(rmd_eval_function(eval, declaration, &callback), "registration can retry after allocation recovery");
            }
            if (callback == NULL) abort();
            callbacks[callback_count++] = callback;
        }
        if (failure == 0) failures_to_test = state.calls - initial_calls;
        else check(failed, "each evaluator arena allocation failure is observed");
        state.fail_at = 0;
        for (index = 0; index < callback_count; ++index)
            if (callbacks[index](41) != 42) abort();
        rmd_eval_destroy(eval);
        rmd_context_destroy(&context);
        check(state.live == 0, "failed registration releases all context allocations");
    }
}

static void expect_trap(const char *expression)
{
    char text[256];
    RmdSource source;
    RmdContext context;
    RmdUnit *unit;
    RmdEval *eval;
    pid_t child;
    int status = 0;
    int errors[2];
    char diagnostic[640];
    ssize_t length;
    (void)snprintf(text, sizeof(text), "fn f()->unit{\n%s;\n}", expression);
    source = source_text(text);
    rmd_context_init(&context, NULL);
    if (!parse(&context, &source, &unit)) abort();
    eval = rmd_eval_create(&context, NULL);
    if (pipe(errors) != 0) abort();
    child = fork();
    if (child == 0) {
        struct rlimit limit = {0, 0};
        if (close(errors[0]) != 0 || dup2(errors[1], STDERR_FILENO) < 0 ||
            close(errors[1]) != 0 || setrlimit(RLIMIT_CORE, &limit) != 0) _exit(98);
        (void)rmd_eval_call(eval, unit->declarations, NULL, 0, NULL);
        _exit(99);
    }
    if (close(errors[1]) != 0) abort();
    length = read(errors[0], diagnostic, sizeof(diagnostic) - 1);
    if (length < 0 || close(errors[0]) != 0) abort();
    diagnostic[length] = 0;
    if (child < 0 || waitpid(child, &status, 0) != child) abort();
    check(WIFSIGNALED(status) && WTERMSIG(status) == SIGABRT, "required trap ends the process");
    check(strstr(diagnostic, "eval-test:2:") != NULL &&
          strstr(diagnostic, "required execution trap") != NULL, "trap reports the original source line and column");
    rmd_eval_destroy(eval);
    rmd_context_destroy(&context);
}

static void test_failures(void)
{
    const char *text = "fn huge()->i32{var a:[u8;1000000]=uninit;a[0usize]=42u8;return a[0usize] as i32;}";
    RmdSource source = source_text(text);
    RmdContext context;
    RmdUnit *unit;
    AllocatorState state = {false, 0, 0, 0};
    RmdAllocator allocator = {&state, test_allocate, test_release};
    RmdEval *eval;
    int32_t value = 0;
    int32_t (*callback)(void) = NULL;
    pid_t child;
    int status = 0;
    rmd_context_init(&context, &allocator);
    if (!parse(&context, &source, &unit)) abort();
    eval = rmd_eval_create(&context, NULL);
    check(rmd_eval_function(eval, unit->declarations, &callback), "prepare callback before allocation failure");
    state.fail = true;
    check(!rmd_eval_call(eval, unit->declarations, NULL, 0, &value) &&
          strstr(context.error, "allocation") != NULL && context.failure == NULL,
          "ordinary evaluator allocation failure returns a diagnostic");
    child = fork();
    if (child == 0) {
        struct rlimit limit = {0, 0};
        if (setrlimit(RLIMIT_CORE, &limit) != 0 || freopen("/dev/null", "w", stderr) == NULL) _exit(98);
        (void)callback();
        _exit(99);
    }
    if (child < 0 || waitpid(child, &status, 0) != child) abort();
    check(WIFSIGNALED(status) && WTERMSIG(status) == SIGABRT,
          "callback resource failure aborts instead of returning a fabricated value");
    state.fail = false;
    check(rmd_eval_call(eval, unit->declarations, NULL, 0, &value) && value == 42,
          "ordinary evaluation retries after resource recovery");
    check(!rmd_eval_call(eval, unit->declarations, NULL, 1, &value), "call validates argument count");
    check(!rmd_eval_call(eval, unit->declarations, NULL, 0, NULL), "call validates result storage");
    rmd_eval_destroy(eval);
    rmd_eval_destroy(eval);
    rmd_context_destroy(&context);
    check(state.live == 0, "context releases all evaluator arena allocations");
    expect_trap("trap");
    expect_trap("1u8/0u8");
    expect_trap("1i64%0i64");
    expect_trap("-128i8/-1i8");
    expect_trap("-128i8%-1i8");
    expect_trap("-9223372036854775808i64/-1i64");
    expect_trap("-9223372036854775808i64%-1i64");
    expect_trap("1u8<<8u8");
    expect_trap("1u64>>64u64");
    expect_trap("1i16<<-1i16");
}

int main(void)
{
    test_runtime();
    test_reentry();
    test_native_identity();
    test_callback_types();
    test_root();
    test_arithmetic();
    test_conversions_and_comparisons();
    test_registration_failures();
    test_failures();
    printf("evaluator: %u/%u checks passed\n", checks - failures, checks);
    return failures == 0 ? 0 : 1;
}
