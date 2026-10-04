#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check resource source programs, generated output, and ownership diagnostics."""

import argparse
import fnmatch
import re
import resource
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = """
extern fn putchar(code:i32)->i32="putchar";
resource Token { id:i32; } drop drop_token;
fn emit(code:i32)->unit { unsafe { putchar(code); } }
fn token(code:i32)->Token { unsafe { return make Token { id:code }; } }
fn drop_token(value:mut Token)->unit { unsafe { putchar(value.id); } }
"""


def program(body, declarations="", common=True):
    return (
        (COMMON if common else "")
        + declarations
        + "\nfn main(argc:i32,argv:**u8)->i32 {\n"
        + body
        + "\nreturn 0i32;\n}\n"
    )


def wide_record_source(count=512):
    fields = "".join(f"field{index}:i32;" for index in range(count))
    values = ",".join(f"field{index}:{index}i32" for index in reversed(range(count)))
    checks = "".join(
        f"if value.field{index}!={index}i32 {{return 1i32;}}" for index in range(count)
    )
    return program(
        f"var value:Wide=make Wide {{{values}}};{checks}",
        f"record Wide {{{fields}}}",
        common=False,
    )


def cleanup_tree_source(depth):
    records = "".join(
        f"record Tree{level} {{first:Tree{level - 1}; last:Tree{level - 1};}}\n"
        for level in range(1, depth + 1)
    )
    return (
        "resource Tree0 {value:i32;} drop drop_leaf;\n"
        "fn drop_leaf(value:mut Tree0)->unit {}\n"
        + records
        + f"fn consume(value:Tree{depth})->unit {{}}\n"
    )


