#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check loop induction, complete resource views, erasure, and native execution."""

import argparse
import fnmatch
import shutil
import tempfile
from pathlib import Path

from memory import FOREIGN, command
from resource_memory import execute

ROOT = Path(__file__).resolve().parents[1]


def scalar(body="n=n-1usize;", before="", after="", condition="n!=0usize", expected=0):
    return (
        FOREIGN
        + "fn countdown(n:usize)->usize{"
        + before
        + "while "
        + condition
        + "{"
        + body
        + "}"
        + after
        + "return n;}"
        + "fn main(argc:i32,argv:**u8)->i32{var result:usize=countdown(1000usize+argc as usize);"
        + f"if result!={expected}usize{{return 1i32;}}return 0i32;}}"
    )


def walk_source():
    return (
        FOREIGN
        + (ROOT / "examples/ownership/links.crs").read_text()
        + (ROOT / "examples/intrusive/walk.crs")
        .read_text()
        .replace('extern fn emit(code: i32) -> i32 = "putchar";', "")
    )


def accept_cases():
    return {
        "countdown": ("count", scalar()),
        "continue": ("count", scalar("n=n-1usize;if n!=0usize{continue;}")),
        "break": ("count", scalar("n=n-1usize;if n==0usize{break;}")),
        "branch": ("count", scalar("if n%2usize==0usize{n=n-1usize;}else{n=n-1usize;}")),
        "local": ("count", scalar("var step:usize=1usize;step=step+0usize;n=n-step;")),
        "no-modified-bindings": ("count", scalar("break;", expected=1001)),
        "zero-iterations": ("count", scalar().replace("1000usize+argc as usize", "0usize")),
        "uninitialized-body-local": (
            "count",
            scalar("var step:usize=uninit;step=1usize;n=n-step;"),
        ),
        "signed": (
            "count",
            FOREIGN
            + scalar(condition="n>0usize")
            .removeprefix(FOREIGN)
            .replace("usize", "i8")
            .replace("1000i8+argc as i8", "10i8"),
        ),
        "array-read": (
            "count",
            scalar(
                "var x:i32=values[n%2usize];n=n-1usize;",
                before="var values:[i32;2]=make [i32;2]{3i32,7i32};",
            ),
        ),
        "trap-exit": ("count", scalar("if n>500usize{break;}trap;", expected=1001)),
        "walk": ("walk", walk_source()),
    }


