# SPDX-License-Identifier: Apache-2.0

"""Check the CCN stage against Lizard and through real compilation roots."""

import argparse
import re
import shutil
import sys
from importlib.metadata import version
from pathlib import Path

import lizard
from source_order import ROOT, Suite

CASES = [
    ("straight", "return 0;", "return 0i32;", 1),
    (
        "if_else",
        "if(a) {return 1;} else {return 2;}",
        "if a {return 1i32;} else {return 2i32;}",
        2,
    ),
    (
        "else_if",
        "if(a) {return 1;} else if(b) {return 2;} return 0;",
        "if a {return 1i32;} else if b {return 2i32;} return 0i32;",
        3,
    ),
    ("while_true", "while(1) {break;} return 0;", "while true {break;} return 0i32;", 2),
    (
        "loop",
        "while(a && (b || c)) {if(b) {break;} continue;} return 0;",
        "while a && (b || c) {if b {break;} continue;} return 0i32;",
        5,
    ),
    (
        "logical",
        "if(a && b || c) {return 1;} return 0;",
        "if a && b || c {return 1i32;} return 0i32;",
        4,
    ),
    ("return_logic", "return a && b || c;", "return (a && b || c) as i32;", 3),
    (
        "unreachable",
        "return 0; if(a) {return 1;} return 2;",
        "return 0i32; if a {return 1i32;} return 2i32;",
        2,
    ),
    (
        "comment_string",
        '// if && || while\nchar *s="if && || while"; return 0;',
        '// if && || while\nvar s:*u8="if && || while"; return 0i32;',
        1,
    ),
    ("call", "return call(a && b,b || c);", "return call(a && b,b || c);", 3),
    (
        "array",
        "int xs[2]={a && b,b || c}; return 0;",
        "var xs:[bool;2]=make [bool;2]{a && b,b || c}; return 0i32;",
        3,
    ),
    (
        "record_init",
        "struct Flags xs={.x=a && b,.y=b || c}; return 0;",
        "var xs:Flags=make Flags{x:a && b,y:b || c}; return 0i32;",
        3,
    ),
    (
        "assignment",
        "int xs[2]={0,0}; xs[a && b]=a || c; return 0;",
        "var xs:[bool;2]=make [bool;2]{false,false}; xs[(a && b) as usize]=a || c; return 0i32;",
        3,
    ),
    (
        "field",
        "return ((struct Flags){.x=a && b,.y=0}).x;",
        "return (make Flags{x:a && b,y:false}).x as i32;",
        2,
    ),
    ("unary", "return !(a && b);", "return (!(a && b)) as i32;", 2),
    ("bitwise", "return (a & b) | c;", "return ((a as i32) & (b as i32)) | (c as i32);", 1),
    ("recursive", "return recursive(a && b,b,c);", "return recursive(a && b,b,c);", 2),
    ("boundary", "if(a){}" * 14 + "return 0;", "if a {}" * 14 + "return 0i32;", 15),
]

# In 1.21.6, CppRValueRefStates subtracts && when a later '=' appears before
# its terminators. These C expressions are not C++ rvalue references.
LIZARD_UNDERCOUNTS = {"record_init", "assignment", "field"}


def counts(output):
    return {name.decode(): int(ccn) for name, ccn in re.findall(rb": (\w+): CCN=(\d+)", output)}


def compare_lizard(suite, commands):
    c_source = "struct Flags {int x,y;};\n" + "\n".join(
        f"int {name}(int a,int b,int c){{{body}}}" for name, body, _, _ in CASES
    )
    crust_source = "record Flags {x:bool;y:bool;}\n" + "\n".join(
        f"fn {name}(a:bool,b:bool,c:bool)->i32{{{body}}}" for name, _, body, _ in CASES
    )
    expected = {name: ccn for name, _, _, ccn in CASES}
    actual = {
        function.name: function.cyclomatic_complexity
        for function in lizard.analyze_file.analyze_source_code("paired.c", c_source).function_list
    }
    lizard_expected = {name: ccn - (name in LIZARD_UNDERCOUNTS) for name, ccn in expected.items()}
    assert actual == lizard_expected, (actual, lizard_expected)
    c_path = suite.write("paired.c", c_source)
    source = suite.write("paired.crs", crust_source)
    for limit, status in ((15, 0), (14, 1)):
        suite.command(
            [sys.executable, "-m", "lizard", "-w", "--CCN", limit, c_path], expected=status
        )
        for command in commands:
            result = suite.command([*command, "--CCN", limit, source], expected=status)
            assert counts(result.stdout) == expected, result.stdout
            result = suite.command([*command, "-w", "--CCN", limit, source], expected=status)
            assert counts(result.stdout) == {n: c for n, c in expected.items() if c > limit}