def runtime_cases():
    return [
        (
            "end-local-borrow",
            program(
                "var value:Token=token(65i32);var view:mut Token=mut value;"
                "var child:read Token=read view;drop child;drop view;drop value;emit(66i32);"
            ),
            b"AB",
        ),
        (
            "end-returned-borrow",
            program(
                "var value:Token=token(65i32);var view:read Token=identity(read value);"
                "drop view;drop value;",
                "fn identity(value:read Token)->read Token from value {return read value;}",
            ),
            b"A",
        ),
        (
            "consume-pointer-through-mutable-borrow",
            program(
                "unsafe {var value:i32=7i32; var pointer:*i32=&value;"
                "var saved:*i32=take(mut pointer);"
                "if pointer!=null(*i32) || *saved!=7i32 {trap;}}",
                "unsafe fn take(pointer:mut *i32)->*i32 {var saved:*i32=move pointer;"
                "pointer=null(*i32);return saved;}",
                common=False,
            ),
            b"",
        ),
        (
            "explicit-drop-once-and-reinitialize",
            program("var value:Token=token(65i32); drop value; emit(66i32); value=token(67i32);"),
            b"ABC",
        ),
        (
            "explicit-drop-field-order",
            program(
                "var pair:Pair=make Pair {first:token(65i32),last:token(66i32)}; drop pair; emit(67i32);",
                "record Pair {first:Token;last:Token;}",
            ),
            b"BAC",
        ),
        (
            "else-if-cleanup-scopes",
            program(
                "var outer:Token=token(65i32);"
                "if false {var item:Token=token(66i32);}"
                "else if true {var item:Token=token(67i32);defer emit(68i32);emit(88i32);}"
                "else {var item:Token=token(69i32);}emit(89i32);"
            ),
            b"XDCYA",
        ),
        ("wide-record-reverse-initializers-and-fields", wide_record_source(), b""),
        (
            "empty-main-and-zero-argument-functions",
            program(
                "noop(); if answer()!=42i32 { return 1i32; }",
                "fn noop()->unit {} fn answer()->i32 { return 42i32; }",
                common=False,
            ),
            b"",
        ),
        (
            "raii-reverse-declarations",
            program("var a:Token=token(65i32); var b:Token=token(66i32); emit(88i32);"),
            b"XBA",
        ),
        ("discarded-resource-temporary", program("token(65i32); emit(88i32);"), b"AX"),
        (
            "move-local",
            program("var a:Token=token(65i32); var b:Token=move a; emit(88i32);"),
            b"XA",
        ),
        (
            "move-parameter",
            program(
                "var a:Token=token(65i32); consume(move a); emit(89i32);",
                "fn consume(value:Token)->unit { emit(88i32); }",
            ),
            b"XAY",
        ),
        (
            "move-result",
            program(
                "var a:Token=relay(token(65i32)); emit(88i32);",
                "fn relay(value:Token)->Token { return move value; }",
            ),
            b"XA",
        ),
        (
            "defer-scalar-snapshot",
            program("var code:i32=65i32; defer emit(code); code=66i32; emit(88i32);"),
            b"XA",
        ),
        (
            "defer-callee-and-argument-snapshot",
            program(
                "var selected:fn(i32)->unit=first; var code:i32=65i32; "
                "defer selected(code); selected=second; code=66i32; emit(88i32);",
                "fn first(code:i32)->unit { emit(49i32); emit(code); } "
                "fn second(code:i32)->unit { emit(50i32); emit(code); }",
            ),
            b"X1A",
        ),
        (
            "defer-owned-argument",
            program(
                "var a:Token=token(65i32); defer consume(move a); emit(88i32);",
                "fn consume(value:Token)->unit { emit(67i32); }",
            ),
            b"XCA",
        ),
        (
            "defer-shared-borrow",
            program(
                "var a:Token=token(65i32); defer show(read a); emit(88i32);",
                "fn show(value:read Token)->unit { unsafe { emit(value.id+32i32); } }",
            ),
            b"XaA",
        ),
        (
            "defer-exclusive-borrow",
            program(
                "var a:Token=token(65i32); defer change(mut a,66i32); emit(88i32);",
                "fn change(value:mut Token,code:i32)->unit { unsafe { value.id=code; } }",
            ),
            b"XB",
        ),
        (
            "defer-loan-ends-at-block-exit",
            program(
                "var a:Token=token(65i32); { defer show(read a); } change(mut a,66i32);",
                "fn show(value:read Token)->unit { unsafe { emit(value.id+32i32); } } "
                "fn change(value:mut Token,code:i32)->unit { unsafe { value.id=code; } }",
            ),
            b"aB",
        ),
        (
            "borrow-ends-at-block-exit",
            program(
                "var a:Token=token(65i32); { var view:read Token=read a; "
                "unsafe { emit(view.id+32i32); } } change(mut a,66i32);",
                "fn change(value:mut Token,code:i32)->unit { unsafe { value.id=code; } }",
            ),
            b"aB",
        ),
        (
            "read-borrows-of-constants",
            program(
                "var view:read Cell=read cell; if peek(read view)!=65i32 {return 1i32;} "
                "defer emit_read(read cell.code); emit_read(read cell.code); "
                "emit_read(read codes[1usize]);",
                "record Cell {code:i32;} const cell:Cell=make Cell {code:65i32}; "
                "const codes:[i32;2]=make [i32;2] {66i32,67i32}; "
                "fn peek(value:read Cell)->i32 {return value.code;} "
                "fn emit_read(value:read i32)->unit {emit(value);}",
            ),
            b"ACA",
        ),
        (
            "scalar-borrow-repeated-read",
            program(
                "var code:i32=65i32; { var view:read i32=read code; emit(view); emit(view); } "
                "code=66i32; emit(code);"
            ),
            b"AAB",
        ),
        (
            "nested-exclusive-reborrow-release",
            program(
                "var code:i32=65i32; { var view:mut i32=mut code; "
                "{ var child:mut i32=mut view; child=66i32; } emit(view); } emit(code);"
            ),
            b"BB",
        ),
        (
            "defer-reborrow-release",
            program(
                "var code:i32=65i32; { var view:mut i32=mut code; "
                "{ defer change(mut view,66i32); } emit(view); } emit(code);",
                "fn change(value:mut i32,code:i32)->unit {value=code;}",
            ),
            b"BB",
        ),
        (
            "parenthesized-infinite-loop-return",
            program(
                "if run_loop()!=7i32 {return 1i32;}",
                "fn run_loop()->i32 {while (((true))) {"
                "var value:Token=token(65i32); while (true) {break;} return 7i32;}}",
            ),
            b"A",
        ),
        (
            "loop-deferred-loans-release",
            program(
                "var code:i32=65i32; var index:i32=0i32; while index<2i32 { "
                "{ defer change(mut code,66i32+index); } emit(code); index=index+1i32; }",
                "fn change(value:mut i32,next:i32)->unit {value=next;}",
            ),
            b"BC",
        ),
        (
            "continue-releases-deferred-loan",
            program(
                "var code:i32=65i32; var index:i32=0i32; while index<2i32 { "
                "defer change(mut code,66i32+index); index=index+1i32; continue; } emit(code);",
                "fn change(value:mut i32,next:i32)->unit {value=next; emit(value);}",
            ),
            b"BCC",
        ),
        (
            "break-releases-deferred-loan",
            program(
                "var code:i32=65i32; while true { defer change(mut code,66i32); break; } emit(code);",
                "fn change(value:mut i32,next:i32)->unit {value=next; emit(value);}",
            ),
            b"BB",
        ),
        (
            "raw-initialize-one-array-byte",
            program(
                "var storage:[u8;4]=uninit; unsafe { var data:*u8=(&storage) as *u8; "
                "data[0usize]=65u8; emit(data[0usize] as i32); }"
            ),
            b"A",
        ),
        (
            "raw-store-moved-owner",
            program(
                "var a:Token=token(65i32); consume(move a); unsafe { "
                "var p:*Token=&a; *p=token(66i32); drop_token(mut *p); }",
                "fn consume(value:Token)->unit {}",
            ),
            b"AB",
        ),
        (
            "raw-store-uninitialized-owner",
            program("var a:Token=uninit; unsafe { " "*(&a)=token(66i32); drop_token(mut *(&a)); }"),
            b"B",
        ),
        (
            "raw-store-uninitialized-owner-index",
            program(
                "var a:[Token;1]=uninit; unsafe { var p:*Token=(&a) as *Token; "
                "p[0usize]=token(66i32); drop_token(mut p[0usize]); }"
            ),
            b"B",
        ),
        (
            "raw-store-uninitialized-owner-field",
            program(
                "var a:Box=uninit; unsafe { var p:*Box=&a; "
                "p.item=token(66i32); drop_token(mut p.item); }",
                "record Box {item:Token;}",
            ),
            b"B",
        ),
        (
            "assignment-destroys-old-value",
            program("var a:Token=token(65i32); a=token(66i32); emit(88i32);"),
            b"AXB",
        ),
        (
            "self-move-assignment",
            program("var a:Token=token(65i32); a=move a; emit(88i32);"),
            b"XA",
        ),
        (
            "reinitialize-moved-owner",
            program(
                "var a:Token=token(65i32); consume(move a); a=token(66i32); emit(88i32);",
                "fn consume(value:Token)->unit {}",
            ),
            b"AXB",
        ),
        (
            "assignment-owned-field",
            program(
                "var pair:Pair=make Pair { first:token(65i32), last:token(66i32) }; "
                "pair.first=token(67i32); emit(88i32);",
                "record Pair { first:Token; last:Token; }",
            ),
            b"AXBC",
        ),
        (
            "shared-record-cleanup-moves-and-reassignment",
            program(
                "var value:Tree=tree(65i32); value.first.first=token(69i32); "
                "var moved:Tree=move value; defer consume(move moved); "
                "value=tree(70i32); emit(88i32);",
                "record Pair {first:Token; last:Token;} "
                "record Tree {first:Pair; last:Pair;} "
                "fn pair(code:i32)->Pair {return make Pair {first:token(code),last:token(code+1i32)};} "
                "fn tree(code:i32)->Tree {return make Tree {first:pair(code),last:pair(code+2i32)};} "
                "fn consume(value:Tree)->unit {}",
            ),
            b"AXDCBEIHGF",
        ),
        (
            "nested-block-cleanup",
            program(
                "var a:Token=token(65i32); { var b:Token=token(66i32); defer emit(68i32); "
                "{ var c:Token=token(67i32); emit(88i32); } } emit(89i32);"
            ),
            b"XCDBYA",
        ),
        (
            "nested-return-cleanup",
            program(
                "if nested()!=7i32 { return 1i32; } emit(88i32);",
                "fn nested()->i32 { var a:Token=token(65i32); { var b:Token=token(66i32); "
                "defer emit(68i32); return 7i32; } }",
            ),
            b"DBAX",
        ),
        (
            "both-branches-return",
            program(
                "if choose(true)!=1i32 || choose(false)!=2i32 { return 1i32; }",
                "fn choose(flag:bool)->i32 { var a:Token=token(65i32); "
                "if flag { var b:Token=token(66i32); return 1i32; } "
                "else { var c:Token=token(67i32); return 2i32; } }",
            ),
            b"BACA",
        ),
        (
            "equal-move-state-at-join",
            program(
                "var a:Token=token(65i32); if argc>0i32 { consume(move a); } "
                "else { consume(move a); } emit(88i32);",
                "fn consume(value:Token)->unit {}",
            ),
            b"AX",
        ),
        (
            "equal-initialization-at-join",
            program(
                "var a:Token=uninit; if argc>0i32 { a=token(65i32); } "
                "else { a=token(66i32); } emit(88i32);"
            ),
            b"XA",
        ),
        (
            "loop-normal-exit",
            program(
                "var index:i32=0i32; while index<3i32 { var a:Token=token(65i32+index); "
                "index=index+1i32; } emit(88i32);"
            ),
            b"ABCX",
        ),
        (
            "loop-continue-cleanup",
            program(
                "var outer:Token=token(90i32); var index:i32=0i32; while index<3i32 { "
                "var a:Token=token(65i32+index); defer emit(48i32+index); "
                "index=index+1i32; continue; } emit(88i32);"
            ),
            b"0A1B2CXZ",
        ),
        (
            "loop-break-cleanup",
            program(
                "var outer:Token=token(90i32); while true { var a:Token=token(65i32); "
                "{ var b:Token=token(66i32); defer emit(68i32); break; } } emit(88i32);"
            ),
            b"DBAXZ",
        ),
        (
            "loop-break-consumes-owner",
            program(
                "var value:Token=token(65i32); while true {consume(move value); break;}",
                "fn consume(value:Token)->unit {}",
            ),
            b"A",
        ),
        (
            "loop-break-initializes-owner",
            program("var value:Token=uninit; while true {value=token(65i32); break;}"),
            b"A",
        ),
        (
            "loop-return-cleanup",
            program(
                "if nested()!=7i32 { return 1i32; } emit(88i32);",
                "fn nested()->i32 { var a:Token=token(65i32); while true { "
                "var b:Token=token(66i32); defer emit(68i32); return 7i32; } }",
            ),
            b"DBAX",
        ),
        (
            "loop-restores-owner",
            program(
                "var value:Token=token(65i32); var index:i32=0i32; while index<2i32 { "
                "consume(move value); value=token(66i32+index); index=index+1i32; } emit(88i32);",
                "fn consume(value:Token)->unit {}",
            ),
            b"ABXC",
        ),
        (
            "record-callback-before-reverse-fields",
            program(
                "var value:Outer=make Outer { inner:crate(), tail:token(69i32) }; emit(88i32);",
                "resource Crate { first:Token; values:[Token;2]; last:Token; } drop drop_crate; "
                "record Outer { inner:Crate; tail:Token; } "
                "fn drop_crate(value:mut Crate)->unit { emit(80i32); } "
                "fn crate()->Crate { unsafe { return make Crate { first:token(65i32), "
                "values:make [Token;2] { token(66i32),token(67i32) }, last:token(68i32) }; } }",
            ),
            b"XEPDCBA",
        ),
        (
            "nested-array-cleanup",
            program(
                "var values:[[Token;2];2]=make [[Token;2];2] { "
                "make [Token;2] {token(65i32),token(66i32)}, "
                "make [Token;2] {token(67i32),token(68i32)} };"
            ),
            b"DCBA",
        ),
        (
            "partial-resource-argument-evaluation",
            program(
                "take(marked(65i32),later(),marked(66i32)); emit(88i32);",
                "fn marked(code:i32)->Token { emit(code+32i32); return token(code); } "
                "fn later()->i32 { emit(76i32); return 0i32; } "
                "fn take(first:Token,ignored:i32,last:Token)->unit { emit(84i32); }",
            ),
            b"aLbTBAX",
        ),
        (
            "nested-resource-argument-result",
            program(
                "consume(pass(marked(65i32)));",
                "fn marked(code:i32)->Token { emit(code+32i32); return token(code); } "
                "fn pass(value:Token)->Token { emit(80i32); return move value; } "
                "fn consume(value:Token)->unit {}",
            ),
            b"aPA",
        ),
        ("resource-temporary-field-read", program("unsafe { emit(token(65i32).id); }"), b"AA"),
        (
            "defer-partial-resource-arguments",
            program(
                "defer take(marked(65i32),later(),marked(66i32)); emit(88i32);",
                "fn marked(code:i32)->Token { emit(code+32i32); return token(code); } "
                "fn later()->i32 { emit(76i32); return 0i32; } "
                "fn take(first:Token,ignored:i32,last:Token)->unit { emit(84i32); }",
            ),
            b"aLbXTBA",
        ),
        (
            "defer-owned-snapshot-before-reuse",
            program(
                "var value:Token=token(65i32); defer consume(move value); "
                "value=token(66i32); emit(88i32);",
                "fn consume(value:Token)->unit {}",
            ),
            b"XAB",
        ),
        (
            "function-pointer-borrow-signature",
            program(
                "var callback:fn(read Token)->unit=show; var value:Token=token(65i32); callback(read value);",
                "fn show(value:read Token)->unit { unsafe { emit(value.id+32i32); } }",
            ),
            b"aA",
        ),
        (
            "explicit-unsafe-forget",
            program("var value:Token=token(65i32); unsafe { forget move value; } emit(88i32);"),
            b"X",
        ),
        (
            "mixed-defer-and-owner-order",
            program(
                "defer emit(65i32); var b:Token=token(66i32); defer emit(67i32); var d:Token=token(68i32);"
            ),
            b"DCBA",
        ),
        (
            "short-circuit-temporary-cleanup",
            program(
                "if false && condition(token(65i32),true) { return 1i32; } "
                "if !(true || condition(token(66i32),false)) { return 2i32; } "
                "if true && condition(token(67i32),true) { emit(88i32); } "
                "if false || condition(token(68i32),true) { emit(89i32); }",
                "fn condition(value:Token,result:bool)->bool { return result; }",
            ),
            b"CXDY",
        ),
        (
            "terminating-branch-does-not-constrain-join",
            program(
                "branch(true); branch(false);",
                "fn consume(value:Token)->unit {} "
                "fn branch(flag:bool)->unit { var value:Token=token(65i32); "
                "if flag { consume(move value); return; } emit(88i32); }",
            ),
            b"AXA",
        ),
        (
            "safe-function-constant",
            program("selected(65i32);", "const selected:fn(i32)->unit=emit;"),
            b"A",
        ),
        (
            "safe-aggregate-function-constants",
            program(
                "var value:Cell=make Cell {value:14i32}; "
                "if callback(read value)+callbacks.function(read value)+functions[1usize](read value)!=42i32 {return 1i32;} "
                "if negative != -7i32 || cell_size!=4usize || cell_align!=4usize || field_offset!=0usize {return 2i32;} "
                "if optional!=null(fn(read Cell)->i32) {return 3i32;}",
                "record Cell {value:i32;} fn read_cell(value:read Cell)->i32 {return value.value;} "
                "const callback:fn(read Cell)->i32=read_cell; "
                "record Callbacks {function:fn(read Cell)->i32;} "
                "const callbacks:Callbacks=make Callbacks {function:read_cell}; "
                "const functions:[fn(read Cell)->i32;2]=make [fn(read Cell)->i32;2] {read_cell,read_cell}; "
                "const optional:fn(read Cell)->i32=null(fn(read Cell)->i32); "
                "const negative:i32=-7i32; const cell_size:usize=sizeof(Cell); "
                "const cell_align:usize=alignof(Cell); const field_offset:usize=offsetof(Cell,value);",
            ),
            b"",
        ),
        (
            "array-dynamic-index-read-traps",
            program("var values:[i32;1]=make [i32;1] {65i32}; " "emit(values[argc as usize]);"),
            None,
        ),
        (
            "array-dynamic-index-write-traps",
            program(
                "var values:[i32;1]=make [i32;1] {65i32}; "
                "values[argc as usize]=66i32; emit(values[0usize]);"
            ),
            None,
        ),
        (
            "array-dynamic-index-evaluated-once",
            program(
                "var values:[i32;2]=make [i32;2] {65i32,67i32}; "
                "var calls:usize=0usize; values[next(mut calls)]=66i32; "
                "var selected:i32=values[next(mut calls)]; "
                "if calls!=2usize {return 1i32;} emit(values[0usize]); emit(selected);",
                "fn next(calls:mut usize)->usize {calls=calls+1usize; return calls-1usize;}",
            ),
            b"BC",
        ),
        (
            "null-function-call-traps",
            program("var selected:fn()->unit=null(fn()->unit); selected();"),
            None,
        ),
        (
            "deferred-null-snapshot-traps",
            program(
                "var selected:fn()->unit=null(fn()->unit); defer selected(); selected=noop;",
                "fn noop()->unit {}",
            ),
            None,
        ),
    ]


