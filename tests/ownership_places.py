#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check field loans, containing storage, and independent imported interfaces."""

import os

from ownership_imports import command as import_command
from ownership_imports import import_arguments, publish
from ownership_support import command, execute, rejected

PAIR = "record Pair {left:i64;right:i64;} "
LOCAL = "var p:Pair=make Pair{left:1i64,right:2i64};"


def main(body):
    return "fn main(argc:i32,argv:**u8)->i32 {" + body + "return 0i32;}"


def good_cases():
    return {
        "separate-fields": PAIR
        + main(
            LOCAL + "{var a:mut i64=mut p.left;var b:mut i64=mut p.right;a=3i64;b=4i64;}"
            "if p.left!=3i64 || p.right!=4i64 {trap;}"
        ),
        "nested-fields": PAIR
        + "record Outer {pair:Pair;tail:i64;} "
        + main(
            "var p:Outer=make Outer{pair:make Pair{left:1i64,right:2i64},tail:3i64};"
            "{var a:mut i64=mut p.pair.left;var b:mut i64=mut p.pair.right;"
            "var c:mut i64=mut p.tail;a=4i64;b=5i64;c=6i64;}"
            "if p.pair.left!=4i64 || p.pair.right!=5i64 || p.tail!=6i64 {trap;}"
        ),
        "sibling-records": PAIR
        + "record Outer {a:Pair;b:Pair;} "
        + main(
            "var p:Outer=make Outer{a:make Pair{left:1i64,right:2i64},"
            "b:make Pair{left:3i64,right:4i64}};"
            "{var a:mut Pair=mut p.a;var b:mut i64=mut p.b.left;a.right=5i64;b=6i64;}"
            "if p.a.right!=5i64 || p.b.left!=6i64 {trap;}"
        ),
        "borrowed-record": PAIR + "fn change(p:mut Pair)->unit {var a:mut i64=mut p.left;"
        "var b:mut i64=mut p.right;a=3i64;b=4i64;}"
        + main(LOCAL + "change(mut p);if p.left!=3i64 || p.right!=4i64 {trap;}"),
        "field-arguments": PAIR
        + "fn change(a:mut i64,b:mut i64)->unit {a=3i64;b=4i64;}"
        + main(LOCAL + "change(mut p.left,mut p.right);if p.left!=3i64 || p.right!=4i64 {trap;}"),
        "field-write": PAIR
        + main(LOCAL + "var a:mut i64=mut p.left;p.right=4i64;a=3i64;if p.right!=4i64 {trap;}"),
        "returned-field": PAIR
        + "fn left(p:mut Pair)->mut i64 from p.left {return mut p.left;}"
        + main(LOCAL + "var a:mut i64=left(mut p);var b:mut i64=mut p.right;a=3i64;b=4i64;"),
    }


def bad_cases():
    cases = {
        "same-field": "var a:mut i64=mut p.left;var b:mut i64=mut p.left;",
        "whole-after-field": "var a:mut i64=mut p.left;var b:read Pair=read p;",
        "field-after-whole": "var a:mut Pair=mut p;var b:read i64=read p.right;",
        "write-borrowed-field": "var a:read i64=read p.left;p.left=3i64;",
        "replace-container": "var a:read i64=read p.left;p=make Pair{left:3i64,right:4i64};",
        "read-borrowed-field": "var a:mut i64=mut p.left;var value:i64=p.left;",
    }
    results = {name: (PAIR + main(LOCAL + body), "active") for name, body in cases.items()}
    results["shared-parent-write"] = (
        PAIR + "fn bad(p:read Pair)->unit {var a:mut i64=mut p.left;}",
        "shared",
    )
    results["parent-reborrow-write"] = (
        PAIR + main(LOCAL + "var a:mut Pair=mut p;var b:read i64=read a.left;a.left=3i64;"),
        "active",
    )
    results["drop-container"] = (
        "resource Pair {left:i64;right:i64;} drop destroy;fn destroy(p:mut Pair)->unit {}"
        + main(LOCAL + "var a:read i64=read p.left;drop p;"),
        "active",
    )
    results["nested-parent-access"] = (
        PAIR
        + "record Outer {pair:Pair;}"
        + main(
            "var p:Outer=make Outer{pair:make Pair{left:1i64,right:2i64}};"
            "var a:mut i64=mut p.pair.left;var b:read Pair=read p.pair;"
        ),
        "active",
    )
    results["stored-field-versus-container"] = (
        "record View {value:mut i64;}"
        "fn change(view:mut View,value:mut i64)->unit {view.value=2i64;value=3i64;}"
        + main("var x:i64=1i64;var v:View=make View{value:mut x};change(mut v,mut v.value);"),
        "active",
    )
    results["container-versus-stored-field"] = (
        "record View {value:mut i64;}"
        "fn change(value:mut i64,view:mut View)->unit {view.value=2i64;value=3i64;}"
        + main("var x:i64=1i64;var v:View=make View{value:mut x};change(mut v.value,mut v);"),
        "active",
    )
    results["shared-container-field-write"] = (
        "record View {value:mut i64;}"
        + main(
            "var x:i64=1i64;var v:View=make View{value:mut x};"
            "var all:read View=read v;v.value=3i64;"
        ),
        "active",
    )
    for name, use in {
        "nested-view-write": "view.value.left=3i64;",
        "view-address-write": "var pointer:*Pair=&view.value;pointer.left=3i64;",
    }.items():
        results[name] = (
            PAIR
            + "record View {value:mut Pair;}"
            + main(
                LOCAL + "var view:View=make View{value:mut p};" "var all:read View=read view;" + use
            ),
            "active",
        )
    for mode in ("read", "mut"):
        results["field-before-" + mode + "-view"] = (
            "record View {value:mut i64;}"
            + main(
                "var x:i64=1i64;var view:View=make View{value:mut x};"
                "var child:mut i64=mut view.value;var all:" + mode + " View=" + mode + " view;"
            ),
            "active",
        )
    return results


def check_imports(build, directory):
    library = directory / "field-provider.crs"
    library.write_text(
        PAIR + "fn change(p:mut Pair)->unit {var a:mut i64=mut p.left;"
        "var b:mut i64=mut p.right;a=3i64;b=4i64;}"
        "fn left(p:mut Pair)->mut i64 from p.left {return mut p.left;}"
    )
    driver = str(build / "crust-ownership-import-test")
    cache = directory / "fields-cache"
    cache.mkdir()
    receipt = publish(driver, cache, [library])
    library.unlink()
    client = directory / "field-client.crs"
    client.write_text(
        main(
            LOCAL + "change(mut p);if p.left!=3i64 || p.right!=4i64 {trap;}"
            "var a:mut i64=left(mut p);var b:mut i64=mut p.right;a=5i64;b=6i64;"
        )
    )
    output = directory / "field-client"
    args = import_arguments(driver, cache, receipt, client, output)
    import_command(args, env=dict(os.environ))
    command([output])
    client.write_text(main(LOCAL + "var a:mut i64=left(mut p);p.left=5i64;"))
    result = import_command(args, success=False)
    assert "active" in result.stderr, result.stderr


def check_places(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    for name, text in good_cases().items():
        source = directory / f"{name}.crs"
        source.write_text(text)
        generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
        command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, source])
        command([build / "crust-ownership-erasure", source])
        execute(generated, symbols, directory, name, sanitize, b"")
    rejected(compiler, directory, bad_cases())
    check_imports(build, directory)
    print("ownership places: field loans, O0/O2, erasure, source-free imports, 18 rejections")
