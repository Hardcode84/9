#ifndef RMD0_X64_H
#define RMD0_X64_H

#include "rmd0.h"
#include <stdio.h>

typedef struct RmdX64Slot RmdX64Slot;
typedef struct RmdX64Expr RmdX64Expr;
typedef struct RmdX64Function RmdX64Function;
typedef struct RmdX64String RmdX64String;
typedef struct RmdX64Program RmdX64Program;
typedef struct RmdX64Emitter RmdX64Emitter;
typedef struct RmdX64Loop RmdX64Loop;
typedef struct RmdX64Ops RmdX64Ops;
typedef struct RmdX64Alias RmdX64Alias;

struct RmdX64Slot {
    uint64_t offset;
    uint64_t size;
    uint32_t align;
};

struct RmdX64Expr {
    RmdExpr *expression;
    RmdX64Slot value;
    RmdX64Slot scratch;
    RmdX64Slot arguments;
};

struct RmdX64Function {
    RmdDecl *declaration;
    uint64_t identity;
    uint64_t frame_size;
    RmdMap symbols;
    RmdMap expressions;
    RmdX64Function *next;
};

struct RmdX64String {
    RmdExpr *expression;
    uint64_t identity;
    RmdX64String *next;
};

struct RmdX64Alias {
    RmdDecl *declaration;
    uint64_t identity;
    bool definition;
    RmdX64Alias *next;
};

struct RmdX64Program {
    RmdContext *context;
    RmdDecl *entry;
    RmdX64Function *functions;
    RmdX64Function *last_function;
    RmdX64String *strings;
    RmdX64String *last_string;
    RmdMap string_map;
    RmdMap alias_map;
    RmdMap native_symbols;
    RmdX64Alias *aliases;
    size_t alias_count;
    char label_prefix[48];
    uint64_t next_identity;
};

struct RmdX64Loop {
    uint64_t test_label;
    uint64_t end_label;
    RmdX64Loop *previous;
};

struct RmdX64Ops {
    bool (*expression)(RmdX64Emitter *emitter, RmdExpr *expression);
    bool (*place)(RmdX64Emitter *emitter, RmdExpr *expression);
    bool (*statement)(RmdX64Emitter *emitter, RmdStmt *statement);
};

struct RmdX64Emitter {
    RmdX64Program *program;
    RmdX64Function *function;
    FILE *output;
    const RmdX64Ops *operations;
    RmdX64Loop *loop;
    uint64_t next_label;
    uint64_t return_label;
};

extern const RmdX64Ops rmd_x64_default_ops;

/* Preparation requires checked declarations with assigned link names.
   Expression and statement nodes must form trees of distinct occurrences. */
bool rmd_x64_prepare(RmdContext *context, RmdX64Program **result,
                     RmdDecl *entry);
bool rmd_x64_emit_program(RmdX64Program *program, FILE *output);
/* Null operations select direct calls to the default emitter operations. */
bool rmd_x64_emit_program_with_ops(RmdX64Program *program, FILE *output,
                                    const RmdX64Ops *operations);
bool rmd_x64_emit(RmdContext *context, FILE *output, RmdDecl *entry);

/* These stage operations require an active context failure frame. */
RmdX64Slot rmd_x64_reserve(RmdContext *context, RmdX64Function *function,
                          uint64_t size, uint32_t alignment, RmdLoc location);
/* On failure, the output slot is unchanged and a diagnostic is retained. */
bool rmd_x64_try_reserve(RmdContext *context, RmdX64Function *function,
                          uint64_t size, uint32_t alignment, RmdSource *source,
                          size_t offset, RmdX64Slot *result);
void rmd_x64_prepare_function(RmdX64Program *program,
                              RmdX64Function *function);
bool rmd_x64_try_prepare_function(RmdX64Program *program,
                                  RmdX64Function *function);
void rmd_x64_output(RmdX64Emitter *emitter, const char *format, ...);
/* Return false and retain an output diagnostic on failure. */
bool rmd_x64_write(RmdX64Emitter *emitter, const char *text);
void rmd_x64_emit_function(RmdX64Emitter *emitter, RmdX64Function *function);
void rmd_x64_emit_constant(RmdX64Emitter *emitter, RmdDecl *declaration);
void rmd_x64_emit_constant_value(RmdX64Emitter *emitter, RmdExpr *expression);
/* A scalar value is in RAX. An aggregate snapshot is at its value slot, with its address in RAX.
   Reads use an installed place operation to get the address of stored values.
   Grouped values delegate to the child expression operation. */
void rmd_x64_emit_expression(RmdX64Emitter *emitter, RmdExpr *expression);
/* A place leaves its address in RAX without reading its stored value.
   This also applies to fields and elements of temporary aggregate values. */
void rmd_x64_emit_place(RmdX64Emitter *emitter, RmdExpr *expression);
void rmd_x64_emit_statement(RmdX64Emitter *emitter, RmdStmt *statement);
/* These defaults return failure without unwinding through a native caller. */
bool rmd_x64_try_emit_expression(RmdX64Emitter *emitter, RmdExpr *expression);
bool rmd_x64_try_emit_place(RmdX64Emitter *emitter, RmdExpr *expression);
bool rmd_x64_try_emit_statement(RmdX64Emitter *emitter, RmdStmt *statement);
bool rmd_x64_try_emit_constant(RmdX64Emitter *emitter, RmdDecl *declaration);
bool rmd_x64_try_emit_constant_value(RmdX64Emitter *emitter, RmdExpr *expression);
bool rmd_x64_try_emit_function(RmdX64Emitter *emitter, RmdX64Function *function);

#endif
