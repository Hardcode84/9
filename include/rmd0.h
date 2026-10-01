#ifndef RMD0_H
#define RMD0_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <setjmp.h>

#define RMD_VERSION "0.1"
#define RMD_ALIGNOF(T) (sizeof(struct { char byte; T value; }) - sizeof(T))

typedef struct RmdArena RmdArena;
typedef struct RmdArenaBlock RmdArenaBlock;
typedef struct RmdContext RmdContext;
typedef struct RmdSource RmdSource;
typedef struct RmdName RmdName;
typedef struct RmdType RmdType;
typedef struct RmdTypeSyntax RmdTypeSyntax;
typedef struct RmdExpr RmdExpr;
typedef struct RmdStmt RmdStmt;
typedef struct RmdDecl RmdDecl;
typedef struct RmdSymbol RmdSymbol;
typedef struct RmdField RmdField;
typedef struct RmdParam RmdParam;
typedef struct RmdInit RmdInit;
typedef struct RmdUnit RmdUnit;
typedef struct RmdMetaInput RmdMetaInput;
typedef struct RmdMeta RmdMeta;

typedef struct {
    void *user;
    void *(*allocate)(void *user, size_t size);
    void (*release)(void *user, void *allocation);
} RmdAllocator;

struct RmdArena {
    RmdAllocator allocator;
    RmdArenaBlock *blocks;
    size_t bytes_reserved;
};

typedef struct {
    RmdSource *source;
    size_t offset;
} RmdLoc;

struct RmdSource {
    const char *path;
    const unsigned char *bytes;
    size_t size;
    uint64_t identity;
};

struct RmdName {
    const char *text;
    size_t size;
    uint64_t hash;
};

typedef struct {
    uintptr_t key;
    void *value;
} RmdMapEntry;

typedef struct {
    RmdMapEntry *entries;
    size_t count;
    size_t capacity;
} RmdMap;

typedef enum {
    RMD_T_I8, RMD_T_U8, RMD_T_I16, RMD_T_U16,
    RMD_T_I32, RMD_T_U32, RMD_T_I64, RMD_T_U64,
    RMD_T_ISIZE, RMD_T_USIZE, RMD_T_BOOL, RMD_T_UNIT,
    RMD_T_POINTER, RMD_T_ARRAY, RMD_T_FUNCTION, RMD_T_RECORD,
    RMD_T_NAME
} RmdTypeKind;

struct RmdTypeSyntax {
    RmdTypeKind kind;
    RmdLoc loc;
    RmdName *name;
    RmdTypeSyntax *base;
    RmdTypeSyntax **params;
    size_t param_count;
    uint64_t count;
};

struct RmdType {
    RmdTypeKind kind;
    uint64_t size;
    uint32_t align;
    RmdType *base;
    uint64_t count;
    RmdType **params;
    size_t param_count;
    RmdDecl *record_decl;
};

typedef enum {
    RMD_OP_ADD, RMD_OP_SUB, RMD_OP_MUL, RMD_OP_DIV, RMD_OP_REM,
    RMD_OP_SHL, RMD_OP_SHR, RMD_OP_BIT_AND, RMD_OP_BIT_OR,
    RMD_OP_BIT_XOR, RMD_OP_EQ, RMD_OP_NE, RMD_OP_LT, RMD_OP_LE,
    RMD_OP_GT, RMD_OP_GE, RMD_OP_AND, RMD_OP_OR, RMD_OP_NEG,
    RMD_OP_NOT, RMD_OP_BIT_NOT, RMD_OP_DEREF, RMD_OP_ADDRESS
} RmdOp;

typedef enum {
    RMD_E_NAME, RMD_E_INTEGER, RMD_E_BOOL, RMD_E_STRING,
    RMD_E_GROUP, RMD_E_UNARY, RMD_E_BINARY, RMD_E_CALL,
    RMD_E_INDEX, RMD_E_FIELD, RMD_E_CAST, RMD_E_RECORD,
    RMD_E_ARRAY, RMD_E_NULL, RMD_E_SIZEOF, RMD_E_ALIGNOF,
    RMD_E_OFFSETOF
} RmdExprKind;

struct RmdInit {
    RmdName *name;
    RmdLoc loc;
    RmdExpr *value;
    RmdField *field;
    RmdInit *next;
};

