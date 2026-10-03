#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise the optional memory stage on target code and emitted programs."""

import argparse
import fnmatch
import shlex
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOREIGN = """
extern fn allocate(size:usize)->*u8="malloc";
extern fn release(pointer:*u8)->unit="free";
extern fn emit(code:i32)->i32="putchar";
"""
RECORDS = "record Cell {value:i32;} record Link {next:*Link;}"
ALLOCATE = "var p:*Cell=allocate(sizeof(Cell)) as *Cell;if p==null(*Cell) {return 0i32;}"
SLOT_TYPE = "record Use {next:*Use;prev:**Use;}"
SLOT_SETUP = "var head:*Use=null(*Use);var a:Use=uninit;a.next=null(*Use);a.prev=&head;head=&a;{var b:Use=uninit;b.next=head;b.prev=&head;a.prev=&b.next;head=&b;*b.prev=b.next;"


def source(body, declarations=""):
    return (
        FOREIGN
        + RECORDS
        + declarations
        + "fn main(argc:i32,argv:**u8)->i32 {"
        + body
        + "return 0i32;}"
    )


def accept_cases():
    return {
        "heap-write-read-release": source(
            ALLOCATE
            + "(*p).value=42i32;var x:i32=(*p).value;release(p as *u8);if x!=42i32 {return 1i32;}"
        ),
        "null-release": source("release(null(*u8));"),
        "local-address": source("var x:i32=42i32;var p:*i32=&x;*p=7i32;if x!=7i32 {return 1i32;}"),
        "uninitialized-place": source(
            "var x:i32=uninit;var p:*i32=&x;*p=3i32;if x!=3i32 {return 1i32;}"
        ),
        "field-initialization": source(
            "var x:Cell=uninit;x.value=7i32;if x.value!=7i32 {return 1i32;}"
        ),
        "array-initialization": source(
            "var a:[i32;2]=make [i32;2] {3i32,7i32};if a[1usize]!=7i32 {return 1i32;}"
        ),
        "branch-initialization": source(
            "var x:i32=uninit;if argc>0i32 {x=1i32;} else {x=2i32;}var y:i32=x;"
        ),
        "bounded-loop": source("var x:i32=0i32;while x<3i32 {x=x+1i32;}if x!=3i32 {return 1i32;}"),
        "bounded-branch-loop": source(
            "var n:i32=0i32;var y:i32=0i32;while n<2i32 {if n==0i32 {y=1i32;}else {y=2i32;}n=n+1i32;}if y!=2i32 {return 1i32;}"
        ),
        "break-and-continue": source(
            "var x:i32=0i32;while true {x=x+1i32;if x==1i32 {continue;}break;}if x!=2i32 {return 1i32;}"
        ),
        "short-circuit": source(
            "var p:*i32=null(*i32);var a:bool=false && *p==0i32;var b:bool=true || *p==0i32;"
        ),
        "direct-call-write": source(
            "var x:i32=0i32;set(&x);if x!=7i32 {return 1i32;}", "fn set(p:*i32)->unit {*p=7i32;}"
        ),
        "value-call-with-branches": source(
            "var x:i32=0i32;var p:*i32=select(&x,argc>0i32);var value:i32=*p;",
            "fn select(p:*i32,test:bool)->*i32 {if test {*p=7i32;} else {*p=9i32;}return p;}",
        ),
        "aggregate-copy-and-self-copy": source(
            "var a:[Cell;2]=make [Cell;2] {make Cell {value:3i32},make Cell {value:7i32}};"
            "var b:[Cell;2]=a;b=b;if b[1usize].value!=7i32 {return 1i32;}"
        ),
        "aggregate-constructor-alias": source(
            "var a:[i32;2]=make [i32;2] {0i32,1i32};a=make [i32;2] {a[1usize],a[0usize]};"
            "if a[0usize]!=1i32 || a[1usize]!=0i32 {return 1i32;}"
        ),
        "record-constructor-alias": source(
            "var a:Pair=make Pair {x:0i32,y:1i32};a=make Pair {x:a.y,y:a.x};"
            "if a.x!=1i32 || a.y!=0i32 {return 1i32;}",
            "record Pair {x:i32;y:i32;}",
        ),
        "same-scope-cycle": source(
            "var a:Link=make Link {next:null(*Link)};var b:Link=make Link {next:&a};a.next=&b;"
        ),
        "projected-call": source(
            "var c:Cell=make Cell {value:9i32};var p:*i32=field(&c);if *p!=9i32 {return 1i32;}",
            "fn field(p:*Cell)->*i32 {return &(*p).value;}",
        ),
        "unlink-before-free": source(
            "var head:Link=make Link {next:null(*Link)};var node:*Link=allocate(sizeof(Link)) as *Link;if node==null(*Link) {return 0i32;}(*node).next=null(*Link);head.next=node;head.next=null(*Link);release(node as *u8);"
        ),
        "slot-pointer": source(
            "var head:*Link=null(*Link);var node:Link=make Link {next:null(*Link)};var slot:**Link=&head;*slot=&node;*slot=null(*Link);"
        ),
        "pointer-to-pointer-unlink": source(
            SLOT_SETUP
            + "(*b.next).prev=b.prev;}if head!=&a || a.prev!=&head {return 1i32;}*a.prev=a.next;",
            SLOT_TYPE,
        ),
        "pointer-comparison-after-free": source(
            ALLOCATE
            + "release(p as *u8);var q:*Cell=allocate(sizeof(Cell)) as *Cell;if q==null(*Cell) {return 0i32;}(*q).value=7i32;if p==q {var x:i32=(*q).value;}release(q as *u8);"
        ),
        "parameter-reassignment": source(
            "var x:i32=0i32;write(&x,&x);if x!=7i32 {return 1i32;}",
            "fn write(p:*i32,q:*i32)->unit {{p=q;}*p=7i32;}",
        ),
        "skipped-parameter-address": source(
            "var ignored:bool=true || local_address(1i32);",
            "fn local_address(value:i32)->bool {return &value==null(*i32);}",
        ),
        "scalar-storage-reassignment": source(
            "var x:i32=1i32;{x=2i32;}if x!=2i32 {var bad:i32=*null(*i32);}if x!=2i32 {return 1i32;}"
        ),
        "scalar-storage-pointer-reassignment": source(
            "var x:i32=3i32;var y:i32=7i32;var p:*i32=&x;var q:*i32=p;p=&y;if *p!=7i32 || *q!=3i32 {return 1i32;}"
        ),
        "scalar-storage-skipped-uninitialized": source(
            "var x:i32=uninit;var p:*i32=uninit;var a:bool=false && x==0i32;var b:bool=true || *p==0i32;if a || !b {return 1i32;}"
        ),
        "scalar-storage-addressed-parameter": source(
            "var x:i32=0i32;var y:i32=0i32;set(&x,&y);if x!=0i32 || y!=7i32 {return 1i32;}",
            "fn set(p:*i32,q:*i32)->unit {var slot:**i32=&p;{p=q;}**slot=7i32;}",
        ),
        "scalar-storage-alias-write": source(
            "var x:i32=1i32;var p:*i32=&x;x=2i32;*p=7i32;if x!=7i32 {var bad:i32=*null(*i32);}if x!=7i32 {return 1i32;}"
        ),
        "scalar-storage-loop-initialization": source(
            "var i:i32=0i32;var sum:i32=0i32;while i<2i32 {var x:i32=uninit;x=i+1i32;sum=sum+x;i=i+1i32;}if sum!=3i32 {return 1i32;}"
        ),
    }


