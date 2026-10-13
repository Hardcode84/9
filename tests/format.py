#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check formatter layout, source preservation, services, and file publication."""

import argparse
import os
import subprocess
from pathlib import Path

from prepare import compile_package
from run import checked_command

ROOT = Path(__file__).resolve().parents[1]


def command(args, expected=0, **kwargs):
    return checked_command(args, expected=expected, timeout=240, **kwargs)


class Suite:
    def __init__(self, build):
        self.build = build.resolve()
        self.work = self.build / "format-tests"
        self.work.mkdir(exist_ok=True)
        self.tool = self.work / "crust-format"
        self.contract = self.work / "contracts"
        package = self.work / "executable.crs"
        package.write_text(
            f'stage_include(stage,"{ROOT}/stages/format/sources.crs");\n'
            f'stage_source(stage,"{ROOT}/stages/format/main.crs");\n'
            'stage_export(stage,"main");\n'
        )
        libraries = [self.build / "libcrust0.a", self.build / "libcrust0_host.a"]
        compile_package(self.build, package, self.tool, ["-O2"], libraries)
        compile_package(
            self.build, ROOT / "tests/format-package.crs", self.contract, ["-O2"], libraries
        )

    def source(self, name, data):
        path = self.work / name
        path.write_bytes(data)
        return path

    def layouts(self):
        cases = (
            (b"", b""),
            (b" \r\n\t", b""),
            (b"fn f()->unit{}", b"fn f() -> unit {}\n"),
            (
                b"// keep  spaces\r\nfn f(a:i32)->i32{if(a>0i32){return a;}else{return -1i32;}}",
                b"// keep  spaces\nfn f(a: i32) -> i32 {\n    if (a > 0i32) {\n"
                b"        return a;\n    } else {\n        return -1i32;\n    }\n}\n",
            ),
            (
                b'const s:*u8="quotes \\" and \\n";// keep me\nfn f()->unit{f(); // tail\n}',
                b'const s: *u8 = "quotes \\" and \\n"; // keep me\n'
                b"fn f() -> unit {\n    f(); // tail\n}\n",
            ),
            (
                b"fn f()->unit{\n\n\nvar x:u32=1u32;\n\n\nreturn;\n}",
                b"fn f() -> unit {\n\n    var x: u32 = 1u32;\n\n    return;\n}\n",
            ),
            (
                b"fn identity!(Type)(x:Type)->Type{return x;}",
                b"fn identity!(Type)(x: Type) -> Type {\n    return x;\n}\n",
            ),
        )
        paths = []
        for index, (before, after) in enumerate(cases):
            path = self.source(f"case-{index}.crs", before)
            result = command([self.tool, path])
            assert result.stdout == after, (before, result.stdout, after)
            paths.append(path)
            interpreted = command([self.build / "crust", ROOT / "examples/format/main.crs", path])
            assert interpreted.stdout == after
        command([self.contract, "stable", *paths])
        wide = self.source("wide.crs", b"fn f()->unit{" + b"f(1i32," + b"2i32," * 50 + b"3i32);}")
        text = command([self.tool, wide]).stdout
        assert b"f(\n" in text
        command([self.contract, "stable", wide])
        return paths

    def corpus(self, fixtures):
        paths = sorted(
            p for folder in ("api", "stages", "examples") for p in (ROOT / folder).rglob("*.crs")
        )
        # This proves lexical preservation. The reader-switch root uses its explicit
        # service for execution below; its text grammar has a separate layout contract.
        command([self.contract, "stable", *paths, *fixtures])
        wide = self.source("alloc.crs", b"fn f()->unit{" + b"f(1i32, 2i32);" * 2000 + b"}")
        command([self.contract, "sweep", wide])
        print(f"Formatter: {len(paths)} repository sources preserve spans and reach a fixed point")
        return wide

    def failures(self):
        for index, text in enumerate(
            (b"{]", b"(", b")", b'"bad\\q"', b"\x00", b"// zero\x00\n", b"[" * 513 + b"]" * 513)
        ):
            path = self.source(f"invalid-{index}.crs", text)
            result = command([self.tool, "--write", path], 2)
            assert result.stderr and path.read_bytes() == text
        command([self.tool], 2)
        command([self.tool, "--bogus"], 2)
        command([self.tool, self.work / "absent"], 2)
        # Formatting input must never execute its root program.
        effect = self.work / "effect"
        effect.unlink(missing_ok=True)
        path = self.source(
            "effect.crs", f'crust0_host_write_file("{effect}","bad",3usize);'.encode()
        )
        command([self.tool, path])
        assert not effect.exists()
        with open("/dev/full", "wb") as stream:
            failed = subprocess.run([self.tool, path], stdout=stream, stderr=subprocess.PIPE)
        assert failed.returncode == 2 and b"cannot write" in failed.stderr

    def publication(self):
        original = b"fn f()->unit{}"
        path = self.source("with spaces.crs", original)
        path.chmod(0o754)
        command([self.tool, "--check", path], 1)
        command([self.tool, "--write", path])
        assert path.read_bytes() == b"fn f() -> unit {}\n" and path.stat().st_mode & 0o777 == 0o754
        saved = path.stat()
        command([self.tool, "--check", path])
        command([self.tool, "--write", path])
        assert path.stat().st_ino == saved.st_ino and path.stat().st_mtime_ns == saved.st_mtime_ns
        link = self.work / "link.crs"
        link.unlink(missing_ok=True)
        link.symlink_to(path)
        command([self.tool, "--write", link], 2)
        link.unlink()
        os.link(path, link)
        command([self.tool, "--write", path], 2)
        link.unlink()
        dash = self.source("--check", original)
        command([self.tool, "--", dash.name], cwd=self.work)
        directory = self.work / "read-only"
        directory.mkdir(exist_ok=True)
        target = directory / "source.crs"
        target.write_bytes(original)
        directory.chmod(0o555)
        try:
            command([self.tool, "--write", target], 2)
            assert target.read_bytes() == original
        finally:
            directory.chmod(0o755)
        long_name = self.source("x" * 250, original)
        command([self.tool, "--write", long_name])
        command([self.tool, "--check", long_name])
        assert not list(self.work.rglob(".crust-format-*"))

    def custom(self):
        root = ROOT / "examples/format/reader-switch.crs"
        source = ROOT / "examples/reader-switch/main.crs"
        formatted = command([self.build / "crust", root, source]).stdout
        target = self.source("reader-switch.crs", formatted)
        assert command([self.build / "crust", root, target]).stdout == formatted
        assert (
            command([self.build / "crust", target]).stdout
            == command([self.build / "crust", source]).stdout
        )
        mixed = self.source("opaque.crs", b'fn f()->unit{}\n> unmatched {" \t  text\r\n')
        result = command([self.build / "crust", root, mixed]).stdout
        assert result == b'fn f() -> unit {}\n> unmatched {" \t  text\r\n'
        command([self.tool, mixed], 2)

    def sanitize(self, source):
        output = self.work / "contracts-sanitized"
        flags = [
            "-O1",
            "-g",
            "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer",
            "-fno-sanitize-recover=all",
        ]
        libraries = [
            *flags,
            "-std=c99",
            "-pedantic-errors",
            "-I" + str(ROOT / "include"),
            "-I" + str(ROOT / "src"),
            ROOT / "crust0_amalg.c",
            ROOT / "src/profile_linux_x64.c",
            ROOT / "runtime/host.c",
            ROOT / "runtime/host_posix.c",
        ]
        compile_package(self.build, ROOT / "tests/format-package.crs", output, flags, libraries)
        command([output, "sweep", source])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    args = parser.parse_args()
    suite = Suite(args.build)
    fixtures = suite.layouts()
    wide = suite.corpus(fixtures)
    suite.failures()
    suite.publication()
    suite.custom()
    suite.sanitize(wide)
    print(
        "Formatter: layout, interpreted/native parity, failure, write, service and sanitizer checks passed"
    )


if __name__ == "__main__":
    main()
