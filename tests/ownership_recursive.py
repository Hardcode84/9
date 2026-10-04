#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check finite owner summaries against recursive native containers and imports."""

import argparse
import resource
import subprocess
import tempfile
from pathlib import Path

from memory import command
from ownership import replace
from ownership_imports import command as import_command
from ownership_imports import import_arguments, publish
from ownership_runtime import check_runtime

ROOT = Path(__file__).resolve().parents[1]
LINKS = ROOT / "examples/intrusive/links.crs"
PROGRAM = ROOT / "examples/intrusive/recursive/program.crs"


def cases(source):
    return {
        "unconsumed-tail": (
            replace(source, "node: move node.owned_next", "node: null(*Node)"),
            "destructor must consume each owned field",
        ),
        "linked-release": (
            replace(source, "active_unlink(&node);", ""),
            "cannot destroy storage: a surviving reference field",
        ),
        "drop-before-restoration": (
            replace(source, "(*node).owned_next = null(*Node);", ""),
            "resource destruction requires initialized owner fields",
        ),
        "skip-value-drop": (
            replace(source, "drop *node;\n    release(node as *u8);", "release(node as *u8);"),
            "release requires destruction of the stored resource value",
        ),
        "double-release": (
            replace(source, "release(node as *u8);", "release(node as *u8); release(node as *u8);"),
            "value is uninitialized or has been moved",
        ),
        "missing-tail-init": (
            replace(
                source, "(*node).owned_next = move rest.node;\n    rest.node = null(*Node);", ""
            ),
            "owner field requires a fully initialized allocation",
        ),
        "copied-tail": (
            replace(
                source, "(*node).owned_next = move rest.node;", "(*node).owned_next = rest.node;"
            ),
            "cursor cannot outlive its access scope",
        ),
        "stale-cursor": (
            replace(
                source,
                "chain = chain_pop(move chain);",
                "var saved:*Node=chain.node; chain = chain_pop(move chain);",
            ),
            "reclamation conflicts with an active domain cursor",
        ),
        "conflicting-loan": (
            replace(
                source,
                "chain = chain_pop(move chain);",
                "var saved:read Node=read *chain.node; chain = chain_pop(move chain);",
            ),
            "reclamation conflicts with an active domain loan",
        ),
        "move-linked-node": (
            replace(source, "chain = chain_pop(move chain);", "var copied:Node=*chain.node;"),
            "copy of a resource requires an explicit move",
        ),
        "cursor-steals-tail": (
            source
            + """
fn steal(head:read ReadyHead)->unit access(read,Graph) {
    var cursor:*Node=head.node.next;
    if cursor==&head.node {return;}
    var node:*Node=cursor;
    var owned:*Node=move (*node).owned_next;
}
""",
            "owner transfer requires an ownership origin",
        ),
        "branch-null-fact": (
            source
            + """
fn bad(chain:read Chain,choice:bool)->i64 access(read,Graph) {
    if chain.node==null(*Node) {return 0i64;}
    if choice {if (*chain.node).owned_next==null(*Node) {trap;}}
    return (*(*chain.node).owned_next).value;
}
""",
            "pointer access requires live non-null storage",
        ),
        "branch-consumes-child": (
            source
            + """
fn bad(chain:Chain,choice:bool)->Chain access(reclaim,Graph) {
    if chain.node==null(*Node) {return move chain;}
    if choice {
        var tail:Chain=make Chain{node:move (*chain.node).owned_next};
        drop tail;
    }
    return move chain;
}
""",
            "cannot destroy storage: a surviving reference field",
        ),
        "cursor-owner-cycle": (
            source
            + """
fn bad()->unit access(reclaim,Graph) {
    var chain:Chain=chain_new(1usize);
    if chain.node==null(*Node) {return;}
    var cursor:*Node=chain.node;
    var tail:Chain=make Chain{node:move (*cursor).owned_next};
    (*cursor).owned_next=move chain.node;
    chain.node=null(*Node);
}
""",
            "reclamation conflicts with an active domain cursor",
        ),
        "null-owner-after-mut": (
            source
            + """
fn swap(target:mut Chain,source:Chain)->Chain access(edit,Graph) {
    var prior:*Node=move target.node;
    target.node=move source.node;
    source.node=move prior;
    return move source;
}
fn bad()->unit access(reclaim,Graph) {
    var a:Chain=make Chain{node:null(*Node)};
    var b:Chain=chain_new(1usize);
    var prior:Chain=swap(mut a,move b);
    var raw:*Node=move a.node;
    a.node=null(*Node);
    read Graph {release(raw as *u8);}
}
""",
            "release requires exclusive reclamation authority",
        ),
    }