def reject_cases():
    counterexample = "counterexample"
    cases = {
        "impossible-stack-layout-before-access": source(
            "var a:[u8;9223372036854775807]=uninit;var b:[u8;9223372036854775807]=uninit;var c:[u8;9223372036854775807]=uninit;var p:*i32=null(*i32);var x:i32=*p;"
        ),
        "prefix-before-impossible-stack-layout": source(
            "var p:*i32=null(*i32);var x:i32=*p;var a:[u8;9223372036854775807]=uninit;var b:[u8;9223372036854775807]=uninit;"
        ),
        "pruned-prefix-before-impossible-layout": source(
            "var p:*i32=null(*i32);var x:i32=*p;var a:[u8;9223372036854775807]=uninit;var b:[u8;9223372036854775807]=uninit;if argc>0i32 {return 1i32;}"
        ),
        "null-dereference": source("var p:*i32=null(*i32);var x:i32=*p;"),
        "use-after-free": source(
            ALLOCATE + "(*p).value=1i32;release(p as *u8);var x:i32=(*p).value;"
        ),
        "double-free": source(ALLOCATE + "release(p as *u8);release(p as *u8);"),
        "value-call-use-after-release": source(
            ALLOCATE + "(*p).value=7i32;var x:i32=destroy(p);",
            "fn destroy(p:*Cell)->i32 {release(p as *u8);return (*p).value;}",
        ),
        "uninitialized-aggregate-copy": source("var a:Cell=uninit;var b:Cell=a;"),
        "constructor-alias-hides-null-access": source(
            "var a:[i32;2]=make [i32;2] {0i32,1i32};a=make [i32;2] {a[1usize],a[0usize]};"
            "if a[1usize]==0i32 {var bad:i32=*null(*i32);}"
        ),
        "interior-free": source(ALLOCATE + "release((p as *u8)+1isize);"),
        "stack-free": source("var x:i32=0i32;release(&x as *u8);"),
        "uninitialized-local": source("var x:i32=uninit;var y:i32=x;"),
        "uninitialized-field": source("var x:Cell=uninit;var y:i32=x.value;"),
        "uninitialized-heap": source(ALLOCATE + "var x:i32=(*p).value;release(p as *u8);"),
        "conditional-initialization": source("var x:i32=uninit;if argc>0i32 {x=1i32;}var y:i32=x;"),
        "out-of-bounds": source(
            "var a:[i32;2]=make [i32;2] {1i32,2i32};var p:*i32=&a[0usize];var x:i32=p[2usize];"
        ),
        "negative-index": source("var x:i32=0i32;var p:*i32=&x;var y:i32=*(p-1isize);"),
        "out-and-back": source("var x:i32=0i32;var p:*i32=&x;var q:*i32=(p+2isize)-2isize;"),
        "misaligned": source(
            "var x:i64=0i64;var p:*i32=((&x as *u8)+1isize) as *i32;var y:i32=*p;"
        ),
        "escaped-stack": source("var p:*i32=null(*i32);{var x:i32=7i32;p=&x;}var y:i32=*p;"),
        "retained-link": source(
            "var head:Link=make Link {next:null(*Link)};var node:*Link=allocate(sizeof(Link)) as *Link;if node==null(*Link) {return 0i32;}head.next=node;release(node as *u8);"
        ),
        "leaked-owner": source(ALLOCATE),
        "unbounded-loop": source("var x:i32=0i32;while x<argc {x=x+1i32;}"),
        "invalid-before-trap": source("var p:*i32=null(*i32);var x:i32=*p;trap;"),
        "division-before-trap": source("var x:i32=argc/0i32;trap;"),
        "stale-same-address": source(
            ALLOCATE
            + "release(p as *u8);var q:*Cell=allocate(sizeof(Cell)) as *Cell;if q==null(*Cell) {return 0i32;}(*q).value=7i32;if p==q {var x:i32=(*p).value;}release(q as *u8);"
        ),
        "parameter-assignment-lives-through-block": source(
            "var x:i32=0i32;write(&x);", "fn write(p:*i32)->unit {{p=null(*i32);}*p=7i32;}"
        ),
        "stale-array-element": source(
            "var p:*i32=null(*i32);{var a:[i32;2]=make [i32;2] {1i32,2i32};p=&a[1usize];}var x:i32=*p;"
        ),
        "missing-slot-backlink-repair": source(SLOT_SETUP + "}*a.prev=a.next;", SLOT_TYPE),
        "scalar-storage-reassigned-null": source(
            "var x:i32=7i32;var p:*i32=&x;{p=null(*i32);}var y:i32=*p;"
        ),
        "scalar-storage-conditional-uninitialized": source(
            "var x:i32=uninit;var read:bool=argc>0i32 && x==0i32;"
        ),
        "scalar-storage-addressed-parameter-null": source(
            "var x:i32=0i32;set(&x);",
            "fn set(p:*i32)->unit {var slot:**i32=&p;{p=null(*i32);}**slot=7i32;}",
        ),
        "scalar-storage-returned-parameter-address": source(
            "var p:*i32=local(7i32);var x:i32=*p;", "fn local(value:i32)->*i32 {return &value;}"
        ),
        "scalar-storage-loop-reentry-uninitialized": source(
            "var i:i32=0i32;while i<2i32 {var x:i32=uninit;if i==0i32 {x=7i32;}else {var y:i32=x;}i=i+1i32;}"
        ),
        "scalar-storage-escaped-parameter-alias": source(
            "var p:*i32=null(*i32);publish(7i32,&p);var x:i32=*p;",
            "fn publish(value:i32,out:**i32)->unit {*out=&value;}",
        ),
    }
    result = {name: (text, counterexample) for name, text in cases.items()}
    result.update(
        {
            "forged-pointer": (
                source("var p:*i32=42usize as *i32;var x:i32=*p;"),
                "pointer and integer conversion",
            ),
            "unknown-external": (
                source("unknown();", 'extern fn unknown()->unit="unknown";'),
                "no explicit memory contract",
            ),
            "recursive-call": (
                source("again();", "fn again()->unit {again();}"),
                "recursive proof calls",
            ),
            "indirect-call": (
                source("var call:fn()->unit=noop;call();", "fn noop()->unit {}"),
                "local values or direct function calls",
            ),
        }
    )
    return result


