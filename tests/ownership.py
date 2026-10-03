#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check modular link contracts, owner lifetimes, and the intrusive tutorial."""

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


def relation_cases():
    source = (TUTORIAL / "links.crs").read_text()
    return {
        "borrowed-relation-parameter": replace(source, "h: *Hook", "h: read Hook"),
        "missing-backlink": replace(source, "(*after).prev = before;", ""),
        "missing-isolation": replace(
            source, "(*after).prev = before;\n    (*h).prev = h;", "(*after).prev = before;"
        ),
        "splice-missing-reset": replace(source, "(*source).next = source;", ""),
        "splice-member-destination": replace(source, "anchor(at)", "member(at)"),
        "splice-noop": replace(
            source,
            "if at == source || (*source).next == source { return; }",
            "return;",
        ),
        "read-editor": replace(
            source,
            "fn unlink(h: *Hook) -> unit links(edit, Hook)",
            "fn unlink(h: *Hook) -> unit links(read, Hook)",
        ),
        "construction-read": replace(source, "(*h).prev = h;", "(*h).prev = (*h).next;"),
        "observer-during-repair": replace(
            source, "(*before).next = after;", "(*before).next = after; observe(after);"
        )
        + "\nfn observe(h:*Hook)->unit links(read,Hook) cursor(h) {var p:*Hook=(*h).prev;}\n",
        "loop-reinitialization": source
        + "\nfn repeat(h:*Hook)->unit links(edit,Hook) construct(h) {while true {hook_init(h);}}\n",
    }


def owner_cases():
    source = (TUTORIAL / "program.crs").read_text()
    return {
        "second-hook-still-linked": replace(source, "unlink(&(*node).active);", ""),
        "head-still-linked": replace(
            source, "while head.hook.next != &head.hook { unlink(head.hook.next); }", ""
        ),
        "missing-payload-init": replace(source, "(*node).value = value;", ""),
        "missing-hook-init": replace(source, "hook_init(&(*node).active);", ""),
        "double-release": replace(
            source, "release(node as *u8);", "release(node as *u8); release(node as *u8);"
        ),
        "use-after-release": replace(
            source, "release(node as *u8);", "release(node as *u8); (*node).value = 9i64;"
        ),
        "copied-owner-pointer": replace(source, "node: move node", "node: node"),
        "wrong-hook-family": replace(
            source,
            "insert_after(&ready.hook, &(*first.node).ready);",
            "insert_after(&ready.hook, &(*first.node).active);",
        ),
        "saved-cursor-drop": replace(
            source,
            "{ var early: Owner = move first; }",
            "var saved: *Node = first.node; { var early: Owner = move first; }",
        ),
        "pinned-head-move": replace(
            source,
            "hook_init(&ready.hook);",
            "hook_init(&ready.hook); var moved: ReadyHead = move ready;",
        ),
        "forged-owner": replace(
            source,
            "var first: Owner = owner_new(65i64);",
            "var first: Owner = make Owner { node: 4096usize as *Node };",
        ),
        "edit-reclaims": replace(
            source,
            "{ var early: Owner = move first; }",
            "edit Graph { var early: Owner = move first; }",
        ),
    }


