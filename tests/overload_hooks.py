#!/usr/bin/env python3
"""Check an external overload library with ordinary RMD reader and type hooks."""

import argparse
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cflags", default="-O2 -g")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    build = args.build.resolve()
    with tempfile.TemporaryDirectory(prefix="rmd-overload-hooks-") as directory:
        work = Path(directory)
        harness = work / "harness"
        library = work / "ordinary-overload.so"
        shutil.copyfile(build / "rmd-overload-library.so", library)
        sources = ["api/rmd0.rmd", "api/rmd0_host.rmd", "stages/overload/model.rmd",
                   "stages/overload/extension.rmd", "stages/reader/model.rmd",
                   "stages/reader/lex.rmd", "stages/reader/parse.rmd", "tests/overload_hooks.rmd"]
        subprocess.run([str(build / "rmd-c"), "-o", str(harness), *sources,
                        *("--cflag=" + flag for flag in shlex.split(args.cflags)),
                        "--ldflag=" + str(library),
                        "--ldflag=" + str(build / "librmd0.a"),
                        "--ldflag=" + str(build / "librmd0_host.a"),
                        *("--ldflag=" + flag for flag in shlex.split(args.ldflags))],
                       cwd=ROOT, check=True, timeout=120)
        subprocess.run([str(harness)], cwd=ROOT, check=True, timeout=30)
    print("Overload hooks: custom type, exact callee visits, and five diagnostic paths passed")


if __name__ == "__main__":
    main()
