#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check the opaque boundary, local lifetimes, and native container behavior."""

import argparse
import tempfile
from pathlib import Path

from ownership_ending import check_ending
from ownership_expressions import check_expressions
from ownership_places import check_places
from ownership_runtime import check_runtime
from ownership_support import ROOT, SCALAR_FLOW, command, execute
from resources import consumption_rejects


def body(text):
    return "fn main(argc:i32,argv:**u8)->i32 {domain Graph {" + text + "}return 0i32;}"


def rejects():
    owner = "var owner:Owner=owner_new(1i64);"
    head = "var head:ReadyHead=uninit;ready_init(&head);"
    cursor = "var cursor:Cursor=ready_first(read head);"
    return {
        "copy-owner": (body(owner + "var copy:Owner=owner;"), "explicit move"),
        "double-drop": (body(owner + "drop owner;drop owner;"), "has been moved"),
        "after-drop": (
            body(owner + "drop owner;var value:read i64=owner_value(read owner);"),
            "has been moved",
        ),
        "private-read": (body(owner + "var node:*Node=owner.node;"), "private"),
        "private-make": (body("var owner:Owner=make Owner{node:null(*Node)};"), "opaque"),
        "raw-retirement": (body(owner + "release(owner.node as *u8);"), "private"),
        "stable-move": (body(head + "var copy:ReadyHead=move head;"), "address-stable"),
        "stable-replace": (body(head + "ready_init(&head);"), "initialized storage"),
        "drop-during-read": (body(owner + "read Graph {drop owner;}"), "stronger domain authority"),
        "implicit-drop-during-edit": (
            body(owner + "edit Graph {var capture:Owner=move owner;}"),
            "stronger domain authority",
        ),
        "return-cleanup": (
            "fn bad()->i32 {domain Graph {"
            + owner
            + "edit Graph {var capture:Owner=move owner;return 0i32;}}}",
            "stronger domain authority",
        ),
        "head-cleanup": (body(head + "read Graph {drop head;}"), "stronger domain authority"),
        "cursor-escape": (
            body(head + "var saved:Cursor=uninit;read Graph {" + cursor + "saved=move cursor;}"),
            "outlive its access",
        ),
        "cursor-return": (
            "fn bad()->Cursor access(reclaim,Graph) {"
            + head
            + "read Graph {"
            + cursor
            + "return move cursor;}}",
            "escape reclamation",
        ),
        "mutable-alias": (
            body(
                head
                + "edit Graph {"
                + cursor
                + "var a:mut i64=cursor_mut(mut cursor);var b:mut i64=cursor_mut(mut cursor);}"
            ),
            "active",
        ),
        "payload-versus-read-call": (
            body(
                head
                + "edit Graph {"
                + cursor
                + "var a:mut i64=cursor_mut(mut cursor);ready_count(read head);}"
            ),
            "active domain loan",
        ),
        "payload-versus-edit-call": (
            body(
                owner
                + head
                + "edit Graph {"
                + cursor
                + "var a:read i64=cursor_value(read cursor);ready_insert(mut head,read owner);}"
            ),
            "active domain loan",
        ),
        "wrong-instance": (
            body(owner + "domain Graph {" + head + "ready_insert(mut head,read owner);}"),
            "domain",
        ),
        "domain-escape": (
            "fn bad()->Owner access(reclaim,Graph) {domain Graph {return owner_new(1i64);}}",
            "fresh domain",
        ),
        "outer-storage": (
            body("var owner:Owner=uninit;domain Graph {owner=owner_new(1i64);}"),
            "domain instance",
        ),
        "missing-authority": (
            "fn bad()->unit {var owner:Owner=owner_new(1i64);}",
            "stronger domain authority",
        ),
        "borrowed-retirement": (
            body(owner + "read Graph {var view:read Owner=read owner;drop owner;}"),
            "active",
        ),
        "unapproved-type": ("record Private {p:*u8;} opaque;", "explicit trust"),
        "hidden-retainer": ("record Observer {p:*Node;}", "persistent pointers"),
        "heap-formula": ("fn bad()->unit requires(true) {}", "expected '{'"),
        "deferred-reclaim": (
            "fn consume(value:Owner)->unit access(reclaim,Graph) {}"
            + body(owner + "edit Graph {defer consume(move owner);}"),
            "stronger domain authority",
        ),
    }


