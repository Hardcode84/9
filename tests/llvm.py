#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check direct LLVM emission, native ABI, cleanup and source-built packages."""

import argparse
import json
import resource
import signal
from pathlib import Path

from resources import runtime_cases
from run import TYPES, checked_command, integer_cases

ROOT = Path(__file__).resolve().parents[1]


def check(command, expected=0, **kwargs):
    return checked_command(command, expected=expected, timeout=180, **kwargs)


class Suite:
    def __init__(self, build, llvm):
        self.build = build
        self.llvm = llvm
        self.work = build / "llvm-tests"
        self.work.mkdir(exist_ok=True)
        self.driver = build / "llvm-test-driver"
        self.count = 0

    def emit(self, name, source=None, paths=(), exports=(), mode="raw"):
        if source is not None:
            path = self.work / f"{name}.crs"
            path.write_text(source)
            paths = [path]
        ir = self.work / f"{name}.ll"
        options = [item for name in exports for item in ("--export", name)]
        check(
            [
                self.driver,
                mode,
                "--emit-c",
                "-o",
                ir,
                "--symbols",
                str(ir) + ".symbols",
                *options,
                *paths,
            ]
        )
        check([self.llvm / "bin/llvm-as", ir, "-o", self.work / "verified.bc"])
        return ir

    def binary(self, ir, level, libraries=()):
        obj = ir.with_suffix(f".O{level}.o")
        renamed = obj.with_suffix(".renamed.o")
        binary = ir.with_suffix(f".O{level}")
        check(
            [
                self.llvm / "bin/clang",
                "--no-default-config",
                "-x",
                "ir",
                f"-O{level}",
                "-c",
                ir,
                "-o",
                obj,
            ]
        )
        check(["objcopy", "@" + str(ir) + ".symbols", obj, renamed])
        check(["gcc", renamed, *libraries, self.build / "libcrust0_host.a", "-o", binary])
        return binary

    def execute(self, ir, expected=0, output=None, libraries=()):
        for level in (0, 2):
            binary = self.binary(ir, level, libraries)
            result = check([binary], expected)
            if output is not None:
                assert result.stdout == output, (ir, result.stdout)
            self.count += 1


def raw(suite):
    native = suite.work / "native.o"
    check(["gcc", "-std=c99", "-pedantic-errors", "-O2", "-c", "tests/native.c", "-o", native])
    suite.execute(suite.emit("runtime", paths=["tests/runtime.crs"]), libraries=[native])
    suite.execute(
        suite.emit("intrusive", paths=["examples/intrusive/raw.crs"]), output=b"intrusive: ok\n"
    )
    suite.execute(suite.emit("memory", paths=["tests/llvm_memory.crs"]))
    native_names(suite)
    runtime_definition(suite)
    for kind, (bits, signed) in TYPES.items():
        comparisons = [
            f"if ({left})!=({right}){{return 1i32;}}"
            for left, right in integer_cases(kind, bits, signed)
        ]
        source = "fn main(argc:i32,argv:**u8)->i32 {" + "\n".join(comparisons) + "return 0i32;}"
        suite.execute(suite.emit("integer-" + kind, source))
        for operation, left, right in (
            ("/", "1", "0"),
            ("%", "1", "0"),
            ("<<", "1", str(bits)),
            (">>", "1", str(bits)),
        ):
            text = f"fn main(argc:i32,argv:**u8)->i32{{var value:{kind}={left}{kind}{operation}{right}{kind};return value as i32;}}"
            suite.execute(
                suite.emit(
                    f"trap-{kind}-{operation.replace('/', 'div').replace('%', 'rem').replace('<', 'l').replace('>', 'r')}",
                    text,
                ),
                -signal.SIGILL,
            )
        if signed:
            for operation, name in (("/", "div"), ("%", "rem")):
                text = f"fn main(argc:i32,argv:**u8)->i32{{var value:{kind}=-{1 << (bits - 1)}{kind}{operation}(-1{kind});return value as i32;}}"
                suite.execute(suite.emit(f"overflow-{kind}-{name}", text), -signal.SIGILL)
    suite.execute(
        suite.emit(
            "override", "fn main(argc:i32,argv:**u8)->i32{return 7i32+7i32;}", mode="override"
        )
    )
    rejected = check([suite.driver, "bad-override", "--emit-c", suite.work / "override.crs"], 1)
    assert b"callback returned no operand" in rejected.stderr


