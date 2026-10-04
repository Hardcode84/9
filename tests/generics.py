#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise standalone generic definitions through their compiled public API."""

import argparse
import shutil
from pathlib import Path

from source_order import ROOT, Suite

PROVIDER = """
record P { value:i64; }
record Q { first:i64; second:i64; third:i64; }
fn provider_hook()->i32 {return 17i32;}
fn unit_type()->unit {}
"""
EQUAL_LAYOUT = PROVIDER.replace("first:i64; second:i64; third:i64;", "value:i64;")
CONSUMER = """
fn helper()->i32 {return 90i32;}
fn captured()->i32 {return 91i32;}
fn same(value:*First)->*Alias {return value;}
fn consumer()->i32 {return generated();}
"""
TEMPLATE = """
record Item { value:T; next:*Item; }
fn helper()->i32 {return captured();}
fn run()->i32 {return helper();}
"""


def build_driver(suite, filename, evaluator=False):
    sources = [ROOT / "api/crust0.crs", ROOT / "api/crust0_host.crs"]
    if evaluator:
        sources.append(ROOT / "api/crust0_eval.crs")
    sources += [
        path for path in sorted((ROOT / "stages/generics").glob("*.crs")) if path.name != "api.crs"
    ]
    output = suite.work / filename
    flags = [item for flag in suite.cflags for item in ("--cflag", flag)]
    libraries = [suite.build / "libcrust0.a", suite.build / "libcrust0_host.a"]
    if evaluator:
        libraries.insert(0, suite.build / "libcrust0_run.a")
        libraries += ["-ldl", "-lffi"]
    flags += [item for flag in [*libraries, *suite.ldflags] for item in ("--ldflag", flag)]
    suite.command(
        [suite.build / "crust-c", "-o", output, *sources, ROOT / f"tests/{filename}.crs", *flags]
    )
    return output


def run_case(
    suite,
    driver,
    name,
    *,
    template=TEMPLATE,
    provider=PROVIDER,
    consumer=CONSUMER,
    mode="apply",
    values=(17, 17),
    diagnostic=None,
):
    paths = [
        suite.write(f"{name}/{kind}.crs", contents)
        for kind, contents in (
            ("provider", provider),
            ("template", template),
            ("consumer", consumer),
        )
    ]
    result = suite.command(
        [driver, mode, *paths, *map(str, values)], expected=1 if diagnostic else 0
    )
    if diagnostic:
        assert diagnostic in result.stderr, (name, result.stderr)
    else:
        assert not result.stdout and not result.stderr, (name, result.stdout, result.stderr)


def check_successes(suite, driver):
    run_case(suite, driver, "hygiene-and-frozen-input")
    run_case(suite, driver, "equal-layout-nominal-types", provider=EQUAL_LAYOUT)
    run_case(suite, driver, "independent-definitions", mode="independent-definition")
    run_case(
        suite,
        driver,
        "named-parameter-order",
        template="""
record Item { key:Key; values:[Value;2]; }
fn run()->i32 {return (sizeof(Item)*100usize+offsetof(Item,values)) as i32;}
""",
        mode="named-parameters",
        values=(5608, 4024),
    )
    layout = """
record Item { value:T; next:*Item; }
fn run()->i32 {return (sizeof(Item)+offsetof(Item,next)) as i32;}
"""
    run_case(suite, driver, "specialized-layout", template=layout, values=(24, 56))
    run_case(
        suite, driver, "nested-instance", template=layout, mode="nested-instance", values=(24, 56)
    )
    shapes = "record Shapes { scalar:i32; pointer:*P; array:[P;2]; callback:fn(*P,*P)->i32; }"
    run_case(
        suite,
        driver,
        "all-core-types",
        template=layout,
        provider=PROVIDER + shapes,
        mode="core-types",
        values=(24, 56),
    )
    run_case(
        suite,
        driver,
        "reverse-layout",
        template=layout,
        provider=PROVIDER.replace("record P", "record Rename")
        .replace("record Q", "record P")
        .replace("record Rename", "record Q"),
        values=(56, 24),
    )
    recursive = """
record Item { value:T; other:*OtherNode; }
record OtherNode { item:*Item; }
fn odd(n:i32)->i32 {if n==0i32 {return 0i32;} return even(n-1i32);}
fn even(n:i32)->i32 {if n==0i32 {return 1i32;} return odd(n-1i32);}
fn run()->i32 {return even(8i32);}
"""
    run_case(suite, driver, "mutual-pointer-and-call-recursion", template=recursive, values=(1, 1))
    run_case(
        suite,
        driver,
        "literal-storage",
        template=TEMPLATE.replace("return helper();", 'return "AZ"[1usize] as i32;'),
        values=(90, 90),
    )


