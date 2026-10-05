#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the bounded AST layout experiment without changing the production ABI."""

import argparse
import hashlib
import importlib.util
import json
import os
import random
import shutil
import statistics
import time
from pathlib import Path

from layout import ROOT, command, member_paths, prototype, rewrite_members
from report import describe, migration_probe

STRICT = "-std=c99 -pedantic-errors -Wall -Wextra -Werror -Wstrict-prototypes -Wmissing-prototypes -Wshadow -Wvla".split()
FLAGS = [*STRICT, "-O2", "-g"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "bootstrap_measure", ROOT / "benchmarks/bootstrap/measure.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(path):
    path.mkdir()
    for directory in ("include", "src", "tools", "api"):
        shutil.copytree(
            ROOT / directory, path / directory, ignore=shutil.ignore_patterns("__pycache__")
        )
    shutil.copyfile(ROOT / "benchmarks/ast-layout/driver.c", path / "driver.c")
    (path / "tests").mkdir()
    shutil.copyfile(ROOT / "tests/read_test.c", path / "tests/read_test.c")
    (path / "stages/asm").mkdir(parents=True)
    shutil.copyfile(ROOT / "stages/asm/model.crs", path / "stages/asm/model.crs")
    command(["python3", "tools/api.py", "--check"], cwd=path)
    command(["python3", "tools/amalgamate.py"], cwd=path)


def compile_driver(path, cc, sanitize=False, split=False):
    binary = path / ("check-sanitize" if sanitize else "check-split" if split else "check")
    core = ["src/core.c", "src/read.c", "src/check.c"] if split else ["crust0_amalg.c"]
    flags = (
        ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-no-pie"] if sanitize else []
    )
    args = [
        cc,
        *FLAGS,
        *flags,
        "-Iinclude",
        "-Isrc",
        *core,
        "src/profile_linux_x64.c",
        "driver.c",
        "-o",
        str(binary),
    ]
    command(args, cwd=path)
    return binary, args


def workloads(directory):
    generator = load_generator()
    result = {}
    for count in (1000, 8000, 16000, 32000, 64000):
        item = generator.generate(directory, count)
        result[item["name"]] = [item["paths"]["crust"]]
    paths = (
        command(
            [
                "make",
                "-s",
                "--no-print-directory",
                "--eval",
                'ast-inputs:;@printf "%s\\n" $(C_STAGE)',
                "ast-inputs",
            ],
            cwd=ROOT,
        )
        .decode()
        .splitlines()
    )
    stage = directory / "stage"
    stage.mkdir()
    result["c-stage"] = []
    for index, name in enumerate(paths):
        target = stage / f"{index}-{Path(name).name}"
        shutil.copyfile(ROOT / name, target)
        result["c-stage"].append(target)
    return result


def validate(snapshot_path, binary, clang, cc, candidate):
    test = snapshot_path / "tests/read_test.c"
    if candidate:
        # Obtain field IDs and source locations against the unchanged header.
        text, _count = rewrite_members(
            test, snapshot_path.parent / "baseline/include", clang, member_paths()
        )
        test.write_text(text)
    args = [
        cc,
        *FLAGS,
        "-Iinclude",
        "-Isrc",
        "crust0_amalg.c",
        "src/profile_linux_x64.c",
        "tests/read_test.c",
        "-o",
        "reader-test",
    ]
    command(args, cwd=snapshot_path)
    command([str(snapshot_path / "reader-test")])
    for source in ("tests/runtime.crs", "examples/intrusive/raw.crs"):
        command([str(binary), str(ROOT / source)])


def sample(binary, paths, output):
    invocation = [str(binary), *map(str, paths)]
    started = time.perf_counter_ns()
    command(["/usr/bin/time", "-f", "%M", "-o", str(output), *invocation])
    return {"elapsed_ns": time.perf_counter_ns() - started, "rss_kib": int(output.read_text())}


def summarize(rows, rng):
    result = {}
    for metric in ("elapsed_ns", "rss_kib"):
        ratios = [row["candidate"][metric] / row["baseline"][metric] for row in rows]
        draws = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(10000))
        result[metric] = {
            "baseline_median": statistics.median(row["baseline"][metric] for row in rows),
            "candidate_median": statistics.median(row["candidate"][metric] for row in rows),
            "median_paired_ratio": statistics.median(ratios),
            "paired_bootstrap_95_ci": [draws[249], draws[9749]],
        }
    return result


