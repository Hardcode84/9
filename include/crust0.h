#ifndef CRUST0_H
#define CRUST0_H

#include <setjmp.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define CRUST_VERSION "0.1"
#define CRUST_ALIGNOF(T)                                                                           \
    (sizeof(struct {                                                                               \
         char byte;                                                                                \
         T value;                                                                                  \
     }) -                                                                                          \
     sizeof(T))

typedef struct CrustArena CrustArena;
typedef struct CrustArenaBlock CrustArenaBlock;
typedef struct CrustContext CrustContext;
typedef struct CrustSource CrustSource;
typedef struct CrustName CrustName;
typedef struct CrustType CrustType;
typedef struct CrustTypeSyntax CrustTypeSyntax;
typedef struct CrustExpr CrustExpr;
typedef struct CrustStmt CrustStmt;
typedef struct CrustDecl CrustDecl;
typedef struct CrustSymbol CrustSymbol;
typedef struct CrustField CrustField;
typedef struct CrustParam CrustParam;
typedef struct CrustInit CrustInit;
typedef struct CrustUnit CrustUnit;
typedef struct CrustAction CrustAction;
typedef struct CrustRootScope CrustRootScope;

typedef struct {
    void *user;
    void *(*allocate)(void *user, size_t size);
    void (*release)(void *user, void *allocation);
} CrustAllocator;

struct CrustArena {
    CrustAllocator allocator;
    CrustArenaBlock *blocks;
    size_t bytes_reserved;
};

typedef struct {
    CrustSource *source;
    size_t offset;
} CrustLoc;

struct CrustSource {
    const char *path;
    const unsigned char *bytes;
    size_t size;
    uint64_t identity;
};

struct CrustName {
    const char *text;
    size_t size;
    uint64_t hash;
};

typedef struct {
    uintptr_t key;
    void *value;
} CrustMapEntry;

typedef struct {
    CrustMapEntry *entries;
    size_t count;
    size_t capacity;
} CrustMap;

typedef enum {
    CRUST_T_I8,
    CRUST_T_U8,
    CRUST_T_I16,
    CRUST_T_U16,
    CRUST_T_I32,
    CRUST_T_U32,
    CRUST_T_I64,
    CRUST_T_U64,
    CRUST_T_ISIZE,
    CRUST_T_USIZE,
    CRUST_T_BOOL,
    CRUST_T_UNIT,
    CRUST_T_POINTER,
    CRUST_T_ARRAY,
    CRUST_T_FUNCTION,
    CRUST_T_RECORD,
    CRUST_T_NAME
} CrustTypeKind;

struct CrustTypeSyntax {
    CrustTypeKind kind;
    CrustLoc loc;
    CrustName *name;
    CrustTypeSyntax *base;
    CrustTypeSyntax **params;
    size_t param_count;
    uint64_t count;
};

struct CrustType {
    CrustTypeKind kind;
    uint64_t size;
    uint32_t align;
    CrustType *base;
    uint64_t count;
    CrustType **params;
    size_t param_count;
    CrustDecl *record_decl;
};

typedef enum {
    CRUST_OP_ADD,
    CRUST_OP_SUB,
    CRUST_OP_MUL,
    CRUST_OP_DIV,
    CRUST_OP_REM,
    CRUST_OP_SHL,
    CRUST_OP_SHR,
    CRUST_OP_BIT_AND,
    CRUST_OP_BIT_OR,
    CRUST_OP_BIT_XOR,
    CRUST_OP_EQ,
    CRUST_OP_NE,
    CRUST_OP_LT,
    CRUST_OP_LE,
    CRUST_OP_GT,
    CRUST_OP_GE,
    CRUST_OP_AND,
    CRUST_OP_OR,
    CRUST_OP_NEG,
    CRUST_OP_NOT,
    CRUST_OP_BIT_NOT,
    CRUST_OP_DEREF,
    CRUST_OP_ADDRESS
} CrustOp;

typedef enum {
    CRUST_E_NAME,
    CRUST_E_INTEGER,
    CRUST_E_BOOL,
    CRUST_E_STRING,
    CRUST_E_GROUP,
    CRUST_E_UNARY,
    CRUST_E_BINARY,
    CRUST_E_CALL,
    CRUST_E_INDEX,
    CRUST_E_FIELD,
    CRUST_E_CAST,
    CRUST_E_RECORD,
    CRUST_E_ARRAY,
    CRUST_E_NULL,
    CRUST_E_SIZEOF,
    CRUST_E_ALIGNOF,
    CRUST_E_OFFSETOF
} CrustExprKind;

struct CrustInit {
    CrustName *name;
    CrustLoc loc;
    CrustExpr *value;
    CrustField *field;
    CrustInit *next;
};

