#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure native frontend plus text emission separately from LLVM tools."""

import argparse
import hashlib
import json
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def measure(command, runs):
    samples = []
    for _ in range(runs):
        start = time.perf_counter_ns()
        subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
        samples.append(time.perf_counter_ns() - start)
    return {
        "command": list(map(str, command)),
        "samples_ns": samples,
        "median_ns": statistics.median(samples),
    }


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--llvm", type=Path)
    parser.add_argument("--runs", type=int, default=15)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    build = args.build.resolve()
    work = build / "llvm-measure"
    work.mkdir(exist_ok=True)
    llvm = args.llvm
    if llvm is None:
        llvm = Path(
            subprocess.check_output(
                ["python3", "tools/fetch_llvm.py", "release", "--locked"], cwd=ROOT
            )
            .decode()
            .strip()
        )
    llvm = llvm.resolve()
    report = {"runs": args.runs, "driver_sha256": digest(build / "resource-backends"), "cases": {}}
    cases = {
        "intrusive": (
            "ownership",
            ["trusted", "examples/intrusive/links.crs"],
            ["examples/intrusive/program.crs"],
        ),
        "sqlite": (
            "resources",
            [],
            ["examples/resources/sqlite/library.crs", "examples/resources/sqlite/program.crs"],
        ),
    }
    for name, (mode, options, inputs) in cases.items():
        entry = {
            "frontend_and_text": {},
            "inputs": {path: digest(ROOT / path) for path in [*inputs, *options[1:]]},
        }
        report["cases"][name] = entry
        for backend, suffix in (("c", "c"), ("llvm", "ll")):
            output = work / f"{name}.{suffix}"
            command = [
                build / "resource-backends",
                backend,
                mode,
                *options,
                "--emit",
                "-o",
                output,
                *inputs,
            ]
            result = measure(command, args.runs)
            result.update(output_sha256=digest(output), output_bytes=output.stat().st_size)
            entry["frontend_and_text"][backend] = result
        ir = work / f"{name}.ll"
        entry["llvm_tools"] = {
            "parse_verify": measure(
                [llvm / "bin/llvm-as", ir, "-o", work / "verified.bc"], args.runs
            ),
            "parse_optimize_codegen": measure(
                [
                    llvm / "bin/clang",
                    "--no-default-config",
                    "-O2",
                    "-x",
                    "ir",
                    "-c",
                    ir,
                    "-o",
                    work / "target.o",
                ],
                args.runs,
            ),
        }
    report["clang_sha256"] = digest(llvm / "bin/clang")
    report["llvm_as_sha256"] = digest(llvm / "bin/llvm-as")
    (work / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(work / "result.json")


if __name__ == "__main__":
    main()
