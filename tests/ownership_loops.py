#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check loop exits, cleanup, and ownership joins through native programs."""

import argparse
import tempfile
from pathlib import Path

from ownership_expressions import HELPERS, main_body
from ownership_imports import command as import_command
from ownership_imports import import_arguments, publish
from ownership_support import ROOT, command, execute, rejected

BODY = """
var i:i32=0i32;
while i<10i32 {if i==3i32 {break;} i=i+1i32;}
if i!=3i32 {trap;}
var remaining:i64=3i64;
while step(mut remaining) {continue;}
if remaining!=0i64 {trap;}
{
    var outer:Trace=trace_new(90i32);
    var index:i32=0i32;
    while index<3i32 {
        var value:Trace=trace_new(65i32+index);
        defer say(48i32+index);
        index=index+1i32;
        continue;
    }
    emit(88i32);
}
{
    var outer:Trace=trace_new(90i32);
    while true {
        var a:Trace=trace_new(65i32);
        {var b:Trace=trace_new(66i32);defer say(68i32);break;}
    }
    emit(88i32);
}
{
    var value:Trace=trace_new(69i32);
    while ((true)) {drop value;break;}
}
{
    var value:Trace=trace_new(70i32);
    while true {
        if argc>0i32 {drop value;break;}
        else {drop value;break;}
    }
}
var result:i64=uninit;
while true {if argc>0i32 {result=7i64;break;} else {result=9i64;break;}}
if result!=7i64 {trap;}
var value:Trace=uninit;
while true {value=trace_new(71i32);break;}
drop value;
var x:i64=0i64;
while true {var loan:mut i64=mut x;defer set(mut loan,7i64);break;}
if x!=7i64 {trap;}
while x<9i64 {var next:i64=x+1i64;defer set(mut x,next);continue;}
if x!=9i64 {trap;}
var count:i64=0i64;
while count<2i64 {while true {defer increment(mut count);break;} continue;}
if count!=2i64 {trap;}
var replacement:Trace=trace_new(72i32);
i=0i32;
while i<2i32 {
    drop replacement;
    replacement=trace_new(73i32+i);
    i=i+1i32;
    continue;
}
drop replacement;
if choose(true)!=1i64 || choose(false)!=2i64 {trap;}
emit(10i32);
"""
FUNCTIONS = """
fn say(code:i32)->unit {emit(code);}
fn increment(value:mut i64)->unit {value=value+1i64;}
fn choose(flag:bool)->i64 {
    var result:i64=0i64;
    while true {if flag {return 1i64;} result=2i64;break;}
    return result;
}
fn forever()->i64 {while true {continue;}}
"""
LOOPS = HELPERS + FUNCTIONS + main_body(BODY)
OUTPUT = b"NNN0A1B2CXZDBAXZEFGHIJ\n"


def bad_cases():
    return {
        "break-owner-versus-condition": (
            HELPERS
            + main_body("var value:Trace=trace_new(65i32);while argc>0i32 {drop value;break;}"),
            "continuing paths",
        ),
        "break-owner-disagreement": (
            HELPERS
            + main_body(
                "var value:Trace=trace_new(65i32);while true {"
                "if argc>0i32 {drop value;break;} else {break;}}"
            ),
            "continuing paths",
        ),
        "continue-owner-consumed": (
            HELPERS
            + main_body("var value:Trace=trace_new(65i32);while argc>0i32 {drop value;continue;}"),
            "loop edges",
        ),
        "continue-borrow-consumed": (
            HELPERS
            + main_body(
                "var x:i64=0i64;var loan:read i64=read x;while argc>0i32 {drop loan;continue;}"
            ),
            "loop backedge",
        ),
        "break-outer-loan-stays-active": (
            HELPERS
            + main_body(
                "var x:i64=0i64;var loan:read i64=read x;"
                "while true {break;}x=7i64;var later:i64=loan;"
            ),
            "active payload loan",
        ),
        "break-borrow-disagreement": (
            HELPERS
            + main_body(
                "var x:i64=0i64;var loan:read i64=read x;while true {"
                "if argc>0i32 {drop loan;break;} else {break;}}var later:i64=loan;"
            ),
            "has been moved",
        ),
        "break-scalar-not-initialized": (
            main_body("var x:i64=uninit;while argc>0i32 {x=7i64;break;}if x!=7i64 {trap;}"),
            "uninitialized",
        ),
        "break-scalar-exit-disagreement": (
            main_body(
                "var x:i64=uninit;while true {if argc>0i32 {x=7i64;break;} else {break;}}"
                "if x!=7i64 {trap;}"
            ),
            "uninitialized",
        ),
        "continue-initializes-outer": (
            main_body("var x:i64=uninit;while argc>0i32 {x=7i64;continue;}"),
            "loop backedge",
        ),
        "break-local-loan-escape": (
            HELPERS
            + main_body(
                "var saved:View=uninit;while true {" "var x:i64=1i64;saved=view_new(read x);break;}"
            ),
            "outlive",
        ),
        "break-outside-loop": (main_body("break;"), "outside a loop"),
        "continue-outside-loop": (main_body("continue;"), "outside a loop"),
    }


