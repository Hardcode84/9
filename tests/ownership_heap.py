#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check exclusive heap trees without retention domains or trusted providers."""

from ownership_imports import command as import_command
from ownership_imports import import_arguments, publish
from ownership_runtime import check_runtime
from ownership_support import ROOT, command, execute, rejected

HELPERS = """
fn consume(owner:CellOwner)->unit {}
fn consume_with_view(owner:CellOwner,view:read Cell)->unit {}
fn identity(owner:CellOwner)->CellOwner {return move owner;}
fn extract(owner:mut CellOwner)->CellOwner {
    var cell:*Cell=move owner.cell;
    owner.cell=null(*Cell);
    return make CellOwner{cell:move cell};
}
fn refresh(owner:mut CellOwner)->unit {
    var replacement:CellOwner=cell_new(7i64);
    var previous:*Cell=move owner.cell;
    owner.cell=move replacement.cell;
    replacement.cell=null(*Cell);
    if previous!=null(*Cell) {release(previous as *u8);}
}
"""

TREE = """
resource Node {child:*Node;value:i64;part:Cell;} owns(child:storage) drop node_drop;
resource Tree {root:*Node;} owns(root:storage) drop tree_drop;
fn node_drop(node:mut Node)->unit {
    var child:*Node=move node.child;
    if child!=null(*Node) {drop *child;release(child as *u8);}
}
fn tree_drop(tree:mut Tree)->unit {
    var root:*Node=move tree.root;
    if root!=null(*Node) {drop *root;release(root as *u8);}
}
fn tree_new()->Tree {
    var leaf:*Node=allocate(sizeof(Node)) as *Node;
    if leaf==null(*Node) {return make Tree{root:move leaf};}
    leaf.child=null(*Node);leaf.value=7i64;leaf.part=make Cell{value:7i64};
    var root:*Node=allocate(sizeof(Node)) as *Node;
    if root==null(*Node) {
        drop *leaf;release(leaf as *u8);return make Tree{root:move root};
    }
    root.child=move leaf;root.value=8i64;root.part=make Cell{value:8i64};
    return make Tree{root:move root};
}
fn child_view(tree:read Tree)->read Node from tree.root.child {
    if tree.root==null(*Node) {trap;}
    if tree.root.child==null(*Node) {trap;}
    return read *tree.root.child;
}
"""

START = "var owner:CellOwner=cell_new(7i64);if owner.cell==null(*Cell) {return 0i32;}"


def main(body):
    return "fn main(argc:i32,argv:**u8)->i32 {" + body + "return 0i32;}"


def good_cases():
    return {
        "independent-owners": START + "var other:CellOwner=cell_new(9i64);"
        "var view:read Cell=cell_view(read owner);drop other;if view.value!=7i64 {trap;}",
        "restored-field": START + "var cell:*Cell=move owner.cell;owner.cell=move cell;"
        "if owner.cell!=null(*Cell) {if owner.cell.value!=7i64 {trap;}}",
        "returned-owners": START
        + "var returned:CellOwner=identity(move owner);var extracted:CellOwner=extract(mut returned);"
        "drop returned;if extracted.cell!=null(*Cell) {if extracted.cell.value!=7i64 {trap;}}",
        "replaced-owner": START
        + "refresh(mut owner);if owner.cell!=null(*Cell) {if owner.cell.value!=7i64 {trap;}}",
        "null-owner": "var owner:CellOwner=make CellOwner{cell:null(*Cell)};consume(move owner);",
        "recursive-tree": "var tree:Tree=tree_new();if tree.root==null(*Node) {return 0i32;}"
        "var other:Tree=tree_new();var child:read Node=child_view(read tree);"
        "drop other;if child.value!=7i64 {trap;}",
        "addressed-heap-value": "var tree:Tree=tree_new();"
        "if tree.root==null(*Node) {return 0i32;}var address:*Cell=&tree.root.part;"
        "var next:Tree=move tree;if address.value!=8i64 {trap;}",
    }


def bad_cases():
    borrowed = START + "var view:read Cell=cell_view(read owner);"
    return {
        "drop-borrowed-owner": (main(borrowed + "drop owner;drop view;"), "active"),
        "replace-borrowed-owner": (main(borrowed + "refresh(mut owner);drop view;"), "active"),
        "consume-borrowed-owner": (main(borrowed + "consume(move owner);drop view;"), "active"),
        "borrow-after-owner-argument": (
            main(START + "var raw:*Cell=owner.cell;consume_with_view(move owner,read *raw);"),
            "active",
        ),
        "consume-old-alias": (
            main(START + "var raw:*Cell=owner.cell;consume(move owner);var stale:i64=raw.value;"),
            "live non-null storage",
        ),
        "replace-old-alias": (
            main(START + "var raw:*Cell=owner.cell;refresh(mut owner);var stale:i64=raw.value;"),
            "live non-null storage",
        ),
        "wrong-return-path": (
            "fn wrong(a:read CellOwner,b:read CellOwner)->read Cell from a.cell {"
            "if b.cell==null(*Cell) {trap;}return read *b.cell;}",
            "declared source",
        ),
        "unrestored-field": (
            "fn bad(owner:mut CellOwner)->unit {var cell:*Cell=move owner.cell;"
            "if cell!=null(*Cell) {release(cell as *u8);}}",
            "initialized on return",
        ),
        "self-owner": (
            main(
                "var node:*Node=allocate(sizeof(Node)) as *Node;if node==null(*Node) {return 0i32;}"
                "node.child=null(*Node);node.value=7i64;node.part=make Cell{value:7i64};"
                "var previous:*Node=move node.child;"
                "node.child=move node;"
            ),
            "fully initialized",
        ),
    }


