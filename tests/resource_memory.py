#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check resource cleanup and memory proofs through the selected stage."""

import argparse
import fnmatch
import tempfile
from pathlib import Path

from memory import FOREIGN, command

ROOT = Path(__file__).resolve().parents[1]
BOX = """
resource Box {pointer:*u8;} drop box_drop;
fn box_new()->Box {unsafe {
    var p:*u8=allocate(sizeof(i32));
    if p!=null(*u8) {*(p as *i32)=42i32;}
    return make Box {pointer:p};
}}
fn box_drop(value:mut Box)->unit {unsafe {
    var p:*u8=value.pointer;
    value.pointer=null(*u8);
    release(p);
    emit(68i32);
}}
fn see(value:read Box)->unit {unsafe {
    if value.pointer!=null(*u8) {if *(value.pointer as *i32)!=42i32 {trap;}}
    emit(83i32);
}}
fn consume(value:Box)->unit {see(read value);}
"""


def source(body, declarations=""):
    return (
        FOREIGN
        + BOX
        + declarations
        + "fn main(argc:i32,argv:**u8)->i32 {unsafe {"
        + body
        + "return 0i32;}}"
    )


def accept_cases():
    return {
        "defer-borrow": (source("var owner:Box=box_new();defer see(read owner);"), b"SD"),
        "defer-move": (source("var owner:Box=box_new();defer consume(move owner);"), b"SD"),
        "owner-move": (
            source("var owner:Box=box_new();var second:Box=move owner;see(read second);"),
            b"SD",
        ),
        "owner-argument": (source("var owner:Box=box_new();consume(move owner);"), b"SD"),
        "owner-return": (
            source(
                "var owner:Box=forward();see(read owner);",
                "fn forward()->Box {var item:Box=box_new();return move item;}",
            ),
            b"SD",
        ),
        "owner-replacement": (source("var owner:Box=box_new();owner=box_new();"), b"DD"),
        "nested-owner": (
            source(
                "var owner:Box=box_new();var parcel:Parcel=make Parcel {item:move owner};",
                "record Parcel {item:Box;}",
            ),
            b"D",
        ),
        "owner-array": (
            source("var items:[Box;2]=make [Box;2] {box_new(),box_new()};"),
            b"DD",
        ),
        "loop-cleanup": (
            source(
                "var i:i32=0i32;while true {var owner:Box=box_new();i=i+1i32;"
                "if i<2i32 {continue;}break;}"
            ),
            b"DD",
        ),
        "return-capture": (
            source(
                "var value:i32=captured();if value!=42i32 {trap;}",
                "resource Clear {pointer:*i32;} drop clear;"
                "fn clear(value:mut Clear)->unit {unsafe {*value.pointer=0i32;}}"
                "fn captured()->i32 {unsafe {var x:i32=42i32;"
                "var guard:Clear=make Clear {pointer:&x};return x;}}",
            ),
            b"",
        ),
        "returned-loan": (
            source(
                "var owner:Box=box_new();var view:read Box=view_of(read owner);see(read view);",
                "fn view_of(value:read Box)->read Box from value {return read value;}",
            ),
            b"SD",
        ),
        "same-scope-cycle": (
            source(
                "var a:Link=make Link {next:null(*Link)};"
                "var b:Link=make Link {next:&a};a.next=&b;",
                "record Link {next:*Link;}",
            ),
            b"",
        ),
        "aggregate-copy": (
            source(
                "var a:Pair=make Pair {values:make [i32;2] {3i32,7i32}};"
                "var b:Pair=a;b=b;if b.values[1usize]!=7i32 {trap;}",
                "record Pair {values:[i32;2];}",
            ),
            b"",
        ),
    }


def reject_cases():
    cases = {
        "double-release": source("var owner:Box=box_new();").replace(
            "release(p);", "release(p);release(p);"
        ),
        "missing-release": source("var owner:Box=box_new();").replace("release(p);", ""),
        "retained-owner-pointer": source("var owner:Box=box_new();").replace(
            "value.pointer=null(*u8);", ""
        ),
        "access-after-cleanup": source(
            "var alias:*u8=null(*u8);{var owner:Box=box_new();alias=owner.pointer;}"
            "if alias!=null(*u8) {var value:i32=*(alias as *i32);}"
        ),
        "moved-owner-alias": source(
            "var owner:Box=box_new();var alias:*Box=&owner;var second:Box=move owner;"
            "var stale:*u8=(*alias).pointer;"
        ),
        "late-defer": source(
            "var p:*u8=allocate(sizeof(i32));if p==null(*u8) {return 0i32;}"
            "*(p as *i32)=42i32;defer later(p);release(p);",
            "fn later(p:*u8)->unit {unsafe {var value:i32=*(p as *i32);}}",
        ),
        "outer-drop-reads-dead-inner": source(
            "var owner:Observer=make Observer {pointer:null(*i32)};"
            "{var x:i32=42i32;owner.pointer=&x;return 0i32;}",
            "resource Observer {pointer:*i32;} drop observe;"
            "fn observe(value:mut Observer)->unit {unsafe {var x:i32=*value.pointer;}}",
        ).replace("}return 0i32;}}", "}}}"),
        "returned-stack-address": source(
            "var p:*i32=local();var value:i32=*p;",
            "fn local()->*i32 {unsafe {var x:i32=42i32;return &x;}}",
        ),
        "loop-stale-address": source(
            "var saved:*i32=null(*i32);var i:i32=0i32;while i<2i32 {"
            "var x:i32=42i32;if i==0i32 {saved=&x;} else {var stale:i32=*saved;}i=i+1i32;}"
        ),
        "forget-leaks": source("var owner:Box=box_new();forget move owner;"),
        "invalid-before-trap": source("var bad:i32=*null(*i32);trap;").replace(
            "trap;return 0i32;", "trap;"
        ),
    }
    return {name: (text, "counterexample") for name, text in cases.items()}


