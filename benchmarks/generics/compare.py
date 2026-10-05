#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare frozen native generics drivers on ownership and standalone inputs."""

import argparse
import json
import os
import random
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import generics_cost as pair_cost  # noqa: E402
import ownership_generics_cost as ownership_cost  # noqa: E402


def interval(ratios):
    rng = random.Random(123)
    medians = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(10000))
    return {"median": statistics.median(ratios), "ci95": [medians[250], medians[9749]]}


def ownership_run(binary, inputs, work, label):
    return [
        str(binary),
        "generic",
        "measured",
        str(work / f"{label}.c"),
        str(work / f"{label}.rsp"),
        *map(str, inputs["generic"]),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "pair-before", "pair-after", "work"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--cpu", type=int, required=True)
    args = parser.parse_args()
    if args.samples < 20:
        parser.error("at least twenty pairs are required")
    work = args.work.resolve()
    if work.exists() or not work.is_relative_to(ROOT / "build"):
        parser.error("select a new directory under build/")
    os.sched_setaffinity(0, {args.cpu})
    work.mkdir(parents=True)
    before, after = args.before.resolve(), args.after.resolve()
    inputs = {
        mode: [before / "inputs" / f"{name}.crs" for name in names]
        for mode, names in ownership_cost.INPUTS.items()
    }
    binaries = {
        "before": before / "ownership-generics-cost",
        "after": after / "ownership-generics-cost",
    }
    checks = {}
    for label, binary in binaries.items():
        output = work / label
        output.mkdir()
        result = ownership_cost.run_samples(
            SimpleNamespace(samples=1, sanitize=False), output, binary, inputs
        )
        checks[label] = {
            "commands": result[0],
            "erasure": result[1],
            "layouts": result[2],
            "functions": result[4],
        }
    for mode in inputs:
        for suffix in ("c", "rsp"):
            if (work / "before" / f"{mode}.{suffix}").read_bytes() != (
                work / "after" / f"{mode}.{suffix}"
            ).read_bytes():
                raise RuntimeError(f"candidate changed emitted {mode} {suffix}")
    commands = {
        label: ownership_run(binary, inputs, work, label) for label, binary in binaries.items()
    }
    pair_inputs = [
        args.pair_before.resolve() / "inputs" / f"{name}.crs"
        for name in ("types", "pair", "program", "handwritten")
    ]
    pair_commands = {
        label: [str(folder.resolve() / "generics-cost"), *map(str, pair_inputs), "500"]
        for label, folder in (("before", args.pair_before), ("after", args.pair_after))
    }
    samples = []
    rng = random.Random(0)
    for _ in range(args.samples):
        order = ["before", "after"]
        rng.shuffle(order)
        row = {"ownership": {}, "pair": {}}
        for label in order:
            metrics, _, _ = ownership_cost.measure(commands[label])
            row["ownership"][label] = metrics
        rng.shuffle(order)
        for label in order:
            row["pair"][label] = pair_cost.sample(pair_commands[label], 500)
        samples.append(row)
    comparisons = {}
    for case, fields in (
        ("ownership", ("frontend_ns", "emit_ns", "process_wall_ns")),
        ("pair", ("generic_frontend_ns", "handwritten_frontend_ns")),
    ):
        comparisons[case] = {
            field: interval(
                [row[case]["after"][field] / row[case]["before"][field] for row in samples]
            )
            for field in fields
        }
    phases = {
        label: {
            field: statistics.median(row["ownership"][label][field] for row in samples)
            for field in (
                *ownership_cost.PHASES,
                *ownership_cost.METRICS,
                "frontend_ns",
                "process_wall_ns",
            )
        }
        for label in binaries
    }
    report = {
        "scope": "Compiled native stages; fresh ownership compiler processes. frontend_ns includes parsing through ownership checks. emit_ns is C buffer emission. process_wall_ns includes complete emission, symbol handoff and file writes, plus startup, input IO, reporting and teardown. Standalone samples contain 500 fresh context pairs. Target GCC and linking are untimed correctness checks. Stage preparation is recorded separately. No artifact cache lookup is selected.",
        "cpu": args.cpu,
        "commands": commands,
        "pair_commands": pair_commands,
        "preparation": {
            label: json.loads((directory / "preparation.json").read_text())
            for label, directory in (
                ("before", before),
                ("after", after),
                ("pair-before", args.pair_before),
                ("pair-after", args.pair_after),
            )
        },
        "hashes": {
            str(path): pair_cost.fingerprint(path)
            for path in [
                *binaries.values(),
                *(Path(cmd[0]) for cmd in pair_commands.values()),
                *pair_inputs,
                *(path for group in inputs.values() for path in group),
            ]
        },
        "checks": checks,
        "samples": samples,
        "comparisons": comparisons,
        "median_ownership": phases,
    }
    report["frontend_improved"] = comparisons["ownership"]["frontend_ns"]["ci95"][1] < 1
    report["standalone_regressed"] = comparisons["pair"]["generic_frontend_ns"]["ci95"][0] > 1
    (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "comparisons": comparisons,
                "frontend_improved": report["frontend_improved"],
                "standalone_regressed": report["standalone_regressed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