def adversarial_cases():
    source = (TUTORIAL / "program.crs").read_text()
    release = "release(node as *u8);"
    early = "{ var early: Owner = move first; }"
    return {
        "unused-invalid-callee": source
        + "\nfn rogue(owner: mut Owner)->unit access(read,Graph) {release(owner.node as *u8);}\n",
        "temporary-owner-borrow": replace(
            source,
            "var first: Owner = owner_new(65i64);",
            "var escaped: *Node = owner_new(65i64).node; var first: Owner = owner_new(65i64);",
        ),
        "moved-temporary-owner-borrow": replace(
            source, early, "var escaped:*Node=(move first).node;"
        ),
        "stored-payload-borrow": replace(
            source,
            early,
            "{var pointer:*Node=first.node; var view:read Node=read *pointer; "
            "edit Graph {(*pointer).value=7i64;}} " + early,
        ),
        "write-through-read-helper": source
        + "\nfn forbidden(node:read Node)->unit access(edit,Graph) {node.value=7i64;}\n",
        "read-parameter-reclaims": source
        + "\nfn forbidden(node:read Node)->unit access(reclaim,Graph) {}\n",
        "borrow-argument-with-nested-reclaim": replace(
            source,
            early,
            "var observed:i64=read_value(read *first.node,consume(move first));",
        )
        + "\nfn read_value(node:read Node,value:i64)->i64 access(read,Graph) {return node.value+value;}"
        "\nfn consume(owner:Owner)->i64 access(reclaim,Graph) {return 0i64;}\n",
        "discarded-owner-cleanup": replace(
            source,
            early,
            "read Graph {var saved:*Node=first.node; identity(move first); if (*saved).value!=65i64 {trap;}}",
        )
        + "\nfn identity(owner:Owner)->Owner access(read,Graph) {return move owner;}\n",
        "copied-pinned-node": replace(
            source,
            "hook_init(&active.hook);",
            "hook_init(&active.hook); var copied: Node = *first.node;",
        ),
        "overwrite-linked-hook": replace(
            source,
            early,
            "(*first.node).ready = make Hook {prev:null(*Hook),next:null(*Hook)}; " + early,
        ),
        "free-argv": replace(
            source,
            "var first: Owner = owner_new(65i64);",
            "release(argv as *u8); var first: Owner = owner_new(65i64);",
        ),
        "hidden-record-borrow": source + "\nrecord BorrowBox { pointer: *Node; }\n",
        "consume-in-comparison": replace(source, release, "if node == move node {} " + release),
        "consume-in-shortcircuit": replace(
            source, release, "if false && node == move node {} " + release
        ),
        "interior-free": replace(source, release, "release((&(*node).active) as *u8);"),
        "uninitialized-head-drop": replace(
            source,
            "hook_init(&ready.hook);",
            "if argc == 1i32 {return 0i32;} hook_init(&ready.hook);",
        ),
        "uninitialized-head-cleanup": replace(
            source,
            "var first: Owner = owner_new(65i64);",
            "{var never:ReadyHead=make ReadyHead {hook:make Hook {prev:null(*Hook),next:null(*Hook)}};} "
            "var first: Owner = owner_new(65i64);",
        ),
        "stale-isolation": replace(
            source,
            early,
            "edit Graph {var neighbor:*Hook=(*first.node).ready.next; unlink(&(*first.node).ready); "
            "var cached:*Hook=(*first.node).ready.next; insert_after(neighbor,&(*first.node).ready); "
            "if cached!=&(*first.node).ready {trap;} unlink(&(*first.node).active);} "
            "var raw:*Node=move first.node; release(raw as *u8); first.node=null(*Node);",
        ),
        "reordered-isolation": replace(
            source,
            early,
            "edit Graph {isolate_first((*first.node).ready.next,&(*first.node).ready); "
            "unlink(&(*first.node).active);} var raw:*Node=move first.node; "
            "release(raw as *u8); first.node=null(*Node);",
        )
        + "\nfn isolate_first(a:*Hook,b:*Hook)->unit links(edit,Hook) cursor(b) cursor(a) isolated(a) {unlink(a);}\n",
        "partial-owner-return": replace(
            source,
            early,
            "var raw:*Node=move first.node; if argc==2i32 {return 0i32;} first.node=move raw; "
            + early,
        ),
        "byte-cast-dereference": replace(
            source, early, "var bytes:*u8=first.node as *u8; var bad:u8=*bytes; " + early
        ),
        "partial-publication": replace(
            source,
            "hook_init(&active.hook);",
            "hook_init(&active.hook); var staged:*Node=allocate(sizeof(Node)) as *Node; "
            "if staged!=null(*Node) {(*staged).value=68i64; hook_init(&(*staged).ready); "
            "edit Graph {insert_after(&ready.hook,&(*staged).ready);} hook_init(&(*staged).active); "
            "edit Graph {unlink(&(*staged).ready);unlink(&(*staged).active);} release(staged as *u8);}",
        ),
    }


