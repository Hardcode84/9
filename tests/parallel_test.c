#include "crust0_x64.h"

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define JOB_COUNT 6u
#define SNAPSHOT_COUNT 32u

typedef struct {
    const void *object;
    void *bytes;
    size_t size;
} Snapshot;

typedef struct {
    CrustContext context;
    CrustSource source;
    CrustUnit *unit;
    CrustDecl *record;
    CrustDecl *value;
    CrustDecl *function;
    CrustDecl *private_value;
    CrustDecl *callback;
    Snapshot snapshots[SNAPSHOT_COUNT];
    size_t snapshot_count;
} Provider;

typedef struct {
    const char *source;
    const char *link_name;
    unsigned provider;
    unsigned function_provider;
    bool include_function;
    bool include_private;
    const char *expected_error;
} Policy;

typedef struct {
    bool accepted;
    bool aliases_equal;
    uint64_t unit_identity;
    uint64_t declaration_identity;
    uint64_t error_source_identity;
    size_t error_offset;
    char error[512];
    char *output;
    size_t output_size;
    unsigned publication_order;
} Result;

typedef struct {
    pthread_mutex_t mutex;
    pthread_cond_t changed;
    unsigned ready;
    unsigned next;
    bool started;
    bool reverse;
} Gate;

typedef struct {
    Provider *providers;
    const Policy *policy;
    Result *result;
    unsigned index;
    Gate *gate;
} Work;

typedef struct {
    const char *text;
    CrustName *name;
} NameInput;

static const char ordinary_consumer[] =
    "fn consume(p: *Alias) -> u64 {"
    " var node: *Node = p;"
    " return read_node(node) + saved_node(node) + public_value + (*node).value;"
    "}";

static const Policy policies[JOB_COUNT] = {
    {ordinary_consumer, "consumer_a", 0, 0, true, false, NULL},
    {ordinary_consumer, "consumer_b", 1, 1, true, false, NULL},
    {"fn consume() -> u64 { return private_value; }",
     "consumer_private_hidden", 0, 0, true, false, "unknown name 'private_value'"},
    {"fn consume(p: *Node) -> u64 { return read_node(p); }",
     "consumer_function_missing", 0, 0, false, false, "unknown name 'read_node'"},
    {"fn consume() -> u64 { return private_value; }",
     "consumer_private_selected", 0, 0, true, true, NULL},
    {ordinary_consumer, "consumer_wrong_provider", 0, 1, true, false, "type mismatch"}
};

static unsigned checks;
static unsigned failures;

static void check(bool condition, const char *name)
{
    ++checks;
    if (!condition) {
        ++failures;
        fprintf(stderr, "parallel check failed: %s\n", name);
    }
}

static void stop(const char *message)
{
    fprintf(stderr, "parallel test: %s\n", message);
    exit(2);
}

static void pthread_ok(int status)
{
    if (status != 0) stop(strerror(status));
}

static void snapshot(Provider *provider, const void *object, size_t size)
{
    Snapshot *copy;
    if (provider->snapshot_count == SNAPSHOT_COUNT) stop("snapshot capacity exceeded");
    copy = &provider->snapshots[provider->snapshot_count++];
    copy->object = object;
    copy->size = size;
    copy->bytes = malloc(size);
    if (copy->bytes == NULL) stop("snapshot allocation failed");
    memcpy(copy->bytes, object, size);
}

static void freeze_provider(Provider *provider)
{
    CrustDecl *decl;
    CrustField *field;
    CrustParam *param;
    snapshot(provider, &provider->context, sizeof(provider->context));
    snapshot(provider, provider->unit, sizeof(*provider->unit));
    for (decl = provider->unit->declarations; decl != NULL; decl = decl->next) {
        snapshot(provider, decl, sizeof(*decl));
        snapshot(provider, decl->type, sizeof(*decl->type));
        snapshot(provider, decl->symbol, sizeof(*decl->symbol));
        if (decl->init != NULL) snapshot(provider, decl->init, sizeof(*decl->init));
        if (decl->type->param_count != 0) {
            size_t index;
            snapshot(provider, decl->type->params,
                     decl->type->param_count * sizeof(*decl->type->params));
            for (index = 0; index < decl->type->param_count; ++index)
                snapshot(provider, decl->type->params[index], sizeof(*decl->type->params[index]));
        }
        for (field = decl->fields; field != NULL; field = field->next) {
            snapshot(provider, field, sizeof(*field));
            snapshot(provider, field->type, sizeof(*field->type));
        }
        for (param = decl->params; param != NULL; param = param->next) {
            snapshot(provider, param, sizeof(*param));
            snapshot(provider, param->type, sizeof(*param->type));
        }
    }
}

