#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure native source generics against the handwritten tutorial."""

import argparse
import hashlib
import json
import platform
import shlex
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASES = (
    "generic_read_ns",
    "generic_lower_ns",
    "generic_check_ns",
    "generic_cleanup_ns",
    "handwritten_read_ns",
    "handwritten_check_ns",
    "handwritten_cleanup_ns",
)
METRICS = (
    "input_io_ns",
    "generic_arena_bytes",
    "handwritten_arena_bytes",
    "requests",
    "hits",
    "specializations",
    "duplicate_concrete_declarations",
)


def run(command):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {shlex.join(command)}\n{result.stdout}{result.stderr}"
        )
    return result


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(args, work):
    clock = work / "clock.o"
    executable = work / "generics-cost"
    clock_source = ROOT / "benchmarks/ownership/clock_linux_x64.c"
    compiler = shlex.split(args.cc)
    cflags = shlex.split(args.cflags)
    strict = ["-std=c99", "-pedantic-errors", "-Wall", "-Wextra", "-Werror"]
    clock_command = [*compiler, *cflags, *strict, "-c", str(clock_source), "-o", str(clock)]
    sources = [ROOT / "api/crust0.crs", ROOT / "api/crust0_host.crs"]
    sources += [ROOT / f"stages/reader/{name}.crs" for name in ("model", "lex", "parse")]
    sources += [
        path
        for path in sorted((ROOT / "stages/generics").glob("*.crs"))
        if path.name not in {"api.crs", "source_api.crs"}
    ]
    sources += [ROOT / "tests/generics_cost.crs"]
    command = [str(args.build / "crust-c"), "-o", str(executable), *map(str, sources)]
    command += [item for flag in cflags for item in ("--cflag", flag)]
    links = [clock, args.build / "libcrust0.a", args.build / "libcrust0_host.a"]
    command += [item for path in links for item in ("--ldflag", str(path))]
    command += [item for flag in shlex.split(args.ldflags) for item in ("--ldflag", flag)]
    start = time.perf_counter_ns()
    run(clock_command)
    run(command)
    preparation = time.perf_counter_ns() - start
    files = [*sources, clock_source, *links[1:]]
    return executable, {
        "commands": [clock_command, command],
        "wall_ns": preparation,
        "sha256": {str(path): fingerprint(path) for path in files},
        "compilers": {
            "clock": run([*compiler, "--version"]).stdout.splitlines()[0],
            "stage_backend": run(["gcc", "--version"]).stdout.splitlines()[0],
        },
    }


def inputs(work):
    directory = work / "inputs"
    directory.mkdir()
    result = []
    for name in ("types", "pair", "program", "handwritten"):
        source = ROOT / f"examples/generics/{name}.crs"
        target = directory / source.name
        target.write_bytes(source.read_bytes())
        result.append(target)
    return result


def sample(command, rounds):
    start = time.perf_counter_ns()
    result = run(command)
    wall = time.perf_counter_ns() - start
    if result.stderr:
        raise RuntimeError(result.stderr)
    values = [int(value) for value in result.stdout.split()]
    if len(values) != len(PHASES) + len(METRICS):
        raise RuntimeError(f"unexpected cost report: {result.stdout!r}")
    raw = dict(zip((*PHASES, *METRICS), values, strict=True))
    if raw["specializations"] != rounds * 10:
        raise RuntimeError(f"tutorial must produce ten concrete declarations per round: {raw}")
    if raw["requests"] != raw["hits"] + raw["specializations"] or raw["hits"] == 0:
        raise RuntimeError(f"specialization counters are inconsistent: {raw}")
    if raw["duplicate_concrete_declarations"] != 0:
        raise RuntimeError(f"cache produced duplicate concrete declarations: {raw}")
    raw["process_wall_ns"] = wall
    raw["generic_frontend_ns"] = sum(raw[name] for name in PHASES[:3])
    raw["handwritten_frontend_ns"] = raw["handwritten_read_ns"] + raw["handwritten_check_ns"]
    raw["frontend_ratio"] = raw["generic_frontend_ns"] / raw["handwritten_frontend_ns"]
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--work", type=Path, default=ROOT / "build/generics-cost-run")
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=200)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--cflags", default="-O2 -g")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    if args.samples < 1 or not 1 <= args.rounds <= 100000:
        parser.error("samples must be positive; rounds must be in 1..100000")
    args.build = args.build.resolve()
    work = args.work.resolve()
    if work.exists():
        parser.error("work directory exists; select a new directory to preserve earlier reports")
    if not work.is_relative_to(ROOT / "build"):
        parser.error("work directory must be under ignored build/")
    work.mkdir(parents=True)
    captured = inputs(work)
    executable, preparation = prepare(args, work)
    command = [str(executable), *map(str, captured), str(args.rounds)]
    rows = [sample(command, args.rounds) for _ in range(args.samples)]
    report = {
        "scope": (
            "Native code; source snapshots are read once per process before the compiler phases. "
            "Each round creates fresh contexts. Generic read includes context initialization, "
            "source copies, and parsing; lower includes normalization and specialization with "
            "all internal cache hits; check includes argument validation and seed checks. "
            "Handwritten read includes context initialization and seed parsing of the complete "
            "equivalent source; handwritten check includes collection, resolution, and checking. "
            "Cleanup is separate. Successful cache reuse is verified outside compiler clocks. "
            "No C emission, target GCC, or target linking is timed. Process wall includes startup, "
            "input I/O, cache verification, reporting, and all measured phases. Arena bytes are "
            "reserved compiler storage, excluding the captured input buffers."
        ),
        "machine": platform.platform(),
        "preparation": preparation,
        "command": command,
        "input_sha256": {path.name: fingerprint(path) for path in captured},
        "rounds_per_sample": args.rounds,
        "samples": rows,
        "median_frontend_ratio": statistics.median(row["frontend_ratio"] for row in rows),
        "median_ns_per_compilation": {
            name: statistics.median(row[name] / args.rounds for row in rows)
            for name in (*PHASES, "generic_frontend_ns", "handwritten_frontend_ns")
        },
    }
    path = work / "report.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"report: {path}")
    print(f"median generic/handwritten frontend: {report['median_frontend_ratio']:.3f}")
    print(
        f"requests/hits/instances per sample: {rows[0]['requests']}/{rows[0]['hits']}/{rows[0]['specializations']}"
    )
    print(
        f"arena bytes generic/handwritten: {rows[0]['generic_arena_bytes']}/{rows[0]['handwritten_arena_bytes']}"
    )
    print("duplicate concrete declarations: 0")


if __name__ == "__main__":
    main()
