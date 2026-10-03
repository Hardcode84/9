#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check initialization delegation through aliases, control flow, and cleanup."""

import argparse
import tempfile
from pathlib import Path

from memory import command
from resource_memory import ROOT, execute, source

SET = "fn set(p:*i32)->unit {unsafe {*p=42i32;}}"
OBSERVE = (
    "resource Observer {p:*i32;} drop observe;"
    "fn observe(value:mut Observer)->unit {unsafe {emit(*value.p);}}"
)
LATER = "fn later(p:*i32)->unit {unsafe {emit(*p);}}"
PAIR = "record Pair {a:i32;b:i32;}"


def accept_cases():
    return {
        "output-scalar": (source("var x:i32=uninit;set(&x);if x!=42i32 {trap;}", SET), b""),
        "output-loan": (
            source(
                "var x:i32=uninit;set(mut x);if x!=42i32 {trap;}",
                "fn set(p:mut i32)->unit {p=42i32;}",
            ),
            b"",
        ),
        "output-returned-loan": (
            source(
                "var x:i32=uninit;set(&x);{var view:read i32=get(read x);"
                "if view!=42i32 {trap;}}x=0i32;",
                SET + "fn get(p:read i32)->read i32 from p {return read p;}",
            ),
            b"",
        ),
        "output-record": (
            source(
                "var pair:Pair=uninit;set(&pair.a);pair.b=3i32;"
                "var copy:Pair=pair;if copy.a!=42i32 || copy.b!=3i32 {trap;}",
                SET + PAIR,
            ),
            b"",
        ),
        "output-array": (
            source(
                "var array:[i32;2]=uninit;set(&array[0usize]);array[1usize]=7i32;"
                "var copy:[i32;2]=array;if copy[0usize]!=42i32 || copy[1usize]!=7i32 {trap;}",
                SET,
            ),
            b"",
        ),
        "output-pointer-transfer": (
            source(
                "var p:*u8=uninit;acquire(&p);var q:*u8=move p;release(q);",
                "fn acquire(out:**u8)->unit {unsafe {*out=allocate(1usize);}}",
            ),
            b"",
        ),
        "output-pointer-reinitialize": (
            source(
                "var p:*u8=null(*u8);var q:*u8=move p;reset(&p);release(p);release(q);",
                "fn reset(out:**u8)->unit {unsafe {*out=null(*u8);}}",
            ),
            b"",
        ),
        "output-branch-mixed": (
            source(
                "var x:i32=uninit;if argc>0i32 {set(&x);}else {x=42i32;}" "if x!=42i32 {trap;}",
                SET,
            ),
            b"",
        ),
        "output-guarded-read": (
            source("var x:i32=uninit;if argc>0i32 {x=42i32;}if argc>0i32 {emit(x);}"),
            b"*",
        ),
        "output-short-circuit": (
            source(
                "var x:i32=uninit;var ok:bool=argc>0i32 && set(&x);" "if ok {if x!=42i32 {trap;}}",
                "fn set(p:*i32)->bool {unsafe {*p=42i32;return true;}}",
            ),
            b"",
        ),
        "output-loop-break": (
            source("var x:i32=uninit;while true {x=42i32;break;}if x!=42i32 {trap;}"),
            b"",
        ),
        "output-loop-continue": (
            source(
                "var x:i32=uninit;var i:i32=0i32;while i<2i32 {"
                "if i==0i32 {x=42i32;i=i+1i32;continue;}if x!=42i32 {trap;}i=i+1i32;}"
                "if x!=42i32 {trap;}"
            ),
            b"",
        ),
        "output-drop": (
            source(
                "var x:i32=uninit;set(&x);var owner:Observer=make Observer {p:&x};", SET + OBSERVE
            ),
            b"*",
        ),
        "output-defer": (source("var x:i32=uninit;defer later(&x);set(&x);", SET + LATER), b"*"),
        "output-cleanup-initializes": (
            source("var x:i32=uninit;{defer set(&x);}if x!=42i32 {trap;}", SET),
            b"",
        ),
        "output-owner-construction": (
            source("var owner:Box=uninit;owner=box_new();see(read owner);"),
            b"SD",
        ),
        "output-owner-branch-exit": (
            source("var owner:Box=uninit;if argc>0i32 {owner=box_new();return 0i32;}"),
            b"D",
        ),
        "output-owner-loop": (
            source(
                "var owner:Box=uninit;var i:i32=0i32;while i<2i32 {"
                "owner=box_new();{var taken:Box=move owner;}i=i+1i32;}"
            ),
            b"DD",
        ),
    }


