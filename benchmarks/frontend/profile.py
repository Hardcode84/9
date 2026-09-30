#!/usr/bin/env python3
"""Fetch pinned inputs and measure compiler checks in separate processes.

Run from the repository root. Failed compiler commands stop the experiment.
Output directories must be empty. Downloaded source files stay in the cache.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import random
import signal
import statistics
import subprocess
import tarfile
import time
import urllib.request
import zipfile


CACHE = Path(".profile-cache")
SOURCES = CACHE / "sources"
INPUTS = [
    {
        "name": "sqlite",
        "url": "https://sqlite.org/2025/sqlite-amalgamation-3500400.zip",
        "sha256": "1d3049dd0f830a025a53105fc79fd2ab9431aea99e137809d064d8ee8356b032",
    },
    {
        "name": "json",
        "url": "https://raw.githubusercontent.com/nlohmann/json/v3.12.0/single_include/nlohmann/json.hpp",
        "sha256": "aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63",
    },
    {
        "name": "regex",
        "url": "https://static.crates.io/crates/regex-syntax/regex-syntax-0.8.8.crate",
        "sha256": "7a2d987857b319362043e95f5353c0535c1f58eec5336fdfcf626430af7def58",
    },
]
UNICODE = ["unicode", "unicode-age", "unicode-bool", "unicode-case",
           "unicode-gencat", "unicode-perl", "unicode-script", "unicode-segment"]


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def prepare():
    SOURCES.mkdir(parents=True, exist_ok=True)
    for spec in INPUTS:
        archive_path = CACHE / (spec["name"] + ".download")
        if not archive_path.exists():
            with urllib.request.urlopen(spec["url"], timeout=60) as response:
                archive_path.write_bytes(response.read())
        data = archive_path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != spec["sha256"]:
            raise RuntimeError(f"Checksum mismatch for {spec['name']}: {actual}")
        if spec["name"] == "sqlite":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for filename in ("sqlite3.c", "sqlite3.h"):
                    (SOURCES / filename).write_bytes(
                        archive.read("sqlite-amalgamation-3500400/" + filename))
        elif spec["name"] == "json":
            (SOURCES / "nlohmann").mkdir(exist_ok=True)
            (SOURCES / "nlohmann/json.hpp").write_bytes(data)
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                archive.extractall(SOURCES, filter="data")
        print(f"Verified {spec['name']}: {actual}", flush=True)


def cases():
    result = {}
    for compiler in ("clang-20", "gcc"):
        result[f"sqlite-{compiler}"] = [compiler, "-std=gnu11", "-O0", "-g0",
                                       "-fsyntax-only", str(SOURCES / "sqlite3.c")]
    for compiler in ("clang++-20", "g++"):
        for kind in ("include", "client"):
            result[f"json-{kind}-{compiler}"] = [
                compiler, "-std=c++17", "-O0", "-g0", "-fsyntax-only",
                "-I", str(SOURCES), f"benchmarks/frontend/json_{kind}.cpp"]
    for variant, features in (("default", ["std"] + UNICODE), ("std", ["std"])):
        command = ["rustc", "--crate-name", "regex_syntax", "--crate-type", "lib",
                   "--edition=2021", "--emit=metadata", "-Copt-level=0",
                   "-Cdebuginfo=0", "-Zthreads=1"]
        for feature in features:
            command += ["--cfg", f'feature="{feature}"']
        command += [str(SOURCES / "regex-syntax-0.8.8/src/lib.rs"), "-o",
                    str(CACHE / f"regex-{variant}.rmeta")]
        result[f"regex-{variant}-rustc"] = command
    return result


def verify_inputs():
    for spec in INPUTS:
        data = (CACHE / (spec["name"] + ".download")).read_bytes()
        if hashlib.sha256(data).hexdigest() != spec["sha256"]:
            raise ValueError(f"Changed input archive: {spec['name']}")
        if spec["name"] == "sqlite":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                expected = {filename: archive.read("sqlite-amalgamation-3500400/" + filename)
                            for filename in ("sqlite3.c", "sqlite3.h")}
        elif spec["name"] == "json":
            expected = {"nlohmann/json.hpp": data}
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                expected = {member.name: archive.extractfile(member).read()
                            for member in archive.getmembers() if member.isfile()}
        for filename, content in expected.items():
            if (SOURCES / filename).read_bytes() != content:
                raise ValueError(f"Changed extracted input: {filename}")


def run_process(command, timeout=120, **options):
    """Run a command and return its exit status and captured output.

    On timeout or interruption, terminate its process group and wait for the
    direct child. Re-raise the exception after that cleanup.
    """
    with subprocess.Popen(command, start_new_session=True, **options) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                if process.poll() is None:
                    raise
            process.communicate()
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def environment():
    result = os.environ.copy()
    result["LC_ALL"] = "C"
    result["RUSTC_BOOTSTRAP"] = "1"
    return result


def command_output(command):
    return subprocess.check_output(command, text=True, env=environment()).strip()


def metadata(args, selected):
    cpuinfo = Path("/proc/cpuinfo").read_text().splitlines()
    model = next(line.split(":", 1)[1].strip() for line in cpuinfo
                 if line.startswith("model name"))
    return {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cpu": model, "logical_cpus": os.cpu_count(), "pinned_cpu": args.cpu,
        "smt_siblings": Path(f"/sys/devices/system/cpu/cpu{args.cpu}/topology/thread_siblings_list").read_text().strip(),
        "governor": Path(f"/sys/devices/system/cpu/cpu{args.cpu}/cpufreq/scaling_governor").read_text().strip(),
        "kernel": platform.release(), "os_release": Path("/etc/os-release").read_text(),
        "memory_kib": int(Path("/proc/meminfo").read_text().splitlines()[0].split()[1]),
        "load_start": Path("/proc/loadavg").read_text().split()[:3],
        "versions": {
            "clang": command_output(["clang-20", "--version"]).splitlines()[0],
            "gcc": command_output(["gcc", "--version"]).splitlines()[0],
            "rustc": command_output(["rustc", "--version", "--verbose"]),
            "libstdc++": command_output(["dpkg-query", "-W", "-f=${Version}", "libstdc++-13-dev"]),
            "python": platform.python_version(),
        },
        "inputs": INPUTS, "commands": selected,
        "environment_overrides": {"LC_ALL": "C", "RUSTC_BOOTSTRAP": "1"},
        "seed": args.seed, "repeats": args.repeats,
        "filesystem_cache": "warm after one discarded run per case",
        "compiler_cache": "no PCH, modules, incremental cache, or compiler daemon",
        "standard_libraries": "installed C/C++ headers and prebuilt Rust sysroot",
    }


def run(command, stem, cpu):
    time_path = stem.with_suffix(".time.json")
    stderr_path = stem.with_suffix(".stderr")
    invocation = ["/usr/bin/time", "-f",
                  '{"user_s":%U,"system_s":%S,"max_rss_kib":%M}',
                  "-o", str(time_path), "taskset", "-c", str(cpu)] + command
    start = time.perf_counter_ns()
    with stderr_path.open("w") as stderr:
        process = run_process(invocation, stdout=subprocess.PIPE, stderr=stderr,
                              text=True, env=environment())
    wall_s = (time.perf_counter_ns() - start) / 1e9
    if process.returncode:
        raise RuntimeError(f"Compiler failed ({process.returncode}): {command}\n"
                           + stderr_path.read_text())
    if process.stdout:
        stem.with_suffix(".stdout").write_text(process.stdout)
    measurement = json.loads(time_path.read_text())
    measurement.update(wall_s=wall_s, command=command, stderr=str(stderr_path))
    return measurement


def measure(args, selected):
    records = []
    rng = random.Random(args.seed)
    for name, command in selected.items():
        run(command, args.output / f"warmup-{name}", args.cpu)
    for index in range(args.repeats):
        order = list(selected)
        rng.shuffle(order)
        for name in order:
            result = run(selected[name], args.output / f"{index:02d}-{name}", args.cpu)
            if Path(result["stderr"]).read_text():
                raise RuntimeError(f"Unexpected diagnostic: {result['stderr']}")
            result.update(case=name, repetition=index)
            records.append(result)
        save(args.output / "measurements.json", records)
        print(f"Completed measurement round {index + 1}/{args.repeats}", flush=True)
    summary = {}
    for name in selected:
        rows = [row for row in records if row["case"] == name]
        wall = [row["wall_s"] for row in rows]
        summary[name] = {
            "n": len(rows), "median_wall_s": statistics.median(wall),
            "min_wall_s": min(wall), "max_wall_s": max(wall),
            "median_cpu_s": statistics.median(row["user_s"] + row["system_s"] for row in rows),
            "median_rss_kib": statistics.median(row["max_rss_kib"] for row in rows),
        }
    save(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


def profile(args, selected):
    records = []
    for index in range(args.repeats):
        for name, original in selected.items():
            command = original.copy()
            stem = args.output / f"{index:02d}-{name}"
            if command[0].startswith("clang"):
                command += ["-Xclang", f"-ftime-trace={stem}.trace.json",
                            "-Xclang", "-ftime-trace-granularity=0"]
            elif command[0] in ("gcc", "g++"):
                command += ["-ftime-report"]
            else:
                command += ["-Ztime-passes", "-Ztime-passes-format=json",
                            f"-Zself-profile={stem}.self"]
            result = run(command, stem, args.cpu)
            result.update(case=name, repetition=index)
            records.append(result)
            save(args.output / "measurements.json", records)
            print(f"Profiled {name} ({index + 1}/{args.repeats})", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "measure", "profile"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--cpu", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260930)
    parser.add_argument("--cases", nargs="+")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
        return
    if not args.output or args.repeats < 1:
        parser.error("A new output directory and a positive repeat count are required")
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("The selected CPU is outside the process affinity")
    verify_inputs()
    selected = cases()
    if args.cases:
        selected = {name: selected[name] for name in args.cases}
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / "environment.json", metadata(args, selected))
    {"measure": measure, "profile": profile}[args.action](args, selected)


if __name__ == "__main__":
    main()