static void check_provider(const Provider *provider)
{
    size_t index;
    bool unchanged = true;
    for (index = 0; index < provider->snapshot_count; ++index) {
        const Snapshot *copy = &provider->snapshots[index];
        if (memcmp(copy->object, copy->bytes, copy->size) != 0) unchanged = false;
    }
    check(unchanged, "published provider facts remain unchanged");
}

static bool prepare_provider(Provider *provider, unsigned index)
{
    static const char *const sources[] = {
        "record Node { value: u64; next: *Node; }"
        "const public_value: u64 = 11u64;"
        "fn read_node(p: *Node) -> u64 { return (*p).value + public_value; }"
        "const private_value: u64 = 17u64;"
        "const saved_node: fn(*Node) -> u64 = read_node;",
        "record Node { value: u64; next: *Node; }"
        "const public_value: u64 = 22u64;"
        "fn read_node(p: *Node) -> u64 { return (*p).value + public_value; }"
        "const private_value: u64 = 27u64;"
        "const saved_node: fn(*Node) -> u64 = read_node;"
    };
    static const char *const links[][4] = {
        {"provider_a_value", "provider_a_read_node", "provider_a_private", "provider_a_callback"},
        {"provider_b_value", "provider_b_read_node", "provider_b_private", "provider_b_callback"}
    };
    memset(provider, 0, sizeof(*provider));
    crust_context_init(&provider->context, NULL);
    provider->source.path = index == 0 ? "provider-a" : "provider-b";
    provider->source.bytes = (const unsigned char *)sources[index];
    provider->source.size = strlen(sources[index]);
    provider->source.identity = 101 + index;
    if (!crust_read(&provider->context, &provider->source, &provider->unit) ||
        !crust_collect(&provider->context) || !crust_resolve(&provider->context) ||
        !crust_check(&provider->context)) {
        fprintf(stderr, "provider: %s\n", provider->context.error);
        return false;
    }
    provider->record = provider->unit->declarations;
    provider->value = provider->record->next;
    provider->function = provider->value->next;
    provider->private_value = provider->function->next;
    provider->callback = provider->private_value->next;
    provider->value->link_name = links[index][0];
    provider->function->link_name = links[index][1];
    provider->private_value->link_name = links[index][2];
    provider->callback->link_name = links[index][3];
    freeze_provider(provider);
    return true;
}

static void intern_name(CrustContext *ctx, void *data)
{
    NameInput *input = data;
    input->name = crust_intern(ctx, (const unsigned char *)input->text, strlen(input->text));
}

static bool bind_name(CrustContext *ctx, const char *name, CrustDecl *decl,
                      CrustName **bound_name)
{
    NameInput input;
    input.text = name;
    input.name = NULL;
    if (!crust_run_stage(ctx, intern_name, &input) || !crust_bind(ctx, input.name, decl))
        return false;
    if (bound_name != NULL) *bound_name = input.name;
    return true;
}

static bool apply_policy(CrustContext *ctx, const Work *work,
                         CrustName **node_name, CrustName **alias_name)
{
    const Policy *policy = work->policy;
    Provider *provider = &work->providers[policy->provider];
    Provider *function_provider = &work->providers[policy->function_provider];
    if (!bind_name(ctx, "Node", provider->record, node_name) ||
        !bind_name(ctx, "Alias", provider->record, alias_name) ||
        !bind_name(ctx, "public_value", provider->value, NULL) ||
        !bind_name(ctx, "saved_node", provider->callback, NULL)) return false;
    if (policy->include_function &&
        !bind_name(ctx, "read_node", function_provider->function, NULL)) return false;
    if (policy->include_private &&
        !bind_name(ctx, "private_value", provider->private_value, NULL)) return false;
    return true;
}

static void test_constant_dependency(Provider *provider)
{
    CrustContext ctx;
    CrustDecl conflicting_function = *provider->function;
    conflicting_function.link_name = "conflicting_function_link";
    crust_context_init(&ctx, NULL);
    check(bind_name(&ctx, "saved", provider->callback, NULL),
          "constant binding supplies its function dependency");
    check(!bind_name(&ctx, "conflict", &conflicting_function, NULL) &&
          strstr(ctx.error, "conflicting facts") != NULL,
          "function dependency rejects a later conflicting identity");
    check(bind_name(&ctx, "read_node", provider->function, NULL),
          "valid dependency alias is accepted after a rejected binding");
    check(bind_name(&ctx, "saved_again", provider->callback, NULL),
          "constant identity can have multiple supplied names");
    crust_context_destroy(&ctx);
}

