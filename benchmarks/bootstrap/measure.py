#!/usr/bin/env python3
"""Measure fresh compiler processes on one CPU.

Run from the repository root. The script builds an isolated optimized compiler,
checks the executable witness, and saves raw samples and paired bootstrap ratios.
A failed command or changed input stops the experiment.
"""

import argparse
import hashlib
import json
import os
import platform
import random
import re
import shlex
import shutil
import signal
import statistics
import subprocess
import time
from pathlib import Path

ENDPOINTS = {
    "gcc-syntax": "GCC C99 parsing and semantic checks; -fsyntax-only",
    "clang-syntax": "Clang C99 parsing and semantic checks; -fsyntax-only",
    "crust-check": "CRUST reader, declaration collection, type resolution, body checking",
    "crust-prepare": "CRUST check plus native link validation and frame/value planning; source AST operations remain",
    "crust-assembly": "CRUST check, preparation, lowering, and complete textual assembly emitted to stdout; stdout goes to DEVNULL",
}
C_CASES = ("gcc-syntax", "clang-syntax")
CRUST_CASES = ("crust-check", "crust-prepare", "crust-assembly")
ENV = {"PATH": os.environ["PATH"], "LC_ALL": "C", "LANG": "C", "TZ": "UTC"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def relative(path):
    path = Path(path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Repository paths must be relative and cannot contain '..'")
    return path


def capture(command):
    result = run_process(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result.check_returncode()
    if result.stderr:
        raise RuntimeError(f"Unexpected diagnostic from {command}: {result.stderr}")
    return result.stdout.strip()


def run_process(command, **options):
    with subprocess.Popen(command, env=ENV, start_new_session=True, **options) as process:
        try:
            stdout, stderr = process.communicate(timeout=120)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                if process.poll() is None:
                    raise
            process.communicate()
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def generate(directory, count):
    directory.mkdir(parents=True, exist_ok=True)
    stem = directory / f"ordinary-{count}"
    c = [
        "typedef unsigned long u64;\ntypedef struct Node Node;\n"
        "struct Node { u64 value; u64 salt; Node *next; };\n"
    ]
    crust = ["record Node { value: u64; salt: u64; next: *Node; }\n"]
    for index in range(count):
        literal = (index * 53) % 4093 + 1
        name = f"work_{index:05d}"
        c.append(
            f"u64 {name}(Node *node, u64 x) {{\n"
            f"    u64 y = (x + {literal}ul) ^ node->value;\n"
            "    if (y < node->salt) {\n"
            "        y = y * 3ul + node->salt;\n"
            "    } else {\n"
            "        y = y - node->value;\n"
            "    }\n"
            "    node->value = y;\n"
            "    return y + x;\n}\n"
        )
        crust.append(
            f"fn {name}(node: *Node, x: u64) -> u64 {{\n"
            f"    var y: u64 = (x + {literal}u64) ^ (*node).value;\n"
            "    if y < (*node).salt {\n"
            "        y = y * 3u64 + (*node).salt;\n"
            "    } else {\n"
            "        y = y - (*node).value;\n"
            "    }\n"
            "    (*node).value = y;\n"
            "    return y + x;\n}\n"
        )
    paths = {"c": stem.with_suffix(".c"), "crust": stem.with_suffix(".crs")}
    paths["c"].write_text("".join(c))
    paths["crust"].write_text("".join(crust))
    return {
        "name": f"ordinary-{count}",
        "functions": count,
        "paths": paths,
        "library": True,
        "expected_assembly_functions": count,
    }


def commands(workload, compiler):
    include = ["-Iinclude"] if not workload["library"] else []
    result = {
        "gcc-syntax": [
            "gcc",
            "-std=c99",
            "-pedantic-errors",
            "-O0",
            "-g0",
            "-fsyntax-only",
            *include,
            str(workload["paths"]["c"]),
        ],
        "clang-syntax": [
            "clang-20",
            "-std=c99",
            "-pedantic-errors",
            "-O0",
            "-g0",
            "-fsyntax-only",
            *include,
            str(workload["paths"]["c"]),
        ],
    }
    library = ["--library"] if workload["library"] else []
    for name, option in (
        ("crust-check", "--check"),
        ("crust-prepare", "--prepare"),
        ("crust-assembly", "-S"),
    ):
        result[name] = [str(compiler), *library, option, str(workload["paths"]["crust"])]
    return result


def measure(command):
    start = time.perf_counter_ns()
    process = run_process(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    elapsed = time.perf_counter_ns() - start
    if process.returncode != 0 or process.stderr:
        raise RuntimeError(
            f"Compiler failed or wrote a diagnostic: {command}\n"
            + process.stderr.decode("utf-8", "replace")
        )
    return elapsed


def compiler_sources():
    paths = [Path("Makefile")]
    for directory, pattern in (
        ("src", "*.c"),
        ("src", "*.h"),
        ("include", "*.h"),
        ("runtime", "*.c"),
    ):
        paths.extend(sorted(Path(directory).rglob(pattern)))
    return {str(path): sha256(path) for path in paths}


def binary_info(path):
    path = Path(path).resolve()
    return {"file_name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}


def shared_libraries(path):
    result = []
    for line in capture(["ldd", str(path)]).splitlines():
        match = re.search(r"(?:=>\s+)?(/\S+)\s+\(", line)
        if match:
            result.append(binary_info(match[1]))
        elif "not found" in line:
            raise RuntimeError("A compiler shared library is unavailable")
    return sorted(result, key=lambda entry: entry["file_name"])


def tool_info(command):
    path = shutil.which(command, path=ENV["PATH"])
    if path is None:
        raise FileNotFoundError(f"Required compiler is unavailable: {command}")
    result = binary_info(path)
    result["command"] = command
    result["version"] = capture([command, "--version"]).splitlines()[0]
    result["shared_libraries"] = shared_libraries(path)
    return result


def dependency_manifest(command):
    invocation = ["-M" if part == "-fsyntax-only" else part for part in command]
    output = capture(invocation).replace("\\\n", " ")
    names = shlex.split(output.split(":", 1)[1])
    root = Path.cwd()
    result = []
    for name in names:
        path = Path(name).resolve()
        try:
            label = str(path.relative_to(root))
            kind = "repository"
        except ValueError:
            label = path.name
            kind = "system_header"
        result.append(
            {"name": label, "kind": kind, "bytes": path.stat().st_size, "sha256": sha256(path)}
        )
    return result


def optional_text(path):
    try:
        return {"value": Path(path).read_text().strip()}
    except OSError as error:
        return {"unavailable": type(error).__name__}


def environment(cpu):
    cpuinfo = Path("/proc/cpuinfo").read_text().splitlines()
    model = next(line.split(":", 1)[1].strip() for line in cpuinfo if line.startswith("model name"))
    return {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cpu_model": model,
        "logical_cpus": os.cpu_count(),
        "pinned_cpu": cpu,
        "smt_siblings": optional_text(
            f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list"
        ),
        "governor": optional_text(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor"),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "os_release": Path("/etc/os-release").read_text(),
        "memory_kib": int(Path("/proc/meminfo").read_text().splitlines()[0].split()[1]),
        "load_start": Path("/proc/loadavg").read_text().split()[:3],
        "cpu_reserved": False,
        "frequency_control": "governor recorded; frequency and turbo are not fixed",
        "python": platform.python_version(),
        "child_environment": {
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
            "PATH": "inherited for executable lookup; all other variables omitted",
        },
    }


def percentile(values, fraction):
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def summarize(samples, workloads, count, draws, seed):
    output = {}
    for workload in workloads:
        name = workload["name"]
        rounds = [
            {
                row["endpoint"]: row["wall_ns"]
                for row in samples
                if row["workload"] == name and row["round"] == index
            }
            for index in range(count)
        ]
        if any(set(row) != set(ENDPOINTS) for row in rounds):
            raise ValueError(f"Incomplete paired coverage for {name}")
        medians = {case: statistics.median(row[case] for row in rounds) for case in ENDPOINTS}
        fastest = min(C_CASES, key=medians.get)
        comparisons = {}
        for endpoint in CRUST_CASES:
            rng = random.Random(f"{seed}:{name}:{endpoint}")
            ratios = []
            fastest_draws = {case: 0 for case in C_CASES}
            for _ in range(draws):
                selected = rng.choices(rounds, k=count)
                c_medians = {
                    case: statistics.median(row[case] for row in selected) for case in C_CASES
                }
                selected_fastest = min(C_CASES, key=c_medians.get)
                fastest_draws[selected_fastest] += 1
                ratios.append(
                    statistics.median(row[endpoint] for row in selected)
                    / c_medians[selected_fastest]
                )
            ratios.sort()
            interval = [percentile(ratios, 0.025), percentile(ratios, 0.975)]
            comparisons[endpoint] = {
                "crust_over_fastest_c_median_ratio": medians[endpoint] / medians[fastest],
                "paired_bootstrap_percentile_95_ci": interval,
                "fastest_c_observed": fastest,
                "fastest_c_bootstrap_selections": fastest_draws,
                "upper_ci_at_most_one": interval[1] <= 1,
            }
        output[name] = {
            "samples_per_endpoint": count,
            "median_wall_ms": {key: value / 1e6 for key, value in medians.items()},
            "min_wall_ms": {key: min(row[key] for row in rounds) / 1e6 for key in ENDPOINTS},
            "max_wall_ms": {key: max(row[key] for row in rounds) / 1e6 for key in ENDPOINTS},
            "comparisons": comparisons,
        }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, default=Path("build/perf/crust0"))
    parser.add_argument("--inputs", type=Path, default=Path(".profile-cache/bootstrap-inputs"))
    parser.add_argument("--samples", type=int, default=25)
    parser.add_argument("--bootstrap-draws", type=int, default=10000)
    parser.add_argument("--cpu", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()
    for path in (args.output, args.compiler, args.inputs):
        relative(path)
    if args.samples < 20 or args.bootstrap_draws < 1000:
        parser.error("Use at least 20 samples and 1000 bootstrap draws")
    if args.compiler.name != "crust0":
        parser.error("The isolated Makefile build must use an crust0 executable")
    if args.output.exists():
        parser.error("The output JSON already exists; select a new path")
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("The selected CPU is outside the allowed affinity set")
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This experiment requires the Linux x86-64 execution profile")
    os.sched_setaffinity(0, {args.cpu})
    workloads = [generate(args.inputs, count) for count in (1000, 8000)]
    witness_source = Path("examples/intrusive/program.crs")
    workloads.append(
        {
            "name": "intrusive",
            "functions": len(re.findall(r"^fn ", witness_source.read_text(), re.M)),
            "paths": {"c": Path("benchmarks/bootstrap/intrusive.c"), "crust": witness_source},
            "library": False,
            "expected_assembly_functions": len(
                re.findall(r"^fn ", witness_source.read_text(), re.M)
            )
            + 1,
        }
    )
    build = [
        "make",
        "-B",
        "-j1",
        f"BUILD={args.compiler.parent}",
        "CC=gcc",
        "CFLAGS=-O2 -g0",
        "all",
    ]
    source_hashes = compiler_sources()
    script_hash = sha256("benchmarks/bootstrap/measure.py")
    start = time.perf_counter_ns()
    build_output = capture(build)
    build_ns = time.perf_counter_ns() - start
    if compiler_sources() != source_hashes:
        raise RuntimeError("Compiler source changed during the isolated build")
    print("Isolated compiler build complete", flush=True)
    witness_build = [
        "make",
        "-j1",
        f"BUILD={args.compiler.parent}",
        "CC=gcc",
        "CFLAGS=-O2 -g0",
        str(args.compiler.parent / "intrusive"),
        str(args.compiler.parent / "intrusive-c"),
    ]
    capture(witness_build)
    witness_runs = {}
    for name in ("intrusive", "intrusive-c"):
        output = capture([str(args.compiler.parent / name)])
        if output != "intrusive: ok":
            raise RuntimeError(f"Unexpected executable witness output: {output!r}")
        witness_runs[name] = output
    toolchains = {
        name: tool_info(command)
        for name, command in (("gcc", "gcc"), ("clang", "clang-20"), ("crust", str(args.compiler)))
    }
    cc1 = capture(["gcc", "-print-prog-name=cc1"])
    toolchains["gcc"]["cc1"] = binary_info(cc1)
    toolchains["gcc"]["cc1"]["shared_libraries"] = shared_libraries(cc1)
    for name, command in (("gcc", "gcc"), ("clang", "clang-20")):
        toolchains[name]["target"] = capture([command, "-dumpmachine"])
    selected = {workload["name"]: commands(workload, args.compiler) for workload in workloads}
    input_info = {}
    assembly = {}
    for workload in workloads:
        name = workload["name"]
        input_info[name] = {
            "functions": workload["functions"],
            "library": workload["library"],
            "sources": {
                kind: {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
                for kind, path in workload["paths"].items()
            },
            "c_header_dependencies": {
                case: dependency_manifest(selected[name][case]) for case in C_CASES
            },
        }
        path = args.inputs / (name + ".s")
        with path.open("wb") as output:
            process = run_process(
                selected[name]["crust-assembly"], stdout=output, stderr=subprocess.PIPE
            )
        if process.returncode != 0 or process.stderr:
            raise RuntimeError(f"Assembly preflight failed for {name}: {process.stderr!r}")
        count = path.read_bytes().count(b", @function\n")
        if count != workload["expected_assembly_functions"]:
            raise RuntimeError(f"Incomplete assembly for {name}: {count} functions")
        assembly[name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "function_definitions": count,
            "preflight_path": str(path),
        }
    result = {
        "schema": 1,
        "status": "running",
        "environment": environment(args.cpu),
        "measurement_command": [
            "python3",
            "benchmarks/bootstrap/measure.py",
            "--output",
            str(args.output),
            "--compiler",
            str(args.compiler),
            "--inputs",
            str(args.inputs),
            "--samples",
            str(args.samples),
            "--bootstrap-draws",
            str(args.bootstrap_draws),
            "--cpu",
            str(args.cpu),
            "--seed",
            str(args.seed),
        ],
        "method": {
            "samples_per_endpoint": args.samples,
            "seed": args.seed,
            "bootstrap_draws": args.bootstrap_draws,
            "confidence": 0.95,
            "randomization": "shuffle workloads each round; shuffle five endpoints within each workload",
            "pairing": "one sample for every endpoint per workload and round",
            "bootstrap": "resample complete paired rounds; ratio of medians; reselect fastest C median in each draw",
            "intervals": "per comparison; no simultaneous coverage claim",
            "timing": "perf_counter_ns around process launch and completion, including fresh process startup and wait",
            "stdout": "DEVNULL for every timed command; -S has no -o argument",
            "warmup": "one discarded timed run per command after build and preflight",
            "os_file_cache": "warm; no cache eviction",
            "compiler_cache": "none",
            "cpu_affinity": "controller and all compiler descendants pinned to one logical CPU",
            "excluded": "installed compiler/stage preparation, input generation, preflight, and final assembling/linking",
            "scope": "ordinary generated functions and the direct intrusive witness; no SQLite, self-host, or checked-language speed claim",
            "handoff": "--prepare retains source AST operations and is not full backend handoff; full assembly is a conservative upper bound that includes lowering and emission",
        },
        "build": {
            "command": build,
            "wall_ns": build_ns,
            "stdout_sha256": hashlib.sha256(build_output.encode()).hexdigest(),
            "source_sha256": source_hashes,
            "compiler_binary": toolchains["crust"],
            "stage_preparation_in_frontend_samples": False,
        },
        "script_sha256": script_hash,
        "toolchains": toolchains,
        "endpoints": ENDPOINTS,
        "commands": selected,
        "inputs": input_info,
        "assembly_preflight": assembly,
        "executable_witness": witness_runs,
        "warmups": [],
        "samples": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save(args.output, result)
    for name, cases in selected.items():
        for endpoint, command in cases.items():
            result["warmups"].append(
                {"workload": name, "endpoint": endpoint, "wall_ns": measure(command)}
            )
    print("Warmup complete; starting timing rounds", flush=True)
    rng = random.Random(args.seed)
    for index in range(args.samples):
        order = list(selected)
        rng.shuffle(order)
        for name in order:
            endpoints = list(selected[name])
            rng.shuffle(endpoints)
            for endpoint in endpoints:
                result["samples"].append(
                    {
                        "round": index,
                        "sequence": len(result["samples"]),
                        "workload": name,
                        "endpoint": endpoint,
                        "wall_ns": measure(selected[name][endpoint]),
                    }
                )
        save(args.output, result)
        print(f"Completed paired round {index + 1}/{args.samples}", flush=True)
    if compiler_sources() != source_hashes:
        raise RuntimeError("Compiler source changed during the experiment")
    if sha256("benchmarks/bootstrap/measure.py") != script_hash:
        raise RuntimeError("Measurement script changed during the experiment")
    for workload in workloads:
        for kind, path in workload["paths"].items():
            if sha256(path) != input_info[workload["name"]]["sources"][kind]["sha256"]:
                raise RuntimeError("Workload source changed during the experiment")
    for name, command in (("gcc", "gcc"), ("clang", "clang-20"), ("crust", str(args.compiler))):
        current = tool_info(command)
        if (
            current["sha256"] != toolchains[name]["sha256"]
            or current["shared_libraries"] != toolchains[name]["shared_libraries"]
        ):
            raise RuntimeError("Compiler binary changed during the experiment")
    if (
        binary_info(cc1)["sha256"] != toolchains["gcc"]["cc1"]["sha256"]
        or shared_libraries(cc1) != toolchains["gcc"]["cc1"]["shared_libraries"]
    ):
        raise RuntimeError("GCC frontend binary changed during the experiment")
    for name, cases in selected.items():
        for case in C_CASES:
            if dependency_manifest(cases[case]) != input_info[name]["c_header_dependencies"][case]:
                raise RuntimeError("A C input dependency changed during the experiment")
    result["summary"] = summarize(
        result["samples"], workloads, args.samples, args.bootstrap_draws, args.seed
    )
    result["environment"]["load_end"] = Path("/proc/loadavg").read_text().split()[:3]
    result["status"] = "complete"
    save(args.output, result)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
