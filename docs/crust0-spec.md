<!-- SPDX-License-Identifier: Apache-2.0 -->

# Crust0 language specification

Version 0.1. This specification defines the implemented seed language and
its compiler-library contracts.

Crust0 is the bootstrap language for Crust compiler libraries. This document
defines its syntax, static rules, execution rules, and compiler construction
contract. A conforming implementation must implement these requirements.
Examples do not add rules.

The basic compilation path targets C-level speed through backend handoff.
The root can select more capable checking stages with higher compilation cost.
Such a stage must state its guarantees and cost; it need not meet the basic
profile's speed gate. This choice adds no checking policy to the seed.
The [bootstrap guide](bootstrap.md) gives build and test commands for the
C99 implementation. Section 14 defines the validation and measurement boundaries.

Crust0 is a low-level language with raw memory preconditions. It does not claim
memory safety. Ownership, borrowing, cleanup, and unsafe policy belong to
separate compiled language stages.
The checked ownership stage uses the [explicit trusted-container boundary](ownership-model.md#opaque-storage-and-explicit-trust). Its direct-list client
is checked; its pointer implementation must uphold the declared contracts.
The ownership model must not require whole-program analysis. Function interfaces
and type and field declarations must encode all safety conditions needed across
function boundaries. Check each body against those contracts, with local flow
analysis. The user-facing model must be no more complex than Rust's for both
application and container authors. The [checked ownership overview](design.md#checked-ownership)
defines the acceptance gate. The [ownership stage contract](ownership-model.md)
describes an external implementation based on local ownership facts and
explicit trusted-container interfaces. The [intrusive tutorial](../examples/intrusive/README.md)
uses those rules without container-specific stage logic.
These requirements add no ownership feature to the seed.

## 1 Scope and minimum facilities

The seed has these facilities only:

| Facility | Reason it is present |
|---|---|
| Fixed-width integers and booleans | Tokens, offsets, tags, arithmetic, and decisions |
| Records and fixed arrays | Compiler data, tables, buffers, and explicit layout |
| Raw pointers and field addresses | Graphs, caller-selected storage, and native library access |
| Typed function values | Direct calls, callbacks, and selected compiler stages |
| Declarations and explicit signatures | Direct lookup and independent body checking |
| Blocks, assignment, conditionals, and loops | Ordinary compiler algorithms |
| Foreign calls and layout queries | Allocation, input/output, and backend libraries |

All seed values are copyable. Copying a pointer does not copy its allocation.
There is no implicit allocation, cleanup, reference count, or user code in a
copy operation. All state other than constant data is local or reached through
explicit pointers.

There are no generics, overloads, implicit conversions, methods, inheritance,
closures, exceptions, tagged unions, floating-point types, variable arguments,
implicit compile-time function execution, or built-in module management.
There are no module, import, pub, owner, borrow, defer, unsafe, macro,
quotation, or general stage-definition keywords. The `crust` launcher executes
root actions in source order. Those actions call ordinary functions through
public interfaces and can replace the reader for unread root bytes.

Compiler libraries can define their own trees, types, and intermediate
representations as ordinary Crust0 data. They select a reader, checker, and
backend adapter whose contracts agree. The seed tree is one available
representation; section 12 describes its construction and replacement APIs.

## 2 Target profile

The supported execution profile is Linux x86-64, little endian, with 8-bit bytes
and 64-bit data pointers. It uses the System V AMD64 scalar calling convention.
This is a bounded bootstrap target, not a claim of kernel or full C support.

| Type | Size and alignment in bytes | Value representation |
|---|---:|---|
| `i8`, `u8`, `bool` | 1 | Signed 8-bit, unsigned 8-bit, or boolean |
| `i16`, `u16` | 2 | Signed or unsigned 16-bit |
| `i32`, `u32` | 4 | Signed or unsigned 32-bit |
| `i64`, `u64`, `isize`, `usize` | 8 | Signed or unsigned 64-bit |
| Data pointer or function value | 8 | Native pointer representation |

Signed integers use two's complement. Boolean storage contains 0 for false
or 1 for true. Null data pointers and null function values have all-zero
representations. `usize` and `isize` are distinct types from `u64` and `i64`.

The scalar ABI reference is the AMD64 ABI draft 0.99.6, sections 3.1 and 3.2.
This reference defines the selected scalar boundary.
[Selected AMD64 ABI](https://refspecs.linuxbase.org/elf/x86_64-abi-0.99.pdf)

A different execution profile must define these representations and its ABI
before it accepts a program. It must have a distinct profile identity. A
backend adapter can target another machine without changing the host profile
of the Crust0 compiler program itself.

## 3 Lexical rules

Source is a byte sequence. Syntax uses ASCII. Bytes at least 128 can occur
inside comments and strings and retain their byte values. They are not
identifier characters. A zero byte in source is an error; use an escape in
a string. Source positions use byte offsets and line numbers.

Whitespace consists of space, tab, carriage return, and line feed. A line feed
ends a line. Whitespace does not end a statement. `//` starts a comment that
ends before the next line feed or at end of input. There are no block comments.

An identifier starts with an ASCII letter or `_`. Later characters can also
be decimal digits. Identifiers are case-sensitive. All quoted words in the
grammar, including primitive type names, are reserved. Keywords require an
identifier boundary. Names such as `sizeof_buffer` remain identifiers.

Use longest matching punctuation tokens. In particular, `->`, `==`,
`!=`, `<=`, `>=`, `<<`, `>>`, `&&`, and `||` are single tokens.

A typed integer token has decimal digits, or `0x` followed by hexadecimal
digits, then one integer type suffix. Examples are `12u32`, `0xffu8`, and
`1usize`. Separators and unsuffixed expression integers are not accepted.
An array count is an unsuffixed decimal token in the array type grammar.
Malformed numeric text is an error, not a valid numeric prefix plus a name.

A string starts and ends with `"`. It contains bytes other than `"`, `\\`,
zero, line feed, or carriage return, or one of these escapes:
`\\`, `\"`, `\n`, `\r`, `\t`, `\0`, `\xHH`.
`HH` is exactly two hexadecimal digits. Other escapes and unterminated strings
are errors. The decoded bytes are followed by one additional zero byte.
Embedded zero bytes from escapes are permitted.

## 4 Grammar

The grammar below defines a plain Crust0 unit and the initial root actions.
`crust_read` and `crust_read_range` accept a whole declaration unit. `crust_read_one`
reads one root action and stops at its exact delimiter. It does not tokenize
the following byte. A selected replacement reader determines the grammar of
subsequent input. `meta`, `source`, and `link` are ordinary identifiers.
The [source runner contract](source-runner.md) defines input paths, initial
bindings, phase ownership, execution, and errors.

The grammar uses EBNF. Brackets mean optional text. Braces mean repetition.
Quoted text is a token. `Name`, `Integer`, `Count`, and `String` are lexical
tokens defined above. `EOF` is the end of the source unit.

~~~text
File        = { Declaration } EOF ;
Root        = { RootAction } EOF ;
RootAction  = Declaration | SimpleStatement
            | ( Block | IfStatement | "while" Expr Block ) ";" ;

Declaration = "record" Name "{" Field { Field } "}"
              | "fn" Name Params "->" Type Block
              | "extern" "fn" Name Params "->" Type "=" String ";"
              | "const" Name ":" Type "=" Expr ";" ;
Field       = Name ":" Type ";" ;
Params      = "(" [ Param { "," Param } [ "," ] ] ")" ;
Param       = Name ":" Type ;
Types       = Type { "," Type } [ "," ] ;
Type        = IntegerType | "bool" | "unit" | Name
            | "*" Type | ArrayType
            | "fn" "(" [ Types ] ")" "->" Type ;
ArrayType   = "[" Type ";" Count "]" ;
IntegerType = "i8" | "i16" | "i32" | "i64" | "isize"
            | "u8" | "u16" | "u32" | "u64" | "usize" ;

Block       = "{" { Statement } "}" ;
Statement   = Block
            | IfStatement
            | "while" Expr Block
            | SimpleStatement ;
IfStatement = "if" Expr Block [ "else" ( Block | IfStatement ) ] ;
SimpleStatement = "var" Name ":" Type "=" ( "uninit" | Expr ) ";"
            | "break" ";" | "continue" ";"
            | "return" [ Expr ] ";" | "trap" ";"
            | Expr [ "=" Expr ] ";" ;

Expr        = Or ;
Or          = And { "||" And } ;
And         = BitOr { "&&" BitOr } ;
BitOr       = BitXor { "|" BitXor } ;
BitXor      = BitAnd { "^" BitAnd } ;
BitAnd      = Equal { "&" Equal } ;
Equal       = Compare [ ( "==" | "!=" ) Compare ] ;
Compare     = Shift [ ( "<" | "<=" | ">" | ">=" ) Shift ] ;
Shift       = Add { ( "<<" | ">>" ) Add } ;
Add         = Multiply { ( "+" | "-" ) Multiply } ;
Multiply    = Cast { ( "*" | "/" | "%" ) Cast } ;
Cast        = Unary { "as" Type } ;
Unary       = ( "!" | "~" | "-" | "*" | "&" ) Unary | Postfix ;
Postfix     = Primary {
                "(" [ Arguments ] ")" | "[" Expr "]" | "." Name
              } ;
Arguments   = Expr { "," Expr } [ "," ] ;
Primary     = Name | Integer | String | "true" | "false"
            | "(" Expr ")"
            | "make" Name "{" [ Fields ] "}"
            | "make" ArrayType "{" [ Arguments ] "}"
            | "null" "(" Type ")"
            | "sizeof" "(" Type ")" | "alignof" "(" Type ")"
            | "offsetof" "(" Name "," Name ")" ;
Fields      = FieldInit { "," FieldInit } [ "," ] ;
FieldInit   = Name ":" Expr ;
~~~

Repeated binary operations associate to the left. The productions define
precedence from lowest to highest. Equality and ordered comparisons cannot
chain within their own precedence level. Parentheses can group any expression.

The grammar does not depend on whether an identifier names a type or a value.
`make` separates construction from a following statement block. Assignment is
a statement; its left expression is checked as a place after parsing.

`else if` is another conditional in the `else` branch. Each arm counts toward
the reader's recursion bound. Other branch bodies require braces. The seed
reader and checker each enforce a 256-level traversal budget; nested
expressions and statements share that budget.

## 5 Declarations and names

A seed compilation input is a declaration set and an explicit binding table.
A source file supplies declarations. The driver supplies any bindings to
declarations from other inputs. For a standalone file, that table can be empty.
It is compiler data, not a second source language or a hidden file loader.

One top-level namespace contains records, functions, foreign declarations,
constants, and supplied bindings. Duplicate names are errors. There is no
overloading or declaration merging. Collect all declarations before resolving
their types. Functions can call later functions and recurse. Records can refer
to later records. Bind top-level names before checking a dependent body.

An external binding supplies a declaration identity and its complete type facts.
Record facts include fields and layout. Function facts include the signature
and link identity. Constant facts include the type, value, and storage identity.
Dependencies between these facts must also be supplied. No function body is
needed to check a use. The caller must reject incomplete or conflicting facts
at their input boundary. Internal consumers use the established facts directly.

Record identity is a driver-assigned declaration identity. Distinct record
declarations have distinct identities. Two supplied names can denote the same
record identity. Reusing an identity with conflicting facts is an input error.
The identity must survive independent body checking and must not depend on
worker order or process-local addresses. The driver chooses its representation.
It need not use paths or module names.

The seed has no source search, import syntax, visibility, export list, package
registry, module graph, or interface cache. A module metastage can provide all
of these, including qualified names and rules for import cycles. It resolves
its names to explicit bindings through the public compiler API. It need not
generate combined source text or make the seed scan files again.

Parameters and local variables form lexical scopes. All parameters are visible
at body entry. Each block, `if` branch, and `while` body introduces a scope.
This also applies to user-constructed trees with a non-block branch or loop body.
A local binding becomes visible after its initializer. A parameter
or local name must not duplicate a currently visible local, parameter, top-level
declaration, or supplied binding. Disjoint completed scopes can reuse a local
name. Field names belong only to their record and must be unique within it.

Every parameter, result, variable, constant, and field has an explicit type.
There are no local type declarations, alias declarations, private fields, or
inferred signatures in seed syntax. A module library can select visible names
before it supplies a binding table. Visibility is not an additional seed check.

## 6 Types and data layout

Storage types are integers, `bool`, pointers, function types, records, and
fixed arrays. `unit` is permitted only as a function result. It has no stored
value, address, size, or alignment. Thus `*unit`, unit fields, and unit variables
are errors. Use `*u8` for an erased data address.

Array counts must be positive decimal literals. An array has exactly that many
elements. Its alignment is the element alignment; its stride is the element
size. Its size is count times stride. There are no zero-size types or arrays.
Reject any storage type whose size exceeds the maximum `isize` value. Compute
layout with checked mathematical integers; layout overflow is a static error.

A record is nominal: different declarations define different types. Fields
have declaration order. Place each field at the next offset that satisfies
its alignment. Record alignment is the largest field alignment. Round the end
of the final field up to that alignment to obtain record size. Empty records,
by-value layout cycles, and sizes greater than `isize` maximum are errors.
Pointer recursion does not require the pointee's layout to be complete.

Array, pointer, and function types are equal when their corresponding component
types and array counts are equal. Recursive type comparison follows nominal
record identities; it does not repeatedly expand record definitions.

Record and array values can be constructed, stored, and copied. Their copies
copy field or element values. Padding has no value and is not implicitly zeroed.
There is no generated aggregate equality. There are no implicit array-to-pointer
or record-to-pointer conversions.

Function parameters and results are scalar in this version. A scalar is an
integer, boolean, data pointer, or function value. A result can also be `unit`.
Pass aggregates through explicit pointers. This restriction applies to all
functions and function types. It avoids both a C aggregate ABI classifier and
a second seed calling convention. Richer frontends can define aggregate calls
in their own IR and adapter.

## 7 Expressions and constants

Every expression has one exact type. Operators accept only the categories
defined here. There is no promotion, conversion search, or body-dependent
type inference. A function call requires the declared number and exact types
of arguments. Its result has the declared result type. A name in a type position
must name a record. A name in a value position must name a local, parameter,
constant, or function. A record name is not a value.

`make R { ... }` requires a record type and each field exactly once. It permits
any written field order. Each value must have that field's exact type.
`make [T; N] { ... }` requires exactly N expressions of type T.
No field or element is initialized implicitly.

An integer token has its suffix type and must fit that type. For direct unary
minus on a signed integer token, apply the sign before range checking.
Thus `-128i8` is valid; `128i8` and `-(128i8)` are errors. Other unary minus
operations use the ordinary arithmetic rule.

A string has type `*u8`. It points to the first byte of static read-only storage
containing the decoded bytes and final zero. The pointer is never null, even
for an empty string. The storage lasts for the program. Identical literal
storage may be merged; programs must not require distinct literal addresses.

`null(T)` requires a data pointer or function type and produces its null value.
It does not allocate storage. `sizeof(T)` and `alignof(T)` return `usize` target
facts for a storage type. `offsetof(R, f)` returns the byte offset of a declared
record field as `usize`. These operations have no operand evaluation or runtime
reflection.

### Integer and boolean operations

Except for pointer offsets below, binary arithmetic, bitwise operations, shifts,
and integer comparisons require the same integer type on both operands.

| Operation | Meaning |
|---|---|
| `+`, `-`, `*`, unary `-` | Result modulo 2 raised to the type's bit width |
| `/` | Integer quotient; signed division truncates toward zero |
| `%` | Remainder with the dividend's sign, or zero |
| Invalid `/` or `%` | Zero divisor or signed minimum with divisor minus one traps |
| `<<` | Shift left, discarding bits outside the width |
| `>>` | Arithmetic shift for signed types; logical shift for unsigned types |
| Invalid shift | Negative count or count at least the width traps |
| `&`, `|`, `^`, `~` | Bit operations on the fixed-width representation |
| `<`, `<=`, `>`, `>=` | Integer comparison using the declared signedness |
| `==`, `!=` | Equality for matching integer, boolean, pointer, or function types |
| `!`, `&&`, `||` | Boolean operations; operands must be `bool` |

The remainder satisfies `a = q * b + r` for the mathematical quotient q.
Booleans have no arithmetic operations and are not truthy integers. Pointer
equality compares addresses; function equality compares callable identities,
with null equal only to null. There is no ordered pointer comparison.

### Casts and pointer offsets

`as` permits only these cases:

- Integer to integer: reduce the mathematical source value modulo 2 raised
  to the target bit width, then interpret the target signedness.
- `bool` to integer: produce 0 or 1. Integer to `bool`: compare with zero.
- Data pointer to data pointer: preserve the address and allocation origin.
  This conversion itself does not read memory or establish alignment.
- Data pointer to `usize`, or `usize` to data pointer: use the representation
  and origin rules in section 8.
- A scalar value to its own type: preserve the value.

There is no data-pointer/function-value conversion or conversion between
different function types. There is no aggregate cast.

For a data pointer `p: *T`, `p + n` and `p - n` require `n: isize` and advance
or retreat by `n * sizeof(T)` bytes. The calculation uses mathematical integers;
it must not wrap an address or leave its allocation, except for one-past.
Null plus or minus zero is null. Other offsets from null violate the raw
memory contract. Pointer-pointer subtraction is not an operation.

### Constants

A `const` declares immutable static storage of its stated type. The initializer
is restricted to typed integer literals, direct negative integer literals,
booleans, strings, null, layout queries, function names, and record or array
construction from these forms. Parentheses can group these forms.
Every initializer must have the exact declared type.

Reading another constant, arithmetic, casts, calls, pointer dereferences, and
conditional evaluation are not constant initializers in Crust0. A generator can
produce literal tables before the reader runs. This avoids a general constant
execution engine in the seed. Layout queries depend only on the type graph.
Function names produce symbol references without executing their bodies.

Constants need no dynamic initialization order. All constant storage is ready
at program entry. Its scalar fields and padding follow section 6; static
storage does not promise zero-valued padding.

## 8 Storage and raw memory

A storage allocation is a live byte extent with a base address, size, alignment,
and read or write permissions. Its identity ends when its lifetime ends.
Reusing its address creates a different allocation. These are semantic facts;
Crust0 does not require a runtime allocation registry or pointer metadata.

Each local variable and parameter has its own storage, live until its block
or function exits. A loop's block creates new local lifetimes on each entry.
Assignments change values without moving that storage. Static constants and
strings remain live for the program. Allocation through a library follows that
library's explicit lifetime contract. No pointer automatically extends a lifetime.

`var x: T = value;` evaluates the initializer before x becomes visible and
stores its value. `var x: T = uninit;` reserves storage without initializing
it. Address-taking and stores can initialize that storage. Reads require
initialized values. The seed does not promise to prove raw initialization or
alias preconditions. It must not insert mandatory zeroing to avoid them.

A place is a local or parameter, a constant, a pointer dereference, a field
of a record place, an element of an array place, or a pointer index.
Parentheses preserve place status. A field or array element of a temporary
value can be read but has no addressable place. Function names are values,
not data places. There is no implicit dereference on field selection.
Field selection requires a record and an existing field. Indexing requires
an array or data pointer. Dereference requires a data pointer; address-taking
requires a place. Computing a place does not read its stored value. A place
used as a value reads only the selected field or element, not its whole record.

`&place` returns a pointer to its storage without reading its value. It retains
the whole allocation's origin, including for a field. `*p` denotes the T place
at a pointer `p: *T`. Forming a dereference or pointer-index place requires live,
aligned storage for the complete T, even when used only to take its address.
It does not require the stored value to be initialized. Thus `&*null(*u8)`
violates the raw contract. Array indexing requires `usize` and an index below the
array count. Pointer indexing requires `usize` and denotes the corresponding
T place within the allocation. Index address calculations must not wrap.

Every raw load or store requires all of the following:

1. The original allocation is live, and the complete access is inside it.
2. The address meets the accessed type's alignment.
3. A read sees initialized value fields or scalar bytes that represent a value
   of that type. Aggregate padding need not be initialized.
4. A write has permission to modify those bytes.
5. Concurrent accesses obey the synchronization contract; conflicting ordinary
   accesses with at least one write must not race.

One-past pointers can be formed but not dereferenced. A field pointer can be
converted to `*u8` and offset within its whole allocation. This permits recovery
of an enclosing record with `offsetof`, subject to alignment and valid storage.
The pointer's type alone promises neither exclusivity nor a distinct alias class.

Integer casts preserve the pointer's numeric representation and original
allocation identity as a validity condition. Converting zero produces null.
A nonzero `usize` can become a valid pointer only by restoring a representation
derived from a pointer to the same still-live allocation. This permits removing
temporary tag bits before conversion back. It does not permit a file-supplied
integer to authorize memory access or restore a freed allocation after reuse.
Foreign interfaces can explicitly establish additional pointer origins.

All bit patterns represent integer values. Boolean values require 0 or 1.
Pointers and function values require a representation established by the
operations or foreign contracts in this specification. Native function calls
require a non-null function value with the exact signature and ABI.

Aggregate reads require all value fields to be initialized. Aggregate assignment
evaluates the complete source value before modifying the destination. Overlap
must have this value-copy behavior. It does not promise a particular padding
value. Typed reads and writes use representation rules, not C effective-type
alias restrictions. No optimizer may infer `noalias` or incompatible alias
classes from `*T` alone.

The host byte-move operation can copy padding and uninitialized bytes without
interpreting them. It transfers initialization state: initialized source bytes
initialize destination bytes; uninitialized source bytes remain uninitialized
at the destination. Moving a valid pointer representation preserves its origin
contract.
Observing uninitialized or padding bytes as ordinary integer values is outside
the raw contract. Use explicit encoding before sending records as external data.

Direct assignment to a constant or one of its fields is a static error.
Writes through an alias to constant or string storage violate write permission.
There is no deep immutability claim for an allocation reached through a pointer
stored in a constant.

A raw contract violation has no defined execution result. A compiler is not
required to find it or add runtime checks. This is the exact safety boundary
of Crust0. The specified arithmetic traps remain defined behavior. Build options
cannot change valid-program meaning or remove those required traps.

## 9 Evaluation and control flow

Evaluate operands from left to right. For a call, evaluate the callee, then
each argument, then call the selected function. Each operand is evaluated
exactly once. Record initializers use written field order; array initializers
use element order. `&&` evaluates its right operand only if its left is true.
`||` evaluates its right operand only if its left is false.

For assignment, first evaluate the destination place, then the source value,
then store that value. Their types must be identical. The destination must
remain live and writable through the store. An expression statement evaluates
its expression and discards the result. A `unit` call has no stored result.

An `if` or `while` condition must have type `bool`. `if` executes only the
selected block. `while` tests before each iteration. `break` exits the nearest
loop; `continue` begins its next condition test. Either statement outside a
loop is an error. There are no labels, jumps, or implicit cleanup actions.

`return value;` requires the function's non-unit result type. Evaluate the
value before local storage dies. `return;` is valid only for a `unit` result.
Falling out of a unit function returns normally.

A non-unit function must not have a structural path to the end of its body.
For this check, `return`, `trap`, `break`, and `continue` do not fall through
to the next statement. A block falls through if its statement sequence can
reach the end. An `if` falls through if either branch does; a missing `else`
falls through. Every `while` is treated as able
to fall through, even with a literal true condition. This rule needs no loop
proof or constant execution. Unreachable statements still require static checks.

`trap;` and a required arithmetic trap end the process abnormally. They do not
run cleanup or return a value. Recovery, exception unwinding, and nonlocal jumps
across Crust0 frames are outside the execution contract. Resource exhaustion must
produce an explicit failure; it must not report a successful partial result.

## 10 Functions and foreign calls

Parameters are mutable local copies of the argument values. A function name
has its declared function type and denotes its callable value. There is no
implicit context pointer. Direct recursion and mutual recursion are permitted.
All declared bodies require checking, including bodies without a caller.

Defined functions and foreign functions use the same scalar native ABI.
The initial profile uses these C boundary types:

| Crust0 type | Native C boundary type |
|---|---|
| `bool` | `_Bool` |
| `i8`, `u8` | `signed char`, `unsigned char` |
| `i16`, `u16` | `short`, `unsigned short` |
| `i32`, `u32` | `int`, `unsigned int` |
| `i64`, `u64` | `long`, `unsigned long` in the selected LP64 profile |
| `isize`, `usize` | Pointer-sized signed or unsigned integer |
| `*T` | Native data pointer |
| Function value | Native function pointer with the mapped signature |
| `unit` result | `void` result |

Apply the ABI's argument and result rules, including rules for narrow integers
and booleans. Equal storage width alone does not establish ABI compatibility.
A function value can be passed to a native callback parameter when its complete
mapped signature matches. The caller must preserve callback code and any
separate context storage for every permitted call.

An `extern fn` has no body. Its string names an exact native symbol. The decoded
name must be nonempty ASCII with no embedded zero. It has the declared scalar
signature. The foreign implementation must obey the same ABI and the declared
memory contract. A declaration cannot make a mismatched native function safe.
Variable arguments and aggregate or floating-point calls need an ordinary
native bridge or another frontend's ABI adapter.

The driver assigns a native link identity to each defined function and static
data object that crosses a compilation boundary. This mapping is public compiler
data. References to the same declaration use the same identity. Distinct live
definitions must not share one identity. Repeated references to a native symbol
must agree on its mapped ABI type. Reject conflicting definitions and unresolved
references when making an executable. The seed prescribes no module-based
mangling scheme. A module library can assign link names without changing syntax.

For a hosted executable, the driver selects an entry function with type
`fn(i32, **u8) -> i32`. Its arguments are a nonnegative argument count and
an array of that many readable, zero-terminated strings followed by a null
pointer. This storage remains live for the call. The result is passed to the
host process exit mechanism. A library build need not select an entry function.

## 11 Bootstrap host library

Allocation and input/output are ordinary foreign functions. They are not seed
operations or special names. A bootstrap implementation supplies the following
small library and its source. A caller includes these declarations or receives
equivalent explicit bindings from its driver.

~~~text
extern fn host_alloc(size: usize, alignment: usize) -> *u8 = "crust0_host_alloc";
extern fn host_free(data: *u8) -> unit = "crust0_host_free";
extern fn host_move_bytes(dst: *u8, src: *u8, size: usize) -> unit = "crust0_host_move_bytes";
extern fn host_read_file(path: *u8, data: **u8, size: *usize) -> i32 = "crust0_host_read_file";
extern fn host_write_file(path: *u8, data: *u8, size: usize) -> i32 = "crust0_host_write_file";
extern fn host_write_stream(stream: u32, data: *u8, size: usize) -> i32 = "crust0_host_write_stream";
~~~

The contracts are as follows:

- `host_alloc` requires a size at most the `isize` maximum and a positive
  power-of-two alignment. Zero size returns null and allocates nothing.
  A non-null result is a fresh readable and writable allocation of the requested
  size and alignment, with uninitialized bytes. Failure, including an unsupported
  alignment, returns null. Live allocations do not overlap.
- `host_free` accepts null as a no-op. Otherwise, its argument must be the
  original base of a live allocation from this library. It ends that allocation's
  lifetime exactly once. No access can overlap its release.
- `host_move_bytes` copies the requested byte extent as if through temporary
  storage. Source and destination can overlap. The operation preserves pointer
  origins and copies initialization state as specified in section 8. A zero
  extent permits null pointers. A nonzero extent requires live readable source
  storage and live writable destination storage, but no value interpretation.
- File paths must be readable zero-terminated strings. `host_read_file` requires
  distinct writable output slots that do not overlap the path. It reads bytes
  until end of file and returns 0 on success. It stores an allocated buffer and
  its length. The live buffer is readable and writable, has alignment at least
  1, and contains the initialized file bytes. The caller releases that buffer
  with `host_free`. Empty input produces null and length zero. Failure returns
  a nonzero status, sets both outputs to zero, and retains no allocation.
  No trailing zero is added to file contents. A file that changes during the
  read is not an atomic snapshot.
- `host_write_file` creates or truncates its destination and writes the supplied
  bytes. `host_write_stream` writes to stream 1 for standard output or 2 for
  standard error. Other stream values return a nonzero status. Both return 0
  only after all requested bytes have been written. Failure can leave a written
  prefix. The source bytes must be initialized and readable; zero length permits
  a null data pointer. There is no implicit terminator or atomic replacement.

Input/output failure statuses are opaque nonzero values. No result requires
reading hidden global error state. Allocation inside `host_read_file` follows
the same size limit; an input that exceeds it returns failure.

Threads, locks, processes, clocks, and dynamic loading can be additional native
libraries. They require no new seed syntax. Their memory and synchronization
contracts must be explicit. Crust0 does not infer thread safety from raw pointers.

## 12 Compiler construction and metastages

A metastage is an ordinary program or function used to construct or run a
compiler. It uses the same calls, data, and memory operations as other programs.
The source runner executes checked Crust0 trees and can call prepared native
libraries. It adds no phase macro system or automatic execution of function
bodies during type resolution.

In the source-defined compilation model, the user program selects its stages.
Each custom stage is an ordinary function defined in the user source or supplied
by an external library. The compiler must not recognize a particular backend's
name, path, or implementation. A standalone
driver can prepare and execute those calls, but it does not replace the
requirement that the override be in the user source. The preparation order
and runner operations below define when a selected stage takes effect.

### Source-order root execution

The command is `crust ROOT [ARGUMENT...]`. Capture the root bytes once. Supply
the public root state through the initial `run: *CrustRun` binding. Its arguments
exclude the executable and root path. The installed prelude supplies ordinary
host loading helpers and version-matched public compiler declarations.

Read, check, and execute each complete action before reading the next one.
Capture its reader, executor, and user state pointer together. Pass that state
pointer to both callbacks. Updates select operations and state for the next
action. A successful non-EOF read must advance within the source. Commit that
end before execution. The action can
consume more input, but cannot rewind the cursor. A new reader owns every byte
after the consumed delimiter, including whitespace and comments. EOF must
account for all remaining bytes under that reader's rules.

Root variables retain their storage. Streamed declarations can use earlier
declarations; a function can also refer to itself. Check its body when its
declaration executes. Functions cannot capture root locals. A separately
loaded whole unit retains ordinary forward references and mutual recursion.
Neither checking route rescans all earlier root actions.

A root `return` requires an `i32` result in 0 through 255 and ends the stream.
EOF ends execution with the current status, which starts at zero. No implicit
target compilation or finalization occurs. Later errors do not undo earlier
effects. Retrying or replaying an action is not part of this contract.

The initial root grammar requires a final semicolon after `if`, `while`, and
bare blocks. Function and record declarations end at their closing brace.
Other statements have their ordinary semicolon. Nested blocks and function
bodies are parsed as part of their enclosing action; reader changes cannot
change the meaning of bytes already parsed in that action.

The [runner contract](source-runner.md) defines replaceable operation types,
source identities, native binding, storage lifetime, and callback failure.
The whole-unit grammar remains available through `crust0` and the public reader.

### Public construction interface

An implementation must publish its driver and compiler libraries with source
definitions for their input and output data, constructors, edits, and operation
preconditions. A user must be able to construct valid input for a consumer
without first calling the producer that the user replaces. Opaque handles with
observation callbacks do not meet this requirement.

The public operations must support these boundaries:

| Operation | Required contract |
|---|---|
| Read | Source bytes and diagnostic identity to seed syntax; no declaration lookup |
| Collect | Parsed declarations to names, declared types, constant forms, and bodies |
| Resolve | Declarations, explicit bindings, and target profile to complete type, layout, and signature facts |
| Check | One body and complete required declaration facts to a typed body or diagnostics |
| Lower | Checked seed operations to explicit computation, storage, calls, and control flow with the same meaning |
| Adapt backend input | Operations and target configuration to complete valid input for the selected backend |
| Emit | Backend input and options to output or a stated failure |

These are semantic boundaries, not a mandatory sequence of serialized files
or separate tree copies. Operations can share traversals and storage. The
library must still expose the operations needed to replace a boundary. It must
not require a dynamic dispatch for each node or a universal pass manager.

Each package version publishes concrete Crust0 declarations for its API. This
specification does not fix their in-memory struct layout as a permanent binary
ABI. A caller builds against that package's version. User libraries can use
their own syntax trees, type systems, and IR, then construct the input of the
next selected consumer. There is no mandatory universal language IR.

The public syntax nodes accept context-owned extension kinds. A stage reserves
disjoint ranges with `crust_allocate_kinds` and retains the returned base.
The seed enum end markers delimit the built-in ranges. A stage lowers its
extension nodes before seed checking. Unlowered type, expression, and statement
kinds produce diagnostics. Copying syntax between contexts requires a mapping
for extension kinds. See the [construction API](bootstrap.md) for the C contract.

The Crust reader library accepts root-owned, ordered hook chains. First handled
syntax wins; an unhandled hook preserves input; a diagnostic stops dispatch.
Source passes can select `CsHooks` providers for source types, traversal, and
contracts. Each provider owns its rules and uses consumer queries for child
nodes. The root calls passes in dependency order. These are external library
interfaces; their [contract](../stages/source/README.md) and
[composition example](../examples/composition/README.md) define their use.

The source runner checks a native library's generated public API digest at
load time. Missing and different digests are errors. The library must carry
its own marker. The [runner contract](source-runner.md#files-and-native-inputs)
defines the marker and build requirements.

Source parsers and artifact loaders validate their input formats. Foreign calls
obey their declared ABI and memory contracts. Internal operations consume facts
established by their producers.
An impossible internal state is a compiler defect, not a new recoverable user
error at every handoff. Allocation, input/output, invalid source, and unsupported
target requests can produce explicit failures.

### Module management is a metastage

The seed's binding table is the connection to module libraries. Such a library
can select source files, define `module` or `import` syntax, control visibility,
construct interfaces, choose link names, and schedule dependent compilation.
Package lookup, generated imports, conditional source selection, and caching
are also library policy. None is a privileged compiler service.

A module library must supply complete and consistent declaration facts before
the dependent check starts. It can support cycles by collecting the required
signatures first, or reject cycles under its own published rules. By-value
record cycles remain a seed layout error. A module library must not need to
inspect function bodies to determine a seed function's declared signature.

A minimal driver can take an explicit source list, parse each file once, and
combine its declarations in one flat namespace. Another driver can keep many
binding environments and compile separate units. These are driver choices.
The seed does not require a package resolver or a module cache to bootstrap.

### Preparation and execution

The driver must establish this order where dependencies require it:

1. Prepare the driver and its stage libraries with an earlier available compiler
   configuration. Stage preparation includes all code and native dependencies
   needed to run the stage. No stage can require its own unavailable output to
   prepare itself. Ordinary function recursion is not a preparation cycle.
2. Select a prepared reader, target profile, and options before reading the
   source that uses them. A reader can replace all base syntax. It need not parse
   a seed-language preamble to discover how to parse the rest of the file.
3. Capture the actual input bytes used by each operation. If a result is cached,
   identify those bytes, not a different version read before or after execution.
4. Complete generation and name binding before publishing facts to dependent
   checks. A generator can introduce declarations or dependencies before that
   publication. It cannot silently change an interface already in use.
5. Run the selected language checks while the facts they require still exist.
   Preserve their meaning when lowering or declare a different language policy.
6. Construct complete backend input. Record the frontend handoff here, then
   perform the selected backend optimization, emission, and linking.

A new driver can be an ordinary executable linked to compiler libraries.
Dynamic plugins, a resident compiler server, a JIT, and persistent caches are
not required by the library construction contract. The source runner executes
checked root actions directly and uses libffi for native calls and callbacks.
Root execution includes no hidden assembly or native linking step.
Stage self-compilation uses the previous compiler configuration to build the
next generation of Crust stage libraries and drivers. The C99 seed remains
available; it is not translated to Crust0. No generation requires its own
unavailable output.

Root startup is explicit: execute a small setup prefix with the
seed, prepare the selected backend through an available compiler configuration,
then install the stage that executes subsequent compilation code. A backend
can compile its next generation after its first usable generation exists.
Bootstrap and execution selection belong to ordinary Crust stages. Keeping
the seed evaluator small takes priority over optimizing it for sustained
execution of compiler libraries.

Native library loading does not itself replace action execution. Select the
reader, executor, and user state through the public runner fields. The action
which selects them completes under the previously captured operations; the
new operations receive the next unread action. Completed effects are not
replayed. Earlier storage and published callables retain their lifetime and
identity contracts. A selected execution stage chooses compilation units
under the source-order and unread-input rules above.

The [native stage](../stages/native/README.md) implements one such policy without
a C99 core change. It compiles complete functions and passes earlier storage
and callable values through explicit user state. These library unit rules do
not change the seed grammar or require all execution stages to use functions
as their action payload.

Host execution and target description are separate. `sizeof` in a running
stage describes that stage program's execution profile. A cross-compiler gets
target layout from its target description. It must not serialize a host address
as a target pointer or use host layout as an unstated target assumption.

### Language checks and backend adapters

Ownership, loan checking, resource cleanup, and unsafe syntax belong to
compiled language libraries. They can introduce richer source rules and
representations. Check those rules before lowering discards their information.
Generated code has the same obligations as written code under the selected
language policy. Making a pointer operation in a generator does not prove it safe.

A checked language's safety claim trusts its checker, transformations, backend,
and foreign contracts.
A replacement that weakens them must not retain that safety claim without
establishing the same properties. A small seed does not make the whole trusted
implementation small.

The [ASM stage](../stages/asm/README.md) emits x86-64 assembly. The
[C stage](c-backend.md) emits C and native-symbol arguments for GCC and
`objcopy`. Both are Crust libraries selected by the compilation program.
Their APIs expose storage preparation, target lowering, output buffers, and
failure reporting. The C backend also accepts a function-body emitter callback.
A custom adapter must construct the complete input required by its chosen
backend and preserve the source language's ABI and execution rules.

Backend semantic claims must follow actual language facts. For example, raw
seed pointers do not justify exclusive-access metadata, and wrapping arithmetic
does not justify signed-overflow assumptions. An IR verifier cannot prove these
source-level claims. Required trap behavior must survive lowering.

### Parallel work and optional reuse

The required facts determine scheduling. Independent sources can be read in
parallel. Declaration signatures and layouts can be resolved when their required
type facts are ready. Bodies can be checked when their binding environments are
complete. Independent checked bodies can be lowered in parallel when the chosen
backend API permits it. These dependencies do not require global phase barriers.

Published interfaces must remain stable and live for their readers. Each mutable
work product has one writer or explicit synchronization. An edit that changes
a required fact invalidates results that used the old fact. A transformation
may retain a result only when its contract preserves that result. These are
compiler-library contracts, not a seed-level ownership algorithm.

The root cursor has a serial dependency because an action can change its next
reader. This does not prevent independent target work. A submitted job retains
its selected operations, input snapshots, and required facts. Complete all work
and callback use before releasing that state. One host evaluator requires
exclusive access from one thread, but permits synchronous callback reentry.

Worker completion order must not change accepted programs, nominal identities,
or diagnostic ordering. Order diagnostics by the driver's stable source order,
source position, and diagnostic category. A module library chooses its source
order before scheduling. Backend contexts must obey the backend's own threading
contract. One-worker execution remains a required performance case.

The optional [native job library](../stages/parallel/README.md) runs independent
jobs and joins its workers before returning. The calling Crust program selects
dependencies, immutable inputs, and diagnostic order. Its
[module graph driver](../benchmarks/parallel/README.md) checks these contracts
with consumers that borrow checked provider declarations. It adds no scheduler
to the seed.

No cache is needed for correctness or the first speed result. A persistent
cache must account for stage and helper code, representations, source and binding
facts, target settings, options, and every external input that can affect output.
Optional file lookups must record absence as well as presence. Producers use
the captured input bytes. Root effects run on every invocation. Artifact reuse
must validate the stored bytes before loading them.
Treat a compiled backend as a toolchain input to the application speed gate.
Measure backend construction and automatic cache validation separately. A
request that builds a changed project stage still includes that work in its
stated endpoint. The optional
[artifact cache](../stages/cache/README.md) reuses complete files from explicit
input snapshots and a user build function. It does not store compiler contexts
or replay root effects. The root loads the selected artifact and installs its
operations explicitly.

## 13 Complete seed examples

This program creates and removes a directly linked stack node. The driver
selects `main` as its hosted entry. Only the output function is external.
Build the tools with `make all c-stage` from the repository root, then save the
following source as `build/seed-list.crs`.

~~~text
extern fn write_stream(stream: u32, data: *u8, size: usize) -> i32 = "crust0_host_write_stream";

record Hook {
    prev: *Hook;
    next: *Hook;
}

fn init(h: *Hook) -> unit {
    (*h).prev = h;
    (*h).next = h;
}

fn unlink(h: *Hook) -> unit {
    var p: *Hook = (*h).prev;
    var n: *Hook = (*h).next;
    (*p).next = n;
    (*n).prev = p;
    init(h);
}

fn main(argc: i32, argv: **u8) -> i32 {
    var head: Hook = uninit;
    var node: Hook = uninit;
    init(&head);
    init(&node);
    node.prev = &head;
    node.next = &head;
    head.next = &node;
    head.prev = &node;
    unlink(&node);
    if head.next != &head || head.prev != &head {
        return 1i32;
    }
    if write_stream(1u32, "ok\n", 3usize) != 0i32 {
        return 2i32;
    }
    return 0i32;
}
~~~

Compile and run it with:

```sh
build/crust0 -o build/seed-list.s build/seed-list.crs
gcc -no-pie build/seed-list.s build/libcrust0_host.a -o build/seed-list
build/seed-list
```

The output is `ok` and a newline. Both nodes remain live through every access.
This raw program relies on the
memory preconditions in section 8. For checked client lifetimes, individual
node destruction, and storage reuse, use the
[intrusive tutorial](../examples/intrusive/README.md). Its root selects the
ownership stage and an explicitly trusted provider that unlinks before release.

This second source uses constant tables, record values, and a function value.
Save it as `build/seed-values.crs`. The entry checks that `apply()` returns
`18u32`.

~~~text
record Pair {
    first: u32;
    second: u32;
}

const widths: [u32; 3] = make [u32; 3] { 8u32, 16u32, 32u32 };

fn plus_one(value: u32) -> u32 {
    return value + 1u32;
}

fn apply() -> u32 {
    var f: fn(u32) -> u32 = plus_one;
    var pair: Pair = make Pair { second: widths[1usize], first: 1u32 };
    return f(pair.first + pair.second);
}

fn main(argc: i32, argv: **u8) -> i32 {
    if apply() != 18u32 { return 1i32; }
    return 0i32;
}
~~~

```sh
build/crust-c -o build/seed-values build/seed-values.crs
build/seed-values
```

The program returns zero and prints no text.

## 14 Conformance and performance gates

A conforming implementation rejects invalid tokens, grammar, binding kinds,
duplicate names, invalid type graphs, type mismatches, invalid place uses,
invalid constant forms, and missing returns. Diagnostics identify the input
and source position when one exists. A stated implementation resource limit
must fail explicitly; it must not omit a check or accept partial output.

The repository implements seed syntax, execution, and root control. Both
backends compile their own next generations. The optional
[ownership stage](ownership-model.md) checks each function from finite local
state and declared interfaces. It checks resource moves, integer and pointer
handles, stored loans, returned origins, cleanup, and domain access. The
[intrusive tutorial](../examples/intrusive/README.md) uses a trusted opaque
provider and checked client. Provider correctness includes internal retention
and retirement. The [owning tree](../examples/ownership-graphs/README.md) and
[one-way index](../examples/ownership-index/README.md) use the same rules.
Independent imports preserve selected trust. Ownership state erases before
emission.

Validation covers these contracts:

| Case | Required observation |
|---|---|
| Grammar | Accepted and rejected forms agree with section 4 without name-dependent parsing |
| Integer boundaries | Literal limits, wrapping, casts, division, remainder, and shifts obey section 7 |
| Storage | Layout, padding, field addresses, overlapping copies, initialization transfer, and live pointer round trips obey section 8 |
| Native boundary | All scalar widths, booleans, indirect calls, and native callbacks agree with the selected ABI |
| Explicit bindings | Independent bodies use the same declared facts; absent or conflicting facts fail at the input boundary |
| Module replacement | A library supplies discovery, visibility, and dependency policy without a core module resolver |
| Public construction | A user driver replaces a reader and one backend lowering through published APIs |
| Stage self-compilation | Build the Crust backend and driver through the C99 seed, then through two successive generations of their own output, with caches disabled. Compare generated code and native names. Use the final generation to build and run the direct-list program |

Ownership configurations additionally check client lifetime errors, provider
selection, independent imports, and erasure. Resource configurations check
cleanup, native handles, and borrowed SQLite results. Each selected stage
requires its own correctness checks and cost measurements.

There are two frontend measurement endpoints:

- **Check:** source input through name binding, interface construction, type
  checking, and all selected language checks. Compare with the fastest eligible
  GCC or Clang syntax-check configuration on equivalent inputs.
- **Handoff:** all check work plus lowering and construction of complete backend
  input. For the C stage, include C and symbol text serialization. Compare with
  Clang frontend IR emission with LLVM passes disabled, including serialization.

The main application gate starts with a compiled backend, a fresh process, and
no saved application result. Include root execution, installed interface checks,
native library loading, target work, and cleanup. Exclude final target GCC
compilation and linking. Measure backend bootstrap and automatic cache validation
separately. A changed project stage requires a separate configuration that
includes its preparation cost.

For a configuration that claims C-level speed, use at least 20 randomized paired
samples against the fastest eligible C baseline. Require a median candidate/C ratio
at most 1.00 and a 95% bootstrap confidence upper bound at most 1.00. Apply this
rule to one-worker builds as well as matched parallel builds. Application
result reuse or more workers cannot excuse failure in the one-worker case
with the same compiled backend. Record exact commands, build flags, source and
tool hashes, CPU selection, worker count, cache conditions, raw paired samples,
and confidence intervals. Check equivalent final program behavior outside the
timed interval. Keep reports in ignored build storage. The
[source-runner guide](source-runner.md#compiled-backend-application-gate) gives
the command for this gate. The [benchmark guide](../benchmarks/README.md)
identifies each executable workload and its comparison boundary.

A failed correctness case blocks expansion. Identify the operation responsible,
change it, and repeat that witness before adding another dependent layer. A
slower optional checking stage can proceed when its capability and cost are
explicit. If measurement cannot establish the speed gate, do not call that
configuration C-level. The seed and each checked configuration have separate
cost claims. Unsupported checks and exhausted checker limits are diagnostics,
not permission to emit unchecked code under the same safety claim.

Runtime costs also require evidence. Compare selected abstractions with C that
performs the same operations and required checks. No feature can require unused
runtime metadata, registration, allocation, or indirect calls. Do not claim that
the optimizer removes a cost without inspecting the emitted result.

## 15 Implementation map

The C99 seed supplies the reader, checker, evaluator, and root runner. Its
public declarations are in `include/`; generated Crust bindings are in `api/`.
Build the seed with `make build/crust`. Its evaluator can run backend source
to construct a first native generation. `make all c-stage` builds the ASM and
C backends. Their next generations compile through their own output.

Module management, ownership, cleanup, overloads, highlighting, cache policy,
and native execution are libraries under `stages/`. Their tutorials specify
prerequisites, selection calls, and build commands. Roots under `examples/`
select those libraries through ordinary calls.

Resource checking retains cleanup plans outside the lowered tree. Composed
stages consume source contracts and those plans before emission. The ownership
stage checks local storage and function interfaces. Root-selected trusted
providers supply opaque representation operations under explicit contracts.
See the [ownership contract](ownership-model.md) for accepted operations.

Ownership facts erase before backend optimization. Owners and views retain
their ordinary value and pointer representations. Cleanup emits the declared
calls. Ownership adds no runtime validity checks, identity metadata, pointer
tags, reference counts, or hidden cleanup flags. Null checks before release
and debug-only bounds checks are permitted;
debug-only checks provide no release-build bounds guarantee.