def command(arguments, expected=0, timeout=180):
    result = subprocess.run(
        [str(arg) for arg in arguments], cwd=ROOT, capture_output=True, timeout=timeout
    )
    if result.returncode != expected:
        raise RuntimeError(
            f"{shlex.join(map(str, arguments))}: expected {expected}, got {result.returncode}\n{result.stdout.decode()}{result.stderr.decode()}"
        )
    return result


def ring_cases(build, directory):
    path = ROOT / "examples/ownership/links.crs"
    original = path.read_text()
    command([build / "crust-memory-test", "--ring", "--check", "--library", path])
    mutations = {
        "missing-backlink": ("(*after).prev = before;", ""),
        "null-initial-link": ("(*h).next = h;", "(*h).next = null(*Hook);"),
        "wrong-insert-neighbor": ("(*after).prev = h;", "(*after).prev = at;"),
        "wrong-splice-tail": ("(*after).prev = last;", "(*after).prev = first;"),
        "missing-source-reset": ("(*source).next = source;", ""),
    }
    for name, (old, new) in mutations.items():
        if old not in original:
            raise RuntimeError(f"{name}: mutation does not match source")
        mutated = directory / f"ring-{name}.crs"
        mutated.write_text(original.replace(old, new, 1))
        result = command(
            [build / "crust-memory-test", "--ring", "--check", "--library", mutated], 1
        )
        if "counterexample" not in result.stderr.decode():
            raise RuntimeError(f"{name}: expected proof counterexample: {result.stderr.decode()}")
    return 1 + len(mutations)