struct RmdExpr {
    RmdExprKind kind;
    RmdLoc loc;
    RmdOp op;
    RmdExpr *left;
    RmdExpr *right;
    RmdExpr **args;
    size_t arg_count;
    RmdInit *inits;
    RmdName *name;
    RmdName *field_name;
    RmdTypeSyntax *syntax_type;
    RmdTypeKind literal_type;
    uint64_t integer;
    const unsigned char *bytes;
    size_t byte_count;
    RmdType *type;
    RmdSymbol *symbol;
    RmdField *field;
    bool place;
    bool writable;
};

typedef enum {
    RMD_S_BLOCK, RMD_S_VAR, RMD_S_IF, RMD_S_WHILE, RMD_S_BREAK,
    RMD_S_CONTINUE, RMD_S_RETURN, RMD_S_TRAP, RMD_S_EXPR, RMD_S_ASSIGN
} RmdStmtKind;

struct RmdStmt {
    RmdStmtKind kind;
    RmdLoc loc;
    RmdStmt *next;
    RmdStmt *body;
    RmdStmt *otherwise;
    RmdExpr *expr;
    RmdExpr *value;
    RmdName *name;
    RmdTypeSyntax *syntax_type;
    RmdSymbol *symbol;
    bool uninitialized;
};

struct RmdField {
    RmdName *name;
    RmdLoc loc;
    RmdTypeSyntax *syntax_type;
    RmdType *type;
    uint64_t offset;
    size_t index;
    RmdField *next;
};

struct RmdParam {
    RmdName *name;
    RmdLoc loc;
    RmdTypeSyntax *syntax_type;
    RmdType *type;
    RmdSymbol *symbol;
    RmdParam *next;
};

typedef enum {
    RMD_D_RECORD, RMD_D_FUNCTION, RMD_D_EXTERN, RMD_D_CONST
} RmdDeclKind;

typedef enum {
    RMD_SYM_RECORD, RMD_SYM_FUNCTION, RMD_SYM_CONST,
    RMD_SYM_LOCAL, RMD_SYM_PARAM
} RmdSymbolKind;

struct RmdSymbol {
    RmdSymbolKind kind;
    RmdName *name;
    RmdLoc loc;
    RmdType *type;
    RmdDecl *decl;
    RmdSymbol *scope_next;
};

struct RmdDecl {
    RmdDeclKind kind;
    RmdLoc loc;
    RmdName *name;
    uint64_t unit_identity;
    uint64_t identity;
    const char *link_name;
    RmdTypeSyntax *syntax_type;
    RmdType *type;
    RmdSymbol *symbol;
    RmdField *fields;
    size_t field_count;
    RmdParam *params;
    size_t param_count;
    RmdStmt *body;
    RmdExpr *init;
    RmdDecl *next;
    unsigned resolve_state;
    bool checked;
};

struct RmdUnit {
    RmdSource *source;
    RmdDecl *declarations;
    RmdUnit *next;
};

struct RmdMetaInput {
    RmdMetaInput *next;
    RmdLoc loc;
    char *path;
    bool native;
};

struct RmdMeta {
    RmdUnit *host_unit;
    RmdMetaInput *inputs;
    size_t target_begin;
    RmdLoc loc;
};

typedef struct RmdFailureFrame {
    jmp_buf jump;
    struct RmdFailureFrame *previous;
} RmdFailureFrame;

struct RmdContext {
    RmdArena arena;
    RmdName **names;
    size_t name_count;
    size_t name_capacity;
    RmdMap globals;
    RmdMap identities;
    RmdType builtins[RMD_T_UNIT + 1];
    RmdUnit *units;
    RmdUnit *last_unit;
    RmdFailureFrame *failure;
    RmdLoc error_loc;
    char error[512];
    size_t error_count;
};

/* An initialized arena owns all returned storage until destruction. */
void rmd_arena_init(RmdArena *arena, const RmdAllocator *allocator);
void rmd_arena_destroy(RmdArena *arena);
/* Return null for allocation failure or an unsupported alignment. */
void *rmd_arena_alloc(RmdArena *arena, size_t size, size_t alignment);

