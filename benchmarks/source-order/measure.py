#!/usr/bin/env python3
"""Measure source-order execution through complete C and rename output.

Use existing binaries in --build-dir. No build artifact is replaced. Each
source-order sample reads and executes the complete host root again. The external
backend library is an explicit prepared input. --prepare-library records one
separate rebuild observation from all library sources. --preflight-only checks
the inputs and executable witness without collecting timing rounds.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / "benchmarks/bootstrap/measure.py"
SPEC = importlib.util.spec_from_file_location("bootstrap_measure", BASE_PATH)
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

LIBRARY_SOURCES = [ROOT / path for path in (
    "api/crust0.crust", "api/crust0_host.crust", "api/crust0_stage.crust",
    "stages/c/model.crust", "stages/c/base.crust", "stages/c/types.crust",
    "stages/c/emit.crust", "stages/c/driver.crust", "stages/c/program.crust")]
HOST_INTERFACES = [ROOT / path for path in (
    "api/crust0_stage.crust", "stages/c/api.crust", "stages/c/build.crust")]
C_FLAGS = ["-std=c99", "-pedantic-errors", "-O2", "-g0",
           "-fstack-clash-protection", "-Wno-overlength-strings"]
SYNTAX_FLAGS = ["-std=c99", "-pedantic-errors", "-O0", "-g0", "-fsyntax-only"]
ENDPOINTS = {
    "source-order-c-output": "Fresh crust process: installed prelude read/check, root source-order read/check/evaluation, host inputs, dlopen/dlsym/libffi calls, target frontend, complete C and rename output, and cleanup; no target GCC",
    "prepared-c-output": "Fresh prepared crust-c process: target frontend and complete C and rename output; no host-entry preparation or target GCC",
    "gcc-original-syntax": "Fresh GCC process: preprocessing, parsing, and semantic checks on the matched original C source",
}
COMPARISONS = {
    "source-order-over-original-c": ("source-order-c-output", "gcc-original-syntax"),
    "prepared-over-original-c": ("prepared-c-output", "gcc-original-syntax"),
    "source-order-over-prepared": ("source-order-c-output", "prepared-c-output"),
}


def file_info(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "lines": data.count(b"\n"),
            "sha256": hashlib.sha256(data).hexdigest()}


def checked(command, stdout=subprocess.PIPE):
    process = BASE.run_process(command, stdout=stdout, stderr=subprocess.PIPE)
    if process.returncode != 0 or process.stderr:
        raise RuntimeError(f"Command failed or wrote a diagnostic: {command}\n"
                           + process.stderr.decode("utf-8", "replace"))
    return process.stdout


def source_hashes():
    paths = [ROOT / "Makefile", ROOT / "tools/api.py", ROOT / "tools/prelude.py", BASE_PATH, Path(__file__).resolve()]
    for directory, pattern in (("src", "*.c"), ("src", "*.h"), ("include", "*.h"),
                               ("runtime", "*.c"), ("api", "*.crust"), ("stages", "*.crust"), ("stages/c", "*.crust")):
        paths.extend(sorted((ROOT / directory).glob(pattern)))
    return {str(path.relative_to(ROOT)): BASE.sha256(path) for path in paths}


def artifact_info(path, dynamic=False):
    result = {**file_info(path), **BASE.binary_info(path)}
    if dynamic:
        result["shared_libraries"] = BASE.shared_libraries(path)
    return result


def crust_string(path):
    result = []
    for byte in os.fsencode(path):
        if byte in (34, 92):
            result.append("\\" + chr(byte))
        elif 32 <= byte < 127:
            result.append(chr(byte))
        else:
            result.append(f"\\x{byte:02x}")
    return '"' + "".join(result) + '"'


def staged_source(target, output, native_library):
    lines = [f"host_source(run, {crust_string(os.path.relpath(path, output.parent))});" for path in HOST_INTERFACES]
    lines.extend((f"host_link(run, {crust_string(os.path.relpath(native_library, output.parent))});",
                  f"var target: *CrustSource = host_input(run, {crust_string(os.path.relpath(target, output.parent))}, 1u64);",
                  "return c_build(target, 0usize, (*run).argc, (*run).argv);", ""))
    program = "\n".join(lines).encode("ascii")
    output.write_bytes(program)
    return len(program)


def workloads_in(directory, native_library):
    workloads = [BASE.generate(directory, count) for count in (1000, 8000)]
    intrusive = ROOT / "examples/intrusive/program.crust"
    workloads.append({"name": "intrusive", "library": False,
                      "functions": len(re.findall(r"^fn ", intrusive.read_text(), re.M)),
                      "paths": {"crust": intrusive, "c": ROOT / "benchmarks/bootstrap/intrusive.c"}})
    for workload in workloads:
        staged = directory / f"{workload['name']}-staged.crust"
        workload["root_source_bytes"] = staged_source(workload["paths"]["crust"], staged, native_library)
        workload["paths"]["staged"] = staged
    return workloads


def output_command(workload, binaries, route, response):
    options = ["--library"] if workload["library"] else []
    if route == "source-order":
        return [str(binaries["launcher"]), str(workload["paths"]["staged"]),
                *options, "--emit-c", "--symbols", str(response)]
    return [str(binaries["prepared"]), *options, "--emit-c", "--symbols", str(response),
            str(workload["paths"]["crust"])]


def syntax_command(path, original_intrusive=False):
    includes = ["-I" + str(ROOT / "include")] if original_intrusive else []
    return ["gcc", *SYNTAX_FLAGS, "-Wno-overlength-strings", *includes, str(path)]


def preflight(workload, binaries, directory, build):
    name = workload["name"]
    outputs = {}
    for route in ("source-order", "prepared"):
        c_path = directory / f"{name}-{route}.c"
        response = directory / f"{name}-{route}.rsp"
        command = output_command(workload, binaries, route, response)
        with c_path.open("wb") as stream:
            checked(command, stdout=stream)
        outputs[route] = {"c": c_path, "response": response, "command": command}
    for kind in ("c", "response"):
        if outputs["source-order"][kind].read_bytes() != outputs["prepared"][kind].read_bytes():
            raise RuntimeError(f"Source-order runner and prepared backend emit different {kind} bytes for {name}")
    c_path = outputs["source-order"]["c"]
    response = outputs["source-order"]["response"]
    definitions = len(re.findall(r"^[^;\n]*\br_g[0-9]+\([^;\n]*\)\n\{", c_path.read_text(), re.M))
    if definitions != workload["functions"]:
        raise RuntimeError(f"Incomplete target C output for {name}: {definitions} function definitions")
    commands = {
        "source-order-c-output": output_command(workload, binaries, "source-order", "/dev/null"),
        "prepared-c-output": output_command(workload, binaries, "prepared", "/dev/null"),
        "gcc-original-syntax": syntax_command(workload["paths"]["c"], not workload["library"]),
    }
    checked(commands["gcc-original-syntax"])
    checked(syntax_command(c_path))
    witness = None
    if not workload["library"]:
        raw = directory / "intrusive-raw.o"
        renamed = directory / "intrusive.o"
        executable = directory / "intrusive-source-order"
        reference = directory / "intrusive-c-reference"
        witness_commands = [
            ["gcc", *C_FLAGS, "-c", str(c_path), "-o", str(raw)],
            ["objcopy", "@" + str(response), str(raw), str(renamed)],
            ["gcc", "-no-pie", str(renamed), str(build / "libcrust0_host.a"), "-o", str(executable)],
            ["gcc", *C_FLAGS, "-I" + str(ROOT / "include"), str(workload["paths"]["c"]),
             str(build / "libcrust0_host.a"), "-no-pie", "-o", str(reference)],
        ]
        for command in witness_commands:
            checked(command)
        for path in (executable, reference):
            if checked([str(path)]) != b"intrusive: ok\n":
                raise RuntimeError(f"Intrusive executable witness failed: {path}")
        symbols = checked(["nm", str(executable)])
        forbidden = re.findall(rb"\b(?:crust_[A-Za-z0-9_]*|c_program|c_backend_build)\b", symbols)
        if forbidden:
            raise RuntimeError(f"Host compiler symbols reached the target executable: {forbidden}")
        dynamic = checked(["readelf", "-dW", str(executable)])
        needed = re.findall(rb"\(NEEDED\).*Shared library: \[([^]]+)\]", dynamic)
        if any(b"crust" in name for name in needed):
            raise RuntimeError("The target executable depends on a compiler library")
        witness = {"commands": witness_commands, "source_order_and_reference_stdout": "intrusive: ok\n",
                   "target_executable": artifact_info(executable), "reference_executable": artifact_info(reference),
                   "host_compiler_symbols": [], "symbol_table_sha256": hashlib.sha256(symbols).hexdigest(),
                   "target_needed_libraries": [name.decode() for name in needed]}
    return commands, {
        "identical_source_order_and_prepared_bytes": True,
        "commands": {route: output["command"] for route, output in outputs.items()},
        "c": file_info(c_path), "rename_response": file_info(response),
        "function_definitions": definitions, "executable_witness": witness,
        "c_header_dependencies": {
            endpoint: BASE.dependency_manifest(commands[endpoint])
            for endpoint in ("gcc-original-syntax",)},
    }


def prepare_library(build, directory):
    object_path = directory / "changed-library.o"
    library_path = directory / "changed-library.so"
    commands = [
        ("all-library-CRUST-to-object", [str(build / "crust-c"), "--library", "--object",
            "--export", "c_backend_build", "--export", "c_program", "--cflag=-fPIC",
            "--cflag=-fno-semantic-interposition",
            "-o", str(object_path), *map(str, LIBRARY_SOURCES)]),
        ("shared-library-link", ["gcc", "-shared", "-Wl,-Bsymbolic,-z,text,-z,relro,-z,now",
            str(object_path), "-o", str(library_path)]),
    ]
    observations = []
    for phase, command in commands:
        start = time.perf_counter_ns()
        output = checked(command)
        observations.append({"phase": phase, "command": command,
                             "wall_ns": time.perf_counter_ns() - start,
                             "stdout_sha256": hashlib.sha256(output).hexdigest()})
    return {"measured": True, "observations_per_phase": 1,
            "statistic": "one preparation observation, not a median or confidence interval",
            "commands": observations, "observed_total_wall_ns": sum(row["wall_ns"] for row in observations),
            "sources": [file_info(path) for path in LIBRARY_SOURCES],
            "object": artifact_info(object_path), "library": artifact_info(library_path, dynamic=True),
            "scope": "Read/check/lower all library CRUST sources, emit C, GCC -O2 -fPIC -fno-semantic-interposition compilation, objcopy renaming, and shared linking; installed crust-c and system tools are inputs",
            "included_in_frontend_samples": False,
            "used_as_measured_native_input": False,
            "reason": "A separate output measures a complete source-library rebuild without changing the installed input library"}


def summarize(samples, workloads, rounds, draws, seed):
    result = {}
    for workload in workloads:
        name = workload["name"]
        paired = [{row["endpoint"]: row["wall_ns"] for row in samples
                   if row["workload"] == name and row["round"] == index}
                  for index in range(rounds)]
        if any(set(row) != set(ENDPOINTS) for row in paired):
            raise RuntimeError(f"Incomplete paired coverage for {name}")
        medians = {endpoint: statistics.median(row[endpoint] for row in paired) for endpoint in ENDPOINTS}
        comparisons = {}
        for label, (numerator, denominator) in COMPARISONS.items():
            rng = random.Random(f"{seed}:{name}:{label}")
            ratios = []
            paired_ratios = []
            for _ in range(draws):
                selected = rng.choices(paired, k=rounds)
                ratios.append(statistics.median(row[numerator] for row in selected) /
                              statistics.median(row[denominator] for row in selected))
                paired_ratios.append(statistics.median(row[numerator] / row[denominator] for row in selected))
            ratios.sort()
            paired_ratios.sort()
            interval = [BASE.percentile(ratios, .025), BASE.percentile(ratios, .975)]
            comparisons[label] = {
                "numerator": numerator, "denominator": denominator,
                "ratio_of_medians": medians[numerator] / medians[denominator],
                "paired_bootstrap_percentile_95_ci": interval,
                "median_of_paired_ratios": statistics.median(row[numerator] / row[denominator] for row in paired),
                "paired_ratio_bootstrap_percentile_95_ci":
                    [BASE.percentile(paired_ratios, .025), BASE.percentile(paired_ratios, .975)],
                "upper_ci_at_most_one": interval[1] <= 1,
            }
        differences = [row["source-order-c-output"] - row["prepared-c-output"] for row in paired]
        result[name] = {"rounds": rounds,
            "median_wall_ms": {key: value / 1e6 for key, value in medians.items()},
            "min_wall_ms": {key: min(row[key] for row in paired) / 1e6 for key in ENDPOINTS},
            "max_wall_ms": {key: max(row[key] for row in paired) / 1e6 for key in ENDPOINTS},
            "comparisons": comparisons,
            "source_order_minus_prepared": {"median_paired_difference_ms": statistics.median(differences) / 1e6,
                "scope": "Difference between complete process endpoints; not isolated host-preparation phase attribution"}}
    return result


def verify_frozen(result, workloads, binaries, tools, cc1):
    if source_hashes() != result["source_sha256"]:
        raise RuntimeError("Compiler, stage, or harness source changed during the run")
    for name, path in binaries.items():
        dynamic = name != "host-runtime"
        if artifact_info(path, dynamic) != result["installed_inputs"][name]:
            raise RuntimeError(f"Installed input changed during the run: {name}")
    for name, command in tools.items():
        if BASE.tool_info(command) != result["toolchains"][name]:
            raise RuntimeError(f"Native tool or shared dependency changed during the run: {name}")
    if artifact_info(cc1, dynamic=True) != result["gcc_cc1"]:
        raise RuntimeError("GCC frontend changed during the run")
    for workload in workloads:
        name = workload["name"]
        library = result["inputs"][name]["native_library"]
        if file_info(Path(library["path"])) != library:
            raise RuntimeError("Copied native library changed during the run")
        for kind, path in workload["paths"].items():
            if file_info(path) != result["inputs"][name]["sources"][kind]:
                raise RuntimeError(f"Workload input changed during the run: {name}/{kind}")
        for kind in ("c", "rename_response"):
            expected = result["artifacts"][name][kind]
            if file_info(Path(expected["path"])) != expected:
                raise RuntimeError(f"Generated backend input changed during the run: {name}/{kind}")
        for endpoint in ("gcc-original-syntax",):
            if BASE.dependency_manifest(result["commands"][name][endpoint]) != \
                    result["artifacts"][name]["c_header_dependencies"][endpoint]:
                raise RuntimeError(f"C preprocessing input changed during the run: {name}/{endpoint}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=Path("build"))
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--cpu", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--bootstrap-draws", type=int, default=10000)
    parser.add_argument("--prepare-library", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if Path.cwd() != ROOT:
        parser.error("Run this script from the repository root")
    if args.rounds < 25 or args.warmup < 1 or args.bootstrap_draws < 1000:
        parser.error("Use at least 25 rounds, one warmup, and 1000 bootstrap draws")
    if args.output.exists():
        parser.error("The output already exists; select a new path")
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This experiment requires Linux x86-64")
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("The selected CPU is outside the allowed affinity set")
    build = args.build_dir.resolve()
    binaries = {"launcher": build / "crust", "prepared": build / "crust-c",
                "native-library": build / "crust-c-library.so", "host-runtime": build / "libcrust0_host.a"}
    for path in binaries.values():
        if not path.is_file():
            parser.error(f"Missing prepared input: {path}; build outside this measurement")
    os.sched_setaffinity(0, {args.cpu})
    cache = ROOT / ".profile-cache"
    cache.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="source-orders-", dir=cache))
    temporary = directory / "temporary"
    temporary.mkdir()
    BASE.ENV["TMPDIR"] = str(temporary)
    tools = {name: name for name in ("gcc", "as", "ld", "objcopy", "nm", "readelf")}
    cc1 = Path(BASE.capture(["gcc", "-print-prog-name=cc1"])).resolve()
    result = {
        "schema": 1, "status": "preflight", "environment": BASE.environment(args.cpu),
        "measurement_command": [sys.executable, str(Path(__file__).resolve().relative_to(ROOT)), *sys.argv[1:]],
        "source_sha256": source_hashes(),
        "installed_inputs": {name: artifact_info(path, name != "host-runtime") for name, path in binaries.items()},
        "installed_build_provenance": "Existing artifacts are identified by hashes; their build commands and flags are not inferred from file names",
        "toolchains": {name: BASE.tool_info(command) for name, command in tools.items()},
        "gcc_cc1": artifact_info(cc1, dynamic=True),
        "endpoints": ENDPOINTS, "commands": {}, "inputs": {}, "artifacts": {}, "warmups": [], "samples": [],
        "library_preparation": {"measured": False, "reason": "Use --prepare-library for one separate complete source-library rebuild observation"},
        "method": {
            "rounds_per_endpoint": args.rounds, "warmups_per_endpoint": args.warmup,
            "seed": args.seed, "bootstrap_draws": args.bootstrap_draws, "confidence": .95,
            "randomization": "Shuffle workloads each round and all three endpoints within each workload",
            "pairing": "One sample for every endpoint in the same workload and round",
            "bootstrap": "Resample complete paired rounds; report ratio of medians and median of paired ratios separately",
            "intervals": "Per comparison; no simultaneous-coverage claim",
            "timing": "perf_counter_ns around fresh process launch and completion; includes all child processes and cleanup",
            "outputs": "Complete C stdout and rename text go to DEVNULL; preflight preserves and compares both streams",
            "cold_source_order": "Each invocation reads/checks the installed prelude and root, executes ordinary host code, loads the explicit native library, and runs the target frontend; no prepared-root cache or per-action as/ld",
            "prepared_inputs": "Launcher, crust-c, explicit native backend library, host runtime, and system tools already exist",
            "library_preparation": "Optional separate single rebuild observation; excluded from frontend samples and not combined with their confidence intervals",
            "excluded": "Workload generation, preflight, installed compiler construction, and final target GCC/objcopy/link execution",
            "generated_c_syntax": "Untimed preflight validation only; target GCC parsing, compilation, and linking are excluded from measurements",
            "os_file_cache": "Warm; no cache eviction; each invocation has a fresh process, evaluator, module state, and host context",
            "compiler_cache": "No compiler or execution-result cache; no root assembler/linker preparation",
            "cpu_affinity": "Controller and descendants pinned to the selected allowed CPU; CPU is not reserved",
            "temporary_directory": str(temporary),
            "required_speed_gate": "source-order-c-output upper 95% ratio-of-medians bound <= 1 versus GCC syntax on matched original C for every workload",
            "scope": "Direct intrusive witness and matched 1000/8000 ordinary functions; no whole-language or memory-safety claim",
        },
    }
    result["environment"]["child_environment"]["TMPDIR"] = str(temporary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    BASE.save(args.output, result)
    try:
        ordinary_library = directory / "ordinary output.plugin"
        ordinary_library.write_bytes(binaries["native-library"].read_bytes())
        workloads = workloads_in(directory, ordinary_library)
        for workload in workloads:
            name = workload["name"]
            result["inputs"][name] = {"functions": workload["functions"], "library": workload["library"],
                "root_source_bytes": workload["root_source_bytes"],
                "sources": {kind: file_info(path) for kind, path in workload["paths"].items()},
                "explicit_host_sources": [file_info(path) for path in HOST_INTERFACES],
                "native_library": file_info(ordinary_library)}
            commands, artifacts = preflight(workload, binaries, directory, build)
            result["commands"][name] = commands
            result["artifacts"][name] = artifacts
            print(f"Preflight passed: {name}", flush=True)
            BASE.save(args.output, result)
        if args.prepare_library:
            result["library_preparation"] = prepare_library(build, directory)
            BASE.save(args.output, result)
        verify_frozen(result, workloads, binaries, tools, cc1)
        if list(temporary.iterdir()):
            raise RuntimeError("Stage temporary files remain after preflight")
        if args.preflight_only:
            result["status"] = "preflight-complete"
            BASE.save(args.output, result)
            print("Preflight complete; no timing rounds collected", flush=True)
            return
        result["status"] = "running"
        for index in range(args.warmup):
            for name, endpoints in result["commands"].items():
                for endpoint, command in endpoints.items():
                    result["warmups"].append({"round": index, "workload": name, "endpoint": endpoint,
                                              "wall_ns": BASE.measure(command)})
        rng = random.Random(args.seed)
        for index in range(args.rounds):
            order = list(result["commands"])
            rng.shuffle(order)
            for name in order:
                endpoints = list(ENDPOINTS)
                rng.shuffle(endpoints)
                for endpoint in endpoints:
                    result["samples"].append({"round": index, "sequence": len(result["samples"]),
                        "workload": name, "endpoint": endpoint,
                        "wall_ns": BASE.measure(result["commands"][name][endpoint])})
            BASE.save(args.output, result)
            print(f"Paired round {index + 1}/{args.rounds}", flush=True)
        verify_frozen(result, workloads, binaries, tools, cc1)
        if list(temporary.iterdir()):
            raise RuntimeError("Stage temporary files remain after measurement")
        result["summary"] = summarize(result["samples"], workloads, args.rounds, args.bootstrap_draws, args.seed)
        failed = [name for name, summary in result["summary"].items()
                  if not summary["comparisons"]["source-order-over-original-c"]["upper_ci_at_most_one"]]
        result["speed_gate"] = {"passed": not failed, "failed_workloads": failed,
                                "comparison": "source-order-over-original-c"}
        result["environment"]["load_end"] = Path("/proc/loadavg").read_text().split()[:3]
        result["status"] = "complete"
        BASE.save(args.output, result)
        print(json.dumps({"summary": result["summary"], "speed_gate": result["speed_gate"]}, indent=2))
    except BaseException as error:
        result["status"] = "failed"
        result["error"] = f"{type(error).__name__}: {error}"
        BASE.save(args.output, result)
        raise
    if failed:
        raise SystemExit("Cold source-order output speed gate failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
