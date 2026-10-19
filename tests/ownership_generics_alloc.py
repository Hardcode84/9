#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check ownership generic allocation failures with instrumented stages and core."""

import argparse
import shlex
import tempfile
from pathlib import Path

from host import WINDOWS, host_sources, sanitizer_compiler, sanitizer_environment, sanitizer_flags
from host import run as host_run
from prepare import sources

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default=sanitizer_compiler())
    parser.add_argument("--amalgamation", type=int, choices=(0, 1), default=1)
    parser.add_argument("--sources", nargs="+")
    args = parser.parse_args()
    args.build = args.build.resolve()
    if args.sources is None:
        args.sources = sources(args.build, "generics/ownership/package.crs")
    environment = sanitizer_environment()

    def run(command):
        result = host_run(
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
                "--emit",
                "--symbols",
                symbols,
                "-o",
                generated,
                *args.sources,
                ROOT / "tests/ownership_generics_alloc.crs",
            ]
        )
        flags = ["-std=c99", "-pedantic-errors", *sanitizer_flags()]
        cc = shlex.split(args.cc)
        run([*cc, *flags, "-c", generated, "-o", work / "input.o"])
        run(["objcopy", f"@{symbols}", work / "input.o", work / "stage.o"])
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
                *([] if WINDOWS else ["-no-pie"]),
                *host_sources(args.amalgamation),
                *(["-lbcrypt"] if WINDOWS else []),
                work / "stage.o",
                "-o",
                work / "sweep",
            ]
        )
        run([work / "sweep"])
    print("ownership generic allocation sweep and sticky diagnostics passed")


if __name__ == "__main__":
    main()