def local_cases():
    resource = "resource Value {n:i64;} drop dispose;fn dispose(v:mut Value)->unit {}"
    return {
        "defer-borrow": resource
        + "fn observe(v:read Value)->unit {if v.n!=7i64 {trap;}} fn main(argc:i32,argv:**u8)->i32 {var v:Value=make Value{n:7i64};defer observe(read v);return 0i32;}",
        "defer-move": resource
        + "fn consume(v:Value)->unit {} fn main(argc:i32,argv:**u8)->i32 {var v:Value=make Value{n:7i64};defer consume(move v);return 0i32;}",
        "defer-order": 'extern fn emit(c:i32)->i32 foreign(scalar)="putchar";fn put(c:i32)->unit {emit(c);} fn main(argc:i32,argv:**u8)->i32 {defer put(75i32);defer put(79i32);return 0i32;}',
        "scalar-flow": SCALAR_FLOW,
        "domain-after-record": "record Cell {value:i64;} domain D(Cell);"
        "fn main(argc:i32,argv:**u8)->i32 {domain D {"
        "var cell:Cell=make Cell{value:7i64};if cell.value!=7i64 {trap;}}return 0i32;}",
    }


def local_rejects():
    allocation = 'extern fn allocate(size:usize)->*u8 foreign(allocate)="malloc";\n'
    cases = {
        "missing-domain-member": (
            "domain D(Missing);",
            "domain member must name a declared record",
        ),
        "non-record-domain-member": (
            "domain D(value);const value:i64=1i64;",
            "domain member must name a declared record",
        ),
        "duplicate-domain-member": (
            "domain D(Cell,Cell);record Cell {value:i64;}",
            "duplicate ownership field annotation",
        ),
        "multiple-domain-membership": (
            "domain A(Cell);domain B(Cell);record Cell {value:i64;}",
            "record cannot belong to multiple domains",
        ),
        "allocation-byte-count": (
            allocation + "fn bad()->unit {var p:*u8=allocate(8usize);}",
            "allocation size must be sizeof(Record) so the checker can track its fields",
        ),
        "allocation-scalar-type": (
            allocation + "fn bad()->unit {var p:*u8=allocate(sizeof(i64));}",
            "allocation type must be a record with field contracts",
        ),
        "allocation-in-loop": (
            allocation + "record Cell {value:i64;}\n"
            "fn bad(run:bool)->unit {while run {var p:*u8=allocate(sizeof(Cell));}}",
            "direct allocation in a loop requires a helper that returns an owning resource",
        ),
        "uninitialized": ("fn bad()->i64 {var value:i64=uninit;return value;}", "uninitialized"),
        "branch-initialization": (
            "fn bad(test:bool)->i64 {var value:i64=uninit;if test {value=1i64;}return value;}",
            "uninitialized",
        ),
        "return-stack-loan": (
            "fn bad(x:read i64)->read i64 from x {var y:i64=1i64;return read y;}",
            "declared source",
        ),
        "return-wrong-origin": (
            "fn bad(x:read i64,y:read i64)->read i64 from x {return read y;}",
            "declared source",
        ),
        "shared-write": ("fn bad(x:read i64)->unit {x=2i64;}", "shared"),
        "defer-borrow-escape": (
            "fn use(x:read i64)->unit {} fn bad()->unit {var x:i64=1i64;defer use(read x);x=2i64;}",
            "active",
        ),
        "defer-mutable-read": (
            "fn set(x:mut i64)->unit {x=2i64;} fn bad()->i64 {var x:i64=1i64;defer set(mut x);return x;}",
            "active",
        ),
    }
    cases.update({name: (source, diagnostic) for name, source, diagnostic in consumption_rejects()})
    return cases


RUNTIME_TREE = "fn main(argc:i32,argv:**u8)->i32 access(reclaim,Forest) {\n var root:Tree=tree_new(1i64);\n var count:i32=argc+64i32;\n while count>0i32 {\n  var next:Tree=tree_new(2i64);\n  tree_attach_left(mut next,move root);\n  root=move next;\n  count=count-1i32;\n }\n return 0i32;\n}\n"