static void read_output(FILE *output, Result *result)
{
    long length;
    if (fseek(output, 0, SEEK_END) != 0) stop("cannot seek output file");
    length = ftell(output);
    if (length < 0 || (uintmax_t)length >= SIZE_MAX) stop("invalid output file size");
    if (fseek(output, 0, SEEK_SET) != 0) stop("cannot rewind output file");
    result->output_size = (size_t)length;
    result->output = malloc(result->output_size + 1);
    if (result->output == NULL) stop("output allocation failed");
    if (fread(result->output, 1, result->output_size, output) != result->output_size)
        stop("cannot read output file");
    result->output[result->output_size] = '\0';
}

static void compile_consumer(Work *work)
{
    CrustContext ctx;
    CrustSource source;
    CrustUnit *unit;
    CrustX64Program *program;
    CrustSymbol *node;
    CrustSymbol *alias;
    CrustName *node_name;
    CrustName *alias_name;
    Result *result = work->result;
    FILE *output = NULL;
    memset(result, 0, sizeof(*result));
    crust_context_init(&ctx, NULL);
    source.path = work->policy->link_name;
    source.bytes = (const unsigned char *)work->policy->source;
    source.size = strlen(work->policy->source);
    source.identity = 1001 + work->index;
    if (!apply_policy(&ctx, work, &node_name, &alias_name) || !crust_read(&ctx, &source, &unit) ||
        !crust_collect(&ctx) || !crust_resolve(&ctx)) goto done;
    node = crust_map_get(&ctx.globals, (uintptr_t)node_name);
    alias = crust_map_get(&ctx.globals, (uintptr_t)alias_name);
    result->aliases_equal = node != NULL && alias != NULL &&
        node->decl == alias->decl && crust_type_equal(node->type, alias->type);
    result->unit_identity = unit->declarations->unit_identity;
    result->declaration_identity = unit->declarations->identity;
    if (!crust_check_body(&ctx, unit->declarations)) goto done;
    unit->declarations->link_name = work->policy->link_name;
    if (!crust_x64_prepare(&ctx, &program, NULL)) goto done;
    output = tmpfile();
    if (output == NULL) stop("cannot open private output file");
    if (!crust_x64_emit_program(program, output)) goto done;
    read_output(output, result);
    result->accepted = true;
done:
    if (output != NULL && fclose(output) != 0) stop("cannot close output file");
    if (!result->accepted) {
        memcpy(result->error, ctx.error, sizeof(result->error));
        result->error_offset = ctx.error_loc.offset;
        if (ctx.error_loc.source != NULL)
            result->error_source_identity = ctx.error_loc.source->identity;
    }
    crust_context_destroy(&ctx);
}

static void *worker(void *data)
{
    Work *work = data;
    Gate *gate = work->gate;
    unsigned turn;
    pthread_ok(pthread_mutex_lock(&gate->mutex));
    ++gate->ready;
    pthread_ok(pthread_cond_broadcast(&gate->changed));
    while (!gate->started)
        pthread_ok(pthread_cond_wait(&gate->changed, &gate->mutex));
    pthread_ok(pthread_mutex_unlock(&gate->mutex));
    compile_consumer(work);
    turn = gate->reverse ? JOB_COUNT - 1 - work->index : work->index;
    pthread_ok(pthread_mutex_lock(&gate->mutex));
    while (gate->next != turn)
        pthread_ok(pthread_cond_wait(&gate->changed, &gate->mutex));
    work->result->publication_order = gate->next++;
    pthread_ok(pthread_cond_broadcast(&gate->changed));
    pthread_ok(pthread_mutex_unlock(&gate->mutex));
    return NULL;
}

static void run_parallel(Provider *providers, Result *results, bool reverse)
{
    Gate gate;
    Work work[JOB_COUNT];
    pthread_t threads[JOB_COUNT];
    unsigned index;
    memset(&gate, 0, sizeof(gate));
    gate.reverse = reverse;
    pthread_ok(pthread_mutex_init(&gate.mutex, NULL));
    pthread_ok(pthread_cond_init(&gate.changed, NULL));
    for (index = 0; index < JOB_COUNT; ++index) {
        unsigned selected = reverse ? index : JOB_COUNT - 1 - index;
        work[selected].providers = providers;
        work[selected].policy = &policies[selected];
        work[selected].result = &results[selected];
        work[selected].index = selected;
        work[selected].gate = &gate;
        pthread_ok(pthread_create(&threads[selected], NULL, worker, &work[selected]));
    }
    pthread_ok(pthread_mutex_lock(&gate.mutex));
    while (gate.ready != JOB_COUNT)
        pthread_ok(pthread_cond_wait(&gate.changed, &gate.mutex));
    gate.started = true;
    pthread_ok(pthread_cond_broadcast(&gate.changed));
    pthread_ok(pthread_mutex_unlock(&gate.mutex));
    for (index = 0; index < JOB_COUNT; ++index)
        pthread_ok(pthread_join(threads[index], NULL));
    pthread_ok(pthread_cond_destroy(&gate.changed));
    pthread_ok(pthread_mutex_destroy(&gate.mutex));
}

