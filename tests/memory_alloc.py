#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail each host and context arena allocation during the selected proof stage."""

import argparse
import fnmatch
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
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
                "drop",
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
    parser.add_argument("--ownership", action="store_true")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--summaries", action="store_true")
    selection.add_argument("--contracts", action="store_true")
    selection.add_argument("--loops", action="store_true")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--no-sanitize", action="store_true")
    parser.add_argument("--work", type=Path)
    parser.add_argument("--jobs", type=int, default=1, help="independent allocation sweep shards")
    parser.add_argument(
        "--timeout", type=float, default=180, help="seconds per exhaustive input sweep shard"
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.ownership and (args.resources or args.summaries or args.contracts or args.loops):
        parser.error("--ownership selects its own stage and inputs")
    if args.contracts or args.loops:
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
    if args.loops:
        from memory_loop import accept_cases as loop_cases

        models = {name: item[0] for name, item in loop_cases().items()}
        cases = {name: item[1] for name, item in loop_cases().items()}
        names = ("countdown", "continue", "break", "walk")
    if args.ownership:
        from ownership_contracts import SCALAR_FLOW

        links = (ROOT / "examples/intrusive/links.crs").read_text()
        program = (ROOT / "examples/intrusive/program.crs").read_text()
        node = program.split("record Node", 1)[1].split("resource Owner", 1)[0]
        types = "domain Graph(Node);\nrecord Node" + node
        cases = {
            "views": (ROOT / "examples/ownership-basics/views.crs").read_text(),
            "native": (ROOT / "examples/ownership-basics/handles.crs").read_text(),
            "scalar-flow": SCALAR_FLOW,
            "scalar-loan": "fn clear(flag:mut bool)->unit {flag=false;} "
            "fn main()->i32 {var flag:bool=true; clear(mut flag); "
            "if flag {return 1i32;} return 0i32;}",
            "scalar-call": "domain D(Flag); record Flag {value:bool;} domain(D); "
            "fn set(flag:mut Flag)->unit access(edit,D) {flag.value=true;} "
            "fn main()->i32 access(reclaim,D) {var flag:Flag=make Flag{value:false}; "
            "set(mut flag); if flag.value {return 1i32;} return 0i32;}",
            "reference-only": "domain D(Cell); record Cell {next:*Cell;} domain(D) references(next); "
            "fn initialize(p:*Cell)->unit access(edit,D) initializes(p) requires(p!=null(*Cell)) "
            "{(*p).next=null(*Cell);}",
            "links": types + links,
            "graph": (ROOT / "examples/ownership-graphs/program.crs").read_text(),
            "intrusive": links + (ROOT / "examples/intrusive/program.crs").read_text(),
            "fields": links + (ROOT / "examples/intrusive/fields.crs").read_text(),
            "recursive": links + (ROOT / "examples/intrusive/recursive/program.crs").read_text(),
        }
        names = tuple(cases)
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
        if args.loops:
            sources = [
                *sources[:-1],
                "stages/memory/loop.crs",
                "examples/intrusive/walk-options.crs",
                "examples/intrusive/walk-stage.crs",
                "tests/memory_loop_models.crs",
                "tests/memory_loop_alloc.crs",
            ]
        if args.ownership:
            sources = [
                path
                for path in resource_stage()[:-1]
                if not path.startswith(("stages/memory/", "stages/resource_memory/"))
            ]
            sources += [
                str(path.relative_to(ROOT))
                for path in sorted((ROOT / "stages/ownership").glob("*.crs"))
                if path.name not in ("api.crs", "build.crs", "library_api.crs")
            ]
            sources += [
                "api/crust0_eval.crs",
                "api/crust0_run.crs",
                "stages/native/model.crs",
                "stages/native/linux.crs",
                "stages/cache/model.crs",
                "stages/cache/linux.crs",
                "stages/cache/artifact.crs",
                "stages/cache/inputs.crs",
                "tests/ownership_alloc.crs",
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
            model = models[name] if models else ("rewrite" if args.summaries else "")

            def sweep(shard, source=source, model=model, name=name):
                result = run([executable, source, model, shard, args.jobs], timeout=args.timeout)
                matched = re.fullmatch(
                    rb"memory allocation: ([0-9]+) of ([0-9]+) failure points checked\n",
                    result.stdout,
                )
                if matched is None or result.stderr:
                    raise RuntimeError(
                        f"unexpected output for {name}: {result.stdout!r} {result.stderr!r}"
                    )
                return tuple(map(int, matched.groups()))

            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                results = list(pool.map(sweep, range(1, args.jobs + 1)))
            count = sum(checked for checked, _ in results)
            if count == 0 or any(expected != count for _, expected in results):
                raise RuntimeError(f"allocation shards did not cover all failure points for {name}")
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
