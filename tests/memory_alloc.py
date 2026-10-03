#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail each host arena allocation during the actual memory proof stage."""

import argparse
import fnmatch
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from memory import accept_cases
from resource_initialization import accept_cases as initialization_cases
from resource_memory import accept_cases as resource_cases

ROOT = Path(__file__).resolve().parents[1]
STAGE = [
    "api/crust0.crs",
    "api/crust0_host.crs",
    "api/crust0_stage.crs",
    *[f"stages/c/{name}.crs" for name in ("model", "base", "types", "emit", "driver", "program")],
    *[
        f"stages/proof/{name}.crs"
        for name in (
            "model",
            "base",
            "terms",
            "state",
            "query",
            "expression",
            "execute",
            "verify",
            "z3",
        )
    ],
    *[
        f"stages/memory/{name}.crs"
        for name in (
            "options",
            "model",
            "base",
            "plan",
            "storage",
            "expr",
            "foreign",
            "statement",
            "assign",
            "copy",
            "summary_plan",
            "summary_terms",
            "summary",
            "program",
        )
    ],
    "tests/memory_alloc.crs",
]
CASES = (
    "heap-write-read-release",
    "branch-initialization",
    "bounded-branch-loop",
    "direct-call-write",
    "projected-call",
)


def resource_stage():
    return [
        *STAGE[:-1],
        *[f"stages/reader/{name}.crs" for name in ("model", "lex", "parse")],
        *[
            f"stages/resources/{name}.crs"
            for name in (
                "model",
                "base",
                "read",
                "types",
                "constants",
                "state",
                "cleanup",
                "places",
                "expr",
                "control",
                "emit",
                "program",
                "build",
            )
        ],
        *[f"stages/resource_memory/{name}.crs" for name in ("model", "view", "effects", "program")],
        "tests/resource_memory_alloc.crs",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--amalgamation", type=int, choices=(0, 1), default=1)
    parser.add_argument("--z3-flags", default="-lz3")
    parser.add_argument("--resources", action="store_true")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--summaries", action="store_true")
    selection.add_argument("--contracts", action="store_true")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--no-sanitize", action="store_true")
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    if args.contracts:
        args.resources = True
    compiler = args.build.resolve() / "crust-c"
    if not compiler.is_file():
        parser.error(f"compiler does not exist: {compiler}")
    cases = (
        {name: item[0] for name, item in (resource_cases() | initialization_cases()).items()}
        if args.resources
        else accept_cases()
    )
    names = (
        (
            "defer-move",
            "owner-return",
            "owner-array",
            "loop-cleanup",
            "pointer-local",
            "pointer-index-once",
            "output-cleanup-initializes",
            "output-loop-continue",
        )
        if args.resources
        else CASES
    )
    if args.summaries:
        from memory_summary import accept_cases as summary_cases

        cases = summary_cases(args.resources)
        names = (
            "aliased-swap",
            "new-pointer-cell",
            "consume-field" if args.resources else "guarded-read",
        )
    models = {}
    if args.contracts:
        from memory_contract import accept_cases as contract_cases

        models = {name: item[0] for name, item in contract_cases().items()}
        cases = {name: item[1] for name, item in contract_cases().items()}
        names = ("aliased-swap", "conditional-body", "new-pointer-cell")
    selected = [
        name
        for name in names
        if not args.case or any(fnmatch.fnmatchcase(name, pattern) for pattern in args.case)
    ]
    if not selected:
        parser.error("no test cases selected")
    work = (
        args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix="crust-memory-alloc-"))
    )
    work.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"

    def run(command, timeout=180):
        result = subprocess.run(
            list(map(str, command)),
            cwd=ROOT,
            env=environment,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError(
                f"command failed ({result.returncode}): {command}\n"
                f"{result.stdout.decode(errors='replace')}{result.stderr.decode(errors='replace')}"
            )
        return result

    completed = False
    try:
        sources = resource_stage() if args.resources else STAGE
        if args.contracts:
            sources = [
                *sources[:-1],
                "stages/memory/contract.crs",
                "tests/memory_contract_models.crs",
                "tests/memory_contract_alloc.crs",
            ]
        generated = work / "fixture.c"
        response = work / "fixture.rsp"
        run(
            [
                compiler,
                "--library",
                "--export",
                "memory_alloc_verify",
                "--emit-c",
                "-o",
                generated,
                "--symbols",
                response,
                *sources,
            ]
        )
        flags = ["-std=c99", "-pedantic-errors", "-g", "-O1", "-fno-omit-frame-pointer"]
        if not args.no_sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        run([args.cc, *flags, "-c", generated, "-o", work / "fixture.input.o"])
        run(["objcopy", f"@{response}", work / "fixture.input.o", work / "fixture.o"])
        strict = [
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wstrict-prototypes",
            "-Wmissing-prototypes",
            "-Wshadow",
            "-Wvla",
        ]
        solver = shlex.split(args.z3_flags)
        executable = work / "fixture"
        run(
            [
                args.cc,
                *flags,
                *strict,
                "-Iinclude",
                "-Isrc",
                "-no-pie",
                work / "fixture.o",
                "tests/memory_alloc.c",
                *(
                    ["crust0_amalg.c"]
                    if args.amalgamation
                    else ["src/core.c", "src/read.c", "src/check.c"]
                ),
                "src/profile_linux_x64.c",
                "runtime/host.c",
                "runtime/host_posix.c",
                "-Wl,--wrap=crust0_host_alloc",
                "-Wl,--wrap=crust0_host_free",
                *solver,
                "-o",
                executable,
            ]
        )
        total = 0
        for name in selected:
            source = work / f"{name}.crs"
            source.write_text(cases[name])
            selected_model = (
                [models[name]] if args.contracts else (["rewrite"] if args.summaries else [])
            )
            result = run([executable, source, *selected_model])
            matched = re.fullmatch(
                rb"memory allocation: ([0-9]+) failure points checked\n", result.stdout
            )
            if matched is None or result.stderr:
                raise RuntimeError(
                    f"unexpected output for {name}: {result.stdout!r} {result.stderr!r}"
                )
            count = int(matched.group(1))
            if count == 0:
                raise RuntimeError(f"no allocation failure was exercised for {name}")
            total += count
            print(f"{name}: {count} allocation failures checked", flush=True)
        print(
            f"Memory allocation suite: {len(selected)} inputs; {total} failure points; "
            f"{'native' if args.no_sanitize else 'GCC ASan, UBSan, and leak detection'}"
        )
        completed = True
    finally:
        if completed and args.work is None:
            shutil.rmtree(work)
        else:
            print(f"Allocation test artifacts: {work}", flush=True)


if __name__ == "__main__":
    main()