def consumption_rejects():
    ticket = (
        "resource Ticket {value:i64;} drop ticket_drop;\nfn ticket_drop(t:mut Ticket)->unit {}\n"
    )
    holder = ticket + (
        "resource Holder {inner:Ticket;} drop holder_drop;\n"
        "fn holder_drop(h:mut Holder)->unit {}\n"
        "fn consume(t:Ticket)->unit {}\n"
    )
    cases = [
        (
            "resource-field-move-" + name,
            holder + "fn bad(h:Holder)->" + result + " {unsafe {\n// expect-error\n" + body + "}}",
            "cannot move a resource from this place; cleanup requires the whole owner",
        )
        for name, result, body in (
            ("initializer", "unit", "var item:Ticket=move h.inner;"),
            ("argument", "unit", "consume(move (h.inner));"),
            ("return", "Ticket", "return move h.inner;"),
        )
    ]
    for mode in ("read", "mut"):
        cases += [
            (
                "move-from-" + mode + "-parameter",
                ticket + f"fn bad(t:{mode} Ticket)->Ticket {{\n// expect-error\nreturn move (t);}}",
                "cannot move out of a borrowed value",
            ),
            (
                "drop-" + mode + "-parameter",
                ticket + f"fn bad(t:{mode} Ticket)->unit {{\n// expect-error\ndrop (t);}}",
                "cannot drop a borrowed value",
            ),
        ]
    return cases


