#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare two cold native builds with GCC and Clang on frozen target inputs."""

import argparse
import gzip
import importlib.util
import json
import os
import random
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(root):
    spec = importlib.util.spec_from_file_location(
        "native_measure", root / "benchmarks/native/measure.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


N = load(ROOT)
M = N.M
B = M.BASE


def ratio(rows, candidate, baselines):
    def paired(sample):
        fastest = min(
            baselines, key=lambda name: statistics.median(r[name]["cold_ns"] for r in sample)
        )
        return statistics.median(r[candidate]["cold_ns"] / r[fastest]["cold_ns"] for r in sample)

    rng = random.Random(20261002)
    draws = sorted(paired(rng.choices(rows, k=len(rows))) for _ in range(10000))
    median = paired(rows)
    interval = [B.percentile(draws, 0.025), B.percentile(draws, 0.975)]
    return {"median": median, "ci95": interval, "pass": median <= 1 and interval[1] <= 1}


def snapshot(root, build):
    module = load(root)
    inputs = module.M.source_hashes()
    inputs["examples/native/main.crs"] = B.sha256(root / "examples/native/main.crs")
    artifacts = {
        name: M.artifact_info(build / name, not name.endswith(".a"))
        for name in ("crust", "crust0", "crust-c-library.so", "libcrust0.a", "libcrust0_host.a")
    }
    return {"root": str(root), "build": str(build), "sources": inputs, "artifacts": artifacts}


def verify_snapshot(frozen):
    root = Path(frozen["root"])
    build = Path(frozen["build"])
    for path, digest in frozen["sources"].items():
        if B.sha256(root / path) != digest:
            raise RuntimeError(f"Source changed during measurement: {path}")
    for name, artifact in frozen["artifacts"].items():
        if M.artifact_info(build / name, not name.endswith(".a")) != artifact:
            raise RuntimeError(f"Build artifact changed during measurement: {name}")


def executable_check(entry, build):
    work = Path(entry["roots"]["after"]["path"]).parent
    obj, renamed = work / "target.o", work / "renamed.o"
    executable, original = work / "target", work / "original"
    commands = [
        ["gcc", *M.C_FLAGS, "-c", str(work / "target.c"), "-o", str(obj)],
        ["objcopy", "@" + str(work / "target.rsp"), str(obj), str(renamed)],
        ["gcc", "-no-pie", str(renamed), str(build / "libcrust0_host.a"), "-o", str(executable)],
    ]
    start = time.perf_counter_ns()
    for command in commands:
        M.checked(command)
    elapsed = time.perf_counter_ns() - start
    original_command = [
        "gcc",
        *M.C_FLAGS,
        "-Iinclude",
        entry["inputs"]["c"]["path"],
        str(build / "libcrust0_host.a"),
        "-o",
        str(original),
    ]
    M.checked(original_command)
    actual = M.checked([str(executable)])
    if M.checked([str(original)]) != actual:
        raise RuntimeError("Native target and original C disagree")
    return {
        "target_commands": commands,
        "original_command": original_command,
        "target_toolchain_ns": elapsed,
        "observations": 1,
        "output": actual.decode(),
    }


def profile(frozen, workload, directory, perf):
    root = Path(frozen["root"])
    build = Path(frozen["build"])
    module = load(root)
    sources = [*module.M.LIBRARY_SOURCES, root / "stages/c/main.crs"]
    names = [
        name
        for path in sources
        for name in re.findall(r"^fn (\w+)\(", path.read_text(), re.M)
        if name != "main"
    ]
    assembly = directory / "profile.s"
    obj = directory / "profile.o"
    binary = directory / "profile"
    commands = [
        [
            str(build / "crust0"),
            "-S",
            "-o",
            str(assembly),
            *[arg for name in names for arg in ("--export", name)],
            *map(str, sources),
        ],
        ["as", "--64", str(assembly), "-o", str(obj)],
        [
            "gcc",
            "-no-pie",
            str(obj),
            str(build / "libcrust0.a"),
            str(build / "libcrust0_host.a"),
            "-o",
            str(binary),
        ],
    ]
    for command in commands:
        M.checked(command)
    command = [
        str(binary),
        "--library",
        "--emit-c",
        "-o",
        "/dev/null",
        str(workload["paths"]["crust"]),
    ]
    repeat = directory / "profile.py"
    repeat.write_text(
        "import subprocess\nfor _ in range(20): subprocess.run(" + repr(command) + ", check=True)\n"
    )
    data = directory / "profile.perf"
    record = [
        perf,
        "record",
        "-q",
        "-e",
        "cycles:u",
        "-F",
        "9999",
        "-o",
        str(data),
        "--",
        sys.executable,
        str(repeat),
    ]
    M.checked(record)
    report = [
        perf,
        "report",
        "--stdio",
        "--no-children",
        "-i",
        str(data),
        "--sort",
        "dso,symbol",
        "--percent-limit",
        "1",
    ]
    return {
        "scope": "Untimed diagnostic: ASM-built C driver with function exports for symbol attribution; target frontend and emission only; 20 fresh processes; not cold stage preparation",
        "build_commands": commands,
        "target_command": command,
        "record_command": record,
        "report_command": report,
        "binary_sha256": B.sha256(binary),
        "data_sha256": B.sha256(data),
        "report": M.checked(report).decode(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--before",
        type=Path,
        required=True,
        help="frozen checkout with make all c-stage outputs in build/",
    )
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument(
        "--perf", type=Path, help="native Linux perf executable for symbol profiles"
    )
    args = parser.parse_args()
    before = args.before.resolve()
    build = args.build.resolve()
    report_path = args.output.resolve()
    perf = str(args.perf.resolve()) if args.perf else None
    if args.rounds < 20 or report_path.exists():
        parser.error("Use at least 20 rounds and a new output path")
    os.sched_setaffinity(0, {args.cpu})
    os.chdir(ROOT)
    directory = Path(tempfile.mkdtemp(prefix="cold-native-", dir=build))
    states = {"before": snapshot(before, before / "build"), "after": snapshot(ROOT, build)}
    tools = {name: B.tool_info(name) for name in ("gcc", "clang-20", "as", "ld", "objcopy")}
    if perf:
        tools[perf] = B.tool_info(perf)
    script_hash = B.sha256(__file__)
    result = {
        "revision": B.capture(["git", "rev-parse", "HEAD"]),
        "source_diff": B.capture(
            ["git", "diff", "HEAD", "--", "src", "include", "runtime", "api", "stages"]
        ),
        "command": sys.argv,
        "environment": B.environment(args.cpu),
        "script_sha256": script_hash,
        "builds": states,
        "tools": tools,
        "method": {
            "rounds": args.rounds,
            "seed": 20261002,
            "bootstrap_draws": 10000,
            "state": "Fresh process and empty stage-result cache; warm OS caches; one CPU. Only seed and system tools are installed inputs to each native route.",
            "endpoint": "Root startup, stage preparation, native continuations, target frontend, complete C and symbol files, cleanup. Final target GCC is excluded; GCC used to prepare stages is included.",
            "baseline": "Original C syntax checks with GCC and Clang; select fastest median in each paired bootstrap resample.",
            "phases": "bootstrap includes ASM stage build and load; continuation_preparation includes both native action builds and loads; native_target includes target frontend and emission; startup_cleanup is the remaining cold process time",
            "stop": "Any failed one-worker cold case blocks parallel scheduler expansion. This experiment is not the complete specification matrix.",
        },
        "workloads": [],
    }
    workloads = [B.generate(directory, count) for count in (1000, 8000)]
    workloads.insert(
        0,
        {
            "name": "intrusive",
            "library": False,
            "paths": {
                "crust": ROOT / "examples/intrusive/program.crs",
                "c": ROOT / "benchmarks/bootstrap/intrusive.c",
            },
        },
    )
    for workload in workloads:
        entry = {
            "name": workload["name"],
            "inputs": {name: M.file_info(path) for name, path in workload["paths"].items()},
            "commands": {},
            "roots": {},
            "samples": [],
        }
        for label, state in states.items():
            work = directory / f"{workload['name']}-{label}"
            work.mkdir()
            module = load(Path(state["root"]))
            root = module.roots(workload, work, Path(state["build"]))["native"]
            output, symbols = work / "target.c", work / "target.rsp"
            entry["roots"][label] = {
                "path": str(root),
                "source": root.read_text(),
                "sha256": B.sha256(root),
            }
            entry["commands"][label] = [
                str(Path(state["build"]) / "crust"),
                str(root),
                *(["--library"] if workload["library"] else []),
                "--emit-c",
                "-o",
                str(output),
                "--symbols",
                str(symbols),
            ]
            N.sample(entry["commands"][label], True)
            hashes = [B.sha256(output), B.sha256(symbols)]
            if "output_sha256" in entry and hashes != entry["output_sha256"]:
                raise RuntimeError(f"Different target output: {workload['name']} {label}")
            entry["output_sha256"] = hashes
        entry["commands"]["gcc"] = M.syntax_command(workload["paths"]["c"], not workload["library"])
        entry["commands"]["clang"] = ["clang-20", *entry["commands"]["gcc"][1:]]
        entry["headers"] = {
            name: B.dependency_manifest(entry["commands"][name]) for name in ("gcc", "clang")
        }
        for name in ("gcc", "clang"):
            N.sample(entry["commands"][name])
        if not workload["library"]:
            entry["executable_check"] = executable_check(entry, build)
        result["workloads"].append(entry)

    rng = random.Random(20261002)
    for index in range(args.rounds):
        order = list(result["workloads"])
        rng.shuffle(order)
        for entry in order:
            routes = list(entry["commands"])
            rng.shuffle(routes)
            row = {name: N.sample(entry["commands"][name], name in states) for name in routes}
            for label in states:
                work = Path(entry["roots"][label]["path"]).parent
                if [B.sha256(work / "target.c"), B.sha256(work / "target.rsp")] != entry[
                    "output_sha256"
                ]:
                    raise RuntimeError(f"Output changed: {entry['name']} {label}")
                if list(work.glob("crust-*")):
                    raise RuntimeError(f"Temporary native images remain: {label}")
            entry["samples"].append(row)
        print(f"paired round {index + 1}/{args.rounds}", flush=True)

    for entry in result["workloads"]:
        rows = entry["samples"]
        entry["median_ms"] = {
            name: {
                field.removesuffix("_ns"): statistics.median(row[name][field] for row in rows) / 1e6
                for field in rows[0][name]
            }
            for name in entry["commands"]
        }
        entry["after_over_before"] = ratio(rows, "after", ["before"])
        entry["after_over_fastest_c"] = ratio(rows, "after", ["gcc", "clang"])
        for info in entry["inputs"].values():
            if B.sha256(info["path"]) != info["sha256"]:
                raise RuntimeError("Target input changed")
        for name in ("gcc", "clang"):
            if B.dependency_manifest(entry["commands"][name]) != entry["headers"][name]:
                raise RuntimeError("C headers changed")
        for info in entry["roots"].values():
            if B.sha256(info["path"]) != info["sha256"]:
                raise RuntimeError("Root input changed")
        print(entry["name"], json.dumps(entry["median_ms"]), flush=True)
    if perf:
        result["profiles"] = {}
        for label, state in states.items():
            work = directory / ("profile-" + label)
            work.mkdir()
            result["profiles"][label] = profile(state, workloads[-1], work, perf)
    for state in states.values():
        verify_snapshot(state)
    if B.sha256(__file__) != script_hash or any(
        B.tool_info(name) != info for name, info in tools.items()
    ):
        raise RuntimeError("Measurement script or tool changed")
    result["single_worker_pass"] = all(
        entry["after_over_fastest_c"]["pass"] for entry in result["workloads"]
    )
    opener = gzip.open if report_path.suffix == ".gz" else open
    with opener(report_path, "wt") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return 0 if result["single_worker_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
