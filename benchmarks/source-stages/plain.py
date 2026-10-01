#!/usr/bin/env python3
"""Compare two prepared compilers on plain source through complete assembly."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("measure", ROOT / "benchmarks/bootstrap/measure.py")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, default=Path("build/rmd0"))
    parser.add_argument("--before-revision", required=True)
    parser.add_argument("--cpu", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if Path.cwd() != ROOT or args.rounds < 25 or args.output.exists():
        parser.error("Run at the repository root with at least 25 rounds and a new output path")
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("The selected CPU is outside the allowed affinity set")
    os.sched_setaffinity(0, {args.cpu})
    cache = ROOT / ".profile-cache"
    cache.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="plain-source-", dir=cache))
    workloads = [BASE.generate(directory, count) for count in (1000, 8000)]
    workloads.append({"name": "intrusive", "library": False,
                      "paths": {"rmd": ROOT / "examples/intrusive/program.rmd"}})
    binaries = {"before": args.before.resolve(), "after": args.after.resolve()}
    hashes = {name: BASE.binary_info(path) for name, path in binaries.items()}
    commands = {workload["name"]: {
        name: [str(binary), str(workload["paths"]["rmd"]),
               *(["--library"] if workload["library"] else []), "-S"]
        for name, binary in binaries.items()} for workload in workloads}
    for name, routes in commands.items():
        outputs = []
        for command in routes.values():
            result = BASE.run_process(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode or result.stderr:
                raise RuntimeError(f"Compilation failed: {command}: {result.stderr!r}")
            outputs.append(result.stdout)
            BASE.measure(command)
        if outputs[0] != outputs[1]:
            raise RuntimeError(f"Plain source assembly differs: {name}")
    samples = []
    rng = random.Random(20261001)
    for index in range(args.rounds):
        names = list(commands)
        rng.shuffle(names)
        for name in names:
            routes = list(binaries)
            rng.shuffle(routes)
            row = {"round": index, "workload": name}
            for route in routes:
                row[route] = BASE.measure(commands[name][route])
            samples.append(row)
    summary = {}
    for name in commands:
        rows = [row for row in samples if row["workload"] == name]
        ratios = sorted(statistics.median(row["after"] / row["before"]
                        for row in rng.choices(rows, k=len(rows))) for _ in range(10000))
        summary[name] = {
            "before_ms": statistics.median(row["before"] for row in rows) / 1e6,
            "after_ms": statistics.median(row["after"] for row in rows) / 1e6,
            "median_paired_ratio": statistics.median(row["after"] / row["before"] for row in rows),
            "paired_bootstrap_95_ci": [BASE.percentile(ratios, .025), BASE.percentile(ratios, .975)]}
    for name, path in binaries.items():
        if BASE.binary_info(path) != hashes[name]:
            raise RuntimeError(f"Compiler changed during measurement: {name}")
    result = {"environment": BASE.environment(args.cpu), "before_revision": args.before_revision,
              "boundary": "Source-first plain RMD to complete assembly; no native assembly or linking; identical output bytes",
              "method": "Fresh processes; 25 or more randomized paired rounds; 10000 bootstrap draws; warm OS cache",
              "binaries": hashes, "commands": commands, "samples": samples, "summary": summary,
              "input_hashes": {workload["name"]: BASE.sha256(workload["paths"]["rmd"]) for workload in workloads},
              "source_sha256": BASE.compiler_sources()}
    BASE.save(args.output, result)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
