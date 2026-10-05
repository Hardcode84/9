/* SPDX-License-Identifier: Apache-2.0 */

/* This measurement tool uses the seed reader and lexer from one translation unit. */
#include "crust0_amalg.c"

#include <stdio.h>
#include <stdlib.h>

typedef struct {
    CrustContext context;
    CrustSource source;
    size_t *closing;
    unsigned char *edits;
    size_t tokens;
    size_t arrows;
    size_t saved;
} Rewrite;

static void mark_expression(Rewrite *rewrite, CrustExpr *expr, unsigned depth)
{
    CrustInit *init;
    size_t index;
    if (expr == NULL)
        return;
    if (depth >= READ_DEPTH_LIMIT)
        crust_fail(&rewrite->context, expr->loc, "rewrite traversal depth exceeded");
    if (expr->kind == CRUST_E_FIELD && expr->left->kind == CRUST_E_GROUP &&
        expr->left->left->kind == CRUST_E_UNARY && expr->left->left->op == CRUST_OP_DEREF) {
        size_t open = expr->left->loc.offset;
        CrustExpr *operand = expr->left->left->left;
        if (operand->kind != CRUST_E_UNARY && operand->kind != CRUST_E_BINARY &&
            operand->kind != CRUST_E_CAST) {
            rewrite->edits[open] = 3;
            rewrite->edits[rewrite->closing[open]] = 1;
            rewrite->saved += 2;
        }
        rewrite->edits[expr->left->left->loc.offset] = 1;
        rewrite->edits[expr->loc.offset] = 2;
        ++rewrite->arrows;
        ++rewrite->saved;
    }
    mark_expression(rewrite, expr->left, depth + 1);
    mark_expression(rewrite, expr->right, depth + 1);
    for (index = 0; index < expr->arg_count; ++index)
        mark_expression(rewrite, expr->args[index], depth + 1);
    for (init = expr->inits; init != NULL; init = init->next)
        mark_expression(rewrite, init->value, depth + 1);
}

static void mark_statement(Rewrite *rewrite, CrustStmt *stmt, unsigned depth)
{
    if (depth >= READ_DEPTH_LIMIT)
        crust_fail(&rewrite->context, stmt->loc, "rewrite traversal depth exceeded");
    for (; stmt != NULL; stmt = stmt->next) {
        mark_expression(rewrite, stmt->expr, depth + 1);
        mark_expression(rewrite, stmt->value, depth + 1);
        if (stmt->body != NULL)
            mark_statement(rewrite, stmt->body, depth + 1);
        if (stmt->otherwise != NULL)
            mark_statement(rewrite, stmt->otherwise, depth + 1);
    }
}

static void rewrite_stage(CrustContext *ctx, void *data)
{
    Rewrite *rewrite = data;
    Reader reader;
    size_t *stack = crust_alloc(ctx, rewrite->source.size * sizeof(size_t), CRUST_ALIGNOF(size_t));
    size_t count = 0;
    size_t offset = 0;
    memset(&reader, 0, sizeof(reader));
    reader.ctx = ctx;
    reader.source = &rewrite->source;
    reader.end = rewrite->source.size;
    for (;;) {
        next_token(&reader);
        if (reader.token.kind == TOK_EOF)
            break;
        ++rewrite->tokens;
        if (reader.token.kind == '(')
            stack[count++] = reader.token.loc.offset;
        else if (reader.token.kind == ')') {
            if (count == 0)
                crust_fail(ctx, reader.token.loc, "unmatched closing parenthesis");
            rewrite->closing[stack[--count]] = reader.token.loc.offset;
        }
    }
    if (count != 0)
        crust_fail(ctx, reader.token.loc, "unmatched opening parenthesis");
    while (offset < rewrite->source.size) {
        CrustAction action;
        if (!crust_read_one(ctx, &rewrite->source, offset, rewrite->source.size, &action))
            return;
        offset = action.end;
        if (action.declaration != NULL) {
            mark_expression(rewrite, action.declaration->init, 0);
            if (action.declaration->body != NULL)
                mark_statement(rewrite, action.declaration->body, 0);
        }
        if (action.statement != NULL)
            mark_statement(rewrite, action.statement, 0);
    }
}

static bool load_input(Rewrite *rewrite, const char *path)
{
    FILE *input = fopen(path, "rb");
    unsigned char *bytes;
    long length;
    bool success;
    if (input == NULL)
        return false;
    if (fseek(input, 0, SEEK_END) != 0 || (length = ftell(input)) <= 0 ||
        (uint64_t)length >= SIZE_MAX / sizeof(size_t) || fseek(input, 0, SEEK_SET) != 0) {
        fclose(input);
        return false;
    }
    rewrite->source.size = (size_t)length;
    bytes = crust_try_alloc(&rewrite->context, (size_t)length, 1);
    if (bytes == NULL) {
        fclose(input);
        return false;
    }
    rewrite->source.bytes = bytes;
    rewrite->source.path = path;
    rewrite->source.identity = 1;
    success = fread(bytes, 1, (size_t)length, input) == (size_t)length;
    if (fclose(input) != 0)
        success = false;
    return success;
}

static bool write_output(Rewrite *rewrite, const char *path)
{
    FILE *output = fopen(path, "wb");
    size_t index;
    bool success;
    if (output == NULL)
        return false;
    for (index = 0; index < rewrite->source.size; ++index) {
        if (rewrite->edits[index] == 2)
            fputs("->", output);
        else if (rewrite->edits[index] == 3)
            fputc(' ', output);
        else if (rewrite->edits[index] == 0)
            fputc(rewrite->source.bytes[index], output);
    }
    success = ferror(output) == 0;
    if (fclose(output) != 0)
        success = false;
    return success;
}

int main(int argc, char **argv)
{
    Rewrite rewrite;
    bool success = false;
    if (argc != 3)
        return 2;
    memset(&rewrite, 0, sizeof(rewrite));
    crust_context_init(&rewrite.context, NULL);
    if (load_input(&rewrite, argv[1])) {
        rewrite.closing = crust_try_alloc(&rewrite.context, rewrite.source.size * sizeof(size_t),
                                          CRUST_ALIGNOF(size_t));
        rewrite.edits = crust_try_alloc(&rewrite.context, rewrite.source.size, 1);
        success = rewrite.closing != NULL && rewrite.edits != NULL &&
                  crust_run_stage(&rewrite.context, rewrite_stage, &rewrite) &&
                  rewrite.context.error_count == 0 && write_output(&rewrite, argv[2]);
    }
    if (success)
        printf("{\"tokens\":%zu,\"arrows\":%zu,\"after\":%zu}\n", rewrite.tokens, rewrite.arrows,
               rewrite.tokens - rewrite.saved);
    else
        fprintf(stderr, "%s: rewrite failed: %s\n", argv[1], rewrite.context.error);
    crust_context_destroy(&rewrite.context);
    return success && !ferror(stdout) ? 0 : 1;
}
