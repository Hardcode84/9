#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check stored loans, declared result origins, and their native representation."""

import argparse
import os
import tempfile
from pathlib import Path

from ownership_imports import command as import_command
from ownership_imports import import_arguments, unpack
from ownership_support import command, execute, rejected

ROOT = Path(__file__).resolve().parents[1]
READING = "record View {value:read i64;} "
EDITING = "record View {value:mut i64;} "


def main_body(body):
    return "fn main(argc:i32,argv:**u8)->i32 {" + body + "return 0i32;}"


def reject_cases():
    local = "var x:i64=1i64;var view:View=make View{value:read x};"
    return {
        "write-under-view": (
            READING + main_body(local + "x=2i64;"),
            "active payload loan",
        ),
        "escape-block": (
            READING
            + main_body("var view:View=uninit;{var x:i64=1i64;view=make View{value:read x};}"),
            "stored view would outlive its source loan",
        ),
        "escape-local": (
            READING
            + "fn bad(x:read i64)->View from x {var y:i64=0i64;return make View{value:read y};}",
            "stored result does not derive from its declared source parameter",
        ),
        "missing-origin": (
            READING + "fn bad(x:read i64)->View {return make View{value:read x};}",
            "view record result requires a from parameter",
        ),
        "copy-view": (
            READING + main_body(local + "var duplicate:View=view;"),
            "transfer requires movable owned or fresh storage",
        ),
        "use-moved": (
            READING + main_body(local + "var next:View=move view;var stale:i64=view.value;"),
            "uninitialized or has been moved",
        ),
        "use-dropped": (
            READING + main_body(local + "drop view;var stale:i64=view.value;"),
            "uninitialized or has been moved",
        ),
        "use-dropped-on-both-branches": (
            READING
            + main_body(
                local + "if argc>1i32 {drop view;} else {drop view;}var stale:i64=view.value;"
            ),
            "uninitialized or has been moved",
        ),
        "write-under-view-after-join": (
            READING
            + main_body(local + "var n:i64=0i64;if argc>1i32 {n=view.value;} else {n=2i64;}x=n;"),
            "active payload loan",
        ),
        "double-drop": (
            READING + main_body(local + "drop view;drop view;"),
            "uninitialized or has been moved",
        ),
        "replace-origin": (
            READING + "fn bad(a:mut View,b:View)->unit {a=move b;}",
            "borrowed view records must retain their stored loan origins",
        ),
        "return-independent-origins": (
            "record Pair {first:read i64;second:read i64;}"
            "fn pair(a:read i64,b:read i64)->Pair from a {"
            "return make Pair{first:read a,second:read b};}",
            "stored result does not derive from its declared source parameter",
        ),
        "local-first-origin": (
            "record Pair {first:read i64;second:read i64;}"
            + main_body(
                "var a:i64=1i64;var b:i64=2i64;"
                "var pair:Pair=make Pair{first:read a,second:read b};a=3i64;"
            ),
            "active",
        ),
        "local-second-origin": (
            "record Pair {first:read i64;second:read i64;}"
            + main_body(
                "var a:i64=1i64;var b:i64=2i64;"
                "var pair:Pair=make Pair{first:read a,second:read b};b=3i64;"
            ),
            "active",
        ),
        "duplicate-mut": (
            "record View {a:mut i64;b:mut i64;}"
            + main_body("var x:i64=1i64;var v:View=make View{a:mut x,b:mut x};"),
            "active borrow",
        ),
        "mut-via-shared": (
            EDITING + "fn bad(view:read View)->unit {view.value=2i64;}",
            "active borrow",
        ),
        "shared-field-write": (
            READING + "fn bad(view:mut View)->unit {view.value=2i64;}",
            "shared field view permits only reads",
        ),
        "borrow-uninit": (
            "record Data {a:i64;} record View {data:read Data;}"
            + main_body("var d:Data=uninit;var v:View=make View{data:read d};"),
            "loan requires initialized storage",
        ),
        "persistent-field": (
            "domain D(View);record View {value:read i64;} domain(D);",
            "stored loans require a scoped view record",
        ),
        "persistent-nested-field": (
            "domain D(Outer);" + READING + "record Outer {view:View;} domain(D);",
            "stored loans require a scoped view record",
        ),
        "wrong-field-origin": (
            READING + "record Pair {first:i64;second:i64;} "
            "fn wrong(pair:read Pair)->View from pair.first {return make View{value:read pair.second};}",
            "returned loan does not match its declared storage path",
        ),
        "wrong-target-type": (
            READING + "fn wrong(x:read i32)->View from x {trap;}",
            "stored result type differs from its declared origin",
        ),
        "shared-to-mutable-result": (
            EDITING + "fn wrong(x:read i64)->View from x {trap;}",
            "mutable stored result requires a mutable source parameter",
        ),
        "pointer-loan-field": (
            "record View {value:read *i64;}",
            "stored loan target must be a scalar or record type",
        ),
        "replace-nested-origin": (
            READING + "record Outer {view:View;} fn bad(a:mut Outer,b:View)->unit {a.view=move b;}",
            "borrowed view records must retain their stored loan origins",
        ),
        "one-branch-drops": (
            EDITING
            + main_body(
                "var x:i64=1i64;var v:View=make View{value:mut x};" "if argc==0i32 {drop v;}x=2i64;"
            ),
            "continuing paths must agree on owner consumption",
        ),
        "stored-view-loop-effect": (
            "domain D(Cell);record Cell {value:i64;} domain(D);"
            "record View {flag:mut bool;} "
            "fn bad(p:*Cell)->i64 access(read,D) {"
            "var flag:bool=true;{var view:View=make View{flag:mut flag};"
            "while view.flag {view.flag=false;}}"
            "if flag {return 0i64;}return (*p).value;}",
            "pointer access requires live non-null storage",
        ),
        "stored-view-branch-effect": (
            "domain D(Cell);record Cell {value:i64;} domain(D);"
            "record View {flag:mut bool;} "
            "fn bad(view:mut View,test:bool,p:*Cell)->i64 access(read,D) {"
            "view.flag=true;if test {view.flag=false;}"
            "if view.flag {return 0i64;}return (*p).value;}",
            "pointer access requires live non-null storage",
        ),
        **effect_cases(),
    }