def reject_cases():
    consume = "fn consume(value:Token)->unit {}"
    observe = "fn observe(value:read Token)->unit {}"
    condition = "fn condition(value:Token)->bool { return true; }"
    return [
        (
            "end-borrow-with-child",
            program(
                "var value:Token=token(65i32);var view:read Token=read value;"
                "var child:read Token=read view;drop view;"
            ),
            "child loans",
        ),
        (
            "end-deferred-borrow",
            program(
                "var value:Token=token(65i32);var view:read Token=read value;"
                "defer observe(read view);drop view;",
                observe,
            ),
            "child loans",
        ),
        (
            "ended-borrow-use",
            program(
                "var value:Token=token(65i32);var view:read Token=read value;"
                "drop view;observe(read view);",
                observe,
            ),
            "has been moved",
        ),
        (
            "explicit-drop-twice",
            program("var value:Token=token(65i32); drop value; drop value;"),
            "uninitialized",
        ),
        (
            "explicit-drop-borrowed",
            program("var value:Token=token(65i32); var loan:read Token=read value; drop value;"),
            "borrow",
        ),
        (
            "explicit-drop-partial",
            program(
                "var pair:Pair=make Pair {first:token(65i32),last:token(66i32)}; drop pair.first;",
                "record Pair {first:Token;last:Token;}",
            ),
            "whole owner",
        ),
        (
            "duplicate-record-field",
            program("", "record Duplicate {value:i32; value:i32;}", common=False),
            "duplicate record field",
        ),
        (
            "unknown-constructor-field",
            program(
                "var value:Pair=make Pair {absent:0i32};", "record Pair {value:i32;}", common=False
            ),
            "record has no such field",
        ),
        (
            "unknown-place-field",
            program(
                "var value:Pair=make Pair {field:0i32}; value.absent;",
                "record Pair {field:i32;}",
                common=False,
            ),
            "record has no such field",
        ),
        (
            "copy-in-initializer",
            program("var a:Token=token(65i32); var b:Token=a;"),
            "explicit move",
        ),
        (
            "copy-into-parameter",
            program("var a:Token=token(65i32); consume(a);", consume),
            "explicit move",
        ),
        (
            "copy-in-result",
            program("", "fn bad(value:Token)->Token { return value; }"),
            "explicit move",
        ),
        (
            "use-after-move",
            program("var a:Token=token(65i32); var b:Token=move a; observe(read a);", observe),
            "uninitialized or has been moved",
        ),
        (
            "double-move",
            program("var a:Token=token(65i32); consume(move a); consume(move a);", consume),
            "uninitialized or has been moved",
        ),
        (
            "double-move-in-call-arguments",
            program(
                "var value:Token=token(65i32);\n" "// expect-error\nboth(move value,move value);",
                "fn both(first:Token,second:Token)->unit {}",
            ),
            "uninitialized or has been moved",
        ),
        (
            "double-move-in-record-initializers",
            program(
                "var value:Token=token(65i32);\n"
                "// expect-error\nvar pair:Pair=make Pair {first:move value,last:move value};",
                "record Pair {first:Token; last:Token;}",
            ),
            "uninitialized or has been moved",
        ),
        (
            "use-after-equal-branch-moves",
            program(
                "var value:Token=token(65i32);\n"
                "if argc>0i32 {consume(move value);} else {consume(move value); }\n"
                "// expect-error\nobserve(read value);",
                consume + observe,
            ),
            "uninitialized or has been moved",
        ),
        (
            "use-after-continuing-branch-move",
            program(
                "var value:Token=token(65i32);\n"
                "if argc>0i32 {return 0i32;} else {consume(move value); }\n"
                "// expect-error\nobserve(read value);",
                consume + observe,
            ),
            "uninitialized or has been moved",
        ),
        (
            "use-after-loop-move-before-restoration",
            program(
                "var value:Token=token(65i32);\n"
                "while argc>0i32 {consume(move value);\n"
                "// expect-error\nobserve(read value);\nvalue=token(66i32); break;}",
                consume + observe,
            ),
            "uninitialized or has been moved",
        ),
        (
            "unsafe-does-not-end-owner-loan",
            program(
                "var value:Token=token(65i32); var view:read Token=read value;\n"
                "unsafe {\n// expect-error\nconsume(move value);}",
                consume,
            ),
            "active borrow",
        ),
        (
            "unsafe-does-not-revive-moved-owner",
            program(
                "var value:Token=token(65i32); consume(move value);\n"
                "unsafe {\n// expect-error\nobserve(read value);}",
                consume + observe,
            ),
            "uninitialized or has been moved",
        ),
        (
            "unsafe-cast-cannot-forge-borrow",
            program("unsafe {\n// expect-error\nvar view:read i32=0usize as read i32;}"),
            "casts cannot construct resources or borrowed views",
        ),
        (
            "mut-borrow-of-constant",
            program(
                "var view:mut Cell=mut cell;",
                "record Cell {code:i32;} const cell:Cell=make Cell {code:65i32};",
                common=False,
            ),
            "cannot write a constant place",
        ),
        (
            "mut-borrow-of-constant-field",
            program(
                "var view:mut i32=mut cell.code;",
                "record Cell {code:i32;} const cell:Cell=make Cell {code:65i32};",
                common=False,
            ),
            "cannot write a constant place",
        ),
        (
            "uninitialized-owner-read",
            program("var a:Token=uninit; observe(read a);", observe),
            "uninitialized or has been moved",
        ),
        (
            "forged-resource",
            program("var a:Token=make Token {id:65i32};"),
            "raw resource construction requires an unsafe region",
        ),
        (
            "resource-field-access",
            program("var a:Token=token(65i32); emit(a.id);"),
            "resource fields require unsafe access",
        ),
        (
            "raw-dereference",
            program("var p:*i32=null(*i32); var value:i32=*p;"),
            "raw pointer access requires unsafe",
        ),
        (
            "raw-address",
            program("var value:i32=1i32; var p:*i32=&value;"),
            "raw addresses require an unsafe region",
        ),
        (
            "raw-index",
            program("var p:*i32=null(*i32); var value:i32=p[0usize];"),
            "raw pointer access requires unsafe",
        ),
        (
            "raw-pointer-arithmetic",
            program("var p:*u8=null(*u8); var q:*u8=p+1isize;"),
            "pointer arithmetic requires an unsafe region",
        ),
        (
            "raw-pointer-cast",
            program("var p:*u8=0usize as *u8;"),
            "pointer and function casts require an unsafe region",
        ),
        ("foreign-call", program("putchar(65i32);"), "call requires an unsafe region"),
        (
            "unsafe-function-call",
            program("raw();", "unsafe fn raw()->unit {}"),
            "call requires an unsafe region",
        ),
        (
            "unsafe-function-value",
            program("var callback:fn()->unit=raw;", "unsafe fn raw()->unit {}"),
            "unsafe functions can only be called directly",
        ),
        (
            "direct-destructor-call",
            program("var value:Token=token(65i32); drop_token(mut value);"),
            "call requires an unsafe region",
        ),
        (
            "deferred-destructor-call",
            program("var value:Token=token(65i32); defer drop_token(mut value);"),
            "call requires an unsafe region",
        ),
        (
            "destructor-function-value",
            program("var callback:fn(mut Token)->unit=drop_token;"),
            "unsafe functions can only be called directly",
        ),
        (
            "partial-record-move",
            program(
                "var pair:Pair=make Pair {value:token(65i32)}; var value:Token=move pair.value;",
                "record Pair {value:Token;}",
            ),
            "move requires a whole local owner",
        ),
        (
            "partial-array-move",
            program(
                "var values:[Token;1]=make [Token;1] {token(65i32)}; var value:Token=move values[0usize];"
            ),
            "move requires a whole local owner",
        ),
        (
            "move-nonowner",
            program("var value:i32=1i32; var copy:i32=move value;"),
            "move requires a whole local owner",
        ),
        (
            "pointer-move-requires-proof-or-unsafe",
            program("var value:*i32=null(*i32); var copy:*i32=move value;"),
            "pointer moves require unsafe or a memory checker",
        ),
        (
            "write-with-shared-borrow",
            program("var value:i32=65i32; var view:read i32=read value; value=66i32;"),
            "active borrow",
        ),
        (
            "write-through-shared-borrow",
            program("var value:i32=65i32; var view:read i32=read value; view=66i32;"),
            "active borrow",
        ),
        (
            "read-with-exclusive-borrow",
            program("var value:i32=65i32; var view:mut i32=mut value; emit(value);"),
            "active borrow",
        ),
        (
            "move-borrowed-owner",
            program(
                "var value:Token=token(65i32); var view:read Token=read value; consume(move value);",
                consume,
            ),
            "active borrow",
        ),
        (
            "defer-shared-reserves-owner",
            program(
                "var value:Token=token(65i32); defer observe(read value); consume(move value);",
                observe + consume,
            ),
            "active borrow",
        ),
        (
            "defer-shared-blocks-assignment",
            program(
                "var value:Token=token(65i32); defer observe(read value); value=token(66i32);",
                observe,
            ),
            "active borrow",
        ),
        (
            "defer-exclusive-blocks-read",
            program(
                "var value:i32=65i32; defer change(mut value); emit(value);",
                "fn change(value:mut i32)->unit {value=66i32;}",
            ),
            "active borrow",
        ),
        (
            "scalar-borrow-read-keeps-loan",
            program(
                "var value:i32=65i32; var view:read i32=read value; var copy:i32=view; value=66i32;"
            ),
            "active borrow",
        ),
        (
            "field-borrow-read-keeps-loan",
            program(
                "var value:Cell=make Cell {code:65i32}; var view:read Cell=read value; "
                "var copy:i32=view.code; value.code=66i32;",
                "record Cell {code:i32;}",
            ),
            "active borrow",
        ),
        (
            "array-borrow-read-keeps-loan",
            program(
                "var value:[i32;1]=make [i32;1] {65i32}; var view:read [i32;1]=read value; "
                "var copy:i32=view[0usize]; value[0usize]=66i32;"
            ),
            "active borrow",
        ),
        (
            "reborrow-blocks-parent-access",
            program(
                "var value:i32=65i32; var view:mut i32=mut value; var child:mut i32=mut view; emit(view);"
            ),
            "active borrow",
        ),
        (
            "reborrow-cannot-escalate-shared-view",
            program(
                "var value:i32=65i32; var view:read i32=read value; var child:mut i32=mut view;"
            ),
            "active borrow",
        ),
        (
            "borrowed-temporary-cannot-escape-initializer",
            program(
                "var view:read Token=read box().value;",
                "record Box {value:Token;} fn box()->Box {return make Box {value:token(65i32)};}",
            ),
            "borrow would outlive its source storage",
        ),
        (
            "deferred-borrow-cannot-retain-temporary",
            program(
                "defer observe(read box().value);",
                "record Box {value:Token;} fn box()->Box {return make Box {value:token(65i32)};}"
                + observe,
            ),
            "borrow would outlive its source storage",
        ),
        (
            "raw-store-does-not-initialize-owner",
            program(
                "var storage:Token=uninit;\n"
                "unsafe {*(&storage)=token(65i32); drop_token(mut *(&storage));}\n"
                "// expect-error\nconsume(move storage);",
                consume,
            ),
            "uninitialized or has been moved",
        ),
        (
            "raw-store-does-not-initialize-array",
            program(
                "var storage:[u8;4]=uninit;\n"
                "unsafe {var data:*u8=(&storage) as *u8; data[0usize]=65u8;}\n"
                "// expect-error\nvar byte:u8=storage[0usize];"
            ),
            "uninitialized or has been moved",
        ),
        (
            "borrowed-result",
            program("", "fn bad(value:read Token)->read Token {return read value;}"),
            "function results cannot be borrowed views",
        ),
        (
            "borrowed-record-field",
            program("", "record Bad {view:read Token;}"),
            "borrowed views cannot be record fields",
        ),
        (
            "borrowed-array-element",
            program("var values:[read Token;1]=uninit;"),
            "borrow types cannot be stored in pointers or arrays",
        ),
        (
            "borrowed-pointer-element",
            program("var value:*read Token=uninit;"),
            "borrow types cannot be stored in pointers or arrays",
        ),
        (
            "stacked-shared-borrow-type",
            program("", "fn bad(value:read read i32)->unit {}"),
            "borrow modes require a value type, not another borrow mode",
        ),
        (
            "stacked-exclusive-shared-borrow-type",
            program("", "fn bad(value:mut read i32)->unit {}"),
            "borrow modes require a value type, not another borrow mode",
        ),
        (
            "different-move-state-at-join",
            program("var value:Token=token(65i32); if argc>0i32 {consume(move value);}", consume),
            "continuing paths must agree",
        ),
        (
            "different-initialization-at-join",
            program("var value:Token=uninit; if argc>0i32 {value=token(65i32);}"),
            "continuing paths must agree",
        ),
        (
            "parenthesized-loop-break-needs-return",
            program("", "fn run_loop()->i32 {while ((true)) {break;}}"),
            "non-unit function can reach the end",
        ),
        (
            "parenthesized-false-loop-needs-return",
            program("", "fn run_loop()->i32 {while ((false)) {return 7i32;}}"),
            "non-unit function can reach the end",
        ),
        (
            "loop-missing-owner-restoration",
            program(
                "var value:Token=token(65i32); while argc>0i32 {consume(move value);}", consume
            ),
            "loop edges must restore",
        ),
        (
            "break-owner-exit-disagreement",
            program(
                "var value:Token=token(65i32); while argc>0i32 {consume(move value); break;}",
                consume,
            ),
            "continuing paths must agree",
        ),
        (
            "continue-missing-owner-restoration",
            program(
                "var value:Token=token(65i32); while true {consume(move value); continue;}", consume
            ),
            "loop edges must restore",
        ),
        (
            "loop-condition-moves-owner",
            program("var value:Token=token(65i32); while condition(move value) {}", condition),
            "loop edges must restore",
        ),
        (
            "short-circuit-moves-owner",
            program(
                "var value:Token=token(65i32); if argc>0i32 && condition(move value) {}", condition
            ),
            "continuing paths must agree",
        ),
        (
            "function-pointer-read-mut-mismatch",
            program(
                "var callback:fn(read Token)->unit=change;", "fn change(value:mut Token)->unit {}"
            ),
            "incompatible type or borrow mode",
        ),
        (
            "function-pointer-borrow-raw-mismatch",
            program("var callback:fn(*Token)->unit=observe;", observe),
            "incompatible type or borrow mode",
        ),
        (
            "function-pointer-null-borrow-mismatch",
            program("var callback:fn(read Token)->unit=null(fn(mut Token)->unit);"),
            "incompatible type or borrow mode",
        ),
        (
            "nested-function-pointer-borrow-mismatch",
            program(
                "var callback:fn(fn(read Token)->unit)->unit=install;",
                "fn install(callback:fn(mut Token)->unit)->unit {}",
            ),
            "incompatible type or borrow mode",
        ),
        (
            "returned-function-borrow-mismatch",
            program(
                "",
                "fn change(value:mut Token)->unit {} "
                "fn choose()->fn(read Token)->unit {return change;}",
            ),
            "incompatible type or borrow mode",
        ),
        (
            "record-function-borrow-mismatch",
            program(
                "var selected:Callbacks=make Callbacks {function:change};",
                "record Callbacks {function:fn(read Token)->unit;} fn change(value:mut Token)->unit {}",
            ),
            "incompatible type or borrow mode",
        ),
        (
            "shared-then-exclusive-call-borrows",
            program(
                "var value:i32=65i32; both(read value,mut value);",
                "fn both(a:read i32,b:mut i32)->unit {}",
            ),
            "active borrow",
        ),
        (
            "exclusive-then-shared-call-borrows",
            program(
                "var value:i32=65i32; both(mut value,read value);",
                "fn both(a:mut i32,b:read i32)->unit {}",
            ),
            "active borrow",
        ),
        (
            "unsafe-direct-constant",
            program("alias();", 'extern fn raw()->unit="abort"; const alias:fn()->unit=raw;'),
            "constant initializer cannot retain an unsafe function",
        ),
        (
            "unsafe-owned-function-constant",
            program("", "unsafe fn raw()->unit {} const alias:fn()->unit=raw;"),
            "constant initializer cannot retain an unsafe function",
        ),
        (
            "unsafe-record-constant",
            program(
                "aliases.function();",
                'extern fn raw()->unit="abort"; record Callbacks {function:fn()->unit;} '
                "const aliases:Callbacks=make Callbacks {function:raw};",
            ),
            "constant initializer cannot retain an unsafe function",
        ),
        (
            "unsafe-array-constant",
            program(
                "aliases[0usize]();",
                'extern fn raw()->unit="abort"; const aliases:[fn()->unit;1]=make [fn()->unit;1] {raw};',
            ),
            "constant initializer cannot retain an unsafe function",
        ),
        (
            "destructor-constant",
            program("", "const alias:fn(mut Token)->unit=drop_token;"),
            "constant initializer cannot retain an unsafe function",
        ),
        (
            "constant-function-borrow-mismatch",
            program(
                "", "fn change(value:mut Token)->unit {} const alias:fn(read Token)->unit=change;"
            ),
            "constant function value has incompatible source types or borrow modes",
        ),
        (
            "constant-null-borrow-mismatch",
            program("", "const alias:fn(read Token)->unit=null(fn(mut Token)->unit);"),
            "constant initializer has incompatible source types or borrow modes",
        ),
        (
            "defer-nonunit-result",
            program("defer answer();", "fn answer()->i32 {return 1i32;}"),
            "deferred calls must return unit",
        ),
        ("defer-noncall", program("defer 1i32;"), "defer requires a call expression"),
        (
            "defer-resource-copy",
            program("var value:Token=token(65i32); defer consume(value);", consume),
            "explicit move",
        ),
        (
            "forget-outside-unsafe",
            program("var value:Token=token(65i32); forget move value;"),
            "forget requires an unsafe region",
        ),
        (
            "borrow-without-initializer",
            program("var view:read i32=uninit;"),
            "borrowed bindings require an initializer",
        ),
        (
            "drop-missing-definition",
            "resource Bad {id:i32;} drop absent;",
            "resource drop must name a safe defined function",
        ),
        (
            "drop-wrong-borrow-mode",
            "resource Bad {id:i32;} drop cleanup; fn cleanup(value:read Bad)->unit {}",
            "drop parameter must borrow its resource exclusively",
        ),
        (
            "drop-wrong-result",
            "resource Bad {id:i32;} drop cleanup; fn cleanup(value:mut Bad)->i32 {return 0i32;}",
            "drop requires one mut resource parameter and a unit result",
        ),
        ("malformed-resource-clause", "resource Bad {id:i32;}", "expected drop FUNCTION"),
        ("malformed-resource-field", "resource Bad {id:i32} drop cleanup;", "expected ';'"),
        ("malformed-defer-call", program("defer emit(65i32;"), "expected ')'"),
        ("malformed-type", "fn broken(value:)->unit {}", "expected a type"),
        (
            "malformed-number",
            "const bad:u64=18446744073709551616u64;",
            "integer token exceeds 64 bits",
        ),
        ("malformed-string", 'const bad:*u8="unfinished', "unterminated string"),
        ("invalid-source-byte", b"\0", "invalid source byte 0x00"),
    ] + consumption_rejects()


