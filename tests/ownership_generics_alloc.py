#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check ownership generic allocation failures with instrumented stages and core."""

import argparse
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

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

    def run(command):
        result = subprocess.run(
            [str(item) for item in command],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode:
            raise RuntimeError(f"{command}\n{result.stdout}{result.stderr}")

    with tempfile.TemporaryDirectory(prefix="ownership-generics-alloc-", dir=args.build) as tmp:
        work = Path(tmp).resolve()
        generated = work / "stage.c"
        symbols = work / "stage.rsp"
        run(
            [
                args.build / "crust-c",
                "--emit-c",
                "--symbols",
                symbols,
                "-o",
                generated,
                *args.sources,
                ROOT / "tests/ownership_generics_alloc.crs",
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
        cc = shlex.split(args.cc)
        run([*cc, *flags, "-c", generated, "-o", work / "input.o"])
        run(["objcopy", f"@{symbols}", work / "input.o", work / "stage.o"])
        core = (
            ["crust0_amalg.c"] if args.amalgamation else ["src/core.c", "src/read.c", "src/check.c"]
        )
        run(
            [
                *cc,
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
                work / "stage.o",
                "-o",
                work / "sweep",
            ]
        )
        run([work / "sweep"])
    print("ownership generic allocation sweep and sticky diagnostics passed")


if __name__ == "__main__":
    main()
