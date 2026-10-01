"""Record highlighting phases and complete requests, excluding helper compilation."""

import argparse
import hashlib
import json
import math
import platform
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(arguments, **kwargs):
    return subprocess.run([str(arg) for arg in arguments], cwd=ROOT, check=True, **kwargs)


def summary(samples):
    return {
        "median": statistics.median(samples),
        "p95": sorted(samples)[math.ceil(len(samples) * 0.95) - 1],
        "samples": samples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=21)
    args = parser.parse_args()
    if args.rounds < 2:
        parser.error("at least two rounds are required")
    work = ROOT / "build/highlight-profile"
    work.mkdir(parents=True, exist_ok=True)
    large = work / "large.crs"
    large.write_text(
        "".join(f"fn sample_{index}()->u32{{return {index}u32;}}\n" for index in range(25000))
    )
    empty = work / "empty.crs"
    empty.write_bytes(b"")
    sources = [
        "api/crust0.crs",
        "api/crust0_host.crs",
        "stages/reader/model.crs",
        "stages/reader/lex.crs",
    ]
    sources += [
        "stages/highlight/" + name
        for name in ("model.crs", "scan.crs", "output.crs", "program.crs")
    ]
    preparation = {}
    for name, entry in (
        ("profile", "benchmarks/highlight/profile_linux_x64.crs"),
        ("native", "stages/highlight/main.crs"),
    ):
        command = [
            "build/crust-c",
            "-o",
            f"build/highlight-profile/{name}",
            *sources,
            entry,
            "--cflag=-O2",
            "--cflag=-g",
            "--ldflag=build/libcrust0.a",
            "--ldflag=build/libcrust0_host.a",
        ]
        start = time.perf_counter()
        run(command, stdout=subprocess.DEVNULL)
        preparation[name] = {"command": command, "seconds": time.perf_counter() - start}
    results = {}
    for source in (empty, ROOT / "examples/hello/main.crs", ROOT / "stages/c/emit.crs", large):
        samples = [
            json.loads(run([work / "profile", source], capture_output=True).stdout)
            for _ in range(args.rounds)
        ]
        phases = {name: summary([sample[name] for sample in samples]) for name in samples[0]}
        complete = {}
        for option in ("--html", "--tokens"):
            elapsed = []
            for _ in range(args.rounds):
                start = time.perf_counter()
                run([work / "native", option, source], stdout=subprocess.DEVNULL)
                elapsed.append((time.perf_counter() - start) * 1000)
            complete[option] = summary(elapsed)
        editor = json.loads(
            run(
                ["bun", "benchmarks/highlight/adapter.cjs", work / "native", source, args.rounds],
                capture_output=True,
            ).stdout
        )
        for sample in editor:
            sample["total_ms"] = sample["process_transport_json_ms"] + sample["conversion_ms"]
        results[str(source.relative_to(ROOT))] = {
            "bytes": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "phase_cpu_microseconds": phases,
            "process_wall_ms": complete,
            "editor_wall_ms": {
                name: summary([sample[name] for sample in editor]) for name in editor[0]
            },
        }
    tracked_sources = [
        *sources,
        "stages/highlight/main.crs",
        "editors/vscode/adapter.cjs",
        "benchmarks/highlight/profile_linux_x64.crs",
        "benchmarks/highlight/adapter.cjs",
        "benchmarks/highlight/measure.py",
        "build/libcrust0.a",
        "build/libcrust0_host.a",
    ]
    report = {
        "date": "2026-10-01",
        "base_revision": run(["git", "rev-parse", "HEAD"], capture_output=True)
        .stdout.decode()
        .strip(),
        "platform": platform.platform(),
        "rounds": args.rounds,
        "gcc": run(["gcc", "--version"], capture_output=True).stdout.decode().splitlines()[0],
        "scope": "Warm filesystem, fresh native process per sample; no CPU affinity. CPU phases execute scan, HTML, then JSON in one process. Complete output goes to the null device. Editor uses a persistent Bun process and a new native process per request. Helper preparation includes GCC and is excluded from request timings.",
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in tracked_sources
        },
        "binary_sha256": {
            name: hashlib.sha256(binary.read_bytes()).hexdigest()
            for name, binary in (
                ("compiler", ROOT / "build/crust-c"),
                ("native", work / "native"),
                ("profile", work / "profile"),
            )
        },
        "preparation": preparation,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for name, result in results.items():
        print(
            name,
            result["bytes"],
            "bytes:",
            {mode: round(stats["median"], 3) for mode, stats in result["process_wall_ms"].items()},
        )


if __name__ == "__main__":
    main()