def depth_reject_cases():
    # These inputs exceeded the native stack before source-stage depth checks.
    # Flat syntax must not bypass the semantic traversal limit.
    count = 120000
    constant = "const x:i32=" + "+".join(["1i32"] * count) + ";\n"
    records = "".join(f"record R{index} {{ v:R{index + 1}; }}\n" for index in range(count - 1))
    records += f"record R{count - 1} {{ v:i32; }}\nconst x:R0=0i32;\n"
    return [
        ("flat-constant-semantic-depth", constant, "semantic traversal depth limit"),
        ("cross-record-ownership-depth", records, "semantic traversal depth limit"),
    ]


class Failure(Exception):
    pass


class Suite:
    def __init__(self, args, work):
        self.build = args.build.resolve()
        self.compiler = self.build / "crust-resource"
        self.work = work
        self.options = [
            "--cflag=-O2",
            *("--cflag=" + flag for flag in args.cflag),
            *("--ldflag=" + flag for flag in args.ldflag),
        ]
        self.timeout = args.timeout
        self.commands = 0

    def command(self, argv, expected=0, cwd=ROOT):
        command = list(map(str, argv))
        self.commands += 1
        try:
            result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            raise Failure(
                f"timeout after {self.timeout}s: {shlex.join(command)}\n"
                f"{(error.stdout or b'').decode(errors='replace')}\n"
                f"{(error.stderr or b'').decode(errors='replace')}"
            ) from error
        if result.returncode != expected:
            raise Failure(
                f"{shlex.join(command)}\nstatus {result.returncode}, expected {expected}\n"
                f"stdout: {result.stdout!r}\nstderr:\n{result.stderr.decode(errors='replace')}"
            )
        return result

    def source(self, name, source):
        path = self.work / (name + ".crs")
        path.write_bytes(source if isinstance(source, bytes) else source.encode())
        return path

    def runtime(self, name, source, expected):
        path = self.source(name, source)
        checked = self.command([self.compiler, "--check", path])
        if checked.stdout or checked.stderr:
            raise Failure(f"check produced output: {checked.stdout!r} {checked.stderr!r}")
        generated = self.work / (name + ".c")
        symbols = self.work / (name + ".rsp")
        emitted = self.command(
            [self.compiler, "--emit-c", "-o", generated, "--symbols", symbols, path]
        )
        if emitted.stdout or emitted.stderr or not generated.stat().st_size or not symbols.exists():
            raise Failure(
                f"C emission did not produce both artifacts: {emitted.stdout!r} {emitted.stderr!r}"
            )
        output = self.work / name
        compiled = self.command([self.compiler, "-o", output, *self.options, path])
        if compiled.stdout or compiled.stderr:
            raise Failure(f"compile produced output: {compiled.stdout!r} {compiled.stderr!r}")
        # The Linux x86-64 C profile lowers an explicit trap to SIGILL.
        # SIGSEGV from an unchecked null call must not satisfy these cases.
        executed = self.command([output], expected=-signal.SIGILL if expected is None else 0)
        if executed.stdout != (b"" if expected is None else expected) or executed.stderr:
            raise Failure(
                f"{output}\nstdout {executed.stdout!r}, expected {expected!r}\n"
                f"stderr: {executed.stderr.decode(errors='replace')}"
            )

    def reject(self, name, source, diagnostic):
        path = self.source(name, source)
        result = self.command([self.compiler, "--check", path], expected=1)
        located = re.search(rb":\d+:\d+: error: ", result.stderr)
        if result.stdout or diagnostic.encode() not in result.stderr or not located:
            raise Failure(
                f"expected a located diagnostic containing {diagnostic!r}\n"
                f"stdout: {result.stdout!r}\nstderr: {result.stderr.decode(errors='replace')}"
            )
        if isinstance(source, str) and "// expect-error\n" in source:
            expected_line = source[: source.index("// expect-error\n")].count("\n") + 2
            if not re.search(
                rb":" + str(expected_line).encode() + rb":\d+: error: ", result.stderr
            ):
                raise Failure(
                    f"expected rejection at marked line {expected_line}, not at an earlier valid operation\n"
                    f"{result.stderr.decode(errors='replace')}"
                )

    def cli(self, name):
        if name == "cli-entry-source-signature":
            for borrow in ("read", "mut"):
                path = self.source(
                    name + "-" + borrow,
                    f"fn start(argc:i32,argv:{borrow} *u8)->i32{{return 0i32;}}",
                )
                for endpoint in ("--prepare", "--emit-c"):
                    result = self.command(
                        [self.compiler, endpoint, "--entry", "start", path], expected=1
                    )
                    if b"entry must be a defined fn(i32, **u8) -> i32" not in result.stderr:
                        raise Failure(f"lowered ABI accepted a borrowed entry: {result.stderr!r}")
        elif name == "cli-empty-source":
            path = self.source(name, "")
            self.command([self.compiler, "--check", path])
            result = self.command([self.compiler, "--emit-c", "--library", path])
            if not result.stdout or result.stderr:
                raise Failure(f"empty library did not emit C: {result.stdout!r} {result.stderr!r}")
        elif name == "cli-shared-record-cleanup-growth":
            sizes = []
            for depth in (8, 14):
                source = self.source(f"{name}-{depth}", cleanup_tree_source(depth))
                output = source.with_suffix(".c")
                self.command([self.compiler, "--library", "--emit-c", "-o", output, source])
                sizes.append(output.stat().st_size)
            if sizes[1] > 100_000 or sizes[1] > 3 * sizes[0]:
                raise Failure(f"record cleanup expanded with value size: {sizes}")
        elif name == "cli-private-cleanup-separate-objects":
            objects = []
            for label, code in (("left", 65), ("right", 66)):
                source = self.source(
                    f"{name}-{label}",
                    'extern fn putchar(code:i32)->i32="putchar"; '
                    f"resource Cell {{code:i32;}} drop drop_{label}; "
                    f"fn drop_{label}(value:mut Cell)->unit {{unsafe {{putchar(value.code);}}}} "
                    f"fn run_{label}()->unit {{unsafe {{var value:Cell=make Cell {{code:{code}i32}};}}}}",
                )
                output = source.with_suffix(".o")
                self.command(
                    [
                        self.compiler,
                        "--library",
                        "--object",
                        "--cflag=-O0",
                        "--export",
                        f"drop_{label}",
                        "--export",
                        f"run_{label}",
                        "-o",
                        output,
                        source,
                    ]
                )
                symbols = self.command(["nm", "--defined-only", output]).stdout
                if not re.search(rb"\bt r_g[0-9]+\b", symbols):
                    raise Failure(f"cleanup helper has no private function symbol: {symbols!r}")
                public = self.command(["nm", "-g", "--defined-only", output]).stdout
                if set(re.findall(rb"\bT (\S+)", public)) != {
                    f"drop_{label}".encode(),
                    f"run_{label}".encode(),
                }:
                    raise Failure(f"cleanup helper escaped native visibility: {public!r}")
                objects.append(output)
            source = self.source(
                name + "-main",
                program(
                    "unsafe {left(); right();}",
                    'extern fn left()->unit="run_left"; extern fn right()->unit="run_right";',
                    common=False,
                ),
            )
            output = self.work / name
            self.command(
                [
                    self.compiler,
                    "-o",
                    output,
                    source,
                    *(f"--ldflag={path}" for path in objects),
                ]
            )
            if self.command([output]).stdout != b"AB":
                raise Failure("separate private cleanup helpers changed destructor behavior")
        elif name == "cli-private-cleanup-native-alias":
            source = self.source(
                name,
                "resource Token {id:i32;} drop drop_token;\n"
                'extern fn putchar(code:i32)->i32="putchar";\n'
                'extern fn native(value:*Token)->unit="_crust0_u1_d6";\n'
                "fn drop_token(value:mut Token)->unit {unsafe {putchar(68i32);}}\n"
                "fn main(argc:i32,argv:**u8)->i32 {\n"
                "unsafe {var value:Token=make Token{id:1i32}; native(&value);}\n"
                "return 0i32;}\n",
            )
            native = source.with_suffix(".c")
            native.write_text(
                "#include <stdio.h>\n"
                "void _crust0_u1_d6(void *value) {(void)value; putchar(69);}\n"
            )
            native_object = native.with_suffix(".o")
            self.command(["gcc", "-std=c99", "-pedantic-errors", "-c", native, "-o", native_object])
            output = self.work / name
            self.command([self.compiler, "-o", output, source, f"--ldflag={native_object}"])
            if self.command([output]).stdout != b"ED":
                raise Failure("private cleanup captured an external native symbol")
        elif name == "cli-multiple-sources":
            library = self.source(name + "-library", COMMON)
            application = self.source(
                name + "-application", program("var value:Token=token(65i32);", common=False)
            )
            empty = self.source(name + "-empty", "")
            output = self.work / name
            self.command([self.compiler, "--check", empty, library, application])
            self.command([self.compiler, "-o", output, *self.options, empty, library, application])
            if self.command([output]).stdout != b"A":
                raise Failure("multiple-source resource program did not destroy its owner once")
        elif name == "cli-failure-preserves-output":
            path = self.source(name, program("var value:Token=token(65i32); var copy:Token=value;"))
            for mode, suffix in (([], ".exe"), (["--emit-c"], ".c")):
                output = self.work / (name + suffix)
                output.write_bytes(b"retained output\n")
                self.command([self.compiler, *mode, "-o", output, path], expected=1)
                if output.read_bytes() != b"retained output\n":
                    raise Failure(f"failed compilation changed {output}")
        elif name == "cli-source-root":
            package = self.work / "ordinary resource package"
            for relative in (
                "api/crust0_stage.crs",
                "stages/resources/api.crs",
                "examples/resources/hello/main.crs",
            ):
                destination = package / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            output = package / "build/resource-hello"
            output.parent.mkdir()
            shutil.copyfile(
                self.build / "crust-resource-library.so",
                output.parent / "crust-resource-library.so",
            )
            source = package / "examples/resources/hello/main.crs"
            runner = self.build / "crust"
            result = self.command([runner, source], cwd=self.work)
            if result.stdout or result.stderr:
                raise Failure(
                    f"root compilation produced output: {result.stdout!r} {result.stderr!r}"
                )
            result = self.command([output], cwd=self.work)
            if result.stdout != b"Hello, resources!\n" or result.stderr:
                raise Failure(f"resource hello failed: {result.stdout!r} {result.stderr!r}")
            retained = output.read_bytes()
            original = source.read_text()
            source.write_text(original + "fn invalid()->i32{return missing;}\n")
            result = self.command([runner, source], expected=1, cwd=self.work)
            if (
                f"{source}:{original.count(chr(10)) + 1}:".encode() not in result.stderr
                or b"unknown value name" not in result.stderr
                or result.stdout
            ):
                raise Failure(f"root lost the target source location: {result.stderr!r}")
            if output.read_bytes() != retained:
                raise Failure("failed inline target changed the previous executable")
        else:
            raise AssertionError(name)