def histograms(binaries, inputs):
    result = {}
    for name, paths in inputs.items():
        result[name] = {}
        for mode, binary in binaries.items():
            result[name][mode] = json.loads(command([str(binary), "--histogram", *map(str, paths)]))
        for family in ("CrustExpr", "CrustStmt", "CrustDecl", "CrustTypeSyntax"):
            if (
                result[name]["baseline"][family]["counts"]
                != result[name]["candidate"][family]["counts"]
            ):
                raise RuntimeError(f"AST counts differ: {name} {family}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new directory under build/")
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument(
        "--clang", default="clang-20", help="source-location tool, outside timed work"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build") or args.rounds < 20:
        parser.error("use a new directory under build/ and at least 20 rounds")
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("CPU is outside the allowed affinity set")
    output.mkdir(parents=True)
    (output / "experiment").mkdir()
    for path in (ROOT / "benchmarks/ast-layout").glob("*.py"):
        shutil.copyfile(path, output / "experiment" / path.name)
    shutil.copyfile(
        ROOT / "benchmarks/bootstrap/measure.py", output / "experiment/bootstrap-measure.py"
    )
    inputs = workloads(output / "inputs")
    binaries = {}
    builds = {}
    for mode in ("baseline", "candidate"):
        path = output / mode
        snapshot(path)
        if mode == "candidate":
            (output / "rewrites.json").write_text(
                json.dumps(prototype(path, args.clang), indent=2) + "\n"
            )
        binaries[mode], builds[mode] = compile_driver(path, args.cc)
        validate(path, binaries[mode], args.clang, args.cc, mode == "candidate")
        sanitized, _args = compile_driver(path, args.cc, sanitize=True)
        split, _args = compile_driver(path, args.cc, split=True)
        for binary in (sanitized, split):
            for case in ("ordinary-1000", "c-stage"):
                command([str(binary), *map(str, inputs[case])])
        print(
            f"{mode}: built; reader, seed examples, split build, and sanitizers passed", flush=True
        )
    distribution = histograms(binaries, inputs)
    (output / "histograms.json").write_text(json.dumps(distribution, indent=2) + "\n")
    (output / "node-bytes.json").write_text(
        json.dumps(describe(distribution, output / "baseline/include/crust0.h"), indent=2) + "\n"
    )
    hashes = {str(path): digest(path) for paths in inputs.values() for path in paths}
    hashes.update({str(path): digest(path) for path in binaries.values()})
    for mode in binaries:
        for directory in ("include", "src"):
            hashes.update(
                {
                    str(path): digest(path)
                    for path in (output / mode / directory).rglob("*")
                    if path.is_file()
                }
            )
        for name in ("driver.c", "crust0_amalg.c"):
            path = output / mode / name
            hashes[str(path)] = digest(path)
    hashes.update({str(path): digest(path) for path in (output / "experiment").iterdir()})
    os.sched_setaffinity(0, {args.cpu})
    rng = random.Random(20261005)
    rows = []
    for round_index in range(args.rounds):
        names = list(inputs)
        rng.shuffle(names)
        for name in names:
            modes = list(binaries)
            rng.shuffle(modes)
            row = {"round": round_index, "workload": name}
            for mode in modes:
                row[mode] = sample(binaries[mode], inputs[name], output / "rss.txt")
            rows.append(row)
        print(f"paired round {round_index + 1}/{args.rounds}", flush=True)
    summary = {
        name: summarize([row for row in rows if row["workload"] == name], rng) for name in inputs
    }
    migration = migration_probe(
        output / "migration", binaries["baseline"], output / "candidate", inputs["c-stage"]
    )
    if any(digest(Path(path)) != expected for path, expected in hashes.items()):
        raise RuntimeError("a captured input, source, or executable changed during the run")
    report = {
        "revision": command(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        "environment": load_generator().environment(args.cpu),
        "tools": {
            tool: command([tool, "--version"]).decode().splitlines()[0]
            for tool in (args.cc, args.clang)
        },
        "tool_hashes": {
            tool: digest(Path(shutil.which(tool)))
            for tool in (args.cc, args.clang, "/usr/bin/time")
        },
        "builds": builds,
        "inputs": {name: list(map(str, paths)) for name, paths in inputs.items()},
        "hashes": hashes,
        "boundary": "process start, source loading, read/collect/resolve/check, destruction; no backend or target toolchain; histogram is a separate run",
        "samples": rows,
        "summary": summary,
        "memory_gate": all(
            summary[name]["rss_kib"]["median_paired_ratio"] <= 0.60
            for name in ("ordinary-64000", "c-stage")
        ),
        "time_gate": all(
            value["elapsed_ns"]["paired_bootstrap_95_ci"][1] <= 1.02 for value in summary.values()
        ),
        "migration": migration,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if not (report["memory_gate"] and report["time_gate"] and migration["passed"]):
        print("STOP: a gate failed; keep the production ABI. See report.json and migration/.")
        return 2
    print("Measurement gates passed; review the source and stage contract before integration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
