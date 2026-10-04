#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure local ownership checking in fresh compiled-driver processes."""

import argparse
import hashlib
import json
import os
import random
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(command):
    start = time.perf_counter_ns()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    elapsed = time.perf_counter_ns() - start
    if result.returncode:
        raise RuntimeError(f"{command}\n{result.stdout}{result.stderr}")
    fields = [int(x) for x in result.stderr.split()]
    if len(fields) not in (4, 5):
        raise RuntimeError(f"unexpected timing output: {result.stderr}")
    validation = fields.pop(0) if len(fields) == 5 else 0
    return dict(zip(("read_ns", "lower_ns", "check_ns", "emit_ns"), fields, strict=False)) | {
        "validation_ns": validation,
        "process_ns": elapsed,
        "frontend_ns": sum(fields),
    }


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(driver, work, name, client, provider, copies, pairs, rng, imported=None):
    declarations, body = client.read_text().split("fn main(", 1)
    source = work / f"{name}-{copies}.crs"
    source.write_text(declarations + "\n".join(f"fn workload_{i}(" + body for i in range(copies)))
    inputs = ["--library", str(source)]
    if provider:
        inputs = ["trusted", str(provider), *inputs]
    prefix = [str(driver)]
    if imported:
        prefix += ["import", *imported]
    commands = {mode: [*prefix, mode, *inputs] for mode in ("verify", "lower")}
    for command in commands.values():
        run(command)
    samples = []
    for _ in range(pairs):
        order = list(commands)
        rng.shuffle(order)
        samples.append({mode: run(commands[mode]) for mode in order})
    ratios = [x["verify"]["frontend_ns"] / x["lower"]["frontend_ns"] for x in samples]
    estimates = [statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(1000)]
    estimates.sort()
    return {
        "copies": copies,
        "commands": commands,
        "source_sha256": digest(source),
        "provider_sha256": digest(provider) if provider else None,
        "samples": samples,
        "median_frontend_ratio": statistics.median(ratios),
        "median_ratio_bootstrap_95_percent": [estimates[25], estimates[974]],
        "median_check_ns": statistics.median(x["verify"]["check_ns"] for x in samples),
        "median_verified_frontend_ns": statistics.median(
            x["verify"]["frontend_ns"] for x in samples
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--copies", type=int, default=64)
    parser.add_argument("--pairs", type=int, default=15)
    args = parser.parse_args()
    if args.copies < 1 or args.pairs < 5:
        parser.error("copies must be positive and pairs must be at least five")
    args.work.mkdir(parents=True, exist_ok=False)
    driver = args.build.resolve() / "ownership-cost"
    rng = random.Random(173)
    workloads = {
        "intrusive": ("examples/intrusive/program.crs", "examples/intrusive/links.crs"),
        "tree": ("examples/ownership-graphs/program.crs", "examples/ownership-graphs/provider.crs"),
        "handles": ("examples/ownership-basics/handles.crs", None),
        "views": ("examples/ownership-basics/views.crs", None),
    }
    report = {
        "driver_sha256": digest(driver),
        "build_command": "make build/ownership-cost",
        "build_flags": subprocess.check_output(
            ["make", "-s", "ownership-benchmark-config"], cwd=ROOT, text=True
        ).strip(),
        "compiler_version": subprocess.check_output(["cc", "--version"], text=True).splitlines()[0],
        "source_hashes": {
            str(p.relative_to(ROOT)): digest(p)
            for folder in ("stages", "api", "benchmarks/ownership")
            for p in (ROOT / folder).rglob("*")
            if p.suffix in (".crs", ".c", ".py")
        },
        "scope": "fresh compiled driver, read/lower/check/C emission; no target GCC or linking",
        "baseline": "same input and lowering with ownership verification omitted in benchmark only",
        "budget": 2.0,
        "pairs": args.pairs,
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "workloads": {},
    }
    passed = True
    for name, (client, provider) in workloads.items():
        results = [
            measure(
                driver,
                args.work.resolve(),
                name,
                ROOT / client,
                ROOT / provider if provider else None,
                args.copies * factor,
                args.pairs,
                rng,
            )
            for factor in (1, 2, 4)
        ]
        report["workloads"][name] = results
        passed = passed and all(x["median_frontend_ratio"] <= 2.0 for x in results)
        print(name, "ratios", [round(x["median_frontend_ratio"], 3) for x in results])
    cache = args.work.resolve() / "cache"
    cache.mkdir()
    checked = args.work.resolve() / "provider.crs"
    checked.write_text(
        "fn observed(owner:read Owner)->read i64 access(read,Graph) from owner {return owner_value(read owner);}"
    )
    publish = [
        str(driver),
        "publish",
        str(cache),
        str(ROOT / "examples/intrusive/links.crs"),
        str(checked),
    ]
    started = time.perf_counter_ns()
    result = subprocess.run(publish, cwd=ROOT, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr)
    publication_ns = time.perf_counter_ns() - started
    artifact, receipt = result.stderr.splitlines()
    report["independent_library"] = {
        "publication_command": publish,
        "publication_includes_target_gcc_ns": publication_ns,
        "client": measure(
            driver,
            args.work.resolve(),
            "imported-intrusive",
            ROOT / "examples/intrusive/program.crs",
            None,
            args.copies * 4,
            args.pairs,
            rng,
            [str(cache), artifact, receipt],
        ),
    }
    report["passed"] = passed
    (args.work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if not passed:
        raise SystemExit("ownership frontend budget exceeded")


if __name__ == "__main__":
    main()