def effect_cases():
    schema = "domain D(Cell); record Cell {value:i64;} domain(D); " "record View {flag:mut bool;} "
    cases = {}
    for name, parameter, argument in (
        ("borrowed", "mut View", "mut view"),
        ("consumed", "View", "move view"),
    ):
        cases[f"{name}-view-scalar-effect"] = (
            schema + f"fn clear(view:{parameter})->unit {{view.flag=false;}} "
            "fn bad(p:*Cell)->i64 access(read,D) {"
            "var flag:bool=true;{var view:View=make View{flag:mut flag};"
            + f"clear({argument});"
            + "}if flag {return 0i64;} return (*p).value;}",
            "pointer access requires live non-null storage",
        )
    return cases


def lifetime_cases():
    owner = (
        "domain D(Owned); resource Owned {value:i64;} domain(D) drop destroy; "
        "fn destroy(value:mut Owned)->unit access(reclaim,D) {} "
        "record View {target:read Owned;} "
    )
    prefix = (
        "fn bad()->unit access(reclaim,D) {var item:Owned=make Owned{value:1i64};"
        "var view:View=make View{target:read item};"
    )
    return {
        "destroy-borrowed-source": (owner + prefix + "drop item;}", "active payload loan"),
        "move-borrowed-source": (
            owner + prefix + "var moved:Owned=move item;}",
            "active payload loan",
        ),
        "stored-reborrow-alias": (
            EDITING
            + main_body(
                "var x:i64=1i64;var v:View=make View{value:mut x};"
                "var a:View=make View{value:mut v.value};"
                "var b:View=make View{value:mut v.value};"
            ),
            "active payload loan",
        ),
        "stored-scalar-reborrow-after-drop": (
            EDITING
            + main_body(
                "var x:i64=1i64;var v:View=make View{value:mut x};"
                "var y:read i64=read v.value;drop v;x=2i64;"
            ),
            "active borrow",
        ),
        "same-value-wrong-parameter": (
            READING
            + "fn wrong(a:read i64,b:read i64)->View from a {return make View{value:read b};}",
            "stored result does not derive from its declared source parameter",
        ),
        "stored-temporary": (
            READING
            + "fn get(value:read i64)->View from value {return make View{value:read value};} "
            + main_body("var x:i64=1i64;var y:read i64=read get(read x).value;"),
            "borrow would outlive its source storage",
        ),
    }


