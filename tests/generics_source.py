#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check source generic declarations through native stages and both backends."""

import argparse
from pathlib import Path

from source_order import ROOT, Suite

MULTIFILE = (
    """
fn main(argc:i32,argv:**u8)->i32 {
    var value:Pair!(Position,Sample)=make Pair!(Position,Sample) {
        first:make Position {value:41i64}, second:make Sample {value:9i32}
    };
    var first:*Position=pair_first!(Position,Sample)(&value);
    if (*first).value!=41i64 || value.second.value!=9i32 {trap;}
    if pair_size!(Position,Sample)()!=sizeof(Pair!(Position,Sample)) {trap;}
    return 0i32;
}
""",
    """
record Pair!(Key,Value) {first:Key;second:Value;}
fn pair_first!(Key,Value)(pair:*Pair!(Key,Value))->*Key {return &(*pair).first;}
fn pair_size!(Key,Value)()->usize {return sizeof(Pair!(Key,Value));}
""",
    "record Position {value:i64;} record Sample {value:i32;}",
)

NESTED = """
record Box!(T) {value:T;}
fn inner!(T)(box:*Box!(T))->*T {return &(*box).value;}
fn nested!(T)(box:*Box!(Box!(T)))->*T {return inner!(T)(inner!(Box!(T))(box));}
fn identity!(T)(value:T)->T {return value;}
fn main(argc:i32,argv:**u8)->i32 {
    var box:Box!(Box!(i64))=make Box!(Box!(i64)) {value:make Box!(i64) {value:73i64}};
    if *nested!(i64)(&box)!=73i64 {trap;}
    var call:fn(i64)->i64=identity!(i64);
    if call(29i64)!=29i64 {trap;}
    return 0i32;
}
"""

RECURSIVE = """
record Node!(T) {next:*Node!(T);value:T;}
record Left!(T) {right:*Right!(T);value:T;}
record Right!(T) {left:*Left!(T);}
fn odd!(T)(n:T)->bool {if n==0i32 {return false;} return even!(T)(n-1i32);}
fn even!(T)(n:T)->bool {if n==0i32 {return true;} return odd!(T)(n-1i32);}
fn count!(T)(node:*Node!(T))->usize {
    if node==null(*Node!(T)) {return 0usize;}
    return 1usize+count!(T)((*node).next);
}
fn main(argc:i32,argv:**u8)->i32 {
    var tail:Node!(i32)=make Node!(i32) {next:null(*Node!(i32)),value:11i32};
    var head:Node!(i32)=make Node!(i32) {next:&tail,value:22i32};
    var left:Left!(i32)=make Left!(i32) {right:null(*Right!(i32)),value:33i32};
    var right:Right!(i32)=make Right!(i32) {left:&left};
    left.right=&right;
    if (*(*left.right).left).value!=33i32 || count!(i32)(&head)!=2usize {trap;}
    if !even!(i32)(8i32) || !odd!(i32)(7i32) {trap;}
    return 0i32;
}
"""

TYPE_POSITIONS = """
record Box!(T) {value:T;}
fn same!(T)(value:*T)->*T {return value;}
fn cast!(T)(value:*u8)->*T {return value as *T;}
fn increment(value:i32)->i32 {return value+1i32;}
fn main(argc:i32,argv:**u8)->i32 {
    var box:Box!(i32)=make Box!(i32) {value:17i32};
    var empty:*Box!(i32)=null(*Box!(i32));
    var raw:*u8=&box as *u8;
    var pointer:*Box!(i32)=raw as *Box!(i32);
    if pointer==empty || pointer!=cast!(Box!(i32))(raw) {trap;}
    var call:fn(*Box!(i32))->*Box!(i32)=same!(Box!(i32));
    if (*call(&box)).value!=17i32 {trap;}
    var values:[Box!(i32);2]=make [Box!(i32);2] {
        make Box!(i32) {value:3i32},make Box!(i32) {value:5i32}
    };
    if values[0usize].value+values[1usize].value!=8i32 {trap;}
    var array:Box!([i32;2])=make Box!([i32;2]) {value:make [i32;2] {7i32,9i32}};
    var callback:Box!(fn(i32)->i32)=make Box!(fn(i32)->i32) {value:increment};
    var address:Box!(*i32)=make Box!(*i32) {value:&box.value};
    if array.value[1usize]!=9i32 || callback.value(11i32)!=12i32 || *address.value!=17i32 {trap;}
    if sizeof(Box!(i32))!=sizeof(i32) || alignof(Box!(i32))!=alignof(i32) {trap;}
    if offsetof(Box!(i32),value)!=0usize {trap;}
    return 0i32;
}
"""