def check_rejections(suite, driver):
    cases = (
        (
            "missing-free-binding",
            {
                "template": TEMPLATE.replace("captured()", "missing()"),
                "consumer": CONSUMER + "fn missing()->i32{return 9i32;}",
            },
            b"unknown name",
        ),
        ("inline-cycle", {"template": TEMPLATE.replace("next:*Item", "next:Item")}, b"cycle"),
        ("duplicate-parameters", {"mode": "duplicate-parameters"}, b"duplicate name"),
        ("keyword-parameter", {"mode": "keyword-parameter"}, b"identifier"),
        ("builtin-parameter", {"mode": "builtin-parameter"}, b"identifier"),
        ("invalid-parameter", {"mode": "invalid-parameter"}, b"expected"),
        ("capture-parameter", {"mode": "capture-parameter"}, b"name"),
        ("parameter-declaration", {"template": "record T {value:i32;}\n" + TEMPLATE}, b"name"),
        (
            "capture-declaration",
            {"template": "fn captured()->i32{return 1i32;}\n" + TEMPLATE},
            b"name",
        ),
        ("zero-arguments", {"mode": "zero-arguments"}, b"argument"),
        ("extra-arguments", {"mode": "extra-arguments"}, b"argument"),
        ("null-argument", {"mode": "null-argument"}, b"type"),
        ("unit-argument", {"mode": "unit-argument"}, b"unit"),
        ("captured-name-is-private", {"mode": "missing-export"}, b"declaration was not found"),
        ("duplicate-export", {"mode": "duplicate-export"}, b"duplicate name"),
        (
            "nominal-mismatch",
            {
                "provider": EQUAL_LAYOUT,
                "consumer": CONSUMER + "fn wrong(value:*First)->*Other{return value;}",
            },
            b"type mismatch",
        ),
        (
            "incompatible-operation",
            {"template": TEMPLATE.replace("return helper();", "var x:T=uninit;return x+1i32;")},
            b"type",
        ),
        (
            "second-instance-check",
            {"template": TEMPLATE + "fn field(value:*T)->i64{return (*value).value;}"},
            b"field",
        ),
    )
    for name, options, diagnostic in cases:
        run_case(suite, driver, name, diagnostic=diagnostic, **options)


def check_allocations(suite):
    driver = build_driver(suite, "generics_alloc")
    template = "record Item { value:T; next:*Item; fixed:Fixed; }\n"
    template += "\n".join(
        f"fn offset_{index}(value:*Item)->usize {{return offsetof(Item,next)+{index}usize;}}"
        for index in range(160)
    )
    source = suite.write("allocation-template.crs", template)
    suite.command([driver, source])


def tutorial_package(suite):
    package = suite.work / "copied package with spaces"
    for directory in ("api", "stages/modules", "stages/generics", "examples/generics"):
        shutil.copytree(ROOT / directory, package / directory, dirs_exist_ok=True)
    (package / "stages/c").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "stages/c/api.crs", package / "stages/c/api.crs")
    output = package / "build"
    output.mkdir(exist_ok=True)
    for library in ("crust-c-library.so", "crust-generics-library.so", "crust-asm-library.so"):
        shutil.copyfile(suite.build / library, output / library)
    return package


