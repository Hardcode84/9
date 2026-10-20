#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise checked array values, conservative loans, and bounds traps."""

import argparse
import tempfile
from pathlib import Path

from ownership_support import ROOT, command, execute, rejected

PROGRAM = """
record Pair { x:i32; y:i32; }
record Table { cells:[Pair;2]; flags:[bool;2]; }
fn read_at(a:read [Pair;2],i:usize)->i32 { return a[i].x; }
fn write_at(a:mut [Pair;2],i:usize)->unit { a[i].x=9i32; }
fn array()->[Pair;2] {
    return make [Pair;2] {make Pair{x:1i32,y:2i32},make Pair{x:3i32,y:4i32}};
}
fn main(argc:i32,argv:**u8)->i32 {
    var t:Table=make Table{cells:array(),flags:make [bool;2]{false,true}};
    var copy:Table=t;
    var i:usize=0usize;
    while i<2usize {t.cells[i].x=t.cells[i].x+5i32;i=i+1usize;}
    if read_at(read t.cells,1usize)!=8i32 || copy.cells[1usize].x!=3i32 {trap;}
    write_at(mut t.cells,0usize);
    var p:Pair=uninit; p.x=0i32; p.y=1i32;
    i=0usize;
    while i<4usize {p=make Pair{x:p.x+1i32,y:p.y};i=i+1usize;}
    if p.x!=4i32 || t.cells[0usize].x!=9i32 {trap;}
    var nested:[[i32;2];2]=make [[i32;2];2]{make [i32;2]{1i32,2i32},make [i32;2]{3i32,4i32}};
    nested[1usize][0usize]=7i32;
    if nested[0usize][0usize]!=1i32 || nested[1usize][0usize]!=7i32 {trap;}
    var fresh:[i32;2]=uninit;
    fresh=make [i32;2]{5i32,6i32};
    if fresh[0usize]!=5i32 || fresh[1usize]!=6i32 {trap;}
    return 0i32;
}
"""


def check_plain_storage_dag(compiler, directory):
    source = directory / "plain-storage-dag.crs"
    source.write_text(
        "record R0{value:i64;}"
        + "".join(f"record R{i}{{a:R{i-1};b:R{i-1};}}" for i in range(1, 33))
        + "record End{value:[R32;1];}"
        + "fn main(argc:i32,argv:**u8)->i32{return 0i32;}"
    )
    # Declaration checking must visit the type graph, not its expanded layout.
    command([compiler, "--check", source], timeout=10)


def check_arrays(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    check_plain_storage_dag(compiler, directory)
    path = directory / "arrays.crs"
    path.write_text(PROGRAM)
    generated, symbols = path.with_suffix(".c"), path.with_suffix(".rsp")
    command([compiler, "--emit", "--symbols", symbols, "-o", generated, path])
    execute(generated, symbols, directory, "arrays", sanitize, b"")
    prefix = "fn f()->unit {var a:[i32;2]=make [i32;2]{1i32,2i32};"
    cases = {
        "array-uninit": (
            "fn f()->i32 {var a:[i32;2]=uninit;return a[0usize];}",
            "fully initialized",
        ),
        "array-uninit-copy": (
            "fn f()->unit {var a:[i32;2]=uninit;var b:[i32;2]=a;}",
            "initialized",
        ),
        "array-shared-write": ("fn f(a:read [i32;2])->unit {a[0usize]=3i32;}", "shared loan"),
        "array-live-loan": (
            prefix + "var x:read i32=read a[0usize];a[1usize]=3i32;var y:i32=x;}",
            "active",
        ),
        "array-parent-live": (
            prefix + "var x:read [i32;2]=read a;a[0usize]=3i32;var y:i32=x[0usize];}",
            "active",
        ),
        "array-pointer-elements": ("record T {a:[*u8;2];}", "plain scalar"),
        "array-opaque-elements": (
            "record P {x:i32;} opaque; record T {a:[P;2];}",
            "explicit trust",
        ),
        "array-record-pointer": ("record P {p:*u8;} record T {a:[P;2];}", "persistent pointers"),
        "string-index": ('fn f()->u8 {var p:*u8="text";return p[0usize];}', "checked inline array"),
        "string-untrusted": ('fn f(p:*u8)->unit {} fn g()->unit {f("text");}', "domain interface"),
    }
    cases["array-index-consumes-owner"] = (
        "resource H {a:[i32;2];} drop finish; fn finish(h:mut H)->unit {} "
        "fn eat(h:H)->usize {return 0usize;} "
        "fn f()->i32 {var h:H=make H{a:make [i32;2]{1i32,2i32}};return h.a[eat(move h)];}",
        "moved",
    )
    partial = "record P{x:i32;y:i32;} "
    partial_local = "var p:P=uninit;p.x=9i32;"
    initialized = "var a:P=make P{x:1i32,y:2i32};"
    cases.update(
        {
            "partial-element": (
                partial
                + "fn f()->i32 {var a:[P;1]=make [P;1]{make P{x:1i32,y:2i32}};"
                + partial_local
                + "a[0usize]=p;return a[0usize].y;}",
                "initialized",
            ),
            "partial-record": (
                partial + "fn f()->i32 {" + initialized + partial_local + "a=p;return a.y;}",
                "initialized",
            ),
            "partial-loop": (
                partial
                + "fn f(n:i32)->i32 {"
                + initialized
                + partial_local
                + "var i:i32=0i32;while i<n {a=p;i=i+1i32;}return a.y;}",
                "initialized",
            ),
            "partial-nested": (
                partial + "record Outer{p:P;} fn f()->i32 {"
                "var a:Outer=make Outer{p:make P{x:1i32,y:2i32}};var p:Outer=uninit;"
                "p.p.x=9i32;a=p;return a.p.y;}",
                "initialized",
            ),
            "partial-return": (
                partial + "fn f()->P {" + partial_local + "return p;}",
                "initialized",
            ),
            "partial-move": (
                partial + "fn f()->P {" + partial_local + "return move p;}",
                "initialized",
            ),
            "partial-constructor": (
                partial + "fn f()->unit {" + partial_local + "var a:[P;1]=make [P;1]{p};}",
                "initialized",
            ),
            "partial-argument": (
                partial + "fn take(p:P)->unit{} fn f()->unit {" + partial_local + "take(p);}",
                "initialized",
            ),
        }
    )
    rejected(compiler, directory, cases)
    provider = directory / "text-provider.crs"
    provider.write_text('extern fn puts(p:*u8)->i32="puts"; fn show(p:*u8)->unit {puts(p);}')
    path.write_text('fn main(argc:i32,argv:**u8)->i32 {show("array text");return 0i32;}')
    binary = directory / "text"
    command([compiler, "trusted", provider, "-o", binary, path])
    assert command([binary]).stdout == b"array text\n"
    for index in ("2usize", "0xffffffffffffffffusize"):
        path.write_text(
            prefix.replace("fn f()->unit", "fn main(argc:i32,argv:**u8)->i32")
            + f"var i:usize={index};return a[i];"
            + "}"
        )
        command([compiler, "-o", binary, path])
        result = command([binary], expected=-4)
        assert result.stdout == b""
    print(
        f"ownership arrays: values, nested storage, loops, text, O0/O2, {len(cases)} rejections, 2 bounds traps"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(
        prefix="ownership-arrays-", dir=ROOT / args.build
    ) as directory:
        check_arrays((ROOT / args.build).resolve(), Path(directory), args.sanitize)


if __name__ == "__main__":
    main()