def projection_scope(source, statements):
    marker = (
        "        // Reuse allocation independently while the heads and second owner remain live."
    )
    body = "        edit Graph {\n" + statements + "        }\n"
    return replace(source, marker, body + marker)


def projection_cases():
    source = (TUTORIAL / "program.crs").read_text()
    guard = "if ready_cursor == &ready.hook || active_cursor == &active.hook { trap; }"
    cursor = "            var cursor: *Hook = ready.hook.next;\n"
    exclude = "            if cursor == &ready.hook { trap; }\n"
    read = (
        "            var payload: *Node = parent(Node.ready, cursor);\n"
        "            if (*payload).value != 66i64 { trap; }\n"
    )
    reject = {
        "missing-guard": replace(source, guard, ""),
        "wrong-family": replace(
            source, "parent(Node.ready, ready_cursor)", "parent(Node.active, ready_cursor)"
        ),
        "wrong-head": replace(
            source,
            guard,
            "if ready_cursor == &active.hook || active_cursor == &active.hook { trap; }",
        ),
        "anchor-as-member": replace(
            source, "parent(Node.ready, ready_cursor)", "parent(Node.ready, &ready.hook)"
        ),
        "uninitialized-parent": replace(
            source,
            "(*node).value = value;",
            "var view: *Node = parent(Node.ready, &(*node).ready); (*node).value = value;",
        ),
        "stale-association": projection_scope(
            source, cursor + "            unlink(&(*second.node).ready);\n" + exclude + read
        ),
        "write-through-shared-view": projection_scope(
            source, cursor + exclude + read + "            (*payload).value = 7i64;\n"
        ),
        "release-through-shared-view": projection_scope(
            source, cursor + exclude + read + "            release(payload as *u8);\n"
        ),
        "escaped-view": replace(
            source,
            "        // Reuse allocation independently while the heads and second owner remain live.",
            "        var escaped: *Node = null(*Node);\n        read Graph {\n"
            + cursor
            + exclude
            + "            escaped = parent(Node.ready, cursor);\n        }\n"
            + "        // Reuse allocation independently while the heads and second owner remain live.",
        ),
    }
    accept = {
        "member-survives-edit": projection_scope(
            source, cursor + exclude + "            unlink(&(*second.node).ready);\n" + read
        ),
        "other-family-edit": projection_scope(
            source, cursor + "            unlink(&(*second.node).active);\n" + exclude + read
        ),
    }
    return reject, accept


def loop_cases():
    source = (TUTORIAL / "program.crs").read_text()
    guard = "while cursor != &head.hook {"
    advance = "cursor = (*cursor).next;"
    return {
        "missing-member-guard": replace(source, guard, "while cursor != null(*Hook) {"),
        "wrong-family-backedge": replace(source, advance, "cursor = (*node).active.next;"),
        "null-backedge": replace(source, advance, "cursor = null(*Hook);"),
        "advance-loses-member-guard": replace(
            source, advance, advance + " var unchecked:*Node=parent(Node.ready,cursor);"
        ),
        "edit-in-read-loop": replace(source, advance, "unlink(cursor); " + advance),
        "post-loop-member": replace(
            source,
            "return count;",
            "var invalid: *Node = parent(Node.ready, cursor); return count;",
        ),
        "entry-member-is-not-invariant": replace(
            source,
            guard,
            "if cursor == &head.hook {trap;} while count < 1usize {",
        ),
        "wrong-anchor-backedge": source
        + "\nfn wrong_anchor(head:read ReadyHead,other:read ReadyHead)->unit access(read,Graph) {"
        "read Graph {var cursor:*Hook=head.hook.next; while cursor!=&head.hook {"
        "var node:*Node=parent(Node.ready,cursor); cursor=other.hook.next;}}}\n",
        "wrong-anchor-guard": source
        + "\nfn wrong_guard(head:read ReadyHead,other:read ReadyHead)->unit access(read,Graph) {"
        "read Graph {var cursor:*Hook=head.hook.next; while cursor!=&other.hook {"
        "var node:*Node=parent(Node.ready,cursor); cursor=(*cursor).next;}}}\n",
        "cursor-escapes-loop-access": replace(
            source,
            "fn ready_count(head: read ReadyHead) -> usize access(read, Graph) {",
            "fn ready_count(head: read ReadyHead) -> usize access(read, Graph) {"
            "var escaped:*Hook=null(*Hook);",
        ).replace(advance, "escaped=cursor; " + advance, 1),
        "reclaim-from-read-loop": replace(
            source,
            advance,
            "var doomed:Owner=owner_new(3i64); " + advance,
        ),
        "stack-origin-shorter-than-access": source + "\nrecord ScalarBox {value:i64;}\n"
        "fn stack_escape()->unit access(read,Graph) {read Graph {var escaped:*ScalarBox=null(*ScalarBox);"
        "{var temporary:ScalarBox=make ScalarBox {value:1i64}; escaped=&temporary;}}}\n",
    }


