#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check lexical payload loans and declared returned-view origins."""

import argparse
import tempfile
from pathlib import Path

from memory import command
from resource_memory import execute

ROOT = Path(__file__).resolve().parents[1]
TUTORIAL = ROOT / "examples/intrusive"

HELPERS = """
fn loan_pair(a: mut Node, b: mut Node) -> unit access(edit, Graph) {
    a.value = a.value + 1i64;
    b.value = b.value + 1i64;
}
fn loan_identity(owner: Owner) -> Owner { return move owner; }
fn loan_swap(a: mut Owner, b: mut Owner) -> unit access(edit, Graph) {
    var saved: *Node = move a.node;
    a.node = move b.node;
    b.node = move saved;
}
fn loan_unlink(node: mut Node) -> unit access(edit, Graph) { unlink(&node.ready); }
"""


def source(body, extra=""):
    definitions = (TUTORIAL / "program.crs").read_text().split("fn main(", 1)[0]
    return (
        definitions
        + HELPERS
        + extra
        + """
fn main(argc: i32, argv: **u8) -> i32 access(reclaim, Graph) {
    var first: Owner = owner_new(65i64);
    var second: Owner = owner_new(66i64);
    if first.node == null(*Node) || second.node == null(*Node) { return 1i32; }
    {
"""
        + body
        + """
    }
    emit(79i32); emit(75i32); emit(10i32);
    return 0i32;
}
"""
    )


def positives():
    return {
        "payload": source(
            """
        edit Graph {
            loan_pair(mut *first.node, mut *second.node);
            var value: mut i64 = value_mut(mut *second.node);
            value = 66i64;
        }
        read Graph {
            var node: read Node = node_view(read second);
            var value: read i64 = value_view(read node);
            if value != 66i64 { trap; }
            var copied: i64 = value;
            var copied_view: read i64 = read copied;
            if copied_view != 66i64 { trap; }
        }
        """
        ),
        "swap": source(
            """
        edit Graph { loan_swap(mut first, mut second); }
        if first.node == null(*Node) || second.node == null(*Node) { trap; }
        read Graph {
            if (*first.node).value != 66i64 || (*second.node).value != 65i64 { trap; }
        }
        """
        ),
        "scalar-reborrow": source(
            """
        var count: i64 = 0i64;
        {
            var view: mut i64 = mut count;
            { var child: mut i64 = mut view; child = 3i64; }
            view = 7i64;
        }
        if count != 7i64 { trap; }
        """
        ),
        "cursor-result": source(
            """
        var head: ReadyHead = make ReadyHead {hook: make Hook {prev: null(*Hook), next: null(*Hook)}};
        hook_init(&head.hook);
        edit Graph { insert_after(&head.hook, &(*first.node).ready); insert_after(&head.hook, &(*second.node).ready); }
        read Graph {
            var begin: read Hook = first_hook(read head);
            var cursor: *Hook = &begin;
            var count: usize = 0usize;
            while cursor != &head.hook { count = count + 1usize; cursor = (*cursor).next; }
            if count != 2usize { trap; }
            var member: read Node = first_node(read head);
            if member.value != 66i64 { trap; }
        }
        """
        ),
    }


def negatives():
    cases = {
        "shared-write": "edit Graph {var p:*Node=first.node; var view:read Node=read *p; (*p).value=8i64;}",
        "exclusive-read": "edit Graph {var p:*Node=first.node; var view:mut Node=mut *p; var n:i64=(*p).value;}",
        "exclusive-pair": "edit Graph {loan_pair(mut *first.node,mut *first.node);}",
        "shared-mut": "edit Graph {var p:*Node=first.node;var view:read Node=read *p;increment(mut *p);}",
        "reborrow-parent": "edit Graph {var view:mut Node=mut *first.node;var child:mut i64=mut view.value;view.value=8i64;}",
        "scalar-shared-write": "var n:i64=1i64;var view:read i64=read n;n=8i64;",
        "scalar-exclusive-read": "var n:i64=1i64;var view:mut i64=mut n;emit(n as i32);",
        "scalar-reclaim": "var p:*Node=first.node;var view:read i64=read (*p).value;p=null(*Node);drop first;emit(view as i32);",
        "owner-result-reclaim": "var p:*Node=first.node;var moved:Owner=loan_identity(move first);var view:read i64=read (*p).value;p=null(*Node);drop moved;emit(view as i32);",
        "owner-result-exclusive-alias": "var p:*Node=first.node;var moved:Owner=loan_identity(move first);if moved.node==null(*Node){trap;} edit Graph {var view:mut Node=mut *moved.node;var n:i64=(*p).value;} p=null(*Node);",
        "swap-alias": "edit Graph {var p:*Node=first.node;loan_swap(mut first,mut second);if second.node==null(*Node){trap;}var view:mut Node=mut *second.node;var n:i64=(*p).value;}",
        "loan-escape": "var escaped:*Node=null(*Node);{var view:read Node=node_view(read first);escaped=&view;}",
        "domain-relation-alias": "edit Graph {var p:*Node=first.node;var view:read i64=read (*p).value;unlink(&(*second.node).ready);}",
        "domain-helper-alias": "edit Graph {var p:*Node=first.node;var view:read i64=read (*p).value;loan_unlink(mut *second.node);}",
    }
    result = {name: source(body) for name, body in cases.items()}
    result["wrong-field-result"] = source("").replace("from node.value", "from node.ready", 1)
    result["local-result"] = source("").replace(
        "return read node.value;", "var local:i64=7i64;return read local;", 1
    )
    result["wrong-source-result"] = source(
        "",
        """
fn wrong(a:read Owner,b:read Owner)->read Node access(read,Graph) from a.node {
    if b.node==null(*Node) {trap;} return read *b.node;
}
""",
    )
    result["sentinel-result"] = source("").replace("if cursor == &head.hook { trap; }", "", 1)
    result["wrong-family-result"] = source("").replace(
        "return read *parent(Node.ready, cursor)", "return read *parent(Node.active, cursor)", 1
    )
    return result


def run(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    links = TUTORIAL / "links.crs"
    good, bad = positives(), negatives()
    for name, text in good.items():
        path = directory / f"{name}.crs"
        generated, symbols = directory / f"{name}.c", directory / f"{name}.rsp"
        path.write_text(text)
        command(
            [compiler, "--emit-c", "--symbols", symbols, "-o", generated, links, path], timeout=90
        )
        execute(generated, symbols, directory, name, sanitize, b"OK\n")
        command([build / "crust-ownership-erasure", "--check", links, path], timeout=90)
    for name, text in bad.items():
        path = directory / f"reject-{name}.crs"
        path.write_text(text)
        command([compiler, "--check", links, path], 1, timeout=90)
    print(f"ownership loans: {len(good)} native/erasure cases and {len(bad)} rejections passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    options = parser.parse_args()
    build = options.build.resolve()
    with tempfile.TemporaryDirectory(prefix="ownership-loans-", dir=build) as directory:
        run(build, Path(directory), options.sanitize)


if __name__ == "__main__":
    main()
