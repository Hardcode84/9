#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail every allocation through checked clients and explicit trusted providers."""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from ownership import RUNTIME_TREE
from ownership_loops import LOOPS
from ownership_origins import RECORDS

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--amalgamation", type=int, choices=(0, 1), default=1)
    parser.add_argument("--sources", nargs="+", required=True)
    args = parser.parse_args()
    environment = dict(
        os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1"
    )

    def run(argv):
        result = subprocess.run(
            [str(x) for x in argv],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode:
            raise RuntimeError(f"{argv}\n{result.stdout}{result.stderr}")
        return result.stdout

    with tempfile.TemporaryDirectory(prefix="ownership-alloc-", dir=args.build) as tmp:
        work = Path(tmp).resolve()
        generated = work / "stage.c"
        symbols = work / "stage.rsp"
        run(
            [
                args.build / "crust-c",
                "--library",
                "--emit-c",
                "--export",
                "ownership_alloc_verify",
                "--symbols",
                symbols,
                "-o",
                generated,
                *args.sources,
            ]
        )
        flags = [
            "-std=c99",
            "-pedantic-errors",
            "-O1",
            "-g",
            "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all",
            "-fno-omit-frame-pointer",
        ]
        run([args.cc, *flags, "-c", generated, "-o", work / "input.o"])
        run(["objcopy", f"@{symbols}", work / "input.o", work / "stage.o"])
        core = (
            ["crust0_amalg.c"] if args.amalgamation else ["src/core.c", "src/read.c", "src/check.c"]
        )
        run(
            [
                args.cc,
                *flags,
                "-Wall",
                "-Wextra",
                "-Werror",
                "-Wstrict-prototypes",
                "-Wmissing-prototypes",
                "-Wshadow",
                "-Wvla",
                "-Iinclude",
                "-Isrc",
                "-no-pie",
                *core,
                "src/profile_linux_x64.c",
                "runtime/host.c",
                "runtime/host_posix.c",
                "tests/ownership_alloc.c",
                work / "stage.o",
                "-Wl,--wrap=crust0_host_alloc",
                "-Wl,--wrap=crust0_host_free",
                "-o",
                work / "sweep",
            ]
        )
        runtime_tree = work / "runtime-tree.crs"
        runtime_tree.write_text(RUNTIME_TREE)
        loops = work / "loops.crs"
        loops.write_text(LOOPS)
        origins = work / "origins.crs"
        origins.write_text(RECORDS)
        for source, trusted in [
            (origins, ""),
            (loops, ""),
            ("examples/ownership-basics/origins.crs", ""),
            ("examples/ownership-basics/last-use.crs", ""),
            (runtime_tree, "examples/ownership-graphs/provider.crs"),
            ("examples/intrusive/program.crs", "examples/intrusive/links.crs"),
            ("examples/ownership-graphs/program.crs", "examples/ownership-graphs/provider.crs"),
            ("examples/ownership-index/program.crs", "examples/ownership-index/provider.crs"),
            ("examples/ownership-basics/handles.crs", ""),
            ("examples/ownership-basics/views.crs", ""),
            ("examples/ownership-basics/heap.crs", ""),
        ]:
            print(source, run([work / "sweep", source, trusted]).strip())


if __name__ == "__main__":
    main()
