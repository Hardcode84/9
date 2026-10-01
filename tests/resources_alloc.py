#!/usr/bin/env python3
"""Fail each arena allocation during complete resource reading and preparation."""

import argparse
import fnmatch
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import resources


ROOT = Path(__file__).resolve().parents[1]
STAGE = [
    "api/rmd0.rmd", "api/rmd0_host.rmd",
    "stages/reader/model.rmd", "stages/reader/lex.rmd", "stages/reader/parse.rmd",
    *[f"stages/resources/{name}.rmd" for name in (
        "model", "base", "read", "types", "constants", "state", "cleanup",
        "places", "expr", "control")],
    "tests/resources_alloc.rmd",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--no-sanitize", action="store_true")
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    compiler = args.build.resolve() / "rmd-c"
    if not compiler.is_file():
        parser.error(f"compiler does not exist: {compiler}")
    work = args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix="rmd-resources-alloc-"))
    work.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"

    def run(command, timeout=120):
        result = subprocess.run([str(item) for item in command], cwd=ROOT, env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"command failed ({result.returncode}): {command}\n"
                               f"{result.stdout.decode(errors='replace')}{result.stderr.decode(errors='replace')}")
        return result

    completed = False
    try:
        generated = work / "fixture.c"
        response = work / "fixture.rsp"
        run([compiler, "--emit-c", "-o", generated, "--symbols", response, *STAGE])
        flags = ["-std=c99", "-pedantic-errors", "-g", "-O1", "-fno-omit-frame-pointer"]
        if not args.no_sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        run([args.cc, *flags, "-c", generated, "-o", work / "fixture.input.o"])
        run(["objcopy", f"@{response}", work / "fixture.input.o", work / "fixture.o"])
        strict = ["-Wall", "-Wextra", "-Werror", "-Wstrict-prototypes", "-Wmissing-prototypes", "-Wshadow", "-Wvla"]
        executable = work / "fixture"
        run([args.cc, *flags, *strict, "-Iinclude", "-no-pie", work / "fixture.o",
             "src/core.c", "src/read.c", "src/check.c", "runtime/host.c", "-o", executable])
        cases = []
        for name, source, _ in resources.runtime_cases():
            if args.case and not any(fnmatch.fnmatchcase(name, pattern) for pattern in args.case):
                continue
            path = work / f"{name}.rmd"
            path.write_text(source)
            cases.append((name, [path]))
        if not args.case or any(fnmatch.fnmatchcase("sqlite", pattern) for pattern in args.case):
            cases.append(("sqlite", [ROOT / "examples/resources/sqlite/library.rmd",
                                      ROOT / "examples/resources/sqlite/program.rmd"]))
        if not cases:
            parser.error("no test cases selected")
        total = 0
        for name, inputs in cases:
            result = run([executable, *inputs])
            match = re.fullmatch(rb"resource allocation: ([0-9]+) failure points checked\n", result.stdout)
            if match is None or result.stderr:
                raise RuntimeError(f"unexpected output for {name}: {result.stdout!r} {result.stderr!r}")
            count = int(match.group(1))
            if count == 0:
                raise RuntimeError(f"no allocation failure was exercised for {name}")
            total += count
            print(f"{name}: {count} allocation failures checked", flush=True)
        print(f"Resource allocation suite: {len(cases)} inputs; {total} failure points; "
              f"{'native' if args.no_sanitize else 'GCC ASan and UBSan'}")
        completed = True
    finally:
        if completed and args.work is None:
            shutil.rmtree(work)
        else:
            print(f"Allocation test artifacts: {work}", flush=True)


if __name__ == "__main__":
    main()
