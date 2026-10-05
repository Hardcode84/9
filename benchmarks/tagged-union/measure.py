#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare a reader token payload port with the production flat token."""

import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import subprocess
import time
from pathlib import Path

from port import port

ROOT = Path(__file__).resolve().parents[2]


def run(command):
    result = subprocess.run(
        list(map(str, command)), cwd=ROOT, capture_output=True, text=True, timeout=180
    )
    if result.returncode:
        raise RuntimeError(f"{command}\n{result.stdout}{result.stderr}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--cpu", type=int, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build") or args.rounds < 2:
        parser.error("use a new directory under build/ and at least two rounds")
    os.sched_setaffinity(0, {args.cpu})
    output.mkdir(parents=True)
    commands = []
    hashes = {}

    def capture(path):
        path = Path(path)
        relative = path.relative_to(ROOT) if path.is_absolute() else path
        saved = output / "inputs" / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, saved)
        hashes[str(relative)] = hashlib.sha256(saved.read_bytes()).hexdigest()
        return saved

    def execute(command):
        commands.append([str(x) for x in command])
        return run(command)

    for path in Path(__file__).parent.iterdir():
        if path.is_file():
            capture(path)
    reader = [f"stages/reader/{name}.crs" for name in ("model", "lex", "parse")]
    api = ["api/crust0.crs", "api/crust0_host.crs"]
    flat = [capture(path) for path in reader]
    tagged_dir = output / "tagged"
    port(tagged_dir)
    tagged = [tagged_dir / Path(path).name for path in reader]
    api = [capture(path) for path in api]
    test = capture("stages/reader/test.crs")
    eval_api = capture("api/crust0_eval.crs")
    runtime = capture("tests/runtime.crs")
    driver = output / "inputs/benchmarks/tagged-union/driver.crs"
    host = output / "host.o"
    execute(
        [
            "cc",
            "-std=c99",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-c",
            "benchmarks/tagged-union/host.c",
            "-o",
            host,
        ]
    )
    libraries = [
        "build/libcrust0_run.a",
        "build/libcrust0.a",
        "build/libcrust0_host.a",
        "-ldl",
        "-lffi",
    ]
    links = [f"--ldflag={item}" for item in libraries]
    library_sources = execute(
        [
            "make",
            "-s",
            "--no-print-directory",
            "--eval",
            'union-inputs:;@printf "%s\\n" $(UNION_LIBRARY)',
            "union-inputs",
        ]
    ).splitlines()
    inspector = output / "inspect"
    execute(
        [
            "build/crust-c",
            "-o",
            inspector,
            *library_sources,
            "stages/ccn/count.crs",
            "benchmarks/tagged-union/inspect.crs",
            f"--ldflag={host}",
            *links,
        ]
    )
    corpus = sorted((ROOT / "build/reader-tests").glob("syntax-*.crs")) + sorted(
        (ROOT / "build/reader-tests").glob("depth-*.crs")
    )
    if len(corpus) < 100:
        raise RuntimeError("run make check-reader first to prepare the reader parity corpus")
    corpus = [capture(path) for path in corpus]
    rows = {}
    for label, compiler, sources, harness in (
        ("flat", "build/crust-c", flat, test),
        ("tagged", "build/crust-union-test", tagged, tagged_dir / "test.crs"),
    ):
        executable = output / label
        if label == "tagged":
            executable = output / "tagged-reader"
        execute(
            [
                compiler,
                *api,
                *sources,
                driver,
                "--cflag=-O2",
                "-o",
                executable,
                f"--ldflag={host}",
                *links,
            ]
        )
        parity = output / f"{label}-parity"
        execute([compiler, *api, eval_api, *sources, harness, "--cflag=-O2", "-o", parity, *links])
        execute([parity, *corpus, runtime, test])
        ccn = execute([inspector, *api, *sources])
        counts = [int(line.split()[-1]) for line in ccn.splitlines()]
        (output / f"{label}-ccn.txt").write_text(ccn)
        rows[label] = {
            "binary": str(executable),
            "token_bytes": int(execute([executable, runtime])),
            "source_bytes": sum(x.stat().st_size for x in sources),
            "source_lines": sum(len(x.read_text().splitlines()) for x in sources),
            "lowered_ccn_sum": sum(counts),
            "lowered_ccn_max": max(counts),
            "samples_ms": [],
        }
    for index in range(args.rounds):
        order = ("flat", "tagged") if index % 2 == 0 else ("tagged", "flat")
        for label in order:
            start = time.perf_counter_ns()
            execute([rows[label]["binary"], runtime])
            rows[label]["samples_ms"].append((time.perf_counter_ns() - start) / 1e6)
    ratios = [
        b / a
        for a, b in zip(rows["flat"]["samples_ms"], rows["tagged"]["samples_ms"], strict=False)
    ]
    rng = random.Random(0)
    boot = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(5000))
    for path in [
        *library_sources,
        "build/crust-c",
        "build/crust-union-test",
        *libraries[:3],
        "crust0_amalg.c",
    ]:
        hashes[str(path)] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    report = {
        "scope": "100 reader + collect + resolve + check passes per process; target GCC excluded",
        "cpu": args.cpu,
        "commands": commands,
        "hashes": hashes,
        "parity_inputs": len(corpus) + 2,
        "rows": rows,
        "paired_median_ratio": statistics.median(ratios),
        "ratio_ci95": [boot[125], boot[4874]],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in ("commands", "hashes")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
