#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check last-use loan endings through native output and memory-error rejections."""

import argparse
import tempfile
from pathlib import Path

from ownership_support import ROOT, command, execute, rejected

HELPERS = """
extern fn emit(code:i32)->i32 foreign(scalar)="putchar";
resource Ticket {value:i64;} drop finish;
fn finish(ticket:mut Ticket)->unit {emit(ticket.value as i32);}
fn observe(value:read i64)->unit {emit(value as i32);}
fn snapshot(value:i64)->unit {emit(value as i32);}
fn snapshot_pair(value:Pair)->unit {emit(value.left as i32);}
fn identity(value:mut i64)->mut i64 from value {return mut value;}
record View {value:mut i64;}
record Shared {value:read i64;}
record Nested {child:View;}
record Pair {left:i64;right:i64;}
"""


def program(body):
    return HELPERS + "fn main(argc:i32,argv:**u8)->i32{" + body + "return 0i32;}"


def good_cases():
    yield "scalar", "var x:i64=1i64;var r:read i64=read x;var y:i64=r;x=2i64;if x+y!=3i64 {trap;}", b""
    yield "unused", "var x:i64=1i64;var r:mut i64=mut x;x=2i64;", b""
    yield "child", "var x:i64=1i64;var parent:mut i64=mut x;var child:mut i64=mut parent;child=2i64;x=3i64;", b""
    yield "resume-parent", "var x:i64=1i64;var parent:mut i64=mut x;var child:read i64=read parent;var n:i64=child;parent=n+1i64;x=x+1i64;", b""
    yield "returned", "var x:i64=1i64;var r:mut i64=identity(mut x);r=2i64;x=3i64;", b""
    yield "explicit", "var x:i64=1i64;var r:read i64=read x;var n:i64=r;drop r;x=n+1i64;", b""
    yield "branches", "var x:i64=1i64;var r:read i64=read x;if argc>0i32 {var n:i64=r;x=n+1i64;} else {x=3i64;}x=4i64;", b""
    yield "branch-drop", "var x:i64=1i64;var r:read i64=read x;if argc>0i32 {drop r;}x=4i64;", b""
    yield "break-drop", "var x:i64=1i64;var r:read i64=read x;while true {if argc>0i32 {drop r;break;} else {break;}}x=4i64;", b""
    yield "empty-branch", "var x:i64=1i64;var r:read i64=read x;if argc>0i32 {var n:i64=r;}x=4i64;", b""
    yield "condition", "var x:bool=true;var r:read bool=read x;if r {x=false;} else {x=true;}", b""
    yield "loop-local", "var x:i64=0i64;while x<3i64 {var r:mut i64=mut x;r=r+1i64;if x>3i64 {trap;}continue;}if x!=3i64 {trap;}", b""
    yield "loop-exit", "var x:i64=1i64;var r:read i64=read x;var i:i32=0i32;while i<2i32 {if r!=1i64 {trap;}i=i+1i32;}x=2i64;", b""
    yield "break", "var x:i64=1i64;var r:read i64=read x;while true {var n:i64=r;x=n+1i64;break;}x=3i64;", b""
    yield "break-arms", "var x:i64=1i64;var r:read i64=read x;while true {if argc>0i32 {var n:i64=r;x=n+1i64;break;} else {x=3i64;break;}}x=4i64;", b""
    yield "nested-loop", "var x:i64=0i64;while x<2i64 {while true {var r:mut i64=mut x;r=r+1i64;x=x+1i64;break;}continue;}if x!=2i64 {trap;}", b""
    yield "stored", "var x:i64=1i64;var view:View=make View{value:mut x};view.value=2i64;x=3i64;", b""
    yield "stored-child", "var x:i64=1i64;var view:View=make View{value:mut x};var child:mut i64=mut view.value;child=2i64;x=3i64;", b""
    yield "nested-stored", "var x:i64=1i64;var view:Nested=make Nested{child:make View{value:mut x}};view.child.value=2i64;x=3i64;", b""
    yield "moved-stored", "var x:i64=1i64;var view:View=make View{value:mut x};var next:View=move view;next.value=2i64;x=3i64;", b""
    yield "stored-parent-resumes", "var x:i64=1i64;var view:View=make View{value:mut x};var all:read View=read view;var n:i64=all.value;view.value=n+1i64;x=3i64;", b""
    yield "stored-branch", "var x:i64=1i64;var view:Shared=make Shared{value:read x};if argc>0i32 {var n:i64=view.value;x=n+1i64;} else {x=3i64;}", b""
    yield "pointer-child", "var pair:Pair=make Pair{left:1i64,right:2i64};var r:mut Pair=mut pair;var pointer:*Pair=&r;pointer.left=3i64;pair.left=4i64;", b""
    yield "defer-ended", "var x:i64=65i64;var parent:mut i64=mut x;{defer observe(read parent);}x=66i64;observe(read x);", b"AB"
    yield "defer-scalar-copy", "var x:i64=65i64;var r:read i64=read x;defer snapshot(r);x=66i64;observe(read x);", b"BA"
    yield "defer-record-copy", "var pair:Pair=make Pair{left:65i64,right:0i64};var r:read Pair=read pair;defer snapshot_pair(r);pair.left=66i64;observe(read pair.left);", b"BA"
    yield "cleanup-order", "var a:Ticket=make Ticket{value:65i64};var b:Ticket=make Ticket{value:66i64};var r:read Ticket=read a;var n:i64=r.value;a.value=67i64;", b"BC"
    yield "cleanup-child", "var a:Ticket=make Ticket{value:65i64};var r:read Ticket=read a;var child:read i64=read r.value;observe(read child);drop a;", b"AA"
    yield "deferred-stored", "var x:i64=65i64;{var view:Shared=make Shared{value:read x};defer observe(read view.value);}x=66i64;observe(read x);", b"AB"