def reject_cases():
    cases = {
        "invariant-entry": ("false", scalar(), "counterexample"),
        "variant-constant": ("constant", scalar(), "counterexample"),
        "variant-negative": ("negative", scalar(), "counterexample"),
        "missing-terms": ("missing", scalar(), "invariant and an integer variant"),
        "predicate-depth": ("deep", scalar(), "depth budget"),
        "path-budget": ("budget", scalar(), "path budget"),
        "no-decrement": ("count", scalar(""), "counterexample"),
        "counter-increase": ("count", scalar("n=n+1usize;"), "counterexample"),
        "unsigned-wrap": ("count", scalar("n=n-2usize;"), "counterexample"),
        "signed-wrap": (
            "weak",
            FOREIGN
            + scalar("n=n-1usize;", condition="n!=100usize")
            .removeprefix(FOREIGN)
            .replace("usize", "i8")
            .replace("1000i8+argc as i8", "10i8"),
            "counterexample",
        ),
        "missed-branch-update": (
            "count",
            scalar("if n!=500usize{n=n-1usize;}"),
            "counterexample",
        ),
        "middle-invalid-access": (
            "count",
            scalar("if n==500usize{var x:i32=*null(*i32);}n=n-1usize;"),
            "counterexample",
        ),
        "modified-boolean": (
            "count",
            scalar(
                "if seen{var x:i32=*null(*i32);}seen=true;n=n-1usize;",
                before="var seen:bool=false;",
            ),
            "counterexample",
        ),
        "unsafe-before-continue": (
            "count",
            scalar("if n==500usize{var x:i32=*null(*i32);n=n-1usize;continue;}n=n-1usize;"),
            "counterexample",
        ),
        "unsafe-before-break": (
            "count",
            scalar("if n==500usize{var x:i32=*null(*i32);break;}n=n-1usize;"),
            "counterexample",
        ),
        "false-invariant-after-unsafe-prefix": (
            "false",
            scalar(before="var x:i32=*null(*i32);"),
            "counterexample",
        ),
        "condition-access": (
            "count",
            scalar(condition="*null(*i32)==0i32"),
            "counterexample",
        ),
        "uninitialized-outer-binding": (
            "count",
            scalar("x=1usize;n=n-1usize;", before="var x:usize=uninit;"),
            "initialized modified bindings",
        ),
        "uninitialized-local-read": (
            "count",
            scalar("var x:usize=uninit;n=n-x;"),
            "uninitialized",
        ),
        "addressed-binding": (
            "count",
            scalar("var x:usize=n;var p:*usize=&x;n=n-1usize;"),
            "local storage",
        ),
        "memory-write": (
            "count",
            scalar("x=1usize;n=n-1usize;", before="var x:usize=0usize;var p:*usize=&x;"),
            "local storage",
        ),
        "indirect-write": (
            "count",
            scalar("*p=1usize;n=n-1usize;", before="var x:usize=0usize;var p:*usize=&x;"),
            "read-only memory",
        ),
        "nested-call": (
            "count",
            scalar("n=n-emit(0i32) as usize;"),
            "cannot contain calls",
        ),
        "defer-in-body": (
            "count",
            scalar("defer release(null(*u8));n=n-1usize;"),
            "cannot contain calls",
        ),
        "nested-loop": (
            "count",
            scalar("while n>1usize{n=n-1usize;}n=n-1usize;"),
            "requires one loop",
        ),
        "return-from-body": ("count", scalar("return 0usize;"), "does not support"),
        "unsafe-before-trap": ("count", scalar("var x:i32=*null(*i32);trap;"), "counterexample"),
    }
    text = walk_source()
    for name, old, new, diagnostic in (
        ("walk-no-progress", "remaining = remaining - 1usize;", "", "counterexample"),
        (
            "walk-middle-null",
            "cursor = (*cursor).next;",
            "if remaining==500usize{cursor=null(*Hook);}cursor=(*cursor).next;",
            "counterexample",
        ),
        ("walk-no-detach", "unlink(value.hook);", "", "counterexample"),
        ("walk-no-init", "hook_init(&node);", "", "counterexample"),
        (
            "walk-consume-link",
            "cursor = (*cursor).next;",
            "cursor = move (*cursor).next;",
            "counterexample",
        ),
        (
            "walk-mutate-link",
            "cursor = (*cursor).next;",
            "(*cursor).next=cursor;cursor=(*cursor).next;",
            "read-only memory",
        ),
        (
            "walk-unsafe-then-restore",
            "cursor = (*cursor).next;",
            "var saved:*Hook=cursor;cursor=null(*Hook);var p:*Hook=(*cursor).next;cursor=saved;",
            "counterexample",
        ),
    ):
        assert old in text
        cases[name] = ("walk", text.replace(old, new, 1), diagnostic)
    stale = text.replace(
        "    {\n        var node:", "    var stale:*Hook=null(*Hook);\n    {\n        var node:"
    )
    stale = stale.replace(
        "var reached: *Hook = walk(&head, count);",
        "var reached: *Hook = walk(&head, count);stale=reached;",
    )
    stale = stale.replace(
        "var again: *Hook =", "var bad:*Hook=(*stale).next;\n    var again: *Hook ="
    )
    cases["walk-stale-after-cleanup"] = ("walk", stale, "counterexample")
    return cases


def selection(model):
    return ["--walk", "walk", "next"] if model == "walk" else ["--model", model]