def native_cases():
    return {
        "both-branches-drop": (
            EDITING
            + main_body(
                "var x:i64=1i64;var v:View=make View{value:mut x};"
                "if argc==0i32 {drop v;} else {drop v;}x=2i64;"
            ),
            b"",
        ),
        "stored-view-loop": (
            "record View {flag:mut bool;} "
            "fn finish(view:mut View)->unit {while view.flag {view.flag=false;}} "
            + main_body(
                "var flag:bool=true;{var view:View=make View{flag:mut flag};"
                "finish(mut view);}if flag {trap;}"
            ),
            b"",
        ),
        "domain-view": (
            "domain D(Cell);record Cell {value:i64;} domain(D); "
            "record View {cell:mut Cell;} "
            "fn change(view:mut View)->unit access(edit,D) {view.cell.value=7i64;} "
            "fn consume(view:View)->unit access(edit,D) {view.cell.value=9i64;} "
            "fn main(argc:i32,argv:**u8)->i32 access(reclaim,D) {"
            "var cell:Cell=make Cell{value:1i64};"
            "{var view:View=make View{cell:mut cell};change(mut view);consume(move view);}"
            "if cell.value!=9i64 {trap;} return 0i32;}",
            b"",
        ),
        "resource-source": (
            "domain D(Owned);resource Owned {value:i64;} domain(D) drop destroy; "
            'extern fn emit(code:i32)->i32 foreign(scalar)="putchar"; '
            "fn destroy(value:mut Owned)->unit access(reclaim,D) {emit(68i32);} "
            "record View {target:read Owned;} "
            "fn main(argc:i32,argv:**u8)->i32 access(reclaim,D) {"
            "var item:Owned=make Owned{value:1i64};"
            "{var view:View=make View{target:read item};drop view;}"
            "item.value=2i64;return 0i32;}",
            b"D",
        ),
        "two-shared-fields": (
            "record Pair {first:read i64;second:read i64;} "
            "fn pair(value:read i64)->Pair from value {"
            "return make Pair{first:read value,second:read value};} "
            + main_body(
                "var x:i64=3i64;var view:Pair=pair(read x);"
                "if view.first!=3i64 || view.second!=3i64 {trap;}"
            ),
            b"",
        ),
    }


def check_native_cases(build, directory, sanitize):
    for name, (text, output) in native_cases().items():
        source = directory / f"{name}.crs"
        source.write_text(text)
        generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
        command(
            [
                build / "crust-ownership-test",
                "--emit-c",
                "--symbols",
                symbols,
                "-o",
                generated,
                source,
            ]
        )
        command([build / "crust-ownership-erasure", source])
        execute(generated, symbols, directory, name, sanitize, output)


def bodyless(build, directory, source, environment):
    provider, main = source.read_text().split("fn main(", 1)
    library, client = directory / "provider.crs", directory / "client.crs"
    library.write_text(provider)
    client.write_text("fn main(" + main)
    driver = build / "crust-ownership-import-test"
    cache = directory / "cache"
    cache.mkdir()
    result = import_command([str(driver), "publish", str(cache), str(library)], env=environment)
    artifact, digest = result.stdout.splitlines()
    receipt = Path(artifact), digest
    _, _, interface = unpack(receipt[0].read_bytes())
    assert "from view.value" in interface and "value: read i64" in interface
    assert "var " not in interface and "return " not in interface
    library.unlink()
    output = directory / "client"
    import_command(import_arguments(driver, cache, receipt, client, output), env=environment)
    assert command([output]).stdout == b"OK\n"
    client.write_text(
        client.read_text().replace("var answer: i64 =", "count = 0i64; var answer: i64 =", 1)
    )
    result = import_command(
        import_arguments(driver, cache, receipt, client, output), env=environment, success=False
    )
    assert "active payload loan" in result.stderr, result.stderr


def run(build, directory, sanitize):
    source = ROOT / "examples/ownership-basics/views.crs"
    generated, symbols = directory / "views.c", directory / "views.rsp"
    environment = dict(os.environ)
    import_command(
        [
            str(build / "crust"),
            str(source.with_name("main.crs")),
            "--emit-c",
            "--symbols",
            str(symbols),
            "-o",
            str(generated),
            str(source),
        ],
        env=environment,
    )
    import_command([str(build / "crust-ownership-erasure"), str(source)], env=environment)
    execute(generated, symbols, directory, "views", sanitize, b"OK\n")
    bodyless(build, directory, source, environment)
    check_native_cases(build, directory, sanitize)
    cases = {**reject_cases(), **lifetime_cases()}
    rejected(build / "crust-ownership-test", directory, cases)
    print(
        f"stored views: native O0/O2, erasure, bodyless import, no solver, {len(cases)} rejections"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-views-", dir=args.build) as temporary:
        run(args.build.resolve(), Path(temporary), args.sanitize)


if __name__ == "__main__":
    main()