def library_runtime_cases():
    source = (TUTORIAL / "program.crs").read_text()
    splice = """{
            var other:ReadyHead=make ReadyHead {hook:make Hook {prev:null(*Hook),next:null(*Hook)}};
            hook_init(&other.hook);
            edit Graph {splice_init(&other.hook,&ready.hook);}
            var moved:usize=ready_count(read other);
            var source_empty:usize=ready_count(read ready);
            if moved!=2usize || source_empty!=0usize {trap;}
            edit Graph {splice_init(&other.hook,&other.hook);}
            moved=ready_count(read other);
            if moved!=2usize {trap;}
            edit Graph {splice_init(&ready.hook,&other.hook);splice_init(&ready.hook,&other.hook);}
            moved=ready_count(read ready);
            source_empty=ready_count(read other);
            if moved!=2usize || source_empty!=0usize {trap;}
        }
        """
    return {
        "splice-distinct-self-empty": replace(
            source,
            "{ var early: Owner = move first; }",
            splice + "{ var early: Owner = move first; }",
        )
    }


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


def run(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    links = TUTORIAL / "links.crs"
    program = TUTORIAL / "program.crs"
    command([compiler, "--library", "--check", links])
    generated, symbols = directory / "intrusive.c", directory / "intrusive.rsp"
    command(
        [compiler, "--emit-c", "--symbols", symbols, "-o", generated, links, program], timeout=90
    )
    execute(generated, symbols, directory, "intrusive", sanitize, b"OK\n")
    check_runtime(build, directory, ROOT, sanitize)
    command([build / "crust-ownership-erasure", "--check", links, program], timeout=90)
    command([build / "crust", TUTORIAL / "main.crs", "--check", links, program], timeout=90)
    count = rejected(compiler, directory, relation_cases(), "link", [])
    count += rejected(compiler, directory, owner_cases(), "owner", [links])
    count += rejected(compiler, directory, adversarial_cases(), "adversarial", [links])
    count += rejected(compiler, directory, loop_cases(), "loop", [links])
    projection_reject, projection_accept = projection_cases()
    count += rejected(compiler, directory, projection_reject, "projection", [links])
    positives = accepted(compiler, directory, projection_accept, [links], sanitize)
    positives += accepted(compiler, directory, library_runtime_cases(), [links], sanitize)
    renamed = directory / "renamed.crs"
    renamed.write_text(
        links.read_text()
        .replace("Hook", "Cell")
        .replace("prev", "older")
        .replace("next", "newer")
        .replace("unlink", "detach")
    )
    command([compiler, "--library", "--check", renamed])
    reordered = directory / "reordered.crs"
    reordered.write_text(replace(links.read_text(), "cursor(at) member(h)", "member(h) cursor(at)"))
    command([compiler, "--library", "--check", reordered])
    print(
        f"modular ownership: library, tutorial, root, erasure, renaming, {positives} runtime variants, and {count} rejections passed"
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