def run_cases(build, directory, sanitize, pattern):
    count = 0
    compiler = build / "crust-memory-loop-test"
    for name, (model, text) in accept_cases().items():
        if not fnmatch.fnmatchcase(name, pattern):
            continue
        count += 1
        path = directory / f"{name}.crs"
        path.write_text(text)
        output, symbols, reference = (
            directory / f"{name}{suffix}" for suffix in (".c", ".rsp", "-reference.c")
        )
        args = ["--emit-c", "--symbols", symbols, "-o", output, path]
        command([compiler, *selection(model), *args])
        command([compiler, "--reference", "--emit-c", "-o", reference, path])
        if output.read_bytes() != reference.read_bytes():
            raise RuntimeError(f"{name}: invariant changed target C")
        execute(output, symbols, directory, name, sanitize, b"OK\n" if model == "walk" else b"")
        print(f"{name}: proved, erased, executed", flush=True)
    for name, (model, text, message) in reject_cases().items():
        if not fnmatch.fnmatchcase(name, pattern):
            continue
        count += 1
        path = directory / f"{name}.crs"
        path.write_text(text)
        output = directory / f"{name}.c"
        output.write_text("preserve output\n")
        result = command([compiler, *selection(model), "--emit-c", "-o", output, path], 1)
        if message not in result.stderr.decode() or output.read_text() != "preserve output\n":
            raise RuntimeError(f"{name}: wrong rejection: {result.stderr!r}")
        print(f"{name}: rejected", flush=True)
    return count


def root_cases(build, directory, sanitize):
    tree = directory / "relocated tutorial"
    for name in (
        "api/crust0_stage.crs",
        "stages/memory/options.crs",
        "examples/intrusive/walk-options.crs",
        "examples/intrusive/walk-main.crs",
    ):
        target = tree / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    (tree / "build").mkdir()
    shutil.copyfile(
        build / "crust-intrusive-walk-library.so", tree / "build/crust-intrusive-walk-library.so"
    )
    inputs = [ROOT / "examples/ownership/links.crs", ROOT / "examples/intrusive/walk.crs"]
    output, symbols = directory / "root.c", directory / "root.rsp"
    command(
        [
            build / "crust",
            tree / "examples/intrusive/walk-main.crs",
            "--emit-c",
            "--symbols",
            symbols,
            "-o",
            output,
            *inputs,
        ]
    )
    reference = directory / "root-reference.c"
    command([build / "crust-memory-loop-test", "--reference", "--emit-c", "-o", reference, *inputs])
    if output.read_bytes() != reference.read_bytes():
        raise RuntimeError("root: proof changed target C")
    execute(output, symbols, directory, "root", sanitize, b"OK\n")
    (directory / "walk.crs").write_text(walk_source())
    bounded = command([build / "crust-resource-memory-test", "--check", directory / "walk.crs"], 1)
    if "counterexample" not in bounded.stderr.decode():
        raise RuntimeError(f"bounded profile: {bounded.stderr!r}")
    renamed = directory / "renamed.crs"
    renamed.write_text(
        walk_source()
        .replace("walk", "traverse")
        .replace("Hook", "Link")
        .replace("next", "forward")
        .replace("prev", "back")
        .replace(
            "record Link { back: *Link; forward: *Link; }",
            "record Link { forward: *Link; back: *Link; }",
        )
    )
    compiler = build / "crust-memory-loop-test"
    command([compiler, "--walk", "traverse", "forward", "--check", renamed])
    for function, field, message in (
        ("absent", "forward", "absent declaration"),
        ("traverse", "absent", "pointer field"),
        ("unlink", "forward", "hook pointer and a usize count"),
        ("splice_init", "forward", "hook pointer and a usize count"),
    ):
        result = command([compiler, "--walk", function, field, "--check", renamed], 1)
        if message not in result.stderr.decode():
            raise RuntimeError(f"{function}/{field}: {result.stderr!r}")
    return 7


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    parser.add_argument("--filter", default="*")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="crust loop proofs ") as temporary:
        directory, build = Path(temporary), args.build.resolve()
        count = run_cases(build, directory, args.sanitize, args.filter)
        if args.filter in ("*", "root"):
            count += root_cases(build, directory, args.sanitize)
    print(f"Loop proofs: {count} cases passed")


if __name__ == "__main__":
    main()
