/* SPDX-License-Identifier: Apache-2.0 */

#include "crust0.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    CrustContext scratch;
    size_t types[CRUST_T_END];
    size_t expressions[CRUST_E_END];
    size_t statements[CRUST_S_END];
    size_t declarations[CRUST_D_CONST + 1];
    CrustMap seen;
} Histogram;

static bool first_visit(Histogram *histogram, void *node, unsigned depth)
{
    CrustLoc location = {NULL, 0};
    if (depth > 1024)
        crust_fail(&histogram->scratch, location, "histogram depth exceeded");
    if (node == NULL || crust_map_get(&histogram->seen, (uintptr_t)node) != NULL)
        return false;
    crust_map_set(&histogram->scratch, &histogram->seen, (uintptr_t)node, node);
    return true;
}

static void visit_type(Histogram *histogram, CrustTypeSyntax *node, unsigned depth)
{
    size_t index;
    if (!first_visit(histogram, node, depth))
        return;
    ++histogram->types[node->kind];
    visit_type(histogram, node->base, depth + 1);
    for (index = 0; index < node->param_count; ++index)
        visit_type(histogram, node->params[index], depth + 1);
}

static void visit_expr(Histogram *histogram, CrustExpr *node, unsigned depth)
{
    /* left, right, args, inits, syntax_type; indexed by the seed expression kind. */
    static const unsigned children[] = {0, 0, 0, 0, 1, 1, 3, 5, 3, 1, 17, 24, 20, 16, 16, 16, 16};
    unsigned fields;
    size_t index;
    CrustInit *init;
    if (!first_visit(histogram, node, depth))
        return;
    ++histogram->expressions[node->kind];
    fields = children[node->kind];
    if ((fields & 1) != 0)
        visit_expr(histogram, node->left, depth + 1);
    if ((fields & 2) != 0)
        visit_expr(histogram, node->right, depth + 1);
    if ((fields & 4) != 0) {
        for (index = 0; index < node->arg_count; ++index)
            visit_expr(histogram, node->args[index], depth + 1);
    }
    if ((fields & 8) != 0) {
        for (init = node->inits; init != NULL; init = init->next)
            visit_expr(histogram, init->value, depth + 1);
    }
    if ((fields & 16) != 0)
        visit_type(histogram, node->syntax_type, depth + 1);
}

static void visit_stmt(Histogram *histogram, CrustStmt *node, unsigned depth)
{
    for (; node != NULL; node = node->next) {
        if (!first_visit(histogram, node, depth))
            return;
        ++histogram->statements[node->kind];
        visit_type(histogram, node->syntax_type, depth + 1);
        visit_expr(histogram, node->expr, depth + 1);
        visit_expr(histogram, node->value, depth + 1);
        visit_stmt(histogram, node->body, depth + 1);
        visit_stmt(histogram, node->otherwise, depth + 1);
    }
}

static void histogram_stage(CrustContext *scratch, void *data)
{
    Histogram *histogram = (Histogram *)scratch;
    CrustContext *context = data;
    CrustUnit *unit;
    for (unit = context->units; unit != NULL; unit = unit->next) {
        CrustDecl *decl;
        for (decl = unit->declarations; decl != NULL; decl = decl->next) {
            CrustField *field;
            CrustParam *param;
            ++histogram->declarations[decl->kind];
            visit_type(histogram, decl->syntax_type, 0);
            visit_expr(histogram, decl->init, 0);
            visit_stmt(histogram, decl->body, 0);
            for (field = decl->fields; field != NULL; field = field->next)
                visit_type(histogram, field->syntax_type, 0);
            for (param = decl->params; param != NULL; param = param->next)
                visit_type(histogram, param->syntax_type, 0);
        }
    }
}

static void print_counts(const char *name, const size_t *counts, size_t kinds, size_t bytes)
{
    size_t index;
    printf("\"%s\":{\"node_bytes\":%zu,\"counts\":[", name, bytes);
    for (index = 0; index < kinds; ++index)
        printf("%s%zu", index == 0 ? "" : ",", counts[index]);
    printf("]}");
}

static bool print_histogram(CrustContext *context, size_t read_bytes)
{
    Histogram histogram;
    bool success;
    memset(&histogram, 0, sizeof(histogram));
    crust_context_init(&histogram.scratch, NULL);
    success = crust_run_stage(&histogram.scratch, histogram_stage, context);
    if (success) {
        printf("{\"read_arena_bytes\":%zu,\"check_arena_bytes\":%zu,", read_bytes,
               context->arena.bytes_reserved);
        print_counts("CrustTypeSyntax", histogram.types, CRUST_T_END, sizeof(CrustTypeSyntax));
        printf(",");
        print_counts("CrustExpr", histogram.expressions, CRUST_E_END, sizeof(CrustExpr));
        printf(",");
        print_counts("CrustStmt", histogram.statements, CRUST_S_END, sizeof(CrustStmt));
        printf(",");
        print_counts("CrustDecl", histogram.declarations, CRUST_D_CONST + 1, sizeof(CrustDecl));
        puts("}");
    } else {
        fprintf(stderr, "%s\n", histogram.scratch.error);
    }
    crust_context_destroy(&histogram.scratch);
    return success;
}

static bool load_source(CrustSource *source, const char *path, uint64_t identity)
{
    FILE *file = fopen(path, "rb");
    long size;
    unsigned char *bytes;
    bool success;
    if (file == NULL)
        return false;
    if (fseek(file, 0, SEEK_END) != 0 || (size = ftell(file)) < 0 ||
        fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return false;
    }
    bytes = malloc((size_t)size + 1);
    if (bytes == NULL) {
        fclose(file);
        return false;
    }
    source->path = path;
    source->bytes = bytes;
    source->size = (size_t)size;
    source->identity = identity;
    success = fread(bytes, 1, source->size, file) == source->size;
    bytes[size] = 0;
    if (fclose(file) != 0)
        success = false;
    return success;
}

static bool check_sources(CrustContext *context, CrustSource *sources, int count, char **paths,
                          bool histogram)
{
    int index;
    size_t read_bytes;
    for (index = 0; index < count; ++index) {
        CrustUnit *unit;
        if (!load_source(&sources[index], paths[index], (uint64_t)index + 1)) {
            fprintf(stderr, "cannot load source: %s\n", paths[index]);
            return false;
        }
        if (!crust_read(context, &sources[index], &unit))
            return false;
    }
    read_bytes = context->arena.bytes_reserved;
    if (!crust_collect(context) || !crust_resolve(context) || !crust_check(context))
        return false;
    return !histogram || print_histogram(context, read_bytes);
}

int main(int argc, char **argv)
{
    CrustContext context;
    CrustSource *sources;
    bool histogram = argc > 1 && strcmp(argv[1], "--histogram") == 0;
    int begin = histogram ? 2 : 1;
    int count = argc - begin;
    int index;
    bool success;
    if (count <= 0)
        return 2;
    sources = calloc((size_t)count, sizeof(*sources));
    if (sources == NULL)
        return 1;
    crust_context_init(&context, NULL);
    success = check_sources(&context, sources, count, argv + begin, histogram);
    if (ferror(stdout))
        success = false;
    if (context.error_count != 0)
        fprintf(stderr, "%zu:%s\n", context.error_loc.offset, context.error);
    crust_context_destroy(&context);
    for (index = 0; index < count; ++index)
        free((void *)sources[index].bytes);
    free(sources);
    return success ? 0 : 1;
}
