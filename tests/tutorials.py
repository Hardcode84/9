#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the same tutorial sources through C and LLVM, including native stages."""

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

from host import WINDOWS
from run import checked_command

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("hello", "hello", b"Hello, world!\n"),
    ("multiple-files", "multiple-files", b"Hello from another source file!\n"),
    ("modules", "modules", b"modules: 42\n"),
    ("ownership-basics", "ownership-basics", b"BC\n"),
    ("intrusive", "intrusive-checked", b"OK\n"),
    ("ownership-graphs", "ownership-graphs", b"OK\n"),
    ("ownership-index", "ownership-index", b"OK\n"),
    ("resources/hello", "resource-hello", b"Hello, resources!\n"),
    ("resources/returned", "resource-returned", b"42\n"),
    ("overload/hello", "overload-hello", b"A typed function value.\nHello, overloads!\n"),
    ("overload/separate", "overload-separate", b"types: 42\n"),
    ("overload/resources", "overload-resources", b"Owned overloads.\nDeferred overload.\n"),
    ("generics", "generics", b"generics: OK\n"),
    ("generics/ownership", "generics-ownership", b"HFBFOK\n"),
    ("composition", "composition", b"!B"),
    ("union", "union", b"union: OK\n"),
)


def command(arguments, expected=0, **options):
    return checked_command(arguments, expected=expected, timeout=240, text_output=True, **options)


def configuration(work, llvm, level):
    config = work / f"llvm-{level}.crs"
    config.write_text(
        f"const LLVM_DIRECTORY:*u8={json.dumps(str(llvm))};\nconst LLVM_OPTIMIZATION:u32={level}u32;\n"
    )
    package = work / f"compiler-{level}.crs"
    package.write_text(
        f'stage_include(stage,{json.dumps(str(ROOT / "tests/tutorials/compiler-package.crs"))});\n'
        f"stage_source(stage,{json.dumps(config.name)});\n"
    )
    return [
        "--backend",
        package,
        "llvm_backend_build",
        "--stage-compiler",
        package,
        "tutorial_stage_compile",
        "llvm_stage_toolchain",
    ]


