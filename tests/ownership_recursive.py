#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check finite owner summaries against recursive native containers and imports."""

import argparse
import os
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
            replace(source, "unlink(&node.active);", ""),
            "destructor must isolate all embedded hooks",
        ),
        "drop-before-restoration": (
            replace(source, "(*node).owned_next = null(*Node);", ""),
            "resource destruction requires initialized owner fields",
        ),
        "skip-value-drop": (
            replace(source, "drop *node; release(node as *u8);", "release(node as *u8);"),
            "release requires every member hook to be isolated",
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
        "projection-steals-tail": (
            source
            + """
fn steal(head:read ReadyHead)->unit access(read,Graph) {
    var cursor:*Hook=head.hook.next;
    if cursor==&head.hook {return;}
    var node:*Node=parent(Node.ready,cursor);
    var owned:*Node=move (*node).owned_next;
}
""",
            "member projection cannot transfer ownership",
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
            "continuing paths must preserve initialized owned storage",
        ),
        "recursive-owner-cycle": (
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
            "owner field requires a fully initialized allocation",
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
extern fn release(pointer:*u8)->unit foreign(release)="free";
resource Chain { node:*Node; } owns(node) domain(Graph) drop chain_drop;
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
    client.write_text("// SPDX-License-Identifier: Apache-2.0\nfn main(" + main)
    driver = str(build / "crust-ownership-import-test")
    receipt = publish(driver, cache, [links, provider])
    links.unlink()
    provider.unlink()
    environment = dict(os.environ, CRUST_TEST_NO_SOLVER="1")
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
        for name, code in branch_cases(source).items():
            path = directory / f"{name}.crs"
            path.write_text(code)
            command([build / "crust-ownership-test", "--check", LINKS, path])
        for name, (code, diagnostic) in cases(source).items():
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
        "recursive ownership: native counts, erasure, source root, 4 allocation failures, 3 type/branch cases, 16 rejections, and bodyless import passed"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    run((ROOT / args.build).resolve(), args.sanitize)


if __name__ == "__main__":
    main()
