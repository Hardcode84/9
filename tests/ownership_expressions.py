#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check expression order, conditional effects, and call loan boundaries."""

import argparse
import tempfile
from pathlib import Path

from ownership_imports import command as import_command
from ownership_imports import import_arguments, publish
from ownership_support import ROOT, command, execute, rejected

HELPERS = """
extern fn emit(code:i32)->i32 foreign(scalar)="putchar";
record View {value:read i64;}
resource Trace {code:i32;} drop trace_drop;
fn trace_drop(value:mut Trace)->unit {emit(value.code);}
fn trace_new(code:i32)->Trace {return make Trace{code:code};}
fn consume(value:Trace)->bool {return true;}
fn mark(code:i32)->i64 {emit(code);return code as i64;}
fn mark_bool(code:i32,value:bool)->bool {emit(code);return value;}
fn set(value:mut i64,n:i64)->unit {value=n;}
fn bump(value:mut i64)->i64 {value=value+1i64;return value;}
fn get(value:read i64)->i64 {return value;}
fn identity(value:read i64)->read i64 from value {return read value;}
fn view_new(value:read i64)->View from value {return make View{value:read value};}
fn view_get(view:View)->i64 {return view.value;}
fn observe(value:read i64,n:i64)->unit {}
fn positive(value:read i64)->bool {return value>0i64;}
fn step(count:mut i64)->bool {emit(78i32);count=count-1i64;return count>0i64;}
"""

BODY = """
var x:i64=0i64;
set(mut x,mark(65i32));
if x!=65i64 {trap;}
var sum:i64=mark(66i32)+mark(67i32);
if sum!=133i64 {trap;}
if mark_bool(68i32,true) {emit(69i32);} else {trap;}
if false && mark_bool(88i32,true) {trap;}
if true || mark_bool(89i32,false) {} else {trap;}
if mark_bool(70i32,false) || mark_bool(71i32,true) {emit(72i32);}
if mark_bool(73i32,true) && mark_bool(74i32,false) {trap;} else {emit(75i32);}
{defer set(mut x,mark(76i32));}
if x!=76i64 {trap;}
var source:i64=7i64;
set(mut x,get(identity(read source)));
if x!=7i64 {trap;}
source=8i64;
set(mut x,view_get(view_new(read source)));
if x!=8i64 {trap;}
source=9i64;
var old_plus_new:i64=get(read source)+bump(mut source);
if old_plus_new!=19i64 || source!=10i64 {trap;}
if positive(read source) {source=11i64;}
if source!=11i64 {trap;}
if consume(trace_new(77i32)) {} else {trap;}
if false && consume(trace_new(88i32)) {trap;}
if true || consume(trace_new(89i32)) {} else {trap;}
var remaining:i64=3i64;
while step(mut remaining) {emit(79i32);}
if remaining!=0i64 {trap;}
emit(10i32);
"""
OUTPUT = b"ABCDEFGHIJKLMNONON\n"

NATIVE = """
resource File {fd:i32;} owns(fd=-1i32) drop file_drop;
extern fn acquire(value:i32)->i32 foreign(acquire File.fd)="dup";
extern fn release(value:i32)->i32 foreign(move value:File.fd)="close";
extern fn duplicate(value:i32)->i32 foreign(read value:File.fd,acquire File.fd)="dup";
fn file_drop(file:mut File)->unit {
    if file.fd!=-1i32 {var status:i32=release(move file.fd);if status!=0i32 {trap;}}
}
fn file_new()->File {return make File{fd:acquire(1i32)};}
fn replace(file:mut File)->bool {
    if file.fd!=-1i32 {var status:i32=release(move file.fd);if status!=0i32 {trap;}}
    file.fd=acquire(-1i32);
    return true;
}
"""


def main_body(body):
    return "fn main(argc:i32,argv:**u8)->i32 {" + body + "return 0i32;}"