LAZY = """
record Box!(T) {value:T;}
fn unused!(T)(value:*T)->unit {missing_function(value);}
fn field!(T)(value:*T)->i32 {return (*value).value;}
record Value {value:i32;}
fn main(argc:i32,argv:**u8)->i32 {
    var value:Value=make Value {value:51i32};
    if field!(Value)(&value)!=51i32 {trap;}
    return 0i32;
}
"""

REUSE = """
record Box!(T) {value:T;}
fn same!(T)(value:*Box!(T))->*Box!(T) {return value;}
fn main(argc:i32,argv:**u8)->i32 {
    var box:Box!(i32)=make Box!(i32) {value:19i32};
    var first:*Box!(i32)=same!(i32)(&box);
    var second:*Box!(i32)=same!(i32)(first);
    if first!=second || (*second).value!=19i32 {trap;}
    return 0i32;
}
"""


# The driver links only public stage interfaces, as an external client does.
def build_driver(suite, filename="generics_source_driver"):
    sources = [
        ROOT / path
        for path in (
            "api/crust0.crs",
            "api/crust0_host.crs",
            "api/crust0_stage.crs",
            "api/crust0_x64.crs",
            "stages/c/api.crs",
            "stages/generics/source_model.crs",
            "stages/generics/source_api.crs",
        )
    ]
    libraries = [
        suite.build / "crust-generics-library.so",
        suite.build / "crust-c-library.so",
        suite.build / "crust-asm-library.so",
        suite.build / "libcrust0.a",
        suite.build / "libcrust0_host.a",
        "-rdynamic",
    ]
    flags = [item for flag in suite.cflags for item in ("--cflag", flag)]
    flags += [item for flag in [*libraries, *suite.ldflags] for item in ("--ldflag", flag)]
    output = suite.work / filename
    suite.command(
        [suite.build / "crust-c", "-o", output, *sources, ROOT / f"tests/{filename}.crs", *flags]
    )
    return output


def write_inputs(suite, name, contents):
    if isinstance(contents, str):
        contents = (contents,)
    return [suite.write(f"{name}/{index}.crs", source) for index, source in enumerate(contents)]


def compile_output(suite, mode, output, symbols):
    raw = output.with_suffix(".raw.o")
    obj = output.with_suffix(".o")
    if mode == "asm":
        suite.command(["as", "--64", output, "-o", obj])
    else:
        suite.command(
            [
                *suite.cc,
                "-std=c99",
                "-pedantic-errors",
                "-O2",
                "-c",
                output,
                "-o",
                raw,
            ]
        )
        suite.command(["objcopy", f"@{symbols}", raw, obj])
    executable = output.with_suffix(".exe")
    suite.command([*suite.cc, "-no-pie", obj, *suite.ldflags, "-o", executable])
    result = suite.command([executable])
    assert not result.stdout and not result.stderr, (output, result.stdout, result.stderr)


def run_success(suite, driver, name, contents, modes=("c", "asm")):
    inputs = write_inputs(suite, name, contents)
    for mode in modes:
        output = suite.work / name / (mode + (".s" if mode == "asm" else ".c"))
        symbols = output.with_suffix(".rsp")
        result = suite.command([driver, mode, output, symbols, *inputs])
        assert not result.stderr, (name, result.stderr)
        compile_output(suite, mode, output, symbols)


def run_rejection(suite, driver, name, contents, diagnostic, mode="check"):
    inputs = write_inputs(suite, name, contents)
    result = suite.command([driver, mode, "unused", "unused", *inputs], expected=1)
    assert diagnostic in result.stderr, (name, result.stderr)
    if mode != "closed":
        assert any(str(path).encode() in result.stderr for path in inputs), (name, result.stderr)


def check_native(suite, driver):
    run_success(suite, driver, "forward-multifile", MULTIFILE)
    run_success(suite, driver, "nested-types-and-functions", NESTED)
    run_success(suite, driver, "recursive-records-and-functions", RECURSIVE)
    run_success(suite, driver, "all-type-positions", TYPE_POSITIONS)
    run_success(suite, driver, "unused-function-laziness", LAZY)
    run_success(suite, driver, "explicit-lowering", NESTED, modes=("lower-c",))
    run_success(suite, driver, "instance-reuse", REUSE, modes=("reuse-c",))