struct CrustExpr {
    CrustExprKind kind;
    CrustLoc loc;
    CrustOp op;
    CrustExpr *left;
    CrustExpr *right;
    CrustExpr **args;
    size_t arg_count;
    CrustInit *inits;
    CrustName *name;
    CrustName *field_name;
    CrustTypeSyntax *syntax_type;
    CrustTypeKind literal_type;
    uint64_t integer;
    const unsigned char *bytes;
    size_t byte_count;
    CrustType *type;
    CrustSymbol *symbol;
    CrustField *field;
    bool place;
    bool writable;
};

typedef enum {
    CRUST_S_BLOCK,
    CRUST_S_VAR,
    CRUST_S_IF,
    CRUST_S_WHILE,
    CRUST_S_BREAK,
    CRUST_S_CONTINUE,
    CRUST_S_RETURN,
    CRUST_S_TRAP,
    CRUST_S_EXPR,
    CRUST_S_ASSIGN
} CrustStmtKind;

struct CrustStmt {
    CrustStmtKind kind;
    CrustLoc loc;
    CrustStmt *next;
    CrustStmt *body;
    CrustStmt *otherwise;
    CrustExpr *expr;
    CrustExpr *value;
    CrustName *name;
    CrustTypeSyntax *syntax_type;
    CrustSymbol *symbol;
    bool uninitialized;
};

struct CrustField {
    CrustName *name;
    CrustLoc loc;
    CrustTypeSyntax *syntax_type;
    CrustType *type;
    uint64_t offset;
    size_t index;
    CrustField *next;
};

struct CrustParam {
    CrustName *name;
    CrustLoc loc;
    CrustTypeSyntax *syntax_type;
    CrustType *type;
    CrustSymbol *symbol;
    CrustParam *next;
};

typedef enum { CRUST_D_RECORD, CRUST_D_FUNCTION, CRUST_D_EXTERN, CRUST_D_CONST } CrustDeclKind;

typedef enum {
    CRUST_SYM_RECORD,
    CRUST_SYM_FUNCTION,
    CRUST_SYM_CONST,
    CRUST_SYM_LOCAL,
    CRUST_SYM_PARAM
} CrustSymbolKind;

struct CrustSymbol {
    CrustSymbolKind kind;
    CrustName *name;
    CrustLoc loc;
    CrustType *type;
    CrustDecl *decl;
    CrustSymbol *scope_next;
};

struct CrustDecl {
    CrustDeclKind kind;
    CrustLoc loc;
    CrustName *name;
    uint64_t unit_identity;
    uint64_t identity;
    const char *link_name;
    CrustTypeSyntax *syntax_type;
    CrustType *type;
    CrustSymbol *symbol;
    CrustField *fields;
    size_t field_count;
    CrustParam *params;
    size_t param_count;
    CrustStmt *body;
    CrustExpr *init;
    CrustDecl *next;
    unsigned resolve_state;
    bool checked;
};

struct CrustUnit {
    CrustSource *source;
    CrustDecl *declarations;
    CrustUnit *next;
};

struct CrustAction {
    CrustDecl *declaration;
    CrustStmt *statement;
    size_t end;
};

struct CrustRootScope {
    CrustMap locals;
    CrustSymbol *scope;
};

typedef struct CrustFailureFrame {
    jmp_buf jump;
    struct CrustFailureFrame *previous;
} CrustFailureFrame;

struct CrustContext {
    CrustArena arena;
    CrustName **names;
    size_t name_count;
    size_t name_capacity;
    CrustMap globals;
    CrustMap identities;
    void *type_comparison;
    CrustType builtins[CRUST_T_UNIT + 1];
    CrustUnit *units;
    CrustUnit *last_unit;
    CrustFailureFrame *failure;
    CrustLoc error_loc;
    char error[512];
    size_t error_count;
};

/* An initialized arena owns all returned storage until destruction. */
void crust_arena_init(CrustArena *arena, const CrustAllocator *allocator);
void crust_arena_destroy(CrustArena *arena);
/* Return null for allocation failure or an unsupported alignment. */
void *crust_arena_alloc(CrustArena *arena, size_t size, size_t alignment);

void crust_context_init(CrustContext *ctx, const CrustAllocator *allocator);
void crust_context_destroy(CrustContext *ctx);
/* The C callback must permit a nonlocal exit. False retains its diagnostic. */
bool crust_run_stage(CrustContext *ctx, void (*stage)(CrustContext *, void *), void *data);
/* Record a diagnostic without a nonlocal exit. */
void crust_set_error(CrustContext *ctx, CrustSource *source, size_t offset, const char *message);
/* Failure returns null and retains a diagnostic. Zero-size allocation returns null. */
void *crust_try_alloc(CrustContext *ctx, size_t size, size_t alignment);
CrustName *crust_try_intern(CrustContext *ctx, const unsigned char *text, size_t size);
/* Retain a diagnostic and return null on failure. A zero capacity returns null. */
void *crust_try_grow_array(CrustContext *ctx, const void *old, size_t count, size_t capacity,
                           size_t item_size, size_t alignment);