def memory_rejections():
    return {
        "direct-uninitialized": source("var x:i32=uninit;emit(x);"),
        "address-only": source("var x:i32=uninit;var p:*i32=&x;emit(x);"),
        "alias-uninitialized": source("var x:i32=uninit;var p:*i32=&x;emit(*p);"),
        "read-before-output": source(
            "var x:i32=uninit;set(&x);", "fn set(p:*i32)->unit {unsafe {*p=*p+1i32;}}"
        ),
        "wrong-output": source("var x:i32=uninit;var y:i32=uninit;set(&y);emit(x);", SET),
        "partial-record": source("var pair:Pair=uninit;pair.a=3i32;var copy:Pair=pair;", PAIR),
        "partial-array": source("var array:[i32;2]=uninit;array[0usize]=3i32;emit(array[1usize]);"),
        "conditional-output": source(
            "var x:i32=uninit;set(&x,argc);emit(x);",
            "fn set(p:*i32,n:i32)->unit {unsafe {if n>0i32 {*p=42i32;}}}",
        ),
        "conditional-direct": source("var x:i32=uninit;if argc>0i32 {x=42i32;}emit(x);"),
        "short-circuit-output": source(
            "var x:i32=uninit;var ok:bool=argc>0i32 && set(&x);emit(x);",
            "fn set(p:*i32)->bool {unsafe {*p=42i32;return true;}}",
        ),
        "zero-iteration": source("var x:i32=uninit;while false {x=42i32;}emit(x);"),
        "early-break": source(
            "var x:i32=uninit;while true {if argc>0i32 {break;}x=42i32;break;}emit(x);"
        ),
        "early-continue": source(
            "var x:i32=uninit;var i:i32=0i32;while i<2i32 {i=i+1i32;"
            "if i==1i32 {continue;}emit(x);x=42i32;}"
        ),
        "loop-fresh-storage": source(
            "var i:i32=0i32;while i<2i32 {var x:i32=uninit;"
            "if i==0i32 {x=42i32;}else {emit(x);}i=i+1i32;}"
        ),
        "output-pointer-reread": source(
            "var p:*u8=uninit;set(&p);var q:*u8=move p;release(p);release(q);",
            "fn set(out:**u8)->unit {unsafe {*out=null(*u8);}}",
        ),
        "drop-uninitialized": source(
            "var x:i32=uninit;var guard:Observer=make Observer {p:&x};", OBSERVE
        ),
        "defer-uninitialized": source("var x:i32=uninit;defer later(&x);", LATER),
        "defer-capture-too-soon": source(
            "var x:i32=uninit;defer show(x);set(&x);",
            SET + "fn show(x:i32)->unit {unsafe {emit(x);}}",
        ),
        "drop-before-output": source(
            "var x:i32=uninit;defer set(&x);var guard:Observer=make Observer {p:&x};",
            SET + OBSERVE,
        ),
        "invalid-before-trap": source("var x:i32=uninit;emit(x);trap;").replace(
            "trap;return 0i32;", "trap;"
        ),
    }


