#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare fresh compiler processes, elapsed time, RSS, and minor faults."""

import argparse
import json
import os
import random
import statistics
import time
from pathlib import Path

import measure


def sample(command):
    start = time.perf_counter_ns()
    result = measure.run_process(
        ["/usr/bin/time", "-f", "%M %R %U %S", *command],
        stdout=measure.subprocess.DEVNULL,
        stderr=measure.subprocess.PIPE,
        text=True,
    )
    elapsed = time.perf_counter_ns() - start
    result.check_returncode()
    rss, faults, user, system = result.stderr.split()
    return dict(
        wall_ns=elapsed,
        rss_kib=int(rss),
        minor_faults=int(faults),
        user_s=float(user),
        system_s=float(system),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--pairs", type=int, default=20)
    parser.add_argument("--prefix", type=Path, help="execute each compiler through this program")
    args = parser.parse_args()
    os.sched_setaffinity(0, {args.cpu})
    rng = random.Random(12345)
    report = dict(
        environment=measure.environment(args.cpu),
        compiler_sources=measure.compiler_sources(),
        generator_sha256=measure.sha256("benchmarks/bootstrap/measure.py"),
        runner_sha256=measure.sha256(__file__),
        binaries={},
        samples=[],
        medians=[],
    )
    prefix = [str(args.prefix)] if args.prefix else []
    if args.prefix:
        report["prefix"] = measure.binary_info(args.prefix)
    for label in ("before", "after"):
        directory = getattr(args, label)
        report["binaries"][label] = {
            name: measure.binary_info(directory / name) for name in ("crust0", "crust-c")
        }
    for count in (8000, 32000, 64000):
        workload = measure.generate(args.work, count)
        path = workload["paths"]["crust"]
        for endpoint, binary, option in (
            ("check", "crust0", "--check"),
            ("assembly", "crust0", "-S"),
            ("c-prepare", "crust-c", "--prepare"),
        ):
            commands = {
                label: [*prefix, str(getattr(args, label) / binary), "--library", option, str(path)]
                for label in ("before", "after")
            }
            for command in commands.values():
                for _ in range(2):
                    sample(command)
            samples = []
            for pair in range(args.pairs):
                labels = list(commands)
                rng.shuffle(labels)
                for label in labels:
                    samples.append(dict(pair=pair, label=label, **sample(commands[label])))
            report["samples"].append(
                dict(
                    functions=count,
                    endpoint=endpoint,
                    commands=commands,
                    input_sha256=measure.sha256(path),
                    values=samples,
                )
            )
            medians = dict(functions=count, endpoint=endpoint)
            for label in commands:
                medians[label] = {
                    field: statistics.median(s[field] for s in samples if s["label"] == label)
                    for field in ("wall_ns", "rss_kib", "minor_faults", "user_s", "system_s")
                }
            report["medians"].append(medians)
            print(json.dumps(medians), flush=True)
            measure.save(args.output, report)


if __name__ == "__main__":
    main()