def branch_cases(source):
    common = """
fn inspect(chain:read Chain,choice:bool)->unit access(read,Graph) {
    if chain.node==null(*Node) {return;}
    if choice {var value:i64=(*chain.node).value;}
    BRANCH
    if (*chain.node).owned_next!=null(*Node) {
        var value:i64=(*(*chain.node).owned_next).value;
    }
}
"""
    return {
        "one-branch": source + common.replace("BRANCH", ""),
        "two-branches": source
        + common.replace("BRANCH", "else {var pointer:*Node=(*chain.node).owned_next;}"),
        "mutual-types": """// SPDX-License-Identifier: Apache-2.0
domain Graph(Chain, Node);
extern fn release(pointer:*u8)->unit foreign(release)="free";
resource Chain { node:*Node; } owns(node: storage) domain(Graph) drop chain_drop;
record Node { rest:Chain; value:i64; } domain(Graph);
fn chain_drop(chain:mut Chain)->unit access(reclaim,Graph) {
    var node:*Node=move chain.node;
    if node!=null(*Node) {drop *node; release(node as *u8);}
}
fn main()->i32 access(reclaim,Graph) {
    var chain:Chain=make Chain{node:null(*Node)};
    return 0i32;
}
""",
    }


def loop_cases(source):
    def body(text):
        return source + "fn bad(chain:Chain,count:usize)->unit access(reclaim,Graph) {" + text + "}"

    return {
        "loop-lost-owner": (
            body("while count>0usize {var lost:Chain=move chain;}"),
            "restore outer initialization and ownership",
        ),
        "loop-incomplete-replacement": (
            body("while count>0usize {drop chain;var partial:Chain=uninit;chain=move partial;}"),
            "uninitialized or has been moved",
        ),
        "loop-copy-owner": (
            body("while count>0usize {chain=chain_pop(chain);}"),
            "explicit move",
        ),
        "loop-overwrite-owner": (
            body("while count>0usize {chain=chain_new(1usize);}"),
            "overwrite a live owner",
        ),
        "loop-replace-borrowed": (
            body(
                "var loan:read Chain=read chain;while count>0usize {chain=chain_pop(move chain);}"
            ),
            "active",
        ),
        "loop-replace-with-cursor": (
            body("var cursor:*Node=chain.node;while count>0usize {chain=chain_pop(move chain);}"),
            "active domain cursor",
        ),
        "loop-empty-backedge": (
            body("while count>0usize {drop chain;chain=make Chain{node:null(*Node)};drop chain;}"),
            "restore outer initialization and ownership",
        ),
        "loop-partial-backedge": (
            body(
                "while count>0usize {chain=chain_push(move chain);var rest:Chain=make Chain{node:move chain.node};}"
            ),
            "initialized owner fields",
        ),
        "loop-incomplete-field": (
            body("while count>0usize {var rest:Chain=make Chain{node:move chain.node};}"),
            "initialized resource fields",
        ),
        "loop-changed-unwidened-field": (
            body(
                "while count>0usize {var rest:Chain=make Chain{node:move chain.node};chain.node=null(*Node);}"
            ),
            "preserve outer storage",
        ),
        "loop-replacement-null-fact": (
            body(
                "if chain.node==null(*Node) {return;}while count>0usize {var n:i64=(*chain.node).value;chain=chain_pop(move chain);}"
            ),
            "live non-null storage",
        ),
        "loop-pinned-replacement": (
            replace(
                source,
                "attach(chain.node, &ready.node, &active.node);",
                "while count>0usize {ready=move ready;}",
            ),
            "address-stable storage cannot move",
        ),
        "loop-invalid-entry-contract": (
            replace(
                source,
                "attach(chain.node, &ready.node, &active.node);",
                "ready.node.next=null(*Node);while count>0usize {ready=move ready;}",
            ),
            "construction does not establish its record invariant",
        ),
        "loop-plain-record-assignment": (
            source
            + "record Plain {value:i64;} fn bad(count:usize)->unit {var x:Plain=make Plain{value:0i64};while count>0usize {x=make Plain{value:1i64};}}",
            "initialized scalar or domain cursor",
        ),
    }


def loop_accepts(source):
    return {
        "loop-owner-swap": source
        + """
fn swap(a:Chain,b:Chain,count:usize)->unit access(reclaim,Graph) {
    var i:usize=0usize;
    while i<count {var old:Chain=move a;a=move b;b=move old;i=i+1usize;}
}
""",
        "loop-nested-owners": source
        + """
fn nested(chain:Chain,count:usize)->Chain access(reclaim,Graph) {
    var i:usize=0usize;
    while i<count {
        while chain.node!=null(*Node) {chain=chain_pop(move chain);}
        chain=chain_push(move chain);
        i=i+1usize;
    }
    return move chain;
}
""",
        "loop-terminating-return": source
        + """
fn first(chain:Chain,count:usize)->Chain access(reclaim,Graph) {
    while count>0usize {return chain_pop(move chain);}
    return move chain;
}
""",
    }