def type_cases():
    box = "resource Box {value:*Payload;} owns(value:storage) drop box_drop;"
    destructor = "fn box_drop(box:mut Box)->unit {trap;}"
    allocation = "fn bad()->unit {var pointer:*u8=allocate(sizeof(Payload));}"
    view = "record View {value:read i64;}"
    return {
        "boxed-view": (
            "record Payload {value:read i64;}" + box + destructor,
            "cannot retain borrowed fields",
        ),
        "boxed-nested-view": (
            view + "record Payload {view:View;}" + box + destructor,
            "cannot retain borrowed fields",
        ),
        "direct-view-allocation": (
            "record Payload {value:mut i64;}" + allocation,
            "cannot retain borrowed fields",
        ),
        "direct-nested-view-allocation": (
            view + "record Payload {view:View;}" + allocation,
            "cannot retain borrowed fields",
        ),
        "nested-domain-storage": (
            "domain D(Managed);record Managed {value:i64;}record Payload {item:Managed;}"
            + box
            + destructor,
            "transparent domain-free records",
        ),
        "unknown-inline-type": ("record Payload {value:Unknown;}" + allocation, "Unknown"),
    }


def check_imports(build, directory, provider):
    source = directory / "heap-provider.crs"
    source.write_text(provider)
    cache = directory / "heap-cache"
    cache.mkdir()
    driver = build / "crust-ownership-import-test"
    receipt = publish(driver, cache, [source])
    source.unlink()
    client = directory / "heap-client.crs"
    output = directory / "heap-client"
    arguments = import_arguments(driver, cache, receipt, client, output)
    for body in good_cases().values():
        client.write_text(main(body))
        import_command(arguments)
        command([output])
    for source, diagnostic in bad_cases().values():
        client.write_text(source)
        result = import_command(arguments, success=False)
        assert diagnostic in result.stderr, result.stderr


def check_opaque(build, directory):
    trusted = directory / "heap-opaque-provider.crs"
    trusted.write_text("record Hidden {value:i64;} opaque;")
    source = directory / "heap-opaque-client.crs"
    source.write_text(
        "record Payload {hidden:Hidden;}resource Box {value:*Payload;}"
        "owns(value:storage) drop box_drop;fn box_drop(box:mut Box)->unit {trap;}"
    )
    result = command(
        [build / "crust-ownership-test", "trusted", trusted, "--library", "--check", source],
        expected=1,
    )
    assert b"transparent domain-free records" in result.stderr, result.stderr


def check_heap_runtime(build, directory, provider, sanitize):
    source = directory / "heap-runtime-provider.crs"
    source.write_text(provider)
    client = directory / "heap-runtime-client.crs"
    client.write_text(
        main(
            "var first:CellOwner=cell_new(7i64);if first.cell==null(*Cell) {return 1i32;}"
            "var second:CellOwner=cell_new(9i64);if second.cell==null(*Cell) {return 1i32;}"
            "{var view:read Cell=cell_view(read first);drop second;if view.value!=7i64 {trap;}}"
            "drop first;var next:CellOwner=cell_new(11i64);if next.cell==null(*Cell) {return 1i32;}"
        )
    )
    check_runtime(
        build,
        directory,
        ROOT,
        sanitize,
        source_path=source,
        outputs=(b"", b"", b"", b""),
        client_path=client,
        trusted=False,
    )
    client.write_text(
        main(
            "var first:Tree=tree_new();if first.root==null(*Node) {return 1i32;}"
            "{var view:read Node=child_view(read first);var second:Tree=tree_new();"
            "if second.root==null(*Node) {return 1i32;}drop second;if view.value!=7i64 {trap;}}"
            "drop first;var next:Tree=tree_new();if next.root==null(*Node) {return 1i32;}"
        )
    )
    check_runtime(
        build,
        directory,
        ROOT,
        sanitize,
        source_path=source,
        outputs=(b"",) * 7,
        client_path=client,
        trusted=False,
    )


def check_heap(build, directory, sanitize):
    provider = (ROOT / "examples/ownership-basics/heap.crs").read_text().split("fn main(", 1)[0]
    provider += HELPERS + TREE
    compiler = build / "crust-ownership-test"
    for name, body in good_cases().items():
        source = directory / f"heap-{name}.crs"
        source.write_text(provider + main(body))
        generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
        command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, source])
        command([build / "crust-ownership-erasure", source])
        execute(generated, symbols, directory, f"heap-{name}", sanitize, b"")
    cases = {**bad_cases(), **type_cases()}
    rejected(
        compiler,
        directory,
        {
            f"heap-{name}": (provider + source, diagnostic)
            for name, (source, diagnostic) in cases.items()
        },
    )
    check_imports(build, directory, provider)
    check_opaque(build, directory)
    check_heap_runtime(build, directory, provider, sanitize)
    print("exclusive heap: 7 positives, 16 rejections, O0/O2, erasure, imports, null/reuse")
