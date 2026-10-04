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


SCALAR_FLOW = (
    "fn clear(flag:mut bool)->unit {flag=false;} "
    "fn branch(flag:mut bool,test:bool)->unit {flag=true;if test {flag=false;}} "
    "fn finish(flag:mut bool)->unit {while flag {flag=false;}} "
    "fn main(argc:i32,argv:**u8)->i32 {var flag:bool=true;branch(mut flag,true);"
    "if flag {trap;}flag=true;while flag {clear(mut flag);}"
    "flag=true;finish(mut flag);if flag {trap;}return 0i32;}"
)


def scalar_flow_cases():
    schema = "domain D(Cell);record Cell {value:i64;} domain(D) invariant(true); "
    null_access = " access(read,D) requires(p==null(*Cell)) "
    return {
        "scalar-loan-branch": (
            schema
            + "fn bad(flag:mut bool,test:bool,p:*Cell)->i64"
            + null_access
            + "{flag=true;if test {flag=false;}if flag {return 0i64;}return (*p).value;}",
            "pointer access requires live non-null storage",
        ),
        "scalar-loan-loop-call": (
            schema
            + "fn clear(flag:mut bool)->unit {flag=false;} fn bad(p:*Cell)->i64"
            + null_access
            + "{var flag:bool=true;while flag {clear(mut flag);}return (*p).value;}",
            "pointer access requires live non-null storage",
        ),
        "scalar-parameter-loop": (
            schema
            + "fn bad(flag:mut bool,p:*Cell)->i64"
            + null_access
            + "{flag=true;while flag {flag=false;}return (*p).value;}",
            "pointer access requires live non-null storage",
        ),
    }


def scalar_flow_native(build, directory, sanitize):
    source = directory / "scalar-flow.crs"
    source.write_text(SCALAR_FLOW)
    generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
    command(
        [build / "crust-ownership-test", "--emit-c", "--symbols", symbols, "-o", generated, source]
    )
    command([build / "crust-ownership-erasure", source])
    execute(generated, symbols, directory, "scalar-flow", sanitize, b"")


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
        "mutable-scalar-call": (
            "domain D(Cell); record Cell {value:i64;} domain(D) invariant(true); "
            "fn clear(flag:mut bool)->unit {flag=false;} "
            "fn bad(p:*Cell)->i64 access(read,D) requires(p==null(*Cell)) {"
            "var flag:bool=true; clear(mut flag); if flag {return 0i64;} return (*p).value;}",
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
    snapshot = directory / "mutable-scalar-snapshot.crs"
    snapshot.write_text(
        cases["mutable-scalar-call"][0].replace(
            "clear(mut flag); if flag", "var saved:bool=flag; clear(mut flag); if saved"
        )
    )
    command([compiler, "--library", "--check", snapshot])
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
    scalar_flow_native(build, directory, sanitize)
    cases.update(scalar_flow_cases())
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