def tutorial_objects(suite, output, optimization):
    objects = []
    for name in ("1", "2", "program"):
        stem = output / f"generics-{name}"
        raw = output / f"{name}-{optimization}-raw.o"
        obj = output / f"{name}-{optimization}.o"
        suite.command(
            [
                *suite.cc,
                "-std=c99",
                "-pedantic-errors",
                f"-{optimization}",
                "-c",
                stem.with_suffix(".c"),
                "-o",
                raw,
            ]
        )
        suite.command(["objcopy", f"@{stem.with_suffix('.rsp')}", raw, obj])
        objects.append(obj)
    return objects


def check_tutorial_assembly(suite, package):
    root = package / "examples/generics/main.crs"
    setup = root.with_name("setup.crs")
    source = setup.read_text()
    original = 'host_link(root, "../../build/crust-c-library.so")'
    assert source.count(original) == 1
    setup.write_text(
        source.replace(
            original,
            'host_source(root, "../../api/crust0_x64.crs") &&\n'
            '           host_link(root, "../../build/crust-asm-library.so")',
        )
    )
    helper = root.with_name("build.crs")
    source = helper.read_text()
    call = "return c_backend_build(context, entry, options);"
    assert source.count(call) == 1
    source = source.replace(call, "return test_asm(context, entry, (*options).output);")
    source = source.replace('suffix = ".c";', 'suffix = ".s";')
    source = source.replace("generics-program.c", "generics-program.s")
    declarations = """
extern fn test_open(path:*u8, mode:*u8)->*u8="fopen";
extern fn test_close(file:*u8)->i32="fclose";
fn test_asm(context:*CrustContext,entry:*CrustDecl,path:*u8)->i32 {
    var file:*u8=test_open(path,"wb");
    if file==null(*u8) {return 1i32;}
    var success:bool=crust_x64_emit(context,file,entry);
    if test_close(file)!=0i32 {return 1i32;}
    if success {return 0i32;}
    return 1i32;
}
"""
    helper.write_text(source + declarations)
    suite.command([suite.runner, root, "--emit-c"], cwd=suite.work)
    output = package / "build"
    objects = []
    for name in ("1", "2", "program"):
        assembly = output / f"generics-{name}.s"
        obj = output / f"{name}-asm.o"
        suite.command(["as", "--64", assembly, "-o", obj])
        objects.append(obj)
    executable = output / "generics-asm"
    suite.command([*suite.cc, "-no-pie", *objects, *suite.ldflags, "-o", executable])
    assert suite.command([executable]).stdout == b"generics: OK\n"


def check_tutorial(suite):
    package = tutorial_package(suite)
    root = package / "examples/generics/main.crs"
    output = package / "build"
    suite.command([suite.runner, root], cwd=suite.work)
    assert suite.command([output / "generics"]).stdout == b"generics: OK\n"
    suite.command([suite.runner, root, "--emit-c"], cwd=suite.work)
    for optimization in ("O0", "O2"):
        objects = tutorial_objects(suite, output, optimization)
        executable = output / f"generics-{optimization}"
        suite.command([*suite.cc, *objects, *suite.ldflags, "-o", executable])
        actual = suite.command([executable]).stdout
        baseline = output / f"handwritten-{optimization}"
        suite.command(
            [
                suite.build / "crust-c",
                "-o",
                baseline,
                root.with_name("handwritten.crs"),
                "--cflag",
                f"-{optimization}",
            ]
        )
        assert actual == suite.command([baseline]).stdout == b"generics: OK\n"
    check_tutorial_assembly(suite, package)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--cflags", default="-O2")
    parser.add_argument("--ldflags", default="")
    suite = Suite(parser.parse_args())
    suite.work = suite.build / "generics-tests"
    suite.work.mkdir(exist_ok=True)
    driver = build_driver(suite, "generics_driver", evaluator=True)
    check_successes(suite, driver)
    check_rejections(suite, driver)
    check_allocations(suite)
    check_tutorial(suite)
    print(f"generics: {suite.checks} process checks passed")


if __name__ == "__main__":
    main()
