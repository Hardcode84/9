#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare two compiled ownership drivers on identical tutorial inputs."""

import argparse
import hashlib
import json
import os
import random
import statistics
import subprocess
from pathlib import Path

from measure import ROOT, WORKLOADS, digest, run


def compare(commands, pairs, rng):
    for command in commands.values():
        run(command)
    samples = []
    for _ in range(pairs):
        order = list(commands)
        rng.shuffle(order)
        samples.append({side: run(commands[side]) for side in order})
    ratios = {}
    for metric in ("check_ns", "frontend_ns"):
        values = [row["candidate"][metric] / row["baseline"][metric] for row in samples]
        estimates = sorted(statistics.median(rng.choices(values, k=pairs)) for _ in range(1000))
        ratios[metric] = {
            "median": statistics.median(values),
            "bootstrap_95_percent": [estimates[25], estimates[974]],
        }
    return {"commands": commands, "samples": samples, "ratios": ratios}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--baseline-revision", required=True)
    parser.add_argument("--candidate", type=Path, default=ROOT / "build/ownership-cost")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--copies", type=int, default=64)
    parser.add_argument("--pairs", type=int, default=20)
    args = parser.parse_args()
    if args.pairs < 20 or args.copies < 1:
        parser.error("pairs must be at least twenty and copies must be positive")
    args.work = args.work.resolve()
    args.work.mkdir(parents=True, exist_ok=False)
    drivers = {"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()}
    report = {
        "scope": "Compiled drivers: read, lower, verify, emit C; no target GCC or linking",
        "baseline_revision": args.baseline_revision,
        "candidate_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "candidate_diff_sha256": hashlib.sha256(
            subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)
        ).hexdigest(),
        "candidate_source_hashes": {
            str(path.relative_to(ROOT)): digest(path)
            for folder in ("stages", "api", "benchmarks/ownership")
            for path in (ROOT / folder).rglob("*.crs")
        },
        "driver_hashes": {side: digest(path) for side, path in drivers.items()},
        "build_command": "make build/ownership-cost",
        "build_flags": subprocess.check_output(
            ["make", "-s", "ownership-benchmark-config"], cwd=ROOT, text=True
        ).strip(),
        "compiler": subprocess.check_output(["cc", "--version"], text=True).splitlines()[0],
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "pairs": args.pairs,
        "workloads": {},
    }
    rng = random.Random(173)
    for name, (client, provider) in WORKLOADS.items():
        declarations, body = (ROOT / client).read_text().split("fn main(", 1)
        for copies in (args.copies, args.copies * 2, args.copies * 4):
            source = args.work / f"{name}-{copies}.crs"
            source.write_text(
                declarations + "\n".join(f"fn workload_{i}(" + body for i in range(copies))
            )
            inputs = ["trusted", str(ROOT / provider)] if provider else []
            commands = {
                side: [str(driver), "verify", *inputs, "--library", str(source)]
                for side, driver in drivers.items()
            }
            row = compare(commands, args.pairs, rng)
            row.update(
                source_sha256=digest(source),
                provider_sha256=digest(ROOT / provider) if provider else None,
            )
            report["workloads"][f"{name}-{copies}"] = row
            print(
                name,
                copies,
                {key: round(value["median"], 3) for key, value in row["ratios"].items()},
                flush=True,
            )
    (args.work / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
