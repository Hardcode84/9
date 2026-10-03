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
    var p:*u8=move value.pointer;
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
        **pointer_move_cases(),
    }


def pointer_move_cases():
    return {
        "pointer-local": (
            source("var p:*u8=allocate(1usize);var q:*u8=move p;release(q);"),
            b"",
        ),
        "pointer-explicit-clear": (
            source("var owner:Box=box_new();").replace(
                "var p:*u8=move value.pointer;",
                "var p:*u8=value.pointer;value.pointer=null(*u8);",
            ),
            b"D",
        ),
        "pointer-field-reinitialize": (
            source(
                "var owner:Box=box_new();var p:*u8=move owner.pointer;"
                "release(p);owner.pointer=null(*u8);"
            ),
            b"D",
        ),
        "pointer-field-self-move": (
            source("var owner:Box=box_new();owner.pointer=move owner.pointer;see(read owner);"),
            b"SD",
        ),
        "pointer-field-return": (
            source(
                "var owner:Box=box_new();var p:*u8=take(mut owner);"
                "release(p);owner.pointer=null(*u8);",
                "fn take(value:mut Box)->*u8 {unsafe {return move value.pointer;}}",
            ),
            b"D",
        ),
        "pointer-index-once": (
            source(
                "var slots:[*u8;2]=make [*u8;2] {allocate(1usize),null(*u8)};"
                "var index:usize=0usize;var p:*u8=move slots[next(&index)];"
                "if index!=1usize {trap;}release(p);",
                "fn next(index:*usize)->usize {unsafe {var old:usize=*index;"
                "*index=old+1usize;return old;}}",
            ),
            b"",
        ),
        "pointer-indirect": (
            source(
                "var owner:Box=box_new();var slot:**u8=&owner.pointer;"
                "var p:*u8=move *slot;release(p);owner.pointer=null(*u8);"
            ),
            b"D",
        ),
        "pointer-branch": (
            source(
                "var owner:Box=box_new();if argc==1i32 {"
                "var p:*u8=move owner.pointer;release(p);owner.pointer=null(*u8);}"
            ),
            b"D",
        ),
        "pointer-sibling-field": (
            source(
                "var pair:Pair=make Pair {a:allocate(1usize),b:allocate(1usize)};"
                "var p:*u8=move pair.a;release(p);var q:*u8=move pair.b;release(q);",
                "record Pair {a:*u8;b:*u8;}",
            ),
            b"",
        ),
        "pointer-parent-and-child": (
            source(
                "var item:Parent=make Parent {child:box_new(),pointer:allocate(1usize)};",
                "resource Parent {child:Box;pointer:*u8;} drop parent_drop;"
                "fn parent_drop(value:mut Parent)->unit {unsafe {"
                "var p:*u8=move value.pointer;release(p);}}",
            ),
            b"D",
        ),
    }


