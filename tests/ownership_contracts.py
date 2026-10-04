#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check generic graph contracts and typed annotation boundaries."""

import argparse
import tempfile
from pathlib import Path

from memory import command
from ownership import contract_cases, replace
from resource_memory import execute

ROOT = Path(__file__).resolve().parents[1]


def rejected(compiler, directory, cases):
    for name, (source, diagnostic) in cases.items():
        path = directory / f"{name}.crs"
        path.write_text(source)
        result = command([compiler, "--library", "--check", path], expected=1)
        assert diagnostic in result.stderr.decode(), f"{name}: {result.stderr}"


def run(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    example = ROOT / "examples/ownership-graphs"
    source = example / "program.crs"
    generated, symbols = directory / "graph.c", directory / "graph.rsp"
    command(
        [
            build / "crust",
            example / "main.crs",
            "--emit-c",
            "--symbols",
            symbols,
            "-o",
            generated,
            source,
        ]
    )
    command([build / "crust-ownership-erasure", source])
    assert "static bool const" not in generated.read_text(), "domain acquired runtime storage"
    execute(generated, symbols, directory, "graph", sanitize, b"OK\n")
    graph = source.read_text()
    cases = {
        "graph-missing-parent": (
            replace(graph, "(*child).parent = parent;", ""),
            "declared field invariants",
        ),
        "graph-surviving-child": (
            replace(graph, "if left != null(*Branch) { (*left).parent = null(*Branch); }", ""),
            "declared field invariants",
        ),
        "graph-double-free": (
            replace(graph, "release(node as *u8);", "release(node as *u8); release(node as *u8);"),
            "has been moved",
        ),
        "equal-values-different-places": (
            "domain D(Pair); record Pair {first:i64; second:i64;} domain(D) "
            "invariant((*self).first == (*self).second); "
            "fn wrong(pair:read Pair)->read i64 access(read,D) from pair.first {return read pair.second;}",
            "returned loan does not match its declared storage path",
        ),
        "mutable-field-call": (
            "domain D(Cell, Flag); record Cell {value:i64;} domain(D) invariant(true); "
            "record Flag {value:bool;} domain(D); "
            "fn set(flag:mut Flag)->unit access(edit,D) {flag.value=true;} "
            "fn bad(node:*Cell)->i64 access(edit,D) requires(node==null(*Cell)) {"
            "var flag:Flag=make Flag{value:false}; set(mut flag); "
            "if flag.value {return (*node).value;} return 0i64;}",
            "pointer access requires live non-null storage",
        ),
        "self-reference-return": (
            "domain D(Node); record Node {ptr:*Node;} domain(D) references(ptr); "
            "fn bad()->Node access(reclaim,D) {"
            "var node:Node=make Node{ptr:null(*Node)}; node.ptr=&node; return node;}",
            "transfer requires movable owned or fresh storage",
        ),
        "domain-as-value": (
            "domain D(); const leaked:bool=D;",
            "only function names are permitted in constant initializers",
        ),
        "unknown-domain": ("fn f()->unit access(read,Unknown) {}", "requires a declared domain"),
        "unknown-output": (
            "domain D(); fn f()->unit access(edit,D) initializes(missing) {trap;}",
            "declared record pointer",
        ),
        "scalar-output": (
            "domain D(); fn f(x:i64)->unit access(edit,D) initializes(x) {trap;}",
            "declared record pointer",
        ),
        "foreign-contract": (
            'extern fn f(x:i32)->i32 foreign(scalar) ensures(false)="f";',
            "do not accept checked body contracts",
        ),
        "invalid-unused-invariant": (
            "domain D(C); record C {v:i64;} domain(D) invariant(missing);",
            "contract name",
        ),
        "invalid-unreachable-post": ("fn f()->unit ensures(missing) {trap;}", "contract name"),
        "literal-range": ("fn f(x:u8)->unit requires(x == 256u8) {}", "outside its declared type"),
        "bool-order": ("fn f(x:bool)->unit requires(x < true) {}", "invalid for its operand type"),
        "record-equality": (
            "record C {v:i64;} fn f(x:C)->unit requires(x == x) {}",
            "scalars or pointers",
        ),
    }
    scalar = """domain D(Cell);
record Cell { value:u8; } domain(D) invariant((*self).value == 1u8);
fn wrap(p:*Cell)->unit access(edit,D) requires(p!=null(*Cell)) {
    (*p).value = 257u16 as u8;
}
"""
    accepted = directory / "numeric-wrap.crs"
    accepted.write_text(scalar)
    command([compiler, "--library", "--check", accepted])
    cases["numeric-wrap-fails"] = (scalar.replace("257u16", "256u16"), "declared field invariants")
    expected = {
        "missing-update": "declared field invariants",
        "missing-postcondition": "declared field invariants",
        "undeclared-write": "modifies contract",
        "read-editor": "modified fields require edit access",
        "null-input": "pointer access requires live non-null storage",
        "observer-during-update": "declared field invariants",
    }
    for name, code in contract_cases().items():
        cases[name] = (code, expected[name])
    rejected(compiler, directory, cases)
    print(
        f"ownership contracts: graph native/root/erasure, scalar casts, and {len(cases)} semantic rejections passed"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-contracts-", dir=args.build) as temporary:
        run(args.build.resolve(), Path(temporary).resolve(), args.sanitize)


if __name__ == "__main__":
    main()
