#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Test the single-worker gate before building a parallel stage scheduler."""

import argparse
import importlib.util
import json
import os
import random
import re
import resource
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

import workloads as cases

SPEC = importlib.util.spec_from_file_location(
    "source_order", Path(__file__).with_name("measure.py")
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
B = M.BASE
ROOT = M.ROOT


def summary(rows, seed):
    medians = {name: statistics.median(row[name]["wall_ns"] for row in rows) for name in rows[0]}
    ratios = {}
    for candidate, baselines in (("check", ("gcc", "clang")), ("handoff", ("clang_ir",))):

        def paired(sample, candidate=candidate, baselines=baselines):
            fastest = min(
                baselines,
                key=lambda name: statistics.median(row[name]["wall_ns"] for row in sample),
            )
            return statistics.median(
                row[candidate]["wall_ns"] / row[fastest]["wall_ns"] for row in sample
            )

        rng = random.Random(f"{seed}:{candidate}")
        draws = sorted(paired(rng.choices(rows, k=len(rows))) for _ in range(10000))
        interval = [B.percentile(draws, 0.025), B.percentile(draws, 0.975)]
        median = paired(rows)
        ratios[candidate] = {
            "median": median,
            "ci95": interval,
            "pass": median <= 1 and interval[1] <= 1,
        }
    return {"median_ms": {name: value / 1e6 for name, value in medians.items()}, "ratios": ratios}


def sample(command):
    start = resource.getrusage(resource.RUSAGE_CHILDREN)
    elapsed = B.measure(command)
    end = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "wall_ns": elapsed,
        "user_ns": round((end.ru_utime - start.ru_utime) * 1e9),
        "system_ns": round((end.ru_stime - start.ru_stime) * 1e9),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--perf", type=Path, help="Native perf executable for an untimed profile")
    args = parser.parse_args()
    if args.rounds < 20 or args.output.exists():
        parser.error("Use at least 20 rounds and a new output path")
    os.sched_setaffinity(0, {args.cpu})
    build = args.build.resolve()
    directory = Path(tempfile.mkdtemp(prefix="source-gate-", dir=build))
    workloads = M.workloads_in(directory, build / "crust-c-library.so")
    for workload in cases.generate(directory):
        staged = directory / (workload["name"] + "-staged.crs")
        M.staged_source(workload["paths"]["crust"], staged, build / "crust-c-library.so")
        workload["paths"]["staged"] = staged
        workloads.append(workload)
    binaries = {"launcher": build / "crust", "prepared": build / "crust-c"}
    inputs = M.source_hashes()
    inputs[str(Path(__file__).relative_to(ROOT))] = B.sha256(__file__)
    inputs[str(Path(cases.__file__).relative_to(ROOT))] = B.sha256(cases.__file__)
    inputs.update(
        {
            str(path): B.sha256(path)
            for path in [
                *binaries.values(),
                build / "crust-c-library.so",
                build / "libcrust0_host.a",
            ]
        }
    )
    tools = {
        name: B.tool_info(name)
        for name in ("gcc", "clang-20", "as", "ld", "objcopy", "/usr/bin/time")
    }
    if args.perf:
        tools[str(args.perf.resolve())] = B.tool_info(str(args.perf.resolve()))
    cc1 = Path(B.capture(["gcc", "-print-prog-name=cc1"])).resolve()
    inputs[str(cc1)] = B.sha256(cc1)
    installed = {
        str(path): M.artifact_info(path, path.suffix != ".a")
        for path in [
            *binaries.values(),
            build / "crust-c-library.so",
            build / "libcrust0_host.a",
            cc1,
        ]
    }
    result = {
        "revision": B.capture(["git", "rev-parse", "HEAD"]),
        "environment": B.environment(args.cpu),
        "command": sys.argv,
        "source_and_binary_hashes": inputs,
        "tools": tools,
        "installed_artifacts": installed,
        "method": {
            "rounds": args.rounds,
            "seed": 20261002,
            "bootstrap_draws": 10000,
            "starting_state": "Installed crust, crust-c, native C backend, and system tools; fresh root/context each process; one worker; no compilation-result cache; warm OS file cache",
            "check": "Fresh root, prelude and interface checks, native backend loading, target input and semantic checks, cleanup",
            "handoff": "All check work plus complete target C and native symbol files, including serialization",
            "baselines": "Check: fastest GCC or Clang syntax checks per paired resample. Handoff: Clang frontend IR with LLVM passes disabled, including textual IR serialization. Installed versions, no release-current coverage claim.",
            "backend_state": "Compiled backend is a toolchain input. Backend construction and automatic cache validation are separate measurements, not acceptance prerequisites.",
            "excluded": "Final target GCC compilation/linking, input generation, preflight correctness checks, and construction of installed compilers",
            "decision": "A failed one-worker case stops parallel scheduler expansion. This report covers only its listed workloads and selected raw language policy.",
            "resources": "Each timing sample includes child user/system CPU. One separate GNU time observation records per-process high-water RSS including waited-for children, not aggregate simultaneous RSS.",
        },
        "inputs": {},
        "commands": {},
        "preflight": {},
        "warmup": {},
        "samples": [],
    }
    for workload in workloads:
        name = workload["name"]
        commands, artifacts = M.preflight(workload, binaries, directory, build)
        output = directory / f"{name}-timed.c"
        response = directory / f"{name}-timed.rsp"
        options = ["--library"] if workload["library"] else []
        root_command = [str(binaries["launcher"]), str(workload["paths"]["staged"]), *options]
        selected = {
            "check": [*root_command, "--check"],
            "handoff": [*root_command, "--emit-c", "-o", str(output), "--symbols", str(response)],
            "gcc": commands["gcc-original-syntax"],
            "clang": ["clang-20", *commands["gcc-original-syntax"][1:]],
            "clang_ir": [
                "clang-20",
                *[flag for flag in commands["gcc-original-syntax"][1:] if flag != "-fsyntax-only"],
                "-S",
                "-emit-llvm",
                "-Xclang",
                "-disable-llvm-passes",
                "-o",
                str(directory / (name + ".ll")),
            ],
        }
        for command in selected.values():
            M.checked(command)
        llvm_ir = directory / (name + ".ll")
        if len(re.findall(r"^define ", llvm_ir.read_text(), re.M)) != workload["functions"]:
            raise RuntimeError("Clang omitted requested function bodies")
        artifacts["llvm_ir"] = M.file_info(llvm_ir)
        artifacts["input_counts"] = {
            "functions": workload["functions"],
            "crust_bytes": workload["paths"]["crust"].stat().st_size,
            "c_bytes": workload["paths"]["c"].stat().st_size,
        }
        artifacts["timed_outputs"] = {
            str(output): artifacts["c"]["sha256"],
            str(response): artifacts["rename_response"]["sha256"],
        }
        artifacts["resources"] = {}
        for route, command in selected.items():
            usage = directory / (name + "-" + route + ".usage")
            M.checked(["/usr/bin/time", "-o", str(usage), "-f", "%M", *command])
            artifacts["resources"][route] = {
                "max_rss_kib": int(usage.read_text()),
                "observations": 1,
            }
        result["inputs"][name] = {
            kind: M.file_info(path) for kind, path in workload["paths"].items()
        }
        result["preflight"][name] = artifacts
        result["preflight"][name]["all_routes_identical"] = True
        result["preflight"][name]["clang_headers"] = B.dependency_manifest(selected["clang"])
        result["commands"][name] = selected
        result["warmup"][name] = {route: sample(command) for route, command in selected.items()}
        print(f"preflight: {name}", flush=True)
    generated = {str(path): B.sha256(path) for path in directory.iterdir() if path.suffix == ".crs"}
    result["generated_hashes"] = generated
    result["root_sources"] = {
        str(workload["paths"]["staged"]): workload["paths"]["staged"].read_text()
        for workload in workloads
    }
    rng = random.Random(20261002)
    for index in range(args.rounds):
        order = list(result["commands"])
        rng.shuffle(order)
        for name in order:
            routes = list(result["commands"][name])
            rng.shuffle(routes)
            values = {route: sample(result["commands"][name][route]) for route in routes}
            result["samples"].append({"round": index, "workload": name, "values": values})
            for path, digest in result["preflight"][name]["timed_outputs"].items():
                if B.sha256(path) != digest:
                    raise RuntimeError(f"Output changed during measurement: {path}")
        print(f"paired round {index + 1}/{args.rounds}", flush=True)
    for path, expected in {**inputs, **generated}.items():
        assert B.sha256(path) == expected, f"input changed: {path}"
    for name, info in tools.items():
        assert B.tool_info(name) == info, f"tool changed: {name}"
    for path, info in installed.items():
        assert (
            M.artifact_info(Path(path), Path(path).suffix != ".a") == info
        ), f"installed artifact changed: {path}"
    for name, commands in result["commands"].items():
        facts = result["preflight"][name]
        assert (
            B.dependency_manifest(commands["gcc"])
            == facts["c_header_dependencies"]["gcc-original-syntax"]
        )
        assert B.dependency_manifest(commands["clang"]) == facts["clang_headers"]
    result["summary"] = {
        name: summary([row["values"] for row in result["samples"] if row["workload"] == name], name)
        for name in result["commands"]
    }
    result["single_worker_pass"] = all(
        item["pass"] for value in result["summary"].values() for item in value["ratios"].values()
    )
    if args.perf:
        path = directory / "backend.perf"
        command = [
            str(args.perf.resolve()),
            "record",
            "-q",
            "-e",
            "cycles:u",
            "-F",
            "499",
            "-o",
            str(path),
            "--",
            *result["commands"]["ordinary-8000"]["handoff"],
        ]
        M.checked(command, stdout=subprocess.DEVNULL)
        report_command = [
            str(args.perf.resolve()),
            "report",
            "--stdio",
            "--no-children",
            "--call-graph",
            "none",
            "--percent-limit",
            "1",
            "-i",
            str(path),
        ]
        result["profile"] = {
            "tool": tools[str(args.perf.resolve())],
            "command": command,
            "report_command": report_command,
            "report": M.checked(report_command).decode(),
            "data": M.file_info(path),
            "timing": "Separate untimed control after paired samples",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    B.save(args.output, result)
    print(json.dumps(result["summary"], indent=2))
    return 0 if result["single_worker_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
