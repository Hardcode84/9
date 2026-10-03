#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check inferred memory effects, caller obligations, and unchanged target code."""

import argparse
import json
import tempfile
from pathlib import Path

from memory import FOREIGN, command
from resource_memory import execute

ROOT = Path(__file__).resolve().parents[1]


def source(declarations, body):
    return FOREIGN + declarations + "fn main(argc:i32,argv:**u8)->i32 {" + body + "return 0i32;}"


def accept_cases(resources=False):
    cases = {
        "aliased-swap": source(
            "fn rewrite(a:*i32,b:*i32)->unit {var old:i32=*a;*a=*b;*b=old;}",
            "var x:i32=2i32;var y:i32=7i32;rewrite(&x,&y);rewrite(&x,&x);"
            "if x!=7i32 || y!=2i32{return 1i32;}",
        ),
        "caller-branches": source(
            "fn rewrite(p:*i32,n:i32)->unit {*p=*p+n;}",
            "var x:i32=0i32;if argc>0i32 {x=1i32;} else {x=2i32;}"
            "rewrite(&x,5i32);if argc>0i32 && x!=6i32{return 1i32;}",
        ),
        "new-pointer-cell": source(
            "fn rewrite(out:**i32,p:*i32)->unit {*out=p;}",
            "var hold:**i32=allocate(sizeof(*i32)) as **i32;"
            "if hold!=null(**i32) {var x:i32=3i32;rewrite(hold,&x);"
            "var n:i32=**hold;release(hold as *u8);if n!=3i32{return 1i32;}}",
        ),
        "early-return": source(
            "fn rewrite(p:*i32)->unit {*p=2i32;return;*p=3i32;}",
            "var x:i32=1i32;rewrite(&x);if x!=2i32{return 1i32;}",
        ),
        "no-writes": source(
            "fn rewrite(p:*i32)->unit {var n:i32=*p;}",
            "var x:i32=3i32;rewrite(&x);",
        ),
        "new-initialization": source(
            "fn rewrite(p:*i32)->unit {*p=3i32;}",
            "var p:*i32=allocate(sizeof(i32)) as *i32;if p!=null(*i32) {"
            "rewrite(p);var x:i32=*p;release(p as *u8);if x!=3i32{return 1i32;}}",
        ),
        "local-output-initialization": source(
            "fn rewrite(p:*i32)->unit {*p=3i32;}",
            "var x:i32=uninit;rewrite(&x);if x!=3i32{return 1i32;}",
        ),
    }
    if resources:
        del cases["early-return"]
        cases["consume-field"] = source(
            "record Hold {value:*u8;}" "fn rewrite(p:*Hold)->unit {var old:*u8=move (*p).value;}",
            "var p:*u8=allocate(1usize);var h:Hold=make Hold{value:p};rewrite(&h);release(p);",
        )
    else:
        cases["guarded-read"] = source(
            "fn rewrite(p:*i32,out:*bool)->unit {*out=false && *p==0i32;}",
            "var out:bool=true;rewrite(null(*i32),&out);if out{return 1i32;}",
        )
    return cases


def reject_cases(resources=False):
    cases = {
        "null-access": source("fn rewrite(p:*i32)->unit {*p=1i32;}", "rewrite(null(*i32));"),
        "uninitialized-read": source(
            "fn rewrite(p:*i32)->unit {*p=*p+1i32;}",
            "var p:*i32=allocate(sizeof(i32)) as *i32;if p!=null(*i32) {rewrite(p);release(p as *u8);}",
        ),
        "dead-read": source(
            "fn rewrite(p:*i32)->unit {var x:i32=*p;}",
            "var p:*i32=allocate(4usize) as *i32;if p!=null(*i32) {"
            "*p=1i32;release(p as *u8);rewrite(p);}",
        ),
        "published-inner-address": source(
            "fn rewrite(out:**i32,p:*i32)->unit {*out=p;}",
            "var hold:**i32=allocate(sizeof(*i32)) as **i32;if hold!=null(**i32) {"
            "{var x:i32=3i32;rewrite(hold,&x);}release(hold as *u8);}",
        ),
        "caller-store-overlap": source(
            "fn rewrite(p:*u8)->unit {*p=1u8;}", "var n:u64=0u64;rewrite(&n as *u8);"
        ),
        "internal-store-overlap": source(
            "fn rewrite(p:*u64,q:*u8)->unit {*p=0u64;*q=1u8;}",
            "var p:*u8=allocate(sizeof(u64));if p!=null(*u8) {rewrite(p as *u64,p+1isize);release(p);}",
        ),
        "misaligned-access": source(
            "fn rewrite(p:*i32)->unit {*p=1i32;}",
            "var p:*u8=allocate(8usize);if p!=null(*u8) {rewrite((p+1isize) as *i32);release(p);}",
        ),
        "out-of-bounds": source(
            "fn rewrite(p:*i32)->unit {*p=1i32;}",
            "var x:i32=0i32;rewrite(&x+1isize);",
        ),
        "unsafe-prefix-before-trap": source(
            "fn rewrite(p:*i32)->unit {*p=1i32;}", "rewrite(null(*i32));trap;"
        ).removesuffix("return 0i32;}")
        + "}",
        "divisor-precondition": source(
            "fn rewrite(p:*i32,n:i32)->unit {*p=7i32/n;}", "var x:i32=0i32;rewrite(&x,0i32);"
        ),
    }
    if resources:
        cases["consumed-field-read"] = source(
            "record Hold {value:*u8;}" "fn rewrite(p:*Hold)->unit {var old:*u8=move (*p).value;}",
            "var p:*u8=allocate(1usize);var h:Hold=make Hold{value:p};rewrite(&h);"
            "var alias:*u8=h.value;release(p);",
        )
    return {name: (text, "counterexample") for name, text in cases.items()}