class Matrix:
    def __init__(self, build, llvm, formatter=None):
        self.build = build
        self.work = build / "tutorial-matrix"
        self.work.mkdir(exist_ok=True)
        self.package = self.work / "source package"
        self.package.mkdir(exist_ok=True)
        for directory in ("examples", "api", "stages", "tools"):
            shutil.copytree(ROOT / directory, self.package / directory, dirs_exist_ok=True)
        if formatter:
            self.format_sources(formatter)
        self.output = self.package / "build"
        self.output.mkdir(exist_ok=True)
        shutil.copyfile(build / "libcrust0_host.a", self.output / "libcrust0_host.a")
        self.cwd = self.work / "working directory"
        self.cwd.mkdir(exist_ok=True)
        self.profiles = [
            ("c", []),
            ("llvm-O0", configuration(self.work, llvm, 0)),
            ("llvm-O2", configuration(self.work, llvm, 2)),
        ]
        self.results = []
        self.diagnostics = {}

    def format_sources(self, formatter):
        text_root = self.package / "examples/reader-switch/main.crs"
        for source in sorted(self.package.rglob("*.crs")):
            if source == text_root:
                output = command(
                    [self.build / "crust", ROOT / "examples/format/reader-switch.crs", source]
                ).stdout
            else:
                output = command([formatter, source]).stdout
            source.write_bytes(output)

    def root(self, path, selection, arguments=(), expected=0):
        return command(
            [self.build / "crust", self.package / "examples" / path, *selection, *arguments],
            expected,
            cwd=self.cwd,
        )

    def execute(self, profile, path, arguments=(), expected=0, stdout=b"", stderr=b""):
        result = command([path, *arguments], expected, cwd=self.cwd)
        assert (result.stdout, result.stderr) == (stdout, stderr), (profile, path, result)
        self.results.append(
            {
                "profile": profile,
                "program": str(path),
                "status": result.returncode,
                "stdout": result.stdout.hex(),
                "stderr": result.stderr.hex(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )

    def applications(self, profile, selection):
        for name, output, expected in CASES:
            result = self.root(name + "/main.crs", selection)
            assert not result.stdout and not result.stderr, (profile, name, result)
            self.execute(profile, self.output / output, stdout=expected)
        self.root("arguments/main.crs", selection, ["-o", self.output / "arguments"])
        self.execute(
            profile,
            self.output / "arguments",
            ["first", "two words"],
            stdout=b"Program arguments:\nfirst\ntwo words\n",
        )
        self.root(
            "intrusive/raw-main.crs",
            selection,
            ["-o", self.output / "intrusive-raw", "--ldflag", self.output / "libcrust0_host.a"],
        )
        self.execute(profile, self.output / "intrusive-raw", stdout=b"intrusive: ok\n")
        self.root("ccn/build.crs", selection)
        self.execute(profile, self.output / "ccn-example")
        heap = self.package / "examples/ownership-basics/heap.crs"
        self.root("ownership-basics/main.crs", selection, ["-o", self.output / "heap", heap])
        self.execute(profile, self.output / "heap", stdout=b"AB\n")

    def sqlite(self, profile, selection):
        source = ROOT / ".profile-cache/resources-baseline/sqlite3.o"
        if not source.is_file():
            raise RuntimeError(
                "Prepare the pinned SQLite input with examples/resources/sqlite/README.md"
            )
        target = self.package / ".profile-cache/resources-baseline/sqlite3.o"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        binary = self.output / "sqlite-resource"
        # Pass output explicitly; leave the selected LLVM optimization unchanged.
        self.root("resources/sqlite/main.crs", selection, ["-o", binary])
        database = self.work / "input.db"
        database.unlink(missing_ok=True)
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("create table input(seq integer,value)")
            db.executemany("insert into input values(?,?)", [(1, "hello"), (2, 17), (3, None)])
        self.execute(profile, binary, [database], stdout=b"T 68656c6c6f\nI 3137\nN\nrows 3\n")
        self.execute(profile, binary, [self.work / "absent/input.db"], 1, stderr=b"error 14 0 0\n")

    def rejections(self, profile, selection):
        header = "resource Ticket{value:i32;} drop close;fn close(x:mut Ticket)->unit{} "
        cases = (
            (
                "use-after-move",
                "fn f()->i32{var t:Ticket=make Ticket{value:1i32};var u:Ticket=move t;return t.value;}",
                b"moved",
            ),
            (
                "move-borrowed",
                "fn f(t:read Ticket)->unit{var u:Ticket=move t;}",
                b"cannot move out of a borrowed value",
            ),
            ("drop-borrowed", "fn f(t:mut Ticket)->unit{drop t;}", b"cannot drop a borrowed value"),
        )
        for name, body, diagnostic in cases:
            source = self.work / (name + ".crs")
            source.write_text(header + body)
            result = self.root("ownership-basics/main.crs", selection, ["--check", source], 1)
            assert diagnostic in result.stderr, (profile, result.stderr)
            assert self.diagnostics.setdefault(name, result.stderr) == result.stderr
            self.results.append(
                {"profile": profile, "rejection": name, "diagnostic": result.stderr.decode()}
            )

    def output_modes(self, profile, selection):
        source = self.package / "examples/ownership-basics/program.crs"
        output = self.output / "selected-text"
        symbols = self.output / "selected-symbols"
        output.unlink(missing_ok=True)
        symbols.unlink(missing_ok=True)
        self.root("ownership-basics/main.crs", selection, ["--prepare", source])
        assert not output.exists()
        self.root(
            "ownership-basics/main.crs",
            selection,
            ["--emit", "-o", output, "--symbols", symbols, source],
        )
        text = output.read_bytes()
        triple = b"x86_64-w64-windows-gnu" if WINDOWS else b"x86_64-unknown-linux-gnu"
        marker = b'target triple = "' + triple + b'"' if profile.startswith("llvm") else b"r_g"
        assert marker in text and symbols.stat().st_size
        saved = b"retain previous output\n"
        output.write_bytes(saved)
        self.root(
            "ownership-basics/main.crs",
            selection,
            ["-o", output, "--cflag=-crust-invalid-option", source],
            1,
        )
        assert output.read_bytes() == saved
        assert not list(self.output.glob(".crust-*"))
        self.results.append(
            {
                "profile": profile,
                "modes": ["prepare", "text", "failed object"],
                "text_sha256": hashlib.sha256(text).hexdigest(),
            }
        )

    def tools(self, profile, selection):
        root = self.work / "tool.crs"
        root.write_text(
            f'host_source(run,{json.dumps(str(ROOT/"stages/build/load.crs"))});\n'
            f"if !stage_setup(run,{json.dumps(str(ROOT))}){{return 1i32;}};\n"
            f'var stages:*StageSession=stage_open(run,{json.dumps(str(ROOT))},{json.dumps(str(self.output/"stage-cache"))});\n'
            "if stages==null(*StageSession){return 1i32;};\n"
            f'host_source(run,{json.dumps(str(ROOT/"stages/build/backend.crs"))});\n'
            "var backend:ApplicationBackend=uninit;if !application_backend(run,stages,&backend,c_backend_build){return 1i32;};\n"
            'extern fn entry(argc:i32,argv:**u8)->i32="crust_tool_main";\n'
            "if run->argc<1i32 || !application_load(stages,&backend,run->argv[0usize]){return 1i32;};\n"
            "return entry(run->argc,run->argv);\n"
        )
        cases = (
            ("format", [ROOT / "examples/hello/main.crs"], 0),
            ("format", [ROOT / "examples/ownership-basics/program.crs"], 0),
            ("highlight", ["--tokens", ROOT / "examples/hello/main.crs"], 0),
            ("highlight", ["--html", ROOT / "examples/hello/main.crs"], 0),
            ("ccn", ["--CCN", "15", ROOT / "examples/ccn/program.crs"], 0),
            ("ccn", ["--CCN", "15", ROOT / "examples/intrusive/raw.crs"], 1),
        )
        for tool, arguments, status in cases:
            reference = command(
                [self.build / "crust", ROOT / f"examples/{tool}/main.crs", *arguments], status
            )
            result = command(
                [
                    self.build / "crust",
                    root,
                    *selection,
                    ROOT / f"stages/{tool}/tool.crs",
                    *arguments,
                ],
                status,
            )
            assert (result.stdout, result.stderr) == (reference.stdout, reference.stderr), (
                profile,
                tool,
                result,
            )
            self.results.append(
                {
                    "profile": profile,
                    "tool": tool,
                    "status": status,
                    "output_sha256": hashlib.sha256(result.stdout).hexdigest(),
                }
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument(
        "--llvm", type=Path, help="explicit LLVM installation; default is the pinned release"
    )
    parser.add_argument("--profile", choices=["c", "llvm-O0", "llvm-O2"], action="append")
    parser.add_argument(
        "--formatter", type=Path, help="format copied tutorial and stage sources before compilation"
    )
    args = parser.parse_args()
    llvm = (
        args.llvm.resolve()
        if args.llvm
        else Path(
            subprocess.check_output(
                ["python3", ROOT / "tools/fetch_llvm.py", "release", "--locked"], text=True
            ).strip()
        )
    )
    matrix = Matrix(
        args.build.resolve(), llvm, args.formatter.resolve() if args.formatter else None
    )
    try:
        for profile, selection in matrix.profiles:
            if args.profile and profile not in args.profile:
                continue
            matrix.applications(profile, selection)
            matrix.sqlite(profile, selection)
            matrix.rejections(profile, selection)
            matrix.output_modes(profile, selection)
            matrix.tools(profile, selection)
            print(f"Tutorials: {profile} passed", flush=True)
    finally:
        (matrix.work / "results.json").write_text(json.dumps(matrix.results, indent=2) + "\n")


if __name__ == "__main__":
    main()
