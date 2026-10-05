#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare captured native frontends on identical captured source bytes."""

import argparse
import hashlib
import json
import os
import random
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODES = {
    "raw": "raw",
    "opaque": "checked",
    "generic-raw": "generic",
    "generic": "checked",
    "arena": "checked",
}
PHASES = ("read_ns", "check_ns", "emit_ns")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(directory):
    report = directory / "report.json"
    recorded = json.loads(report.read_text())
    driver = directory / "driver"
    assert digest(driver) == recorded["binary_sha256"][str(driver.relative_to(ROOT))], driver
    return {
        "directory": str(directory.relative_to(ROOT)),
        "report_sha256": digest(report),
        "driver_sha256": digest(driver),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--rounds", type=int, default=40)
    args = parser.parse_args()
    directories = {"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()}
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build") or args.rounds < 20:
        parser.error("use a new output directory under build/ and at least twenty rounds")
    captures = {label: capture(path) for label, path in directories.items()}
    output.mkdir(parents=True)
    os.sched_setaffinity(0, {args.cpu})
    inputs = output / "inputs"
    inputs.mkdir()
    reference = directories["baseline"]
    hashes = {}
    for name in (*MODES, "arena-checked"):
        source = reference / f"{name}.crs"
        saved = inputs / source.name
        saved.write_bytes(source.read_bytes())
        hashes[source.name] = digest(saved)
    rng = random.Random(0)
    samples, commands = [], []
    for _ in range(args.rounds):
        order = [(mode, label) for mode in MODES for label in directories]
        rng.shuffle(order)
        sample = {mode: {} for mode in MODES}
        for mode, label in order:
            c_output, symbols = output / f"{label}-{mode}.c", output / f"{label}-{mode}.rsp"
            command = [
                directories[label] / "driver",
                MODES[mode],
                "*",
                inputs / f"{mode}.crs",
                c_output,
                symbols,
            ]
            if mode == "arena":
                command.append(inputs / "arena-checked.crs")
            command = list(map(str, command))
            if command not in commands:
                commands.append(command)
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError(f"{command}\n{result.stdout}{result.stderr}")
            sample[mode][label] = dict(zip(PHASES, map(int, result.stdout.split()), strict=True))
            for actual in (c_output, symbols):
                expected = reference / (mode + actual.suffix)
                assert actual.read_bytes() == expected.read_bytes(), (label, mode, actual)
        samples.append(sample)
    summary = {}
    for mode in MODES:
        ratios = [
            sum(s[mode]["candidate"].values()) / sum(s[mode]["baseline"].values()) for s in samples
        ]
        estimates = sorted(
            statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(2000)
        )
        summary[mode] = {
            "candidate_baseline_ratio": statistics.median(ratios),
            "bootstrap_95": [estimates[50], estimates[1949]],
            "phase_median_ns": {
                label: {
                    phase: statistics.median(s[mode][label][phase] for s in samples)
                    for phase in PHASES
                }
                for label in directories
            },
        }
    report = {
        "captures": captures,
        "input_sha256": hashes,
        "cpu": args.cpu,
        "commands": commands,
        "samples": samples,
        "summary": summary,
        "emitted_bytes_equal": True,
        "tool_sha256": digest(Path(__file__)),
        "scope": "paired fresh native processes on fixed inputs; read/check/emission timers; GCC, linking, IO and setup excluded",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
