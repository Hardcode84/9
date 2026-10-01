/* SPDX-License-Identifier: Apache-2.0 */

#ifndef CRUST0_X64_H
#define CRUST0_X64_H

#include "crust0.h"
#include <stdio.h>

typedef struct CrustX64Slot CrustX64Slot;
typedef struct CrustX64Expr CrustX64Expr;
typedef struct CrustX64Function CrustX64Function;
typedef struct CrustX64String CrustX64String;
typedef struct CrustX64Program CrustX64Program;
typedef struct CrustX64Emitter CrustX64Emitter;
typedef struct CrustX64Loop CrustX64Loop;
typedef struct CrustX64Ops CrustX64Ops;
typedef struct CrustX64Alias CrustX64Alias;

struct CrustX64Slot {
    uint64_t offset;
    uint64_t size;
    uint32_t align;
};

struct CrustX64Expr {
    CrustExpr *expression;
    CrustX64Slot value;
    CrustX64Slot scratch;
    CrustX64Slot arguments;
};

struct CrustX64Function {
    CrustDecl *declaration;
    uint64_t identity;
    uint64_t frame_size;
    CrustMap symbols;
    CrustMap expressions;
    CrustX64Function *next;
};

struct CrustX64String {
    CrustExpr *expression;
    uint64_t identity;
    CrustX64String *next;
};

struct CrustX64Alias {
    CrustDecl *declaration;
    uint64_t identity;
    bool definition;
    CrustX64Alias *next;
};

struct CrustX64Program {
    CrustContext *context;
    CrustDecl *entry;
    CrustX64Function *functions;
    CrustX64Function *last_function;
    CrustX64String *strings;
    CrustX64String *last_string;
    CrustMap string_map;
    CrustMap alias_map;
    CrustMap native_symbols;
    CrustX64Alias *aliases;
    size_t alias_count;
    char label_prefix[48];
    uint64_t next_identity;
};

struct CrustX64Loop {
    uint64_t test_label;
    uint64_t end_label;
    CrustX64Loop *previous;
};

struct CrustX64Ops {
    bool (*expression)(CrustX64Emitter *emitter, CrustExpr *expression);
    bool (*place)(CrustX64Emitter *emitter, CrustExpr *expression);
    bool (*statement)(CrustX64Emitter *emitter, CrustStmt *statement);
};

struct CrustX64Emitter {
    CrustX64Program *program;
    CrustX64Function *function;
    FILE *output;
    const CrustX64Ops *operations;
    CrustX64Loop *loop;
    uint64_t next_label;
    uint64_t return_label;
};

extern const CrustX64Ops crust_x64_default_ops;

/* Preparation requires checked declarations with assigned link names.
   An empty name selects an owned private definition; a null name is invalid.
   External references require a nonempty native name. Keep these names stable
   through emission.
   Expression and statement nodes must form trees of distinct occurrences. */
bool crust_x64_prepare(CrustContext *context, CrustX64Program **result, CrustDecl *entry);
bool crust_x64_emit_program(CrustX64Program *program, FILE *output);
/* Null operations select direct calls to the default emitter operations. */
bool crust_x64_emit_program_with_ops(CrustX64Program *program, FILE *output,
                                     const CrustX64Ops *operations);
bool crust_x64_emit(CrustContext *context, FILE *output, CrustDecl *entry);

/* These stage operations require an active context failure frame. */
CrustX64Slot crust_x64_reserve(CrustContext *context, CrustX64Function *function, uint64_t size,
                               uint32_t alignment, CrustLoc location);
/* On failure, the output slot is unchanged and a diagnostic is retained. */
bool crust_x64_try_reserve(CrustContext *context, CrustX64Function *function, uint64_t size,
                           uint32_t alignment, CrustSource *source, size_t offset,
                           CrustX64Slot *result);
void crust_x64_prepare_function(CrustX64Program *program, CrustX64Function *function);
bool crust_x64_try_prepare_function(CrustX64Program *program, CrustX64Function *function);
void crust_x64_output(CrustX64Emitter *emitter, const char *format, ...);
/* Return false and retain an output diagnostic on failure. */
bool crust_x64_write(CrustX64Emitter *emitter, const char *text);
void crust_x64_emit_function(CrustX64Emitter *emitter, CrustX64Function *function);
void crust_x64_emit_constant(CrustX64Emitter *emitter, CrustDecl *declaration);
void crust_x64_emit_constant_value(CrustX64Emitter *emitter, CrustExpr *expression);
/* A scalar value is in RAX. An aggregate snapshot is at its value slot, with its address in RAX.
   Reads use an installed place operation to get the address of stored values.
   Grouped values delegate to the child expression operation. */
void crust_x64_emit_expression(CrustX64Emitter *emitter, CrustExpr *expression);
/* A place leaves its address in RAX without reading its stored value.
   This also applies to fields and elements of temporary aggregate values. */
void crust_x64_emit_place(CrustX64Emitter *emitter, CrustExpr *expression);
void crust_x64_emit_statement(CrustX64Emitter *emitter, CrustStmt *statement);
/* These defaults return failure without unwinding through a native caller. */
bool crust_x64_try_emit_expression(CrustX64Emitter *emitter, CrustExpr *expression);
bool crust_x64_try_emit_place(CrustX64Emitter *emitter, CrustExpr *expression);
bool crust_x64_try_emit_statement(CrustX64Emitter *emitter, CrustStmt *statement);
bool crust_x64_try_emit_constant(CrustX64Emitter *emitter, CrustDecl *declaration);
bool crust_x64_try_emit_constant_value(CrustX64Emitter *emitter, CrustExpr *expression);
bool crust_x64_try_emit_function(CrustX64Emitter *emitter, CrustX64Function *function);

#endif
