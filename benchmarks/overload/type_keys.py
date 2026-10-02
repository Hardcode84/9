#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure exact overload lookup as type names and call counts grow."""

import argparse
import hashlib
import json
import os
import random
import statistics
import subprocess
import time
from pathlib import Path


def source(name_size, calls, overloaded):
    name = "R" + "x" * (name_size - 1)
    scalar = "take" if overloaded else "take_scalar"
    return (
        f"record {name}{{value:u64;}}\n"
        f"fn take(node:*{name})->unit{{(*node).value=(*node).value+1u64;}}\n"
        f"fn {scalar}(number:u64)->unit{{}}\n"
        "fn main(argc:i32,argv:**u8)->i32{\n"
        f"var node:{name}=make {name}{{value:0u64}};var cursor:*{name}=&node;\n"
        + "take(cursor);\n" * calls
        + f"if node.value!={calls}u64{{return 1i32;}}return 0i32;}}\n"
    )


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command):
    start = time.perf_counter_ns()
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
    if result.returncode or result.stderr:
        raise RuntimeError(f"{command}: {result.returncode}: {result.stderr!r}")
    return (time.perf_counter_ns() - start) / 1e6


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", default="build/crust-overload")
    parser.add_argument("--plain", default="build/crust-c")
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--work", type=Path, default=Path("build/overload-type-keys"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 20:
        parser.error("at least 20 paired samples are required")
    os.sched_setaffinity(0, {args.cpu})
    args.work.mkdir(parents=True, exist_ok=True)
    binaries = dict(before=args.before, after=args.after, plain=args.plain)
    report = {
        "cpu": args.cpu,
        "method": "Fresh processes, two warmups, shuffled paired rounds; --check only. "
        "Plain uses the Crust C driver without overloads, not a C compiler baseline. "
        "Target GCC compilation and execution are separate validation, excluded from samples.",
        "binaries": {
            key: {"path": value, "sha256": digest(value)} for key, value in binaries.items()
        },
        "script_sha256": digest(__file__),
        "workloads": [],
    }
    rng = random.Random(7123)
    for length, calls in ((8, 20000), (8192, 20000), (2000, 2000), (8000, 8000), (32000, 32000)):
        sources = {}
        for label, overloaded in (("overload", True), ("plain", False)):
            path = args.work / f"{length}-{calls}-{label}.crs"
            path.write_text(source(length, calls, overloaded))
            sources[label] = path
        commands = {
            key: [binary, "--check", str(sources["plain" if key == "plain" else "overload"])]
            for key, binary in binaries.items()
        }
        samples = {key: [] for key in commands}
        for iteration in range(args.repeats + 2):
            order = list(commands)
            rng.shuffle(order)
            for key in order:
                elapsed = run(commands[key])
                if iteration >= 2:
                    samples[key].append(elapsed)
        medians = {key: statistics.median(values) for key, values in samples.items()}
        output = args.work / f"{length}-{calls}-program"
        run([args.after, "--cflag=-O0", "-o", str(output), str(sources["overload"])])
        run([str(output)])
        report["workloads"].append(
            dict(
                name_bytes=length,
                calls=calls,
                sources={str(path): digest(path) for path in sources.values()},
                commands=commands,
                samples_ms=samples,
                median_ms=medians,
                runtime="counter equals call count",
            )
        )
        print(length, calls, medians, flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