def native_names(suite):
    names = [
        ".Lcrust_0_string_1",
        ".LFE0",
        'quote"back\\name',
        "line\nbreak",
        "1",
        ".",
        "".join(chr(i) for i in range(1, 128)),
    ]
    source = suite.work / "names.c"
    source.write_text("\n".join(f"int native_{i}(void){{return {i};}}" for i in range(len(names))))
    original = source.with_suffix(".o")
    renamed = source.with_suffix(".renamed.o")
    check(["gcc", "-c", source, "-o", original])
    options, declarations, calls = [], [], []
    for i, name in enumerate(names):
        options.extend(["--redefine-sym", f"native_{i}={name}"])
        encoded = "".join(f"\\x{ord(byte):02x}" for byte in name)
        declarations.append(f'extern fn f{i}()->i32="{encoded}";')
        calls.append(f"if f{i}()!={i}i32{{return 1i32;}}")
    check(["objcopy", *options, original, renamed])
    text = (
        "\n".join(declarations)
        + "fn main(argc:i32,argv:**u8)->i32{"
        + "".join(calls)
        + "return 0i32;}"
    )
    suite.execute(suite.emit("names", text), libraries=[renamed])


def runtime_definition(suite):
    source = """
fn memset(to:*u8,value:i32,count:usize)->*u8 {
    var index:usize=0usize;
    while index<count{to[index]=value as u8;index=index+1usize;}
    return to;
}
fn main(argc:i32,argv:**u8)->i32 {
    var data:[u8;8192]=uninit;
    if memset(&data[0usize],42i32,8192usize)!=&data[0usize]{return 1i32;}
    if data[0usize]!=42u8 || data[8191usize]!=42u8{return 2i32;}
    return 0i32;
}
"""
    ir = suite.emit("runtime-memset", source, exports=["memset"])
    suite.execute(ir)
    for level in (0, 2):
        undefined = check(["nm", "-u", ir.with_suffix(f".O{level}.o")]).stdout
        assert b"memset" not in undefined, "runtime memset calls itself"


def native_contracts(suite):
    suite.execute(
        suite.emit(
            "aliases",
            """
extern fn first(value:i64)->i64="same";
extern fn second(value:isize)->isize="same";
fn same(value:i64)->i64{return value+1i64;}
fn main(argc:i32,argv:**u8)->i32{
    if first(6i64)!=7i64 || second(8isize)!=9isize{return 1i32;}
    return 0i32;
}
""",
            exports=["same"],
        )
    )
    source = suite.work / "invalid-abi.crs"
    source.write_text('extern fn first(x:i32)->i32="same";extern fn second(x:i64)->i32="same";')
    result = check([suite.driver, "raw", "--library", "--emit-c", source], 1)
    assert b"conflicting native ABI" in result.stderr


def cleanup(suite):
    driver = suite.build / "resource-backends"
    for name, text, expected in runtime_cases():
        source = suite.work / f"cleanup-{name}.crs"
        source.write_text(text)
        ir = source.with_suffix(".ll")
        check([driver, "llvm", "resources", "-o", ir, source])
        suite.execute(
            ir, -signal.SIGILL if expected is None else 0, b"" if expected is None else expected
        )
    ir = suite.work / "checked-intrusive.ll"
    check(
        [
            driver,
            "llvm",
            "ownership",
            "trusted",
            "examples/intrusive/links.crs",
            "-o",
            ir,
            "examples/intrusive/program.crs",
        ]
    )
    suite.execute(ir, output=b"OK\n")


def sqlite(suite):
    ir = suite.work / "sqlite.ll"
    check(
        [
            suite.build / "resource-backends",
            "llvm",
            "resources",
            "-o",
            ir,
            "examples/resources/sqlite/library.crs",
            "examples/resources/sqlite/program.crs",
        ]
    )
    # Use the system library for this test; the separate performance witness uses
    # the retained baseline object and fixtures.
    import sqlite3

    database = suite.work / "input.db"
    database.unlink(missing_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("create table input(seq integer, value)")
        connection.executemany("insert into input values(?,?)", [(1, "hello"), (2, 17), (3, None)])
    for level in (0, 2):
        binary = suite.binary(ir, level, ["-l:libsqlite3.so.0"])
        normal = check([binary, database])
        assert normal.stdout == b"T 68656c6c6f\nI 3137\nN\nrows 3\n" and not normal.stderr
        failed = check([binary, suite.work / "absent-parent/input.db"], 1)
        assert failed.stderr == b"error 14 0 0\n"
        suite.count += 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build"))
    parser.add_argument("--llvm", type=Path)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    build = args.build.resolve()
    llvm = args.llvm
    if llvm is None:
        llvm = Path(
            check(["python3", "tools/fetch_llvm.py", "release", "--locked"]).stdout.decode().strip()
        )
    suite = Suite(build, llvm.resolve())
    check([suite.driver, "allocation", "tests/runtime.crs"])
    raw(suite)
    native_contracts(suite)
    cleanup(suite)
    sqlite(suite)
    (suite.work / "result.json").write_text(
        json.dumps({"executions": suite.count, "toolchain": str(suite.llvm)}, indent=2) + "\n"
    )
    print(
        f"LLVM: {suite.count} executions at O0/O2; raw semantics, ABI, cleanup and checked clients passed"
    )


if __name__ == "__main__":
    main()
