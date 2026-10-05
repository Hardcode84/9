#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check an external overload library with ordinary CRUST reader and type hooks."""

import argparse
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cflags", default="-O2 -g")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    build = args.build.resolve()
    with tempfile.TemporaryDirectory(prefix="crust-overload-hooks-") as directory:
        work = Path(directory)
        harness = work / "harness"
        library = work / "ordinary-overload.so"
        shutil.copyfile(build / "crust-overload-library.so", library)
        backend = work / "ordinary-backend.so"
        shutil.copyfile(build / "crust-c-library.so", backend)
        sources = [
            "api/crust0.crs",
            "api/crust0_host.crs",
            "api/crust0_stage.crs",
            "stages/c/api.crs",
            "stages/source/model.crs",
            "stages/source/base.crs",
            "stages/reader/model.crs",
            "stages/overload/model.crs",
            "stages/overload/extension.crs",
            "stages/reader/lex.crs",
            "stages/reader/parse.crs",
            "tests/overload_hooks.crs",
        ]
        subprocess.run(
            [
                str(build / "crust-c"),
                "-o",
                str(harness),
                *sources,
                *("--cflag=" + flag for flag in shlex.split(args.cflags)),
                "--ldflag=" + str(library),
                "--ldflag=" + str(backend),
                "--ldflag=" + str(build / "libcrust0.a"),
                "--ldflag=" + str(build / "libcrust0_host.a"),
                *("--ldflag=" + flag for flag in shlex.split(args.ldflags)),
            ],
            cwd=ROOT,
            check=True,
            timeout=120,
        )
        names = []
        for order in ("first", "shifted"):
            target = work / order
            subprocess.run([str(harness), str(target), order], cwd=ROOT, check=True, timeout=30)
            subprocess.run([str(target)], cwd=ROOT, check=True, timeout=30)
            symbols = subprocess.run(
                ["nm", "--defined-only", str(target)],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            ).stdout
            names.append(
                sorted(line.split()[-1] for line in symbols.splitlines() if "crust_ov1_" in line)
            )
        if not names[0] or names[0] != names[1]:
            raise SystemExit("extension kind allocation order changed native names")
    print(
        "Overload hooks: type queries, buffer growth, stable names, execution, and diagnostics passed"
    )


if __name__ == "__main__":
    main()