def check_syntax(suite, driver):
    cases = (
        ("empty-parameters", "record Pair!() {value:i32;}", b"requires a type parameter"),
        ("duplicate-parameters", "record Pair!(T,T) {value:T;}", b"duplicate generic parameter"),
        ("builtin-parameter", "record Pair!(i32) {value:i32;}", b"expected an identifier"),
        ("keyword-parameter", "record Pair!(while) {value:i32;}", b"expected an identifier"),
        ("parameter-self-name", "record Pair!(Pair) {value:Pair;}", b"conflicts"),
        ("missing-open", "record Pair!T {value:T;}", b"expected '('"),
        ("typed-parameter", "record Pair!(T:type) {value:T;}", b"expected ')'"),
        ("empty-arguments", "record R {value:Pair!();}", b"requires a type argument"),
        ("value-argument", "record R {value:Pair!(4usize);}", b"expected a type"),
        ("generic-extern", 'extern fn call!(T)(x:T)->T="call";', b"extern functions cannot"),
        ("missing-close", "record R {value:Pair!(i32;}", b"expected ')'"),
    )
    for name, source, diagnostic in cases:
        run_rejection(suite, driver, name, source, diagnostic)


def check_contracts(suite, driver):
    box = "record Box!(T) {value:T;}\n"
    cases = (
        ("wrong-arity", box + "record R {value:Box!(i32,u8);}", b"argument"),
        ("missing-arguments", box + "record R {value:Box;}", b"argument"),
        ("unknown-argument", box + "record R {value:Box!(Unknown);}", b"unknown"),
        ("ordinary-application", "record P {value:i32;} record R {value:P!(i32);}", b"generic"),
        ("duplicate-name", (box, box), b"duplicate"),
        ("inline-cycle", "record R!(T) {self:R!(T);} record Use {value:R!(i32);}", b"cycle"),
        (
            "distinct-nominal-arguments",
            box + "record P {value:i32;} record Q {value:i32;}"
            "fn cast(p:*Box!(P))->*Box!(Q) {return p;}",
            b"type",
        ),
        (
            "distinct-definitions",
            box + "record Other!(T) {value:T;}" "fn cast(p:*Box!(i32))->*Other!(i32) {return p;}",
            b"type",
        ),
        (
            "instantiated-body-checked",
            LAZY.replace("return 0i32;", "unused!(Value)(&value); return 0i32;"),
            b"unknown",
        ),
        (
            "each-argument-checked",
            LAZY.replace("return 0i32;", "var x:i32=1i32; field!(i32)(&x); return 0i32;"),
            b"field",
        ),
        (
            "branching-type-expansion",
            "fn grow!(T)()->i32 {return grow!(fn(T,T)->T)();}"
            "fn main(argc:i32,argv:**u8)->i32 {return grow!(i32)();}",
            b"generic type expansion limit of 65536 exceeded",
        ),
        (
            "unbounded-specialization",
            "fn grow!(T)(x:*T)->unit {grow!(*T)(&x);}"
            "fn main(argc:i32,argv:**u8)->i32 {var x:i32=0i32;grow!(i32)(&x);return 0i32;}",
            b"depth",
        ),
    )
    for name, source, diagnostic in cases:
        run_rejection(suite, driver, name, source, diagnostic)
    run_rejection(suite, driver, "closed-inputs", NESTED, b"source input is closed", mode="closed")


def check_parameter_contracts(suite, driver):
    constant = "fn constant!(T)()->i32 {return 1i32;}"
    cases = (
        ("unused-unknown-argument", "Unknown", b"unknown"),
        ("unused-pointer-unit-argument", "*unit", b"unit"),
        ("unused-aggregate-signature-argument", "fn(P)->unit", b"scalar"),
    )
    for name, argument, diagnostic in cases:
        source = (
            constant
            + "record P {value:i32;}"
            + ("fn main(argc:i32,argv:**u8)->i32 {return constant!(" + argument + ")();}")
        )
        run_rejection(suite, driver, name, source, diagnostic)
    for name, declaration in (
        ("generic-name-parameter", "fn read(constant:i32)->i32 {return constant;}"),
        ("generic-name-local", "fn read()->i32 {var constant:i32=1i32;return constant;}"),
        ("type-name-parameter", "fn read!(T)(T:i32)->i32 {return T;}"),
    ):
        source = constant + declaration
        if name == "type-name-parameter":
            source += "fn main(argc:i32,argv:**u8)->i32 {return read!(i32)(1i32);}"
        run_rejection(suite, driver, name, source, b"conflicts")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--cflags", default="-O2")
    parser.add_argument("--ldflags", default="")
    suite = Suite(parser.parse_args())
    suite.work = suite.build / "generics-source-tests"
    suite.work.mkdir(exist_ok=True)
    driver = build_driver(suite)
    check_native(suite, driver)
    check_syntax(suite, driver)
    check_contracts(suite, driver)
    check_parameter_contracts(suite, driver)
    allocations = build_driver(suite, "generics_source_alloc")
    suite.command([allocations])
    bindings = build_driver(suite, "generics_source_bind")
    suite.command([bindings])
    print(f"source generics: {suite.checks} process checks passed")


if __name__ == "__main__":
    main()
