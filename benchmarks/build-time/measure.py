#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure complete C and assembly builds of the intrusive-list example."""

import argparse
import importlib.util
import json
import os
import random
import shutil
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "bootstrap_measure", ROOT / "benchmarks/bootstrap/measure.py"
)
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)


def sample(commands):
    start = time.perf_counter_ns()
    for command in commands:
        BASE.capture(command)
    return time.perf_counter_ns() - start


def summarize(rows):
    rng = random.Random(1010)
    result = {}
    for name in rows[0]:
        values = [row[name] for row in rows]
        draws = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(10000))
        result[name] = {
            "median_ns": statistics.median(values),
            "bootstrap_95_ci_ns": [BASE.percentile(draws, 0.025), BASE.percentile(draws, 0.975)],
        }
    ratios = [row["c-total"] / row["asm-total"] for row in rows]
    draws = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(10000))
    result["c_over_asm_total"] = {
        "median_paired_ratio": statistics.median(ratios),
        "paired_bootstrap_95_ci": [BASE.percentile(draws, 0.025), BASE.percentile(draws, 0.975)],
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.chdir(ROOT)
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        parser.error("use a new output directory under build/")
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("CPU is outside the allowed affinity set")
    os.sched_setaffinity(0, {args.cpu})
    output.mkdir(parents=True)
    source = output / "program.crs"
    shutil.copyfile(ROOT / "examples/intrusive/raw.crs", source)
    shutil.copyfile(__file__, output / "measure.py")
    shutil.copyfile(ROOT / "benchmarks/bootstrap/measure.py", output / "bootstrap-measure.py")
    c = ["build/crust-c", str(source)]
    asm = ["build/crust0", "-S", "-o", str(output / "program.s"), str(source)]
    commands = {
        "c-emit": [
            [
                *c,
                "--emit-c",
                "-o",
                str(output / "program.c"),
                "--symbols",
                str(output / "program.rsp"),
            ]
        ],
        "c-total": [[*c, "-o", str(output / "c-program"), "--ldflag", "build/libcrust0_host.a"]],
        "asm-emit": [asm],
        "asm-total": [
            asm,
            [
                "gcc",
                "-no-pie",
                str(output / "program.s"),
                "build/libcrust0_host.a",
                "-o",
                str(output / "asm-program"),
            ],
        ],
    }
    hashes = BASE.compiler_sources()
    for pattern in ("api/*.crs", "stages/c/*.crs", "stages/asm/*.crs"):
        hashes.update({str(path): BASE.sha256(path) for path in Path().glob(pattern)})
    for path in (
        source,
        Path(__file__),
        ROOT / "benchmarks/bootstrap/measure.py",
        Path("build/crust0"),
        Path("build/crust-c"),
        Path("build/libcrust0_host.a"),
    ):
        hashes[str(path)] = BASE.sha256(path)
    tools = {name: BASE.tool_info(name) for name in ("gcc", "as", "ld", "objcopy")}
    cc1 = BASE.capture(["gcc", "-print-prog-name=cc1"])
    tools["cc1"] = BASE.binary_info(cc1)
    for name in ("gcc", "as", "ld", "objcopy", cc1):
        path = str(Path(shutil.which(name)).resolve())
        hashes[path] = BASE.sha256(path)
    report = {
        "revision": BASE.capture(["git", "rev-parse", "HEAD"]),
        "environment": BASE.environment(args.cpu),
        "current_make_recipe": BASE.capture(["make", "-nB", "all", "c-stage"]),
        "commands": commands,
        "tools": tools,
        "hashes": hashes,
        "boundary": "Prepared standalone backends; complete source-to-executable totals include native tools. Emit endpoints exclude native tools. No root execution, cache validation, backend preparation, or target execution in timed samples.",
    }
    for steps in commands.values():
        sample(steps)
    for name in ("c-program", "asm-program"):
        result = BASE.run_process(
            [str(output / name)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if result.returncode != 0 or result.stdout != b"intrusive: ok\n" or result.stderr:
            raise RuntimeError(
                f"{name}: status {result.returncode}, stdout {result.stdout!r}, stderr {result.stderr!r}"
            )
    rng = random.Random(1010)
    rows = []
    for index in range(20):
        names = list(commands)
        rng.shuffle(names)
        rows.append({name: sample(commands[name]) for name in names})
        print(f"paired round {index + 1}/20", flush=True)
    if any(BASE.sha256(path) != expected for path, expected in hashes.items()):
        raise RuntimeError("a measured source, compiler, or tool changed during the run")
    report["samples_ns"] = rows
    report["summary"] = summarize(rows)
    BASE.save(output / "report.json", report)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