static void compare_result(const Result *serial, const Result *parallel)
{
    check(serial->accepted == parallel->accepted &&
          serial->aliases_equal == parallel->aliases_equal &&
          serial->unit_identity == parallel->unit_identity &&
          serial->declaration_identity == parallel->declaration_identity &&
          serial->error_source_identity == parallel->error_source_identity &&
          serial->error_offset == parallel->error_offset &&
          strcmp(serial->error, parallel->error) == 0,
          "concurrent result and diagnostic equal serial result");
    check(serial->output_size == parallel->output_size &&
          (serial->output_size == 0 ||
           memcmp(serial->output, parallel->output, serial->output_size) == 0),
          "concurrent assembly equals serial assembly");
}

int main(void)
{
    Provider providers[2];
    Result serial[JOB_COUNT];
    Result parallel[JOB_COUNT];
    unsigned index;
    unsigned round;
    for (index = 0; index < 2; ++index)
        if (!prepare_provider(&providers[index], index)) stop("provider preparation failed");
    check(!crust_type_equal(providers[0].record->type, providers[1].record->type),
          "same-layout records from different providers have distinct identities");
    check(providers[0].record->unit_identity == 101 && providers[0].record->identity == 1 &&
          providers[1].record->unit_identity == 102 && providers[1].record->identity == 1,
          "provider identities come from the driver input order");
    test_constant_dependency(&providers[0]);
    for (index = 0; index < JOB_COUNT; ++index) {
        Work work;
        work.providers = providers;
        work.policy = &policies[index];
        work.result = &serial[index];
        work.index = index;
        work.gate = NULL;
        compile_consumer(&work);
        check(serial[index].accepted == (policies[index].expected_error == NULL),
              "driver export policy has the expected result");
        check(serial[index].aliases_equal, "supplied aliases preserve record identity");
        check(serial[index].unit_identity == 1001 + index &&
              serial[index].declaration_identity == 1,
              "consumer identities are assigned before scheduling");
        if (policies[index].expected_error != NULL)
            check(strstr(serial[index].error, policies[index].expected_error) != NULL,
                  "omitted or conflicting binding has a diagnostic");
        else
            check(serial[index].output_size != 0, "successful consumer emits assembly");
        if (serial[index].accepted != (policies[index].expected_error == NULL))
            fprintf(stderr, "%s: %s\n", policies[index].link_name, serial[index].error);
    }
    check(serial[0].output != NULL && strstr(serial[0].output, "provider_a_read_node") != NULL &&
          strstr(serial[0].output, "provider_a_value") != NULL &&
          strstr(serial[0].output, "provider_a_callback") != NULL,
          "driver selects provider A function and constant storage");
    check(serial[1].output != NULL && strstr(serial[1].output, "provider_b_read_node") != NULL &&
          strstr(serial[1].output, "provider_b_value") != NULL &&
          strstr(serial[1].output, "provider_b_callback") != NULL,
          "driver selects provider B function and constant storage");
    check(serial[4].output != NULL && strstr(serial[4].output, "provider_a_private") != NULL,
          "driver can select a name omitted by another visibility policy");
    for (index = 0; index < 2; ++index) check_provider(&providers[index]);
    for (round = 0; round < 2; ++round) {
        bool reverse = round == 0;
        run_parallel(providers, parallel, reverse);
        for (index = 0; index < JOB_COUNT; ++index) {
            compare_result(&serial[index], &parallel[index]);
            check(parallel[index].publication_order ==
                  (reverse ? JOB_COUNT - 1 - index : index),
                  "result publication follows the selected completion order");
            free(parallel[index].output);
        }
        for (index = 0; index < 2; ++index) check_provider(&providers[index]);
    }
    for (index = 0; index < JOB_COUNT; ++index) free(serial[index].output);
    for (index = 0; index < 2; ++index) {
        size_t copy;
        for (copy = 0; copy < providers[index].snapshot_count; ++copy)
            free(providers[index].snapshots[copy].bytes);
        crust_context_destroy(&providers[index].context);
    }
    printf("parallel: %u/%u checks passed; 6 jobs, serial and two concurrent orders\n",
           checks - failures, checks);
    return failures == 0 ? 0 : 1;
}