def check_inputs(suite, commands):
    valid = suite.write("valid.crs", "fn good()->i32{return 0i32;}")
    root = suite.write(
        "data.crs",
        'trap; host_source(run,"missing-source.crs");\n'
        "if true && false {}; return 99i32;\n"
        "\tfn later()->i32{if true{return 1i32;} return 0i32;}\n",
    )
    empty = suite.write("empty.crs", "")
    declarations = suite.write(
        "no-functions.crs",
        '// while && if\nrecord R{x:bool;} extern fn e()->unit="e"; const c:bool=true || false;',
    )
    malformed = [
        suite.write("late-error.crs", "fn good()->unit{}\nfn broken("),
        suite.write("custom-grammar.crs", "return 0i32;\nPRINT Hello"),
        suite.write("deep.crs", "fn deep()->unit{" + "{" * 400 + "}" * 401),
    ]
    dash = suite.write("-leading.crs", valid.read_text())
    for command in commands:
        result = suite.command([*command, root])
        assert result.stdout == f"{root}:3:2: later: CCN=2\n".encode(), result
        assert not suite.command([*command, empty, declarations]).stdout
        result = suite.command([*command, "--", dash.name], cwd=suite.work)
        assert counts(result.stdout) == {"good": 1}
        for arguments in (
            [],
            ["--bad"],
            ["--CCN"],
            ["--CCN", "0", valid],
            ["--CCN", "-1", valid],
            ["--CCN", "", valid],
            ["--CCN", "1x", valid],
            ["--CCN", str(1 << 64), valid],
        ):
            result = suite.command([*command, *arguments], expected=2)
            assert not result.stdout and b"usage:" in result.stderr, result
        assert b"usage:" in suite.command([*command, "--help"]).stdout
        assert counts(suite.command([*command, "--CCN", str((1 << 64) - 1), valid]).stdout) == {
            "good": 1
        }
        for source in [*malformed, suite.work / "missing.crs"]:
            result = suite.command([*command, source], expected=2)
            assert not result.stdout and b": error:" in result.stderr, result
        result = suite.command([*command, "--CCN", 1, root, valid], expected=1)
        assert counts(result.stdout) == {"later": 2, "good": 1}, result
        with open("/dev/full", "wb") as stream:
            result = suite.command([*command, valid], expected=2, stdout=stream)
        assert b"cannot write CCN report" in result.stderr, result


def check_large(suite, commands):
    source = suite.write(
        "long-expression.crs", "fn long()->bool{return " + "true && " * 10000 + "true;}"
    )
    for command in commands:
        result = suite.command([*command, "--CCN", 10001, source])
        assert counts(result.stdout) == {"long": 10001}, result
    source = suite.write(
        "wide-expression.crs",
        "fn wide()->unit{call("
        + ",".join(["true || false"] * 1000)
        + ");}\n"
        + "fn next()->unit{}",
    )
    for command in commands:
        result = suite.command([*command, "--CCN", 1001, source])
        assert counts(result.stdout) == {"wide": 1001, "next": 1}, result
    return source


def check_tutorial(suite):
    copy = suite.work / "copied project"
    for path in ("examples/ccn", "stages/ccn", "stages/modules"):
        shutil.copytree(ROOT / path, copy / path, dirs_exist_ok=True)
    (copy / "stages/c").mkdir(parents=True, exist_ok=True)
    (copy / "api").mkdir(exist_ok=True)
    (copy / "build").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "stages/c/api.crs", copy / "stages/c/api.crs")
    shutil.copyfile(ROOT / "api/crust0_stage.crs", copy / "api/crust0_stage.crs")
    shutil.copyfile(suite.backend, copy / "build/crust-c-library.so")
    root = copy / "examples/ccn/main.crs"
    build = copy / "examples/ccn/build.crs"
    target = copy / "examples/ccn/program.crs"
    output = copy / "build/ccn-example"
    result = suite.command([suite.runner, root, target], cwd=suite.work)
    assert counts(result.stdout) == {"score": 4, "main": 2}, result
    suite.command([suite.runner, build], cwd=suite.work)
    suite.command([output])
    accepted = output.read_bytes()
    build.write_text(
        build.read_text().replace("CCN_LIMIT: usize = 4usize", "CCN_LIMIT: usize = 3usize")
    )
    result = suite.command([suite.runner, build], cwd=suite.work, expected=1)
    assert b"program.crs:3:1: error: function exceeds CCN limit" in result.stderr, result
    assert output.read_bytes() == accepted, "rejection modified the output"


def check_allocations(suite, source):
    fixture = suite.work / "allocation-sweep"
    flags = [item for flag in suite.cflags for item in ("--cflag", flag)]
    flags += [item for flag in suite.ldflags for item in ("--ldflag", flag)]
    suite.command(
        [
            suite.build / "crust-c",
            "-o",
            fixture,
            ROOT / "api/crust0.crs",
            ROOT / "api/crust0_host.crs",
            ROOT / "stages/ccn/count.crs",
            ROOT / "stages/ccn/read.crs",
            ROOT / "stages/ccn/report.crs",
            ROOT / "tests/ccn_alloc.crs",
            "--ldflag",
            suite.build / "libcrust0.a",
            "--ldflag",
            suite.build / "libcrust0_host.a",
            *flags,
        ]
    )
    suite.command([fixture, source])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--cflags", default="-O2")
    parser.add_argument("--ldflags", default="")
    suite = Suite(parser.parse_args())
    suite.work = suite.build / "ccn-tests"
    suite.work.mkdir(exist_ok=True)
    commands = [[suite.build / "crust-ccn"], [suite.runner, ROOT / "examples/ccn/main.crs"]]
    compare_lizard(suite, commands)
    check_inputs(suite, commands)
    wide = check_large(suite, commands)
    check_tutorial(suite)
    check_allocations(suite, wide)
    suite.command([*commands[0], "-w", *sorted((ROOT / "stages/ccn").glob("*.crs"))])
    print(
        f"CCN: {suite.checks} process checks passed; compared {len(CASES)} pairs with Lizard {version('lizard')} "
        f"({len(LIZARD_UNDERCOUNTS)} documented Lizard undercounts)"
    )


if __name__ == "__main__":
    main()