def bad_cases():
    return {
        "pending-mutable-argument": (
            HELPERS + main_body("var x:i64=0i64;set(mut x,bump(mut x));"),
            "active",
        ),
        "pending-returned-argument": (
            HELPERS + main_body("var x:i64=0i64;observe(identity(read x),bump(mut x));"),
            "active",
        ),
        "conditional-consumption": (
            HELPERS
            + main_body(
                "var value:Trace=trace_new(65i32);var b:bool=argc>0i32&&consume(move value);"
            ),
            "continuing paths",
        ),
        "loop-condition-consumption": (
            HELPERS + main_body("var value:Trace=trace_new(65i32);while consume(move value) {}"),
            "loop edges",
        ),
        "discarded-acquisition": (
            NATIVE + main_body("if acquire(1i32)!=-1i32 {}"),
            "unused resource must be consumed",
        ),
        "binary-rhs-consumption": (
            NATIVE
            + main_body(
                "var fd:i32=acquire(1i32);if fd!=-1i32 {"
                "var status:i32=1i32+release(move fd);var other:i32=duplicate(fd);}"
            ),
            "has been moved",
        ),
        "pending-native-argument": (
            NATIVE
            + 'extern fn operation(fd:i32,other:i32)->i32 foreign(read fd:File.fd)="unused";'
            + main_body(
                "var fd:i32=acquire(1i32);if fd!=-1i32 {"
                "var status:i32=operation(fd,release(move fd));}"
            ),
            "active",
        ),
        "stale-native-refinement": (
            NATIVE
            + main_body(
                "var file:File=file_new();if file.fd!=-1i32&&replace(mut file) {"
                "var other:File=make File{fd:duplicate(file.fd)};}"
            ),
            "successful acquisition check",
        ),
        "skipped-native-refinement": (
            NATIVE
            + main_body(
                "var file:File=file_new();if file.fd==-1i32||replace(mut file) {"
                "var other:File=make File{fd:duplicate(file.fd)};}"
            ),
            "successful acquisition check",
        ),
        "loop-condition-native-effect": (
            NATIVE
            + main_body(
                "var file:File=file_new();while replace(mut file) {}"
                "var other:File=make File{fd:duplicate(file.fd)};"
            ),
            "successful acquisition check",
        ),
    }


def check_import(build, directory):
    provider = directory / "expression-provider.crs"
    provider.write_text(HELPERS)
    cache = directory / "expression-cache"
    cache.mkdir()
    driver = str(build / "crust-ownership-import-test")
    receipt = publish(driver, cache, [provider])
    provider.unlink()
    client = directory / "expression-client.crs"
    client.write_text(main_body(BODY))
    output = directory / "expression-client"
    args = import_arguments(driver, cache, receipt, client, output)
    import_command(args)
    assert command([output]).stdout == OUTPUT
    client.write_text(main_body("var x:i64=0i64;observe(identity(read x),bump(mut x));"))
    result = import_command(args, success=False)
    assert "active" in result.stderr, result.stderr


def check_domain(build, directory):
    client = directory / "expression-domain.crs"
    client.write_text(
        "fn observe(value:read i64,owner:Owner)->unit access(reclaim,Graph) {}"
        + main_body(
            "domain Graph {var owner:Owner=owner_new(1i64);"
            "observe(owner_value(read owner),owner_new(2i64));}"
        )
    )
    result = command(
        [
            build / "crust-ownership-test",
            "trusted",
            ROOT / "examples/intrusive/links.crs",
            "--check",
            client,
        ],
        expected=1,
    )
    assert b"active domain loan" in result.stderr, result.stderr


def check_expressions(build, directory, sanitize):
    source = directory / "expressions.crs"
    source.write_text(HELPERS + main_body(BODY))
    generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
    compiler = build / "crust-ownership-test"
    command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, source])
    command([build / "crust-ownership-erasure", source])
    execute(generated, symbols, directory, "expressions", sanitize, OUTPUT)
    source = directory / "native-expressions.crs"
    source.write_text(
        NATIVE
        + "fn standard_output()->i32 {return 1i32;}"
        + main_body("var file:File=make File{fd:acquire(standard_output())};")
    )
    generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
    command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, source])
    command([build / "crust-ownership-erasure", source])
    execute(generated, symbols, directory, "native-expressions", sanitize, b"")
    rejected(compiler, directory, bad_cases())
    check_domain(build, directory)
    check_import(build, directory)
    print(
        "ownership expressions: source order, short circuit, loops, erasure, imports, "
        f"{len(bad_cases()) + 2} rejections"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-expressions-", dir=args.build) as temporary:
        check_expressions(args.build.resolve(), Path(temporary), args.sanitize)


if __name__ == "__main__":
    main()
