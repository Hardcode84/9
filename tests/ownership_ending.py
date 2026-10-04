#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check explicit local loan endings and their cleanup boundaries."""

import argparse
import tempfile
from pathlib import Path

from ownership_imports import command as import_command
from ownership_imports import import_arguments, publish
from ownership_support import ROOT, command, execute, rejected

LOCAL = "var x:i64=1i64;var parent:mut i64=mut x;"
IDENTITY = "fn identity(x:mut i64)->mut i64 from x {return mut x;}"


def main(body):
    return "fn main(argc:i32,argv:**u8)->i32 {" + body + "return 0i32;}"


def good_cases():
    return {
        "end-local": main(LOCAL + "parent=2i64;drop parent;x=3i64;if x!=3i64 {trap;}"),
        "end-shared": main(
            "var x:i64=1i64;var a:read i64=read x;var b:read i64=read x;"
            "drop a;if b!=1i64 {trap;}drop b;x=3i64;"
        ),
        "end-child": main(
            LOCAL + "var child:read i64=read parent;drop child;parent=2i64;drop parent;"
            "if x!=2i64 {trap;}"
        ),
        "end-returned": IDENTITY
        + main("var x:i64=1i64;var view:mut i64=identity(mut x);view=2i64;drop view;x=3i64;"),
        "end-reborrowed-parameter": "fn change(x:mut i64)->unit {var local:mut i64=mut x;"
        "drop local;x=2i64;}" + main("var x:i64=1i64;change(mut x);if x!=2i64 {trap;}"),
        "end-both-branches": main(LOCAL + "if argc>0i32 {drop parent;} else {drop parent;}x=2i64;"),
        "end-loop-local": main(
            "var x:i64=0i64;while x<2i64 {var view:mut i64=mut x;"
            "view=view+1i64;drop view;}if x!=2i64 {trap;}"
        ),
        "end-referent-survives": "resource Ticket {value:i64;} drop destroy;"
        'extern fn emit(x:i32)->i32 foreign(scalar)="putchar";'
        "fn destroy(t:mut Ticket)->unit {emit(t.value as i32);}"
        + main(
            "var ticket:Ticket=make Ticket{value:65i64};var view:mut Ticket=mut ticket;"
            "drop view;ticket.value=66i64;drop ticket;"
        ),
    }


def bad_cases():
    cases = {
        "live-mut-child": ("var child:mut i64=mut parent;drop parent;", "child loans"),
        "live-shared-child": ("var child:read i64=read parent;drop parent;", "child loans"),
        "ended-read": ("drop parent;var n:i64=parent;", "has been moved"),
        "ended-write": ("drop parent;parent=2i64;", "has been moved"),
        "ended-twice": ("drop parent;drop parent;", "has been moved"),
        "child-parent-still-live": (
            "var child:read i64=read parent;drop child;x=2i64;",
            "active",
        ),
        "branch-disagreement": ("if argc>0i32 {drop parent;}", "continuing paths"),
        "loop-consumes-outer": ("while argc>0i32 {drop parent;}", "loop edges"),
    }
    results = {name: (main(LOCAL + text), message) for name, (text, message) in cases.items()}
    results["deferred-child"] = (
        "fn use(x:read i64)->unit {}" + main(LOCAL + "defer use(read parent);drop parent;"),
        "child loans",
    )
    results["stored-child"] = (
        "record View {value:read i64;}"
        + main(LOCAL + "var view:View=make View{value:read parent};drop parent;"),
        "child loans",
    )
    results["returned-child"] = (
        IDENTITY + main(LOCAL + "var child:mut i64=identity(mut parent);drop parent;"),
        "child loans",
    )
    results["projected-view-child"] = (
        "record View {value:mut i64;}"
        + main(
            "var x:i64=1i64;var view:View=make View{value:mut x};"
            "var all:mut View=mut view;var child:mut i64=mut all.value;drop all;"
        ),
        "child loans",
    )
    results["ended-cursor"] = (
        "record Pair {left:i64;}"
        + main(
            "var pair:Pair=make Pair{left:1i64};var parent:mut Pair=mut pair;"
            "var pointer:*Pair=&parent;drop parent;pointer.left=2i64;"
        ),
        "expired",
    )
    results["returned-view-child"] = (
        "record View {value:mut i64;}"
        "fn through(view:mut View)->mut i64 from view.value {return mut view.value;}"
        + main(
            "var x:i64=1i64;var view:View=make View{value:mut x};"
            "var all:mut View=mut view;var child:mut i64=through(mut all);drop all;"
        ),
        "child loans",
    )
    results["ended-copied-view-pointer"] = (
        "record Cell {value:i64;}record View {value:mut Cell;}"
        + main(
            "var cell:Cell=make Cell{value:1i64};var view:View=make View{value:mut cell};"
            "var all:mut View=mut view;var pointer:*Cell=&all.value;var copy:*Cell=pointer;"
            "drop all;copy.value=2i64;"
        ),
        "expired",
    )
    for mode in ("read", "mut"):
        results["end-parameter-" + mode] = (
            "fn bad(x:" + mode + " i64)->unit {drop x;}",
            "cannot drop a borrowed value",
        )
    return results


def check_import(build, directory):
    provider = directory / "ending-provider.crs"
    provider.write_text(IDENTITY)
    driver = str(build / "crust-ownership-import-test")
    cache = directory / "ending-cache"
    cache.mkdir()
    receipt = publish(driver, cache, [provider])
    provider.unlink()
    client = directory / "ending-client.crs"
    client.write_text(main("var x:i64=1i64;var view:mut i64=identity(mut x);drop view;x=2i64;"))
    output = directory / "ending-client"
    args = import_arguments(driver, cache, receipt, client, output)
    import_command(args)
    command([output])
    client.write_text(main(LOCAL + "var view:mut i64=identity(mut parent);drop parent;"))
    result = import_command(args, success=False)
    assert "child loans" in result.stderr, result.stderr


def check_ending(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    for name, text in good_cases().items():
        source = directory / f"{name}.crs"
        source.write_text(text)
        generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
        command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, source])
        command([build / "crust-ownership-erasure", source])
        expected = b"B" if name == "end-referent-survives" else b""
        execute(generated, symbols, directory, name, sanitize, expected)
    rejected(compiler, directory, bad_cases())
    check_import(build, directory)
    provider = ROOT / "examples/intrusive/links.crs"
    source = directory / "end-keeps-domain-permission.crs"
    source.write_text(
        main(
            "domain Graph {var owner:Owner=owner_new(1i64);read Graph {"
            "var view:read Owner=read owner;drop view;drop owner;}}"
        )
    )
    result = command([compiler, "trusted", provider, "--check", source], expected=1)
    assert "stronger domain authority" in result.stderr.decode(), result.stderr
    print("ownership endings: O0/O2, erasure, source-free imports, 19 rejections")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sanitize", action="store_true")
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-end-", dir=ROOT / "build") as temp:
        check_ending(ROOT / "build", Path(temp), arguments.sanitize)