def intrusive_cases(build, directory, sanitize):
    links = ROOT / "examples/ownership/links.crs"
    program = ROOT / "examples/ownership/program.crs"
    compiler = build / "crust-memory-test"
    checked = directory / "intrusive.c"
    ordinary = directory / "intrusive-ordinary.c"
    command([compiler, "--emit-c", "-o", checked, links, program])
    command([build / "crust-c", "--emit-c", "-o", ordinary, links, program])
    if checked.read_bytes() != ordinary.read_bytes():
        raise RuntimeError("intrusive program: proof changed emitted C")
    flags = ["--cflag=-O2"]
    if sanitize:
        flags += [
            "--cflag=-fsanitize=address,undefined",
            "--ldflag=-fsanitize=address,undefined",
            "--ldflag=-no-pie",
        ]
    binary = directory / "intrusive"
    command([build / "crust-c", "-o", binary, *flags, links, program])
    result = command([binary])
    if result.stdout != b"OK\n":
        raise RuntimeError(f"intrusive program: unexpected output {result.stdout!r}")
    original = program.read_text()
    mutations = {
        "second-hook-still-linked": ("unlink(&(*node).active);", ""),
        "head-dies-first-with-links": ("clear(&active);", ""),
        "wrong-projector-offset": ("offsetof(Node, ready)", "offsetof(Node, active)"),
    }
    for name, (old, new) in mutations.items():
        if old not in original:
            raise RuntimeError(f"{name}: mutation does not match source")
        path = directory / f"{name}.crs"
        path.write_text(original.replace(old, new, 1))
        result = command([compiler, "--check", links, path], 1)
        if "counterexample" not in result.stderr.decode():
            raise RuntimeError(f"{name}: expected memory counterexample: {result.stderr.decode()}")
    return 1 + len(mutations)