def run(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    provider = ROOT / "examples/intrusive/links.crs"
    cases = rejects()
    for name, (text, diagnostic) in cases.items():
        path = directory / f"{name}.crs"
        path.write_text(text)
        result = command([compiler, "trusted", provider, "--library", "--check", path], expected=1)
        assert diagnostic in result.stderr.decode(), (name, result.stderr)
    for name, (text, diagnostic) in local_rejects().items():
        path = directory / f"{name}.crs"
        path.write_text(text)
        result = command([compiler, "--library", "--check", path], expected=1)
        assert diagnostic in result.stderr.decode(), (name, result.stderr)
    # Ordinary input cannot grant itself trust, even when its bytes match a library.
    result = command(
        [compiler, "--check", provider, ROOT / "examples/intrusive/program.crs"], expected=1
    )
    assert b"explicit trust" in result.stderr
    for folder, library in [("intrusive", "links.crs"), ("ownership-graphs", "provider.crs")]:
        sources = [
            "trusted",
            ROOT / "examples" / folder / library,
            ROOT / "examples" / folder / "program.crs",
        ]
        generated, symbols = directory / f"{folder}.c", directory / f"{folder}.rsp"
        command(
            [
                compiler,
                *sources[:2],
                "--emit-c",
                "--symbols",
                symbols,
                "-o",
                generated,
                *sources[2:],
            ]
        )
        command([build / "crust-ownership-erasure", *sources])
        execute(generated, symbols, directory, folder, sanitize, b"OK\n")
    runtime_tree = directory / "runtime-tree.crs"
    runtime_tree.write_text(RUNTIME_TREE)
    generated, symbols = runtime_tree.with_suffix(".c"), runtime_tree.with_suffix(".rsp")
    command(
        [
            compiler,
            "trusted",
            ROOT / "examples/ownership-graphs/provider.crs",
            "--emit-c",
            "--symbols",
            symbols,
            "-o",
            generated,
            runtime_tree,
        ]
    )
    command(
        [
            build / "crust-ownership-erasure",
            "trusted",
            ROOT / "examples/ownership-graphs/provider.crs",
            runtime_tree,
        ]
    )
    execute(generated, symbols, directory, "runtime-tree", sanitize, b"")
    heap = (ROOT / "examples/ownership-basics/heap.crs").read_text()
    path = directory / "grouped-allocation.crs"
    path.write_text(heap.replace("allocate(sizeof(Cell))", "allocate((sizeof(Cell)))"))
    command([compiler, "--check", path])
    path = directory / "allocation-helper-loop.crs"
    path.write_text(
        heap[: heap.index("fn main(")] + "fn main(argc:i32,argv:**u8)->i32 access(reclaim,Cells) {"
        "var count:i32=argc;while count>0i32 {var owner:CellOwner=cell_new(65i64);"
        "count=count-1i32;}return 0i32;}"
    )
    command([compiler, "--check", path])
    for name, text in local_cases().items():
        path = directory / f"{name}.crs"
        path.write_text(text)
        generated, symbols = path.with_suffix(".c"), path.with_suffix(".rsp")
        command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, path])
        command([build / "crust-ownership-erasure", path])
        execute(
            generated, symbols, directory, name, sanitize, b"OK" if name == "defer-order" else b""
        )
    forwarded = directory / "forwarded.crs"
    forwarded.write_text(
        "fn initialize(head:*ReadyHead)->unit access(reclaim,Graph) initializes(head) {ready_init(head);}"
        + body("var head:ReadyHead=uninit;initialize(&head);")
    )
    command([compiler, "trusted", provider, "--check", forwarded])
    duplicate_provider = directory / "duplicate-provider.crs"
    duplicate_provider.write_text(
        provider.read_text()
        + "fn twice(a:*ReadyHead,b:*ReadyHead)->unit access(reclaim,Graph) initializes(a,b) {ready_init(a);ready_init(b);}"
    )
    duplicate = directory / "duplicate-output.crs"
    duplicate.write_text(body("var head:ReadyHead=uninit;twice(&head,&head);"))
    result = command([compiler, "trusted", duplicate_provider, "--check", duplicate], expected=1)
    assert b"active" in result.stderr, result.stderr
    check_places(build, directory, sanitize)
    check_expressions(build, directory, sanitize)
    check_ending(build, directory, sanitize)
    check_runtime(build, directory, ROOT, sanitize)
    for artifact in [compiler, build / "crust-ownership-library.so"]:
        assert b"z3" not in command(["ldd", artifact]).stdout.lower()
        assert b"Z3_" not in command(["nm", "-u", artifact]).stdout
    print(
        f"ownership: two containers, address reuse, O0/O2, erasure, {len(cases)+len(local_rejects())+2} rejections"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-local-", dir=args.build) as temporary:
        run(args.build.resolve(), Path(temporary), args.sanitize)


if __name__ == "__main__":
    main()
