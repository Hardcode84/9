#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare native resource compilers on shared cleanup and early exits."""

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

from measure import ROOT, stress_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command):
    start = time.perf_counter_ns()
    result = subprocess.run(list(map(str, command)), cwd=ROOT, capture_output=True, timeout=120)
    elapsed = time.perf_counter_ns() - start
    if result.returncode or result.stderr:
        raise RuntimeError(f"{command}\n{result.stdout!r}\n{result.stderr!r}")
    return elapsed, result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--rounds", type=int, default=20)
    args = parser.parse_args()
    work = args.output.resolve()
    if work.exists() or not work.is_relative_to(ROOT / "build") or args.rounds < 20:
        parser.error("use a new directory under build/ and at least twenty rounds")
    work.mkdir(parents=True)
    os.sched_setaffinity(0, {args.cpu})
    compilers = {}
    report = {"compilers": {}, "cases": {}}
    for name, original in (("baseline", args.baseline), ("candidate", args.candidate)):
        original = original.resolve()
        saved = work / name
        shutil.copy2(original, saved)
        compilers[name] = saved
        report["compilers"][name] = {
            "source": str(original),
            "capture": str(saved),
            "sha256": digest(saved),
        }
    rng = random.Random(0)
    for count in (16, 64, 256):
        text, _, expected = stress_source(count)
        source = work / f"owners-{count}.crs"
        source.write_text(text)
        commands, samples, sizes, hashes = {}, [], {}, {}
        for name, compiler in compilers.items():
            output = work / f"{name}-{count}.c"
            commands[name] = list(map(str, [compiler, "--emit-c", "-o", output, source]))
            run(commands[name])
            sizes[name] = output.stat().st_size
            hashes[name] = digest(output)
            binary = work / f"{name}-{count}"
            run([compiler, "-o", binary, source])
            _, actual = run([binary])
            if actual != expected:
                raise RuntimeError(f"{binary}: expected {expected!r}, got {actual!r}")
        for _ in range(args.rounds):
            order = list(compilers)
            rng.shuffle(order)
            samples.append({name: run(commands[name])[0] for name in order})
        ratios = [sample["candidate"] / sample["baseline"] for sample in samples]
        estimates = sorted(
            statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(2000)
        )
        report["cases"][str(count)] = {
            "input_sha256": digest(source),
            "commands": commands,
            "samples_ns": samples,
            "output_bytes": sizes,
            "output_sha256": hashes,
            "candidate_baseline_ratio": statistics.median(ratios),
            "bootstrap_95": [estimates[50], estimates[1949]],
        }
    report["boundary"] = (
        "fresh native process through complete C output; target compilation and execution checked outside timing"
    )
    (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    for count, case in report["cases"].items():
        print(count, case["candidate_baseline_ratio"], case["bootstrap_95"], case["output_bytes"])


if __name__ == "__main__":
    main()
