#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check generic field contracts, owner lifetimes, and the intrusive tutorial."""

import argparse
import tempfile
from pathlib import Path

from memory import command
from ownership_runtime import check_runtime
from resource_memory import execute

ROOT = Path(__file__).resolve().parents[1]
TUTORIAL = ROOT / "examples/intrusive"


def replace(source, before, after):
    if before not in source:
        raise RuntimeError(f"mutation did not match: {before!r}")
    return source.replace(before, after, 1)


def contract_cases():
    source = (TUTORIAL / "links.crs").read_text()
    program = (TUTORIAL / "program.crs").read_text()
    types = (
        "domain Graph(Node);\nrecord Node"
        + program.split("record Node", 1)[1].split("resource Owner", 1)[0]
    )
    source = types + source
    return {
        "missing-update": replace(source, "(*after).prev = before;", ""),
        "missing-postcondition": replace(source, "(*node).next = node;", ""),
        "undeclared-write": replace(source, "modifies(Node.prev, Node.next)", "modifies()"),
        "read-editor": replace(source, "access(edit, Graph)", "access(read, Graph)"),
        "null-input": replace(source, "requires(node != null(*Node))", ""),
        "observer-during-update": replace(
            source, "(*before).next = after;", "(*before).next = after; observe(after);"
        )
        + "\nfn observe(node:*Node)->unit access(read,Graph) {}\n",
    }


def owner_cases():
    source = (TUTORIAL / "program.crs").read_text()
    release = "release(node as *u8);"
    early = "{ var early: Owner = move first; }"
    return {
        "second-membership-live": replace(source, "active_unlink(node);", ""),
        "head-live": replace(
            source, "while head.node.next != &head.node { ready_unlink(head.node.next); }", ""
        ),
        "missing-payload": replace(source, "(*node).value = value;", ""),
        "missing-pointer-init": replace(source, "(*node).active_next = node;", ""),
        "double-release": replace(source, release, release + release),
        "use-after-release": replace(source, release, release + " (*node).value = 9i64;"),
        "copied-owner": replace(source, "node: move node", "node: node"),
        "saved-cursor": replace(source, early, "var saved:*Node=first.node; " + early),
        "move-stable-head": replace(
            source,
            "node_init(&ready.node, 0i64);",
            "node_init(&ready.node, 0i64); var moved:ReadyHead=move ready;",
        ),
        "forged-owner": replace(
            source,
            "var first: Owner = owner_new(65i64);",
            "var first:Owner=make Owner {node:4096usize as *Node};",
        ),
        "edit-reclaims": replace(source, early, "edit Graph " + early),
        "hidden-reference": source + "\nrecord Hidden { saved:*Node; }\n",
        "outside-schema": source
        + "\nrecord Hidden { saved:*Node; } domain(Graph) references(saved);\n",
        "third-reference": extra_reference(source),
        "consume-comparison": replace(source, release, "if node == move node {} " + release),
        "consume-shortcircuit": replace(
            source, release, "if false && node == move node {} " + release
        ),
        "interior-release": replace(source, release, "release((&(*node).value) as *u8);"),
        "partial-owner-return": replace(
            source,
            early,
            "var raw:*Node=move first.node; if argc==2i32 {return 0i32;} first.node=move raw;"
            + early,
        ),
        "byte-reinterpret": replace(
            source, early, "var bytes:*u8=first.node as *u8; var bad:u8=*bytes; " + early
        ),
        "false-destructor-precondition": replace(
            source,
            "fn owner_drop(owner: mut Owner) -> unit access(reclaim, Graph) {",
            "fn owner_drop(owner: mut Owner) -> unit access(reclaim, Graph) requires(false) {",
        ),
        "null-backedge": replace(source, "cursor = (*cursor).next;", "cursor = null(*Node);"),
        "read-loop-write": replace(
            source, "cursor = (*cursor).next;", "ready_unlink(cursor); cursor = (*cursor).next;"
        ),
        "scope-escape": replace(
            source,
            "fn ready_count(head: read ReadyHead) -> usize access(read, Graph) {",
            "fn ready_count(head: read ReadyHead) -> usize access(read, Graph) { var escaped:*Node=null(*Node);",
        ).replace("cursor = (*cursor).next;", "escaped=cursor; cursor=(*cursor).next;", 1),
        "read-loop-reclaim": replace(
            source,
            "cursor = (*cursor).next;",
            "var doomed:Owner=owner_new(3i64); cursor=(*cursor).next;",
        ),
        "unused-invalid-body": source
        + "\nfn bad(owner:mut Owner)->unit access(read,Graph) {release(owner.node as *u8);}\n",
    }