/* Return a zero-terminated copy, or null with a retained diagnostic on failure. */
char *crust_try_copy_string(CrustContext *ctx, const unsigned char *text, size_t size);
/* Return false and retain a diagnostic if the map update fails. */
bool crust_try_map_set(CrustContext *ctx, CrustMap *map, uintptr_t key, void *value);
/* crust_alloc returns zeroed storage. Construction helpers require a failure frame. */
void *crust_alloc(CrustContext *ctx, size_t size, size_t alignment);
void *crust_grow_array(CrustContext *ctx, const void *old, size_t count, size_t capacity,
                       size_t item_size, size_t alignment);
CrustName *crust_intern(CrustContext *ctx, const unsigned char *text, size_t size);
char *crust_copy_string(CrustContext *ctx, const unsigned char *text, size_t size);
void crust_fail(CrustContext *ctx, CrustLoc loc, const char *format, ...);
void *crust_map_get(const CrustMap *map, uintptr_t key);
void crust_map_set(CrustContext *ctx, CrustMap *map, uintptr_t key, void *value);

/* Input bytes and source descriptors remain live until the context is destroyed. */
bool crust_read(CrustContext *ctx, CrustSource *source, CrustUnit **result);
/* Read [begin, end) with absolute source locations. Empty ranges are valid.
   Invalid ranges or syntax return false, retain a diagnostic, and set result to null.
   Input bytes and source descriptors remain live until the context is destroyed. */
bool crust_read_range(CrustContext *ctx, CrustSource *source, size_t begin, size_t end,
                      CrustUnit **result);
/* Read one root action without reading past its final delimiter. The result is
   unlinked. Exactly one node is nonnull, or both are null at EOF. End is the
   absolute offset after the delimiter, or the range end at EOF. Root blocks,
   if, and while require a final semicolon. Failure clears result.
   Input bytes and source descriptors remain live until context destruction. */
bool crust_read_one(CrustContext *ctx, CrustSource *source, size_t begin, size_t end,
                    CrustAction *result);
/* A binding borrows complete resolved facts. The provider must outlive this context.
   Failure publishes no binding or provider identity. */
bool crust_bind(CrustContext *ctx, CrustName *name, CrustDecl *declaration);
/* Owned syntax has one expression or statement node per occurrence. */
bool crust_collect(CrustContext *ctx);
bool crust_resolve(CrustContext *ctx);
bool crust_check_body(CrustContext *ctx, CrustDecl *function);
bool crust_check(CrustContext *ctx);
/* Visit only this unit. Collect, then resolve, then check its declarations.
   Resolution and checking may use declarations already visible in the context. */
bool crust_collect_unit(CrustContext *ctx, CrustUnit *unit_value);
bool crust_resolve_unit(CrustContext *ctx, CrustUnit *unit_value);
bool crust_check_unit(CrustContext *ctx, CrustUnit *unit_value);
/* Start with a zeroed scope, or visible local symbols owned by this context.
   Retain root locals between calls. Root return values must have type i32.
   Declared functions do not use this scope. Stop the stream after failure. */
bool crust_check_root(CrustContext *ctx, CrustRootScope *scope, CrustStmt *statement);

CrustType *crust_resolve_type(CrustContext *ctx, CrustTypeSyntax *syntax);
/* Return null and retain a diagnostic if type resolution fails. */
CrustType *crust_try_resolve_type(CrustContext *ctx, CrustTypeSyntax *syntax);
/* Type queries require complete resolved facts. */
/* Exact type comparison requires a failure frame for scratch allocation. */
bool crust_type_equal(CrustContext *ctx, const CrustType *a, const CrustType *b);
/* On allocation failure, retain a diagnostic and leave result unchanged. */
bool crust_try_type_equal(CrustContext *ctx, const CrustType *a, const CrustType *b, bool *result);
bool crust_type_integer(const CrustType *type);
bool crust_type_signed(const CrustType *type);
bool crust_type_scalar(const CrustType *type);
unsigned crust_type_bits(const CrustType *type);
CrustType *crust_pointer_type(CrustContext *ctx, CrustType *base);
/* Require a resolved storage type. Return null with a diagnostic on failure. */
CrustType *crust_try_pointer_type(CrustContext *ctx, CrustType *base);

#endif
