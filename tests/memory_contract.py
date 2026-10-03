#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check declared memory effects against bodies, callers, and emitted programs."""

import argparse
import shutil
import tempfile
from pathlib import Path

from memory import FOREIGN, command
from resource_memory import execute

ROOT = Path(__file__).resolve().parents[1]
WRITE = "fn rewrite(p:*i32,n:i32)->unit {*p=n;}"
SWAP = "fn rewrite(a:*i32,b:*i32,scratch:*i32)->unit {var old:i32=*a;*a=*b;*b=old;}"
POINTER = "fn rewrite(out:**i32,value:*i32)->unit {*out=value;}"


def source(declaration, body=""):
    return FOREIGN + declaration + "fn main(argc:i32,argv:**u8)->i32{" + body + "return 0i32;}"


def accept_cases():
    return {
        "aliased-swap": (
            "swap",
            source(
                SWAP,
                "var a:i32=2i32;var b:i32=7i32;var t:i32=4i32;"
                "rewrite(&a,&b,&t);rewrite(&a,&a,&t);if a!=7i32 || b!=2i32{return 1i32;}",
            ),
        ),
        "output-initialization": (
            "write",
            source(WRITE, "var x:i32=uninit;rewrite(&x,7i32);if x!=7i32{return 1i32;}"),
        ),
        "conditional-body": (
            "write",
            source(
                WRITE.replace("*p=n;", "if n>0i32{*p=n;}else{*p=n;}"),
                "var x:i32=0i32;rewrite(&x,argc);if x!=argc{return 1i32;}",
            ),
        ),
        "early-return": (
            "write",
            source(
                WRITE.replace("*p=n;", "if n>0i32{*p=n;return;}*p=n;"),
                "var x:i32=0i32;rewrite(&x,argc);if x!=argc{return 1i32;}",
            ),
        ),
        "new-pointer-cell": (
            "write",
            source(
                POINTER,
                "var x:i32=7i32;var slot:*i32=uninit;rewrite(&slot,&x);"
                "if *slot!=7i32{return 1i32;}",
            ),
        ),
        "empty-effect": ("empty", source("fn rewrite()->unit{}", "rewrite();")),
        "heap-output": (
            "write",
            source(
                WRITE,
                "var p:*i32=allocate(sizeof(i32)) as *i32;"
                "if p!=null(*i32){rewrite(p,7i32);var n:i32=*p;release(p as *u8);"
                "if n!=7i32{return 1i32;}}",
            ),
        ),
    }