def extra_reference(source):
    source = replace(
        source,
        "domain Graph(Node, Owner, ReadyHead, ActiveHead);",
        "domain Graph(Node, Owner, ReadyHead, ActiveHead, Index);",
    )
    return source + "\nrecord Index { saved:*Node; } domain(Graph) references(saved);\n"


def accepted(compiler, directory, cases, inputs, sanitize):
    for name, source in cases.items():
        path = directory / f"accept-{name}.crs"
        path.write_text(source)
        generated, symbols = directory / f"{name}.c", directory / f"{name}.rsp"
        command(
            [compiler, "--emit-c", "--symbols", symbols, "-o", generated, *inputs, path], timeout=90
        )
        execute(generated, symbols, directory, name, sanitize, b"OK\n")
    return len(cases)


def rejected(compiler, directory, cases, prefix, inputs):
    for name, source in cases.items():
        path = directory / f"{prefix}-{name}.crs"
        path.write_text(source)
        output = directory / f"{prefix}-{name}.c"
        output.write_text("output must survive rejection\n")
        result = command(
            [compiler, "--library", "--emit-c", "-o", output, *inputs, path], 1, timeout=90
        )
        if not result.stderr or output.read_text() != "output must survive rejection\n":
            raise RuntimeError(f"{name}: missing diagnostic or output changed on rejection")
    return len(cases)


def basics(build, directory, sanitize):
    tutorial = ROOT / "examples/ownership-basics"
    for name, expected in (("program", b"BC\n"), ("heap", b"AB\n")):
        source = tutorial / f"{name}.crs"
        generated, symbols = directory / f"basic-{name}.c", directory / f"basic-{name}.rsp"
        command(
            [
                build / "crust",
                tutorial / "main.crs",
                "--emit-c",
                "--symbols",
                symbols,
                "-o",
                generated,
                source,
            ]
        )
        command([build / "crust-ownership-erasure", "--check", source])
        execute(generated, symbols, directory, f"basic-{name}", sanitize, expected)
    print("ownership basics: 2 source-root examples, erasure, and native output passed")


def run(build, directory, sanitize):
    basics(build, directory, sanitize)
    compiler = build / "crust-ownership-test"
    links = TUTORIAL / "links.crs"
    program = TUTORIAL / "program.crs"
    command([compiler, "--library", "--check", links, program])
    generated, symbols = directory / "intrusive.c", directory / "intrusive.rsp"
    command(
        [compiler, "--emit-c", "--symbols", symbols, "-o", generated, links, program], timeout=90
    )
    execute(generated, symbols, directory, "intrusive", sanitize, b"OK\n")
    check_runtime(build, directory, ROOT, sanitize)
    command([build / "crust-ownership-erasure", "--check", links, program], timeout=90)
    command([build / "crust", TUTORIAL / "main.crs", "--check", links, program], timeout=90)
    count = rejected(compiler, directory, contract_cases(), "contract", [])
    count += rejected(compiler, directory, owner_cases(), "owner", [links])
    renamed = directory / "renamed.crs"
    text = links.read_text() + program.read_text()
    for old, new in (
        ("Node", "Entry"),
        ("Graph", "Work"),
        ("prev", "older"),
        ("next", "newer"),
        ("unlink", "detach"),
    ):
        text = text.replace(old, new)
    renamed.write_text(text)
    command([compiler, "--library", "--check", renamed], timeout=90)
    print(
        f"ownership: tutorial, root, erasure, exact-address reuse, renaming, and {count} rejections passed"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-", dir=args.build) as temporary:
        run(args.build.resolve(), Path(temporary).resolve(), args.sanitize)


if __name__ == "__main__":
    main()