def reject_cases():
    cases = {
        "double-release": source("var owner:Box=box_new();").replace(
            "release(p);", "release(p);release(p);"
        ),
        "missing-release": source("var owner:Box=box_new();").replace("release(p);", ""),
        "retained-owner-pointer": source("var owner:Box=box_new();").replace(
            "move value.pointer", "value.pointer"
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
        **pointer_move_rejections(),
    }
    rejected = {name: (text, "counterexample") for name, text in cases.items()}
    rejected["pointer-read-loan"] = (
        source(
            "var owner:Box=box_new();var view:read Box=read owner;"
            "var p:*u8=move view.pointer;release(p);"
        ),
        "read",
    )
    return rejected


def pointer_move_rejections():
    return {
        "pointer-local-reread": source("var p:*u8=null(*u8);var q:*u8=move p;var stale:*u8=p;"),
        "pointer-field-reread": source("var owner:Box=box_new();").replace(
            "release(p);", "var stale:*u8=value.pointer;release(p);"
        ),
        "pointer-field-double-move": source("var owner:Box=box_new();").replace(
            "release(p);", "var stale:*u8=move value.pointer;release(p);"
        ),
        "pointer-slot-alias": source(
            "var owner:Box=box_new();var slot:**u8=&owner.pointer;"
            "var p:*u8=move owner.pointer;var stale:*u8=*slot;"
            "release(p);owner.pointer=null(*u8);"
        ),
        "pointer-owner-alias": source(
            "var owner:Box=box_new();var alias:*Box=&owner;"
            "var p:*u8=move owner.pointer;var stale:*u8=(*alias).pointer;"
            "release(p);owner.pointer=null(*u8);"
        ),
        "pointer-retained-observer": source(
            "var observer:Observer=make Observer {pointer:null(*u8)};"
            "{var owner:Box=box_new();observer.pointer=owner.pointer;}",
            "record Observer {pointer:*u8;}",
        ),
        "pointer-drop-twice": source("var owner:Box=box_new();box_drop(mut owner);"),
        "pointer-reentry-before-release": source(
            "var owner:Box=box_new();",
            "fn callback(value:read Box)->unit {unsafe {var stale:*u8=value.pointer;}}",
        ).replace("release(p);", "callback(read value);release(p);"),
        "pointer-reentry-after-release": source(
            "var owner:Box=box_new();",
            "fn callback(value:read Box)->unit {unsafe {var stale:*u8=value.pointer;}}",
        ).replace("release(p);", "release(p);callback(read value);"),
        "pointer-pointee-after-release": source("var owner:Box=box_new();").replace(
            "release(p);", "release(p);if p!=null(*u8) {var stale:i32=*(p as *i32);}"
        ),
        "pointer-deferred-reread": source(
            "var owner:Box=box_new();var slot:**u8=&owner.pointer;"
            "defer see(read owner);var p:*u8=move *slot;release(p);"
        ),
        "pointer-incomplete-owner-move": source(
            "var owner:Box=box_new();var p:*u8=move owner.pointer;"
            "var second:Box=move owner;release(p);"
        ),
        "pointer-child-already-consumed": source(
            "var item:Parent=make Parent {child:box_new()};",
            "resource Parent {child:Box;} drop parent_drop;"
            "fn parent_drop(value:mut Parent)->unit {unsafe {"
            "var p:*u8=move value.child.pointer;release(p);}}",
        ),
        "pointer-argument-order": source(
            "var owner:Box=box_new();both(move owner.pointer,owner.pointer);",
            "fn both(a:*u8,b:*u8)->unit {unsafe {release(a);}}",
        ),
        "pointer-branch-reread": source(
            "var owner:Box=box_new();if argc==1i32 {"
            "var p:*u8=move owner.pointer;release(p);}see(read owner);"
        ),
    }


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
        # Pointer moves must emit the same operations as ordinary pointer reads.
        # Whole-owner moves retain their resource lowering in this comparison.
        for operand in (
            "value.pointer",
            "owner.pointer",
            "p;",
            "slots[next(&index)]",
            "*slot",
            "pair.a",
            "pair.b",
        ):
            text = text.replace("move " + operand, operand)
        path.write_text(text)
        command([build / "crust-resource", "--emit-c", "-o", ordinary, path])
        if generated.read_bytes() != ordinary.read_bytes():
            raise RuntimeError(f"{name}: pointer move added target operations")
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
    tutorial = ROOT / "examples/intrusive"
    links = ROOT / "examples/ownership/links.crs"
    program = tutorial / "closed-program.crs"
    generated = directory / "intrusive.c"
    symbols = directory / "intrusive.rsp"
    command(
        [
            build / "crust",
            tutorial / "closed-main.crs",
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
        "head-dies-with-links": (
            "while head.hook.next != &head.hook { unlink(head.hook.next); }",
            "",
        ),
    }
    for name, (old, new) in mutations.items():
        if old not in original:
            raise RuntimeError(f"{name}: mutation does not match source")
        path = directory / f"{name}.crs"
        path.write_text(original.replace(old, new, 1))
        result = command(
            [build / "crust-resource-memory-test", "--summary", "unlink", "--check", links, path],
            1,
            timeout=600,
        )
        if "counterexample" not in result.stderr.decode():
            raise RuntimeError(f"{name}: expected counterexample: {result.stderr!r}")
        print(f"{name}: rejected", flush=True)
    broken = directory / "broken-unlink.crs"
    link_text = links.read_text()
    repair = "(*after).prev = before;"
    if link_text.count(repair) != 1:
        raise RuntimeError("unlink mutation does not match source")
    broken.write_text(link_text.replace(repair, "", 1))
    result = command(
        [build / "crust-resource-memory-test", "--summary", "unlink", "--check", broken, program],
        1,
        timeout=600,
    )
    if "counterexample" not in result.stderr.decode():
        raise RuntimeError(f"broken unlink summary: expected counterexample: {result.stderr!r}")
    print("broken-unlink-summary: rejected", flush=True)
    return 3 + len(mutations)


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