def small_stack():
    resource.setrlimit(resource.RLIMIT_STACK, (256 * 1024, 256 * 1024))


def native(build, directory, sanitize):
    command([build / "crust-ownership-erasure", LINKS, PROGRAM])
    for optimization in ("-O0", "-O2"):
        output = directory / f"recursive{optimization}"
        flags = ["--cflag", optimization]
        if sanitize:
            flags += [
                "--cflag=-fsanitize=address,undefined",
                "--cflag=-fno-sanitize-recover=all",
                "--ldflag=-fsanitize=address,undefined",
                "--ldflag=-no-pie",
            ]
        command([build / "crust-ownership-test", *flags, "-o", output, LINKS, PROGRAM])
        for count in (0, 1, 2, 17, 257):
            assert command([output, *(["node"] * count)]).stdout == b"OK\n"
        if not sanitize:
            result = subprocess.run(
                [output, *(["node"] * 4096)],
                preexec_fn=small_stack,
                capture_output=True,
                timeout=30,
                check=True,
            )
            assert result.stdout == b"OK\n" and not result.stderr
    check_runtime(
        build,
        directory,
        ROOT,
        sanitize,
        source_path=PROGRAM,
        outputs=(b"OK\n", b"", b"", b"", b""),
        arguments=("node",) * 3,
    )


def separate(build, directory, source):
    cache = directory / "cache"
    cache.mkdir(mode=0o700)
    links = directory / "links.crs"
    provider = directory / "provider.crs"
    client = directory / "client.crs"
    body, main = source.split("fn main(", 1)
    links.write_bytes(LINKS.read_bytes())
    provider.write_text(body)
    client.write_text(
        "// SPDX-License-Identifier: Apache-2.0\n"
        "fn drain(chain:Chain)->Chain access(reclaim,Graph) {"
        "while chain.node!=null(*Node) {chain=chain_pop(move chain);}return move chain;}\n"
        "fn main("
        + main.replace(
            "chain_detached(read chain);", "chain_detached(read chain);chain=drain(move chain);"
        )
    )
    driver = str(build / "crust-ownership-import-test")
    receipt = publish(driver, cache, [links, provider])
    links.unlink()
    provider.unlink()
    environment = None
    output = directory / "imported"
    args = import_arguments(driver, cache, receipt, client, output)
    import_command(args, env=environment)
    for count in (0, 1, 17, 257):
        assert import_command([str(output), *(["node"] * count)]).stdout == "OK\n"
    client.write_text(
        client.read_text().replace(
            "chain = chain_pop(move chain);",
            "var saved:*Node=chain.node; chain = chain_pop(move chain);",
        )
    )
    result = import_command(args, env=environment, success=False)
    assert "reclamation conflicts with an active domain cursor" in result.stderr


def run(build, sanitize):
    source = PROGRAM.read_text()
    with tempfile.TemporaryDirectory(prefix="crust-recursive-", dir=build) as temporary:
        directory = Path(temporary)
        native(build, directory, sanitize)
        for name, code in (branch_cases(source) | loop_accepts(source)).items():
            path = directory / f"{name}.crs"
            path.write_text(code)
            command(
                [
                    build / "crust-ownership-test",
                    "--check",
                    *([] if name == "mutual-types" else [LINKS]),
                    path,
                ]
            )
        failures = cases(source) | loop_cases(source)
        for name, (code, diagnostic) in failures.items():
            path = directory / f"{name}.crs"
            path.write_text(code)
            result = command([build / "crust-ownership-test", "--check", LINKS, path], expected=1)
            assert diagnostic in result.stderr.decode(), f"{name}: {result.stderr}"
        separate(build, directory, source)
        output = directory / "root"
        command(
            [
                build / "crust",
                ROOT / "examples/intrusive/recursive/main.crs",
                "-o",
                output,
                LINKS,
                PROGRAM,
            ]
        )
        assert command([output, "one", "two"]).stdout == b"OK\n"
    print(
        f"recursive ownership: iterative native counts, erasure, source root, 4 allocation failures, "
        f"{len(branch_cases(source)) + len(loop_accepts(source))} type/branch/loop cases, "
        f"{len(failures)} rejections, and bodyless import passed"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    run((ROOT / args.build).resolve(), args.sanitize)


if __name__ == "__main__":
    main()
