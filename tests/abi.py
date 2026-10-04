#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reject stale native stages after a public record layout change."""

import argparse
import json
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Suite:
    def __init__(self, args):
        self.build = args.build.resolve()
        self.runner = args.runner.resolve() if args.runner else self.build / "crust"
        self.work = self.build / "abi-tests"
        self.work.mkdir(exist_ok=True)
        self.cc = shlex.split(args.cc)
        self.cflags = shlex.split(args.cflags)
        self.ldflags = shlex.split(args.ldflags)
        self.args = args
        self.count = 0

    def run(self, command, expected=0):
        result = subprocess.run(list(map(str, command)), capture_output=True, timeout=120)
        assert result.returncode == expected, (command, result)
        self.count += 1
        return result

    def load(self, runner, library, expected=0, diagnostic=b"", before=""):
        root = self.work / "load.crs"
        root.write_text(
            before + f"host_link(run, {json.dumps(str(library))});\n"
            'extern fn inspect(value:*CrustExpr)->u64="inspect";\n'
            "var value:CrustExpr=uninit; value.integer=42u64;\n"
            "if inspect(&value)!=42u64 { return 2i32; };\nreturn 0i32;\n"
        )
        result = self.run([runner, root], expected)
        assert diagnostic in result.stderr, result
        if expected:
            assert str(library).encode() in result.stderr, result
        return result

    def library(self, name, api, backend="c", extra=()):
        source = self.work / f"{name}.crs"
        source.write_text("fn inspect(value:*CrustExpr)->u64{return (*value).integer;}\n")
        obj = source.with_suffix(".o")
        command = [self.build / ("crust-c" if backend == "c" else "crust0")]
        command += ["--library", "--export", "inspect"]
        if backend == "c":
            command += ["--object", "--cflag=-fPIC"]
            command += [option for flag in self.cflags for option in ("--cflag", flag)]
            command += ["-o", obj]
        else:
            command += ["-S", "-o", source.with_suffix(".s")]
        self.run([*command, api, *extra, source])
        if backend != "c":
            self.run(["as", "--64", source.with_suffix(".s"), "-o", obj])
        library = source.with_suffix(".so")
        self.run([*self.cc, "-shared", obj, *self.ldflags, "-o", library])
        return library

    def changed_seed(self):
        checkout = self.work / "changed"
        if checkout.exists():
            shutil.rmtree(checkout)
        checkout.mkdir()
        for directory in ("include", "src", "runtime", "tools", "api"):
            shutil.copytree(ROOT / directory, checkout / directory)
        (checkout / "stages/asm").mkdir(parents=True)
        shutil.copyfile(ROOT / "stages/host.crs", checkout / "stages/host.crs")
        for name in ("Makefile", "crust0_amalg.c"):
            shutil.copyfile(ROOT / name, checkout / name)
        header = checkout / "include/crust0.h"
        original = header.read_text()
        needle = "struct CrustExpr {\n    CrustLoc loc;"
        assert original.count(needle) == 1
        header.write_text(original.replace(needle, needle + "\n    uint64_t abi_test_padding;"))
        self.run(["python3", checkout / "tools/api.py", "--check"], expected=1)
        self.run(
            [
                "make",
                "--no-print-directory",
                "-C",
                checkout,
                "-j2",
                "build/crust",
                "BUILD=build",
                f"CC={self.args.cc}",
                f"CFLAGS={self.args.cflags}",
                f"LDFLAGS={self.args.ldflags}",
                f"AMALGAMATION={self.args.amalgamation}",
            ]
        )
        self.run(["python3", checkout / "tools/api.py", "--check"])
        return checkout


def check_missing(suite, dependency):
    source = suite.work / "unmarked.c"
    source.write_text("int unmarked(void);\nint unmarked(void){return 0;}\n")
    for name, libraries in (("missing", []), ("dependency-marker", [dependency])):
        library = suite.work / f"{name}.so"
        suite.run(
            [
                *suite.cc,
                "-std=c99",
                "-pedantic-errors",
                "-fPIC",
                "-shared",
                source,
                "-Wl,--no-as-needed",
                *libraries,
                *suite.ldflags,
                "-o",
                library,
            ]
        )
        suite.load(suite.runner, library, 1, b"missing native API digest")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--cflags", default="-O2 -g")
    parser.add_argument("--ldflags", default="")
    parser.add_argument("--amalgamation", default="1", choices=("0", "1"))
    suite = Suite(parser.parse_args())
    old = [
        suite.library("old-" + backend, ROOT / "api/crust0.crs", backend)
        for backend in ("c", "asm")
    ]
    for library in old:
        suite.load(suite.runner, library)
    check_missing(suite, old[0])
    changed = suite.changed_seed()
    runner = changed / "build/crust"
    for library in old:
        suite.load(runner, library, 1, b"native API digest mismatch")
    suite.load(runner, suite.build / "crust-c-library.so", 1, b"native API digest mismatch")
    new = suite.library("new", changed / "api/crust0.crs")
    suite.load(runner, new)
    suite.load(suite.runner, new, 1, b"native API digest mismatch")
    mixed = suite.library(
        "mixed", changed / "api/crust0.crs", extra=[ROOT / "api/crust0_stage.crs"]
    )
    suite.load(runner, mixed, 1, b"native API digest mismatch")
    root = suite.work / "stale-source.crs"
    root.write_text(f'host_source(run, {json.dumps(str(ROOT / "api/crust0_stage.crs"))});\n')
    result = suite.run([runner, root], 1)
    assert b"native API digest mismatch in host source" in result.stderr, result
    assert b"crust0_stage.crs:5:" in result.stderr, result
    print(
        f"native API digests: {suite.count} checks, changed-layout seed rejects old C and ASM stages"
    )


if __name__ == "__main__":
    main()