def execute(generated, symbols, directory, name, sanitize, output):
    for optimization in ("-O0", "-O2"):
        binary = directory / f"{name}{optimization}"
        flags = [optimization]
        if sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-no-pie"]
        raw = binary.with_suffix(".input.o")
        renamed = binary.with_suffix(".o")
        command(["gcc", "-std=c99", "-pedantic-errors", *flags, "-c", generated, "-o", raw])
        command(["objcopy", f"@{symbols}", raw, renamed])
        command(["gcc", *flags, renamed, "-o", binary])
        result = command([binary])
        if result.stdout != output:
            raise RuntimeError(f"{name}: expected {output!r}, got {result.stdout!r}")


def run_suite(build, directory, sanitize, pattern):
    compiler = build / "crust-resource-memory-test"
    count = 0
    for name, (text, output) in accept_cases().items():
        if not fnmatch.fnmatchcase(name, pattern):
            continue
        path = directory / f"{name}.crs"
        path.write_text(text)
        generated = directory / f"{name}.c"
        symbols = directory / f"{name}.rsp"
        ordinary = directory / f"{name}-ordinary.c"
        command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, path])
        command([build / "crust-resource", "--emit-c", "-o", ordinary, path])
        if generated.read_bytes() != ordinary.read_bytes():
            raise RuntimeError(f"{name}: proof changed resource C output")
        execute(generated, symbols, directory, name, sanitize, output)
        count += 1
        print(f"{name}: accepted, erased, executed", flush=True)
    for name, (text, diagnostic) in reject_cases().items():
        if not fnmatch.fnmatchcase(name, pattern):
            continue
        path = directory / f"{name}.crs"
        path.write_text(text)
        generated = directory / f"{name}.c"
        generated.write_text("preserve output\n")
        result = command([compiler, "--emit-c", "-o", generated, path], 1)
        if diagnostic not in result.stderr.decode():
            raise RuntimeError(f"{name}: missing {diagnostic}: {result.stderr.decode()}")
        if generated.read_text() != "preserve output\n":
            raise RuntimeError(f"{name}: failed proof changed output")
        count += 1
        print(f"{name}: rejected", flush=True)
    return count


def intrusive_cases(build, directory, sanitize):
    tutorial = ROOT / "examples/ownership/resources"
    links = tutorial.parent / "links.crs"
    program = tutorial / "program.crs"
    generated = directory / "intrusive.c"
    symbols = directory / "intrusive.rsp"
    command(
        [
            build / "crust",
            tutorial / "main.crs",
            "--emit-c",
            "--symbols",
            symbols,
            "-o",
            generated,
            links,
            program,
        ],
        timeout=600,
    )
    execute(generated, symbols, directory, "intrusive", sanitize, b"OK\n")
    basic = command([build / "crust-resource", "--check", links, program], 1)
    if "unsafe" not in basic.stderr.decode():
        raise RuntimeError(f"basic profile: expected raw-access rejection: {basic.stderr!r}")
    original = program.read_text()
    mutations = {
        "second-hook-still-linked": ("unlink(&(*node).active);", ""),
        "head-dies-with-links": ("while head.hook.next!=&head.hook {unlink(head.hook.next);}", ""),
    }
    for name, (old, new) in mutations.items():
        if old not in original:
            raise RuntimeError(f"{name}: mutation does not match source")
        path = directory / f"{name}.crs"
        path.write_text(original.replace(old, new, 1))
        result = command(
            [build / "crust-resource-memory-test", "--check", links, path], 1, timeout=600
        )
        if "counterexample" not in result.stderr.decode():
            raise RuntimeError(f"{name}: expected counterexample: {result.stderr!r}")
        print(f"{name}: rejected", flush=True)
    return 2 + len(mutations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--filter", default="*")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="resource-memory-", dir=args.build) as temporary:
        count = run_suite(args.build.resolve(), Path(temporary), args.sanitize, args.filter)
        if args.filter in ("*", "intrusive"):
            count += intrusive_cases(args.build.resolve(), Path(temporary), args.sanitize)
    print(f"resource memory: {count} cases")


if __name__ == "__main__":
    main()