def reject_cases():
    cases = {
        "wrong-effect": ("write", source(WRITE.replace("*p=n", "*p=0i32"))),
        "missing-effect": ("write", source(WRITE.replace("*p=n;", ""))),
        "wrong-branch": ("write", source(WRITE.replace("*p=n;", "if n>0i32{*p=n;}"))),
        "undeclared-effect": ("empty", source(WRITE)),
        "restored-extra-write": (
            "swap",
            source(
                SWAP.replace(
                    "var old:i32=*a;",
                    "var tmp:i32=*scratch;*scratch=0i32;*scratch=tmp;var old:i32=*a;",
                )
            ),
        ),
        "null-caller": ("write", source(WRITE, "rewrite(null(*i32),2i32);")),
        "uninitialized-caller": (
            "swap",
            source(SWAP, "var a:i32=uninit;var b:i32=7i32;var t:i32=4i32;rewrite(&a,&b,&t);"),
        ),
        "out-of-bounds": ("write", source(WRITE, "var a:i32=0i32;rewrite(&a+1isize,2i32);")),
        "dead-output": (
            "write",
            source(
                WRITE,
                "var p:*i32=allocate(sizeof(i32)) as *i32;"
                "if p!=null(*i32){release(p as *u8);rewrite(p,2i32);}",
            ),
        ),
        "dead-value": (
            "write",
            source(
                POINTER,
                "var p:*i32=allocate(sizeof(i32)) as *i32;"
                "if p!=null(*i32){release(p as *u8);var slot:*i32=uninit;rewrite(&slot,p);}",
            ),
        ),
        "retained-stack-link": (
            "write",
            source(POINTER, "var slot:*i32=null(*i32);{var x:i32=7i32;rewrite(&slot,&x);}"),
        ),
        "retained-heap-link": (
            "write",
            source(
                POINTER,
                "var p:*i32=allocate(sizeof(i32)) as *i32;"
                "if p!=null(*i32){var slot:*i32=uninit;rewrite(&slot,p);release(p as *u8);}",
            ),
        ),
        "overlapping-types": (
            "write",
            source("fn rewrite(p:*u8,n:u8)->unit{*p=n;}", "var x:u64=0u64;rewrite(&x as *u8,2u8);"),
        ),
        "misalignment": (
            "write",
            source(
                WRITE,
                "var p:*u8=allocate(8usize);if p!=null(*u8){"
                "rewrite((p+1isize) as *i32,2i32);release(p);}",
            ),
        ),
    }
    result = {name: (*item, "counterexample") for name, item in cases.items()}
    result.update(
        {
            "vacuous-model": ("false", source(WRITE), "preconditions are inconsistent"),
            "duplicate-model": ("duplicate", source(WRITE), "already selected"),
            "missing-model": ("absent", source(WRITE), "defined unit function and a model"),
            "failed-prepare": ("failed-prepare", source(WRITE), "preparation failed"),
            "unit-result": (
                "empty",
                source("fn rewrite()->i32{return 0i32;}"),
                "defined unit function",
            ),
            "foreign-body": (
                "empty",
                source('extern fn rewrite()->unit="external";'),
                "defined unit function",
            ),
            "missing-body": ("empty", source(""), "absent declaration"),
            "loop": (
                "write",
                source(WRITE.replace("*p=n;", "while n>0i32{*p=n;break;}")),
                "loop-free",
            ),
            "local-storage": (
                "write",
                source(WRITE.replace("*p=n;", "var x:i32=n;*p=*(&x);")),
                "local storage",
            ),
            "cleanup-body": (
                "write",
                source(
                    "fn clear(p:*i32)->unit{*p=0i32;}"
                    + WRITE.replace("*p=n;", "defer clear(p);*p=n;")
                ),
                "cannot contain calls",
            ),
            "nested-call": (
                "write",
                source("fn value(n:i32)->i32{return n;}" + WRITE.replace("*p=n;", "*p=value(n);")),
                "cannot contain calls",
            ),
            "trap": ("write", source(WRITE.replace("*p=n;", "trap;")), "loop-free"),
        }
    )
    return result


def run_cases(build, directory, sanitize):
    compiler = build / "crust-memory-contract-test"
    for name, (model, text) in accept_cases().items():
        path = directory / f"{name}.crs"
        path.write_text(text)
        output, symbols, expanded = (
            directory / f"{name}{suffix}" for suffix in (".c", ".rsp", "-expanded.c")
        )
        command([compiler, "--model", model, "--emit-c", "--symbols", symbols, "-o", output, path])
        command([build / "crust-resource-memory-test", "--emit-c", "-o", expanded, path])
        if output.read_bytes() != expanded.read_bytes():
            raise RuntimeError(f"{name}: contract changed target C")
        execute(output, symbols, directory, name, sanitize, b"")
    for name, (model, text, message) in reject_cases().items():
        path = directory / f"{name}.crs"
        path.write_text(text)
        output = directory / f"{name}.c"
        output.write_text("preserve output\n")
        result = command([compiler, "--model", model, "--emit-c", "-o", output, path], 1)
        if message not in result.stderr.decode() or output.read_text() != "preserve output\n":
            raise RuntimeError(f"{name}: wrong rejection: {result.stderr!r}")
    return len(accept_cases()) + len(reject_cases())