def unsupported_cases():
    return {
        "branch": ("if *p==0i32 {*p=1i32;}", "straight-line"),
        "loop": ("while *p==0i32 {*p=1i32;}", "straight-line"),
        "local-storage": ("var n:i32=1i32;var q:*i32=&n;*p=*q;", "local storage"),
        "foreign-call": ("var n:i32=emit(1i32);*p=n;", "cannot contain calls"),
        "nested-call": ("var n:i32=helper(p);*p=n;", "cannot contain calls"),
    }


def run_suite(build, directory, resources, sanitize):
    compiler = build / ("crust-resource-memory-test" if resources else "crust-memory-test")
    count = 0
    for name, text in accept_cases(resources).items():
        path = directory / f"{name}.crs"
        path.write_text(text)
        checked = directory / f"{name}.c"
        expanded = directory / f"{name}-expanded.c"
        symbols = directory / f"{name}.rsp"
        command(
            [
                compiler,
                "--summary",
                "rewrite",
                "--emit-c",
                "--symbols",
                symbols,
                "-o",
                checked,
                path,
            ]
        )
        command([compiler, "--emit-c", "-o", expanded, path])
        if checked.read_bytes() != expanded.read_bytes():
            raise RuntimeError(f"{name}: summary changed target C")
        execute(checked, symbols, directory, name, sanitize, b"")
        count += 1
    rejected = reject_cases(resources)
    for name, (body, message) in unsupported_cases().items():
        rejected[name] = (
            source(
                "fn helper(p:*i32)->i32 {return *p;}fn rewrite(p:*i32)->unit {" + body + "}",
                "var x:i32=0i32;rewrite(&x);",
            ),
            message,
        )
    for name, (text, message) in rejected.items():
        path = directory / f"{name}.crs"
        path.write_text(text)
        output = directory / f"{name}.c"
        output.write_text("preserve output\n")
        result = command([compiler, "--summary", "rewrite", "--emit-c", "-o", output, path], 1)
        if message not in result.stderr.decode() or output.read_text() != "preserve output\n":
            raise RuntimeError(f"{name}: invalid rejection: {result.stderr!r}")
        count += 1
    path = directory / "selection.crs"
    path.write_text(source("fn rewrite()->unit {}", "rewrite();"))
    for name, message in (
        ("absent", "absent declaration"),
        ("allocate", "defined unit-returning"),
        ("main", "defined unit-returning"),
    ):
        result = command([compiler, "--summary", name, "--check", path], 1)
        if message not in result.stderr.decode():
            raise RuntimeError(f"{name}: invalid selection diagnostic: {result.stderr!r}")
        count += 1
    print(f"{'resource' if resources else 'seed'} memory summaries: {count} cases", flush=True)
    return count


def root_cases(build, directory, sanitize):
    root = directory / "main.crs"
    target = directory / "target.crs"
    target.write_text(
        source(
            "fn rewrite(p:*i32)->unit {*p=7i32;}fn inspect(p:*i32)->unit {var n:i32=*p;}",
            "var x:i32=0i32;rewrite(&x);inspect(&x);if x!=7i32{return 1i32;}",
        )
    )
    prefix = "".join(
        f"host_source(run, {json.dumps(str(ROOT / path))});\n"
        for path in (
            "api/crust0_stage.crs",
            "stages/memory/options.crs",
            "stages/resource_memory/api.crs",
            "stages/resource_memory/build.crs",
        )
    )
    prefix += f"host_link(run, {json.dumps(str(build.resolve() / 'crust-resource-memory-library.so'))});\n"
    template = (
        prefix
        + """
var names:[*u8;2]=make [*u8;2]{"rewrite", "inspect"};
var foreign:[PmForeignSpec;3]=make [PmForeignSpec;3]{
    make PmForeignSpec{name:"allocate",alignment:16usize,kind:PM_ALLOCATE},
    make PmForeignSpec{name:"release",alignment:1usize,kind:PM_RELEASE},
    make PmForeignSpec{name:"emit",alignment:1usize,kind:PM_SCALAR}
};
var options:PmOptions=make PmOptions{foreign:&foreign[0usize],foreign_count:3usize,
    summaries:&names[0usize],summary_count:2usize,max_depth:128usize,
    max_paths:16usize,max_iterations:4usize,milliseconds:10000u32};
var result:i32=resource_memory_build(null(*CrustSource),0usize,(*run).argc,(*run).argv,&options);
if result!=0i32{return result;};
return resource_memory_build(null(*CrustSource),0usize,(*run).argc,(*run).argv,&options);
"""
    )
    root.write_text(template)
    generated = directory / "root.c"
    symbols = directory / "root.rsp"
    command([build / "crust", root, "--emit-c", "--symbols", symbols, "-o", generated, target])
    execute(generated, symbols, directory, "root", sanitize, b"")
    root.write_text(template.replace('"rewrite", "inspect"', '"rewrite", "rewrite"'))
    result = command([build / "crust", root, "--check", target], 1)
    if "same declaration twice" not in result.stderr.decode():
        raise RuntimeError(f"duplicate selection: {result.stderr!r}")
    print("summary roots: two selections, repeated contexts, duplicate rejection", flush=True)
    return 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="memory-summary-", dir=args.build) as temporary:
        count = sum(
            run_suite(args.build, Path(temporary), resources, args.sanitize)
            for resources in (False, True)
        )
        count += root_cases(args.build, Path(temporary), args.sanitize)
    print(f"memory summaries: {count} cases")


if __name__ == "__main__":
    main()