def bad_cases():
    yield "later-read", "var x:i64=1i64;var r:read i64=read x;x=2i64;observe(read r);", "active"
    yield "later-child", "var x:i64=1i64;var p:mut i64=mut x;var c:read i64=read p;x=2i64;observe(read c);", "active"
    yield "later-parent", "var x:i64=1i64;var p:mut i64=mut x;var c:read i64=read p;var n:i64=c;x=2i64;p=3i64;", "active"
    yield "later-branch", "var x:i64=1i64;var r:read i64=read x;x=2i64;if argc>0i32 {observe(read r);}", "active"
    yield "loop-backedge", "var x:i64=1i64;var r:read i64=read x;while argc>0i32 {var n:i64=r;x=2i64;}", "active"
    yield "continue-backedge", "var x:i64=1i64;var r:read i64=read x;while argc>0i32 {var n:i64=r;if argc>1i32 {x=2i64;continue;}break;}", "active"
    yield "deferred", "var x:i64=65i64;var r:read i64=read x;defer observe(read r);x=66i64;", "active"
    yield "deferred-child", "var x:i64=65i64;var p:mut i64=mut x;defer observe(read p);drop p;", "child loans"
    yield "stored-live-child", "var x:i64=1i64;var view:View=make View{value:mut x};var r:read i64=read view.value;x=2i64;observe(read r);", "active"
    yield "stored-live-record-borrow", "var x:i64=1i64;var view:View=make View{value:mut x};var r:mut View=mut view;x=2i64;r.value=3i64;", "active"
    yield "copied-pointer", "var pair:Pair=make Pair{left:1i64,right:2i64};var r:mut Pair=mut pair;var p:*Pair=&r;var q:*Pair=p;pair.left=3i64;q.left=4i64;", "active"
    yield "dropped-use", "var x:i64=1i64;var r:read i64=read x;drop r;observe(read r);", "moved"
    yield "cleanup-borrowed", "var a:Ticket=make Ticket{value:65i64};var r:read Ticket=read a;drop a;observe(read r.value);", "active"


def check_liveness(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    good = list(good_cases())
    for name, body, output in good:
        source = directory / f"last-use-{name}.crs"
        source.write_text(program(body))
        generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
        command([compiler, "--emit-c", "-o", generated, "--symbols", symbols, source])
        execute(generated, symbols, directory, "last-use-" + name, sanitize, output)
        command([build / "crust-ownership-erasure", source])
    tutorial = ROOT / "examples/ownership-basics/last-use.crs"
    generated, symbols = directory / "last-use.c", directory / "last-use.rsp"
    command(
        [
            build / "crust",
            tutorial.with_name("main.crs"),
            "--emit-c",
            "-o",
            generated,
            "--symbols",
            symbols,
            tutorial,
        ]
    )
    execute(generated, symbols, directory, "last-use-tutorial", sanitize, b"AB\n")
    command([build / "crust-ownership-erasure", tutorial])
    bad = {name: (program(body), message) for name, body, message in bad_cases()}
    rejected(compiler, directory, bad)
    print(f"Ownership last use: {len(good)} runtime/erasure cases and {len(bad)} rejections")


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-last-use-", dir=args.build) as temporary:
        check_liveness(args.build.resolve(), Path(temporary).resolve(), args.sanitize)


if __name__ == "__main__":
    cli()