def unlink_cases(build, directory):
    compiler = build / "crust-memory-contract-test"
    caller = directory / "unused.crs"
    caller.write_text(source(""))
    links = (ROOT / "examples/ownership/links.crs").read_text()
    count = 0
    cases = {
        "original": (links, 0),
        "missing-backlink": (links.replace("    (*after).prev = before;\n", ""), 1),
        "missing-detach": (links.replace("    (*h).next = h;\n", ""), 1),
        "conditional": (
            links.replace(
                "    (*h).prev = h;", "    if (*h).prev == h {(*h).prev=h;}else{(*h).prev=h;}"
            ),
            0,
        ),
    }
    for name, (text, expected) in cases.items():
        path = directory / f"{name}-links.crs"
        path.write_text(text)
        result = command(
            [compiler, "--unlink", "unlink", "prev", "next", "--check", path, caller], expected
        )
        if expected and "counterexample" not in result.stderr.decode():
            raise RuntimeError(f"{name}: wrong rejection: {result.stderr!r}")
        count += 1
    path = directory / "renamed.crs"
    path.write_text(
        links.replace("Hook", "Entry")
        .replace("unlink", "detach")
        .replace("prev", "back")
        .replace("next", "forward")
    )
    command([compiler, "--unlink", "detach", "back", "forward", "--check", path, caller])
    count += 1
    for names, message in (
        (["absent", "back", "forward"], "absent declaration"),
        (["detach", "back", "back"], "different link fields"),
        (["detach", "absent", "forward"], "pointer field"),
        (["insert_after", "back", "forward"], "one hook pointer"),
    ):
        result = command([compiler, "--unlink", *names, "--check", path, caller], 1)
        if message not in result.stderr.decode():
            raise RuntimeError(f"{names}: wrong diagnostic: {result.stderr!r}")
        count += 1
    return count


def composition_cases(build, directory):
    compiler = build / "crust-memory-contract-test"
    path = directory / "composition.crs"
    path.write_text(
        source(
            WRITE + "fn inspect(p:*i32)->unit{var n:i32=*p;}",
            "var x:i32=uninit;rewrite(&x,7i32);inspect(&x);",
        )
    )
    command([compiler, "--summary", "inspect", "--model", "write", "--check", path])
    result = command([compiler, "--summary", "rewrite", "--model", "write", "--check", path], 1)
    if "already selected" not in result.stderr.decode():
        raise RuntimeError(f"contract/summary conflict: {result.stderr!r}")
    return 2


def root_fixture(build, directory):
    tree = directory / "tutorial"
    for name in (
        "api/crust0_stage.crs",
        "stages/memory/options.crs",
        "examples/intrusive/contract-options.crs",
        "examples/intrusive/contract-main.crs",
    ):
        target = tree / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    (tree / "build").mkdir()
    shutil.copyfile(
        build / "crust-intrusive-contract-library.so",
        tree / "build/crust-intrusive-contract-library.so",
    )
    return tree / "examples/intrusive/contract-main.crs"


def root_case(build, directory, sanitize, reference):
    output, symbols = directory / "intrusive.c", directory / "intrusive.rsp"
    inputs = [ROOT / "examples/ownership/links.crs", ROOT / "examples/intrusive/program.crs"]
    command(
        [
            build / "crust",
            root_fixture(build, directory),
            "--emit-c",
            "--symbols",
            symbols,
            "-o",
            output,
            *inputs,
        ],
        timeout=600,
    )
    if reference is None:
        reference = directory / "intrusive-baseline.c"
        command(
            [
                build / "crust-resource-memory-test",
                "--summary",
                "unlink",
                "--emit-c",
                "-o",
                reference,
                *inputs,
            ],
            timeout=600,
        )
    if output.read_bytes() != reference.read_bytes():
        raise RuntimeError("intrusive contract changed target C")
    execute(output, symbols, directory, "intrusive", sanitize, b"OK\n")
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    parser.add_argument(
        "--reference", type=Path, help="C captured from the unchanged intrusive inputs"
    )
    parser.add_argument("--case", choices=("small", "root", "all"), default="all")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="crust memory contracts ") as temporary:
        directory, build = Path(temporary), args.build.resolve()
        count = 0
        if args.case != "root":
            count += run_cases(build, directory, args.sanitize) + unlink_cases(build, directory)
            count += composition_cases(build, directory)
            print(f"Memory contracts: {count} body and caller cases", flush=True)
        if args.case != "small":
            count += root_case(build, directory, args.sanitize, args.reference)
        print(f"Memory contracts: {count} cases passed", flush=True)


if __name__ == "__main__":
    main()