def source_report(source):
    if isinstance(source, bytes):
        return repr(source)
    if len(source) > 8192:
        return (
            f"{len(source)} characters; the complete source is retained in the case file.\n"
            f"{source[:2048]}\n... source excerpt omitted ...\n{source[-2048:]}"
        )
    return "\n".join(f"{line:3}: {text}" for line, text in enumerate(source.splitlines(), 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--group", choices=("all", "runtime", "reject", "cli"), default="all")
    parser.add_argument(
        "--case", action="append", default=[], help="run names that match this shell pattern"
    )
    parser.add_argument(
        "--cflag", action="append", default=[], help="append one generated-C compiler argument"
    )
    parser.add_argument(
        "--ldflag", action="append", default=[], help="append one native linker argument"
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    cases = [("runtime", *case) for case in runtime_cases()]
    cases += [("reject", *case) for case in reject_cases() + depth_reject_cases()]
    cases += [
        ("cli", name, None, None)
        for name in (
            "cli-empty-source",
            "cli-entry-source-signature",
            "cli-shared-record-cleanup-growth",
            "cli-private-cleanup-separate-objects",
            "cli-private-cleanup-native-alias",
            "cli-multiple-sources",
            "cli-failure-preserves-output",
            "cli-source-root",
        )
    ]
    cases = [
        case
        for case in cases
        if (args.group == "all" or case[0] == args.group)
        and (not args.case or any(fnmatch.fnmatchcase(case[1], pattern) for pattern in args.case))
    ]
    if not cases:
        parser.error("no test cases selected")
    if args.list:
        for group, name, _, _ in cases:
            print(f"{group}: {name}")
        return 0
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    compiler = args.build.resolve() / "crust-resource"
    if not compiler.is_file():
        parser.error(f"compiler does not exist: {compiler}")
    work = Path(tempfile.mkdtemp(prefix="crust-resources-"))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    suite = Suite(args, work)
    failures = 0
    counts = dict(runtime=0, reject=0, cli=0)
    try:
        for group, name, source, expected in cases:
            try:
                if group == "runtime":
                    suite.runtime(name, source, expected)
                elif group == "reject":
                    suite.reject(name, source, expected)
                else:
                    suite.cli(name)
                counts[group] += 1
            except (Failure, OSError) as error:
                failures += 1
                print(f"FAIL {group}: {name}\n{error}", file=sys.stderr)
                if source is not None:
                    print("Source:\n" + source_report(source), file=sys.stderr)
                if not args.keep_going:
                    break
        print(
            f"Resource suite: {counts['runtime']} runtime, {counts['reject']} rejection, "
            f"{counts['cli']} CLI cases passed; {suite.commands} process checks; {failures} failures"
        )
    finally:
        if failures:
            print(f"Failure inputs and artifacts retained in {work}", file=sys.stderr)
        else:
            shutil.rmtree(work)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