def resource_rejections():
    cases = {
        "owner-unconstructed": ("var owner:Box=uninit;see(read owner);", "uninitialized"),
        "owner-moved": ("var owner:Box=box_new();consume(move owner);see(read owner);", "moved"),
        "owner-branch": (
            "var owner:Box=uninit;if argc>0i32 {owner=box_new();}",
            "continuing paths",
        ),
        "owner-loop": ("var owner:Box=uninit;while true {owner=box_new();break;}", "loop edges"),
        "loan-uninitialized": ("var view:read i32=uninit;", "borrowed bindings"),
        "plain-active-read": (
            "var x:i32=uninit;set(&x);var view:read i32=read x;x=7i32;",
            "active borrow",
        ),
        "plain-active-mut": (
            "var x:i32=uninit;set(&x);var view:mut i32=mut x;emit(x);",
            "active borrow",
        ),
    }
    rejected = {name: (source(text, SET), message) for name, (text, message) in cases.items()}
    rejected["owned-record"] = (
        source("var item:Parcel=uninit;item.child=box_new();", "record Parcel {child:Box;}"),
        "uninitialized",
    )
    rejected["owned-array"] = (
        source("var items:[Box;2]=uninit;items[0usize]=box_new();"),
        "uninitialized",
    )
    rejected["output-owner"] = (
        source(
            "var owner:Box=uninit;set_owner(&owner);see(read owner);",
            "fn set_owner(p:*Box)->unit {unsafe {(*p).pointer=null(*u8);}}",
        ),
        "uninitialized",
    )
    return rejected


def run_suite(build, directory, sanitize):
    compiler = build / "crust-resource-memory-test"
    count = 0
    for name, (text, output) in accept_cases().items():
        path = directory / f"{name}.crs"
        path.write_text(text)
        generated, symbols = directory / f"{name}.c", directory / f"{name}.rsp"
        command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, path])
        execute(generated, symbols, directory, name, sanitize, output)
        count += 1
        print(f"{name}: accepted, executed", flush=True)
    rejected = {name: (text, "counterexample") for name, text in memory_rejections().items()}
    rejected.update(resource_rejections())
    for name, (text, message) in rejected.items():
        path, output = directory / f"{name}.crs", directory / f"{name}.c"
        path.write_text(text)
        output.write_text("preserve output\n")
        result = command([compiler, "--emit-c", "-o", output, path], 1)
        if message not in result.stderr.decode() or output.read_text() != "preserve output\n":
            raise RuntimeError(f"{name}: invalid rejection: {result.stderr!r}")
        count += 1
        print(f"{name}: rejected", flush=True)
    for name in ("output-scalar", "output-loan", "output-branch-mixed", "output-loop-break"):
        path = directory / f"{name}.crs"
        result = command([build / "crust-resource", "--check", path], 1)
        if not any(
            word in result.stderr.decode()
            for word in ("uninitialized", "continuing paths", "loop edges")
        ):
            raise RuntimeError(f"{name}: standalone policy changed: {result.stderr!r}")
        count += 1
    return count


def intrusive_case(build, directory, sanitize):
    program = ROOT / "examples/intrusive/output-init.crs"
    root = ROOT / "examples/intrusive/output-main.crs"
    links = ROOT / "examples/ownership/links.crs"
    generated, symbols = directory / "output-init.c", directory / "output-init.rsp"
    command(
        [build / "crust", root, "--emit-c", "--symbols", symbols, "-o", generated, links, program],
        timeout=600,
    )
    execute(generated, symbols, directory, "output-init", sanitize, b"OK\n")
    for name, text in (
        ("missing-node-init", program.read_text().replace("hook_init(&node);", "")),
        ("missing-detach", program.read_text().replace("unlink(value.hook);", "")),
    ):
        path = directory / f"{name}.crs"
        path.write_text(text)
        result = command([build / "crust", root, "--check", links, path], 1)
        if "counterexample" not in result.stderr.decode():
            raise RuntimeError(f"{name}: invalid rejection: {result.stderr!r}")
    return 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(
        prefix="resource-initialization-", dir=args.build
    ) as temporary:
        count = run_suite(args.build.resolve(), Path(temporary), args.sanitize)
        count += intrusive_case(args.build.resolve(), Path(temporary), args.sanitize)
    print(f"resource initialization: {count} cases")


if __name__ == "__main__":
    main()