def check_import(build, directory):
    provider = directory / "loop-provider.crs"
    provider.write_text(HELPERS + FUNCTIONS)
    cache = directory / "loop-cache"
    cache.mkdir()
    driver = str(build / "crust-ownership-import-test")
    receipt = publish(driver, cache, [provider])
    provider.unlink()
    client = directory / "loop-client.crs"
    client.write_text(main_body(BODY))
    output = directory / "loop-client"
    args = import_arguments(driver, cache, receipt, client, output)
    import_command(args)
    assert command([output]).stdout == OUTPUT
    client.write_text(
        main_body(
            "var value:Trace=trace_new(65i32);while true {" "drop value;break;}consume(move value);"
        )
    )
    result = import_command(args, success=False)
    assert "has been moved" in result.stderr, result.stderr


def check_heap(build, directory, sanitize):
    heap = (ROOT / "examples/ownership-basics/heap.crs").read_text()
    provider = heap[: heap.index("fn main(")]
    source = directory / "loop-heap.crs"
    source.write_text(
        provider
        + main_body(
            "var i:i32=0i32;while i<3i32 {var owner:CellOwner=cell_new(7i64);"
            "if owner.cell==null(*Cell) {trap;}"
            "{var view:read i64=read owner.cell.value;if view!=7i64 {trap;}}"
            "i=i+1i32;if i<3i32 {continue;}break;}if i!=3i32 {trap;}"
        )
    )
    generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
    command(
        [build / "crust-ownership-test", "--emit-c", "--symbols", symbols, "-o", generated, source]
    )
    command([build / "crust-ownership-erasure", source])
    execute(generated, symbols, directory, "loop-heap", sanitize, b"")
    rejected(
        build / "crust-ownership-test",
        directory,
        {
            "continue-owner-field-consumed": (
                provider
                + main_body(
                    "var owner:CellOwner=cell_new(7i64);while argc>0i32 {"
                    "var cell:*Cell=move owner.cell;"
                    "if cell!=null(*Cell) {release(cell as *u8);}continue;}"
                ),
                "loop backedge",
            ),
            "break-freed-alias": (
                provider
                + main_body(
                    "var owner:CellOwner=cell_new(7i64);if owner.cell==null(*Cell) {return 0i32;}"
                    "var alias:*Cell=owner.cell;while true {drop owner;break;}"
                    "if alias.value!=7i64 {trap;}"
                ),
                "live non-null storage",
            ),
        },
    )


def check_domain(build, directory, sanitize):
    source = directory / "loop-domain.crs"
    provider = ROOT / "examples/intrusive/links.crs"
    source.write_text(
        main_body(
            "domain Graph {"
            "var owner:Owner=owner_new(7i64);var head:ReadyHead=uninit;ready_init(&head);"
            "ready_insert(mut head,read owner);var found:bool=false;read Graph {"
            "var cursor:Cursor=ready_first(read head);var end:Cursor=ready_end(read head);"
            "while !cursor_equal(read cursor,read end) {"
            "{var value:read i64=cursor_value(read cursor);if value==7i64 {found=true;break;}}"
            "cursor_advance(mut cursor);continue;}}"
            "if !found {trap;}drop owner;if ready_count(read head)!=0usize {trap;}"
            "}"
        )
    )
    generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
    command(
        [
            build / "crust-ownership-test",
            "trusted",
            provider,
            "--emit-c",
            "--symbols",
            symbols,
            "-o",
            generated,
            source,
        ]
    )
    command([build / "crust-ownership-erasure", "trusted", provider, source])
    execute(generated, symbols, directory, "loop-domain", sanitize, b"")
    for jump in ("break", "continue"):
        source.write_text(
            main_body(
                "domain Graph {var owner:Owner=owner_new(7i64);"
                "while argc>0i32 {var old:Owner=move owner;owner=owner_new(8i64);"
                "edit Graph {var capture:Owner=move old;" + jump + ";}}}"
            )
        )
        result = command(
            [build / "crust-ownership-test", "trusted", provider, "--check", source], expected=1
        )
        assert b"stronger domain authority" in result.stderr, result.stderr


def check_loops(build, directory, sanitize):
    source = directory / "loops.crs"
    source.write_text(LOOPS)
    generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
    command(
        [build / "crust-ownership-test", "--emit-c", "--symbols", symbols, "-o", generated, source]
    )
    command([build / "crust-ownership-erasure", source])
    execute(generated, symbols, directory, "loops", sanitize, OUTPUT)
    rejected(build / "crust-ownership-test", directory, bad_cases())
    check_heap(build, directory, sanitize)
    check_domain(build, directory, sanitize)
    check_import(build, directory)
    print(
        "ownership loops: exit joins, backedges, cleanup, O0/O2, erasure, imports, "
        f"{len(bad_cases()) + 5} rejections"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-loops-", dir=args.build) as temporary:
        check_loops(args.build.resolve(), Path(temporary), args.sanitize)


if __name__ == "__main__":
    main()