def run_suite(build, directory, sanitize, pattern):
    compiler = build / "crust-memory-test"
    count = 0
    for name, text in accept_cases().items():
        if not fnmatch.fnmatchcase(name, pattern):
            continue
        path = directory / f"{name}.crs"
        path.write_text(text)
        generated = directory / f"{name}.c"
        ordinary = directory / f"{name}-ordinary.c"
        command([compiler, "--emit-c", "-o", generated, path])
        command([build / "crust-c", "--emit-c", "-o", ordinary, path])
        if generated.read_bytes() != ordinary.read_bytes():
            raise RuntimeError(f"{name}: proof changed emitted C")
        binary = directory / name
        flags = (
            ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
            if sanitize
            else ["-O0"]
        )
        link = ["--ldflag=-fsanitize=address,undefined", "--ldflag=-no-pie"] if sanitize else []
        command(
            [build / "crust-c", "-o", binary, path, *[f"--cflag={flag}" for flag in flags], *link]
        )
        command([binary])
        count += 1
    for name, (text, diagnostic) in reject_cases().items():
        if not fnmatch.fnmatchcase(name, pattern):
            continue
        path = directory / f"{name}.crs"
        path.write_text(text)
        output = directory / f"{name}.c"
        output.write_text("keep this output\n")
        result = command([compiler, "--emit-c", "-o", output, path], 1)
        if diagnostic not in result.stderr.decode():
            raise RuntimeError(f"{name}: missing diagnostic {diagnostic}: {result.stderr.decode()}")
        if output.read_text() != "keep this output\n":
            raise RuntimeError(f"{name}: rejected compilation changed output")
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build"))
    parser.add_argument("--filter", default="*")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="memory-", dir=args.build) as temporary:
        count = run_suite(
            args.build.resolve(), Path(temporary).resolve(), args.sanitize, args.filter
        )
        if args.filter in ("*", "ring"):
            count += ring_cases(args.build.resolve(), Path(temporary).resolve())
        if args.filter in ("*", "intrusive"):
            count += intrusive_cases(args.build.resolve(), Path(temporary).resolve(), args.sanitize)
    print(f"memory stage: {count} cases; accepted C is identical to ordinary output")


if __name__ == "__main__":
    main()
