#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare record field scanning and indexing through source checking."""

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "resource_measure", ROOT / "benchmarks/resources/measure.py"
)
HELPERS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPERS)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def workload(count):
    fields = "\n".join(f"    field{index:04}:u64;" for index in range(count))
    initializers = ",\n".join(f"        field{index:04}:{index + 1}u64" for index in range(count))
    reads = "\n".join(f"    total=total+select(value.field{index:04});" for index in range(count))
    return (
        f"record Fields {{\n{fields}\n}}\n"
        "fn select(item:u64)->u64 {return item;}\n"
        "fn select(item:i32)->i32 {return item;}\n"
        "fn main(argc:i32,argv:**u8)->i32 {\n"
        f"    var value:Fields=make Fields {{\n{initializers}\n    }};\n"
        "    var total:u64=0u64;\n" + reads + "\n"
        f"    if total!={count * (count + 1) // 2}u64 {{return 1i32;}}\n"
        "    return 0i32;\n}\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
    )
    parser.add_argument("--candidate", type=Path, default=Path("build/crust-overload"))
    parser.add_argument("--counts", default="64,256,1024,4096")
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--cpu", type=int, default=6)
    parser.add_argument("--work", type=Path, default=Path(".profile-cache/overload-fields"))
    parser.add_argument(
        "--output", type=Path, default=Path("build/benchmarks/overload/fields.json")
    )
    args = parser.parse_args()
    counts = [int(item) for item in args.counts.split(",")]
    if not counts or min(counts) < 1 or max(counts) > 9999 or args.rounds < 20 or args.warmup < 1:
        parser.error("require 1..9999 fields, at least 20 paired rounds, and at least one warmup")
    os.chdir(ROOT)
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("selected CPU is outside the process affinity mask")
    os.sched_setaffinity(0, {args.cpu})
    args.work.mkdir(parents=True, exist_ok=True)
    paths = [
        args.baseline,
        args.candidate,
        Path(__file__).relative_to(ROOT),
        Path("benchmarks/resources/measure.py"),
        Path("Makefile"),
        *sorted(Path("stages/overload").glob("*.crs")),
        *sorted(Path("stages/reader").glob("*.crs")),
        *sorted(Path("stages/c").glob("*.crs")),
        *sorted(Path("src").rglob("*.c")),
        *sorted(Path("src").rglob("*.h")),
        *sorted(Path("runtime").glob("*.c")),
        *sorted(Path("include").glob("*.h")),
        *sorted(Path("api").glob("*.crs")),
    ]
    delta = Path("benchmarks/overload/field-index.patch")
    if delta.is_file():
        paths.append(delta)
    frozen = {str(path): sha(path) for path in paths}
    cases = []
    for count in counts:
        path = args.work / f"fields-{count}.crs"
        path.write_text(workload(count))
        frozen[str(path)] = sha(path)
        commands = {
            "scan": [str(args.baseline), "--check", str(path)],
            "index": [str(args.candidate), "--check", str(path)],
        }
        for _ in range(args.warmup):
            for command in commands.values():
                result = HELPERS.run(command)
                if result.stdout or result.stderr:
                    raise RuntimeError(f"unexpected check output: {command}")
        cases.append(
            {
                "fields": count,
                "record_initializers": count,
                "field_reads": count,
                "source_bytes": path.stat().st_size,
                "source_sha256": sha(path),
                "source": str(path),
                "commands": commands,
                "scan_field_comparisons": count * (count + 1),
                "comparison_count_scope": "two ordered scans per field: initializer and field read; excludes other compiler work",
            }
        )
    print("Field workloads passed; starting paired check-only samples.", flush=True)
    rng = random.Random(20261002)
    for case in cases:
        samples = []
        observations = []
        orders = []
        for _ in range(args.rounds):
            order = ["scan", "index"]
            rng.shuffle(order)
            row = {}
            detail = {}
            for endpoint in order:
                observation = HELPERS.timed(case["commands"][endpoint])
                detail[endpoint] = observation
                row[endpoint] = observation["wall_ns"]
            orders.append(order)
            observations.append(detail)
            samples.append(row)
        case.update(
            {
                "samples_ns": samples,
                "observations": observations,
                "orders": orders,
                "median_ms": {
                    key: statistics.median(row[key] for row in samples) / 1e6
                    for key in ("scan", "index")
                },
                "index_to_scan": HELPERS.paired_stats(samples, "scan", "index", 20261002),
            }
        )
        print(case["fields"], case["median_ms"], case["index_to_scan"], flush=True)
    for path, expected in frozen.items():
        if sha(path) != expected:
            raise RuntimeError(f"input changed during timing: {path}; discard this run")
    report = {
        "schema_version": 1,
        "complete": True,
        "method": {
            "cpu": args.cpu,
            "paired_rounds": args.rounds,
            "warmup_per_endpoint": args.warmup,
            "seed": 20261002,
            "processes": "fresh per endpoint, one pinned worker, randomized order within each pair",
            "endpoint": "CRUST reader, source overload selection and mangling, seed semantic checking; no C emission",
            "excluded": "native compiler preparation and all target GCC compilation, assembly, linking, and execution",
            "cache": "warm filesystem cache; no source or semantic cache",
            "interval": "10000 bootstrap resamples of complete paired rounds, ratio-of-medians 95 percent interval",
            "host_noise": "CPU affinity is fixed; shared cache and machine-wide activity remain uncontrolled",
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_model": next(
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
        },
        "baseline": {
            "binary": str(args.baseline),
            "sha256": sha(args.baseline),
            "source_provenance": "saved binary before the three-file field-index change; no source manifest was captured at its build",
        },
        "candidate": {"binary": str(args.candidate), "sha256": sha(args.candidate)},
        "field_change": {
            "files": [
                "stages/overload/model.crs",
                "stages/overload/collect.crs",
                "stages/overload/resolve.crs",
            ],
            "description": "add a per-record field map, populate it once during collection with duplicate rejection, and replace the linear lookup",
            "patch": str(delta) if delta.is_file() else None,
        },
        "frozen_sha256": frozen,
        "workloads": cases,
        "claim_scope": "comparison of one field-lookup change; this experiment has no C compiler baseline and establishes no general C-speed result",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(args.output, flush=True)


if __name__ == "__main__":
    main()