void rmd_context_init(RmdContext *ctx, const RmdAllocator *allocator);
void rmd_context_destroy(RmdContext *ctx);
/* The C callback must permit a nonlocal exit. False retains its diagnostic. */
bool rmd_run_stage(RmdContext *ctx, void (*stage)(RmdContext *, void *), void *data);
/* Record a diagnostic without a nonlocal exit. */
void rmd_set_error(RmdContext *ctx, RmdSource *source, size_t offset, const char *message);
/* Failure returns null and retains a diagnostic. Zero-size allocation returns null. */
void *rmd_try_alloc(RmdContext *ctx, size_t size, size_t alignment);
RmdName *rmd_try_intern(RmdContext *ctx, const unsigned char *text, size_t size);
/* Retain a diagnostic and return null on failure. A zero capacity returns null. */
void *rmd_try_grow_array(RmdContext *ctx, const void *old, size_t count,
                         size_t capacity, size_t item_size, size_t alignment);
/* Return a zero-terminated copy, or null with a retained diagnostic on failure. */
char *rmd_try_copy_string(RmdContext *ctx, const unsigned char *text, size_t size);
/* Return false and retain a diagnostic if the map update fails. */
bool rmd_try_map_set(RmdContext *ctx, RmdMap *map, uintptr_t key, void *value);
/* rmd_alloc returns zeroed storage. Construction helpers require a failure frame. */
void *rmd_alloc(RmdContext *ctx, size_t size, size_t alignment);
void *rmd_grow_array(RmdContext *ctx, const void *old, size_t count,
                     size_t capacity, size_t item_size, size_t alignment);
RmdName *rmd_intern(RmdContext *ctx, const unsigned char *text, size_t size);
char *rmd_copy_string(RmdContext *ctx, const unsigned char *text, size_t size);
void rmd_fail(RmdContext *ctx, RmdLoc loc, const char *format, ...);
void *rmd_map_get(const RmdMap *map, uintptr_t key);
void rmd_map_set(RmdContext *ctx, RmdMap *map, uintptr_t key, void *value);

/* Input bytes and source descriptors remain live until the context is destroyed. */
bool rmd_read(RmdContext *ctx, RmdSource *source, RmdUnit **result);
/* Read [begin, end) with absolute source locations. Empty ranges are valid.
   Invalid ranges or syntax return false, retain a diagnostic, and set result to null.
   Input bytes and source descriptors remain live until the context is destroyed. */
bool rmd_read_range(RmdContext *ctx, RmdSource *source, size_t begin, size_t end,
                    RmdUnit **result);
/* Read one leading meta block into this host context. Do not read its target bytes.
   Without a block, allocate nothing and return a null unit and the first token offset.
   Publish a host unit only after a complete block. Failure clears result.
   Input bytes and source descriptors remain live until the context is destroyed. */
bool rmd_read_meta(RmdContext *ctx, RmdSource *source, RmdMeta *result);
/* A binding borrows complete resolved facts. The provider must outlive this context. */
bool rmd_bind(RmdContext *ctx, RmdName *name, RmdDecl *declaration);
/* Owned syntax has one expression or statement node per occurrence. */
bool rmd_collect(RmdContext *ctx);
bool rmd_resolve(RmdContext *ctx);
bool rmd_check_body(RmdContext *ctx, RmdDecl *function);
bool rmd_check(RmdContext *ctx);

RmdType *rmd_resolve_type(RmdContext *ctx, RmdTypeSyntax *syntax);
/* Return null and retain a diagnostic if type resolution fails. */
RmdType *rmd_try_resolve_type(RmdContext *ctx, RmdTypeSyntax *syntax);
/* Type queries require the resolved facts produced by resolve or accepted by bind. */
bool rmd_type_equal(const RmdType *a, const RmdType *b);
bool rmd_type_integer(const RmdType *type);
bool rmd_type_signed(const RmdType *type);
bool rmd_type_scalar(const RmdType *type);
unsigned rmd_type_bits(const RmdType *type);
RmdType *rmd_pointer_type(RmdContext *ctx, RmdType *base);
/* Require a resolved storage type. Return null with a diagnostic on failure. */
RmdType *rmd_try_pointer_type(RmdContext *ctx, RmdType *base);

#endif
