#!/usr/bin/env python3
"""Measure the CRUST C stage and its GCC backend as separate processes.

Run from the repository root. The script builds both stage variants, checks
their complete output, and records fresh-process samples on one CPU. Preparation
cost is separate from installed-stage cost. A changed input stops the run.
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
import time


BASE_PATH = Path("benchmarks/bootstrap/measure.py")
SPEC = importlib.util.spec_from_file_location("bootstrap_measure", BASE_PATH)
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

STAGE_SOURCES = [Path(path) for path in (
    "api/crust0.crust", "api/crust0_host.crust", "api/crust0_stage.crust", "stages/c/model.crust",
    "stages/c/base.crust", "stages/c/types.crust", "stages/c/emit.crust",
    "stages/c/driver.crust", "stages/c/program.crust", "stages/c/main.crust")]
C_FLAGS = ["-std=c99", "-pedantic-errors", "-O2", "-g0",
           "-fstack-clash-protection", "-Wno-overlength-strings"]
C_ENDPOINTS = ("gcc-syntax", "clang-syntax")
STAGE_ENDPOINTS = tuple(f"{variant}-{phase}" for variant in ("seed", "optimized")
                        for phase in ("check", "prepare", "emit"))
ENDPOINTS = {
    "gcc-syntax": "GCC C99 source parsing and semantic checks; -fsyntax-only",
    "clang-syntax": "Clang C99 source parsing and semantic checks; -fsyntax-only",
}
for variant in ("seed", "optimized"):
    origin = "x64-compiled CRUST stage" if variant == "seed" else "self-C-compiled CRUST stage"
    ENDPOINTS[f"{variant}-check"] = origin + "; source reading, collection, resolution, and body checks"
    ENDPOINTS[f"{variant}-prepare"] = origin + "; check plus complete C and rename text in memory; excludes final buffer concatenation and output"
    ENDPOINTS[f"{variant}-emit"] = origin + "; check plus complete C and rename text emitted to DEVNULL; no GCC process"


def sources():
    paths = [Path(__file__).relative_to(Path.cwd())
             if Path(__file__).is_absolute() else Path(__file__), BASE_PATH,
             Path("tools/api.py")]
    for directory, pattern in (("src", "*.c"), ("include", "*.h"),
                               ("runtime", "*.c"), ("api", "*.crust"),
                               ("stages/c", "*.crust")):
        paths.extend(sorted(Path(directory).glob(pattern)))
    return {str(path): BASE.sha256(path) for path in paths}


def file_info(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "lines": data.count(b"\n"),
            "sha256": hashlib.sha256(data).hexdigest()}


def checked(command, stdout=subprocess.PIPE):
    process = BASE.run_process(command, stdout=stdout, stderr=subprocess.PIPE)
    if process.returncode != 0 or process.stderr:
        raise RuntimeError(f"Command failed or wrote a diagnostic: {command}\n"
                           + process.stderr.decode("utf-8", "replace"))
    return process.stdout


def prepare(build):
    build.mkdir(parents=True, exist_ok=True)
    frozen_makefile = build / "Makefile.frozen"
    frozen_makefile.write_bytes(Path("Makefile").read_bytes())
    seed = build / "crust-c-seed"
    optimized = build / "crust-c"
    library = build / "libcrust0.a"
    host = build / "libcrust0_host.a"
    commands = [
        ("bootstrap-compiler-and-libraries", ["make", "-f", str(frozen_makefile), "-B", "-j1", f"BUILD={build}",
                                            "CC=gcc", "CFLAGS=-O2 -g0", "all"]),
        ("stage-x64-generation", [str(build / "crust0"), "-S", "-o", str(seed) + ".s",
                                  *map(str, STAGE_SOURCES)]),
        ("stage-x64-assembly", ["as", "--64", str(seed) + ".s", "-o", str(seed) + ".o"]),
        ("stage-x64-link", ["gcc", "-no-pie", str(seed) + ".o", str(library), str(host),
                            "-o", str(seed)]),
        ("stage-self-C-generation-GCC-objcopy-link", [str(seed), "-o", str(optimized),
             *map(str, STAGE_SOURCES), "--ldflag", str(library), "--ldflag", str(host)]),
    ]
    records = []
    for name, command in commands:
        start = time.perf_counter_ns()
        output = checked(command)
        records.append({"phase": name, "command": command,
                        "wall_ns": time.perf_counter_ns() - start,
                        "stdout_sha256": hashlib.sha256(output).hexdigest()})
        print(f"Prepared {name}", flush=True)
    for binary in (seed, optimized):
        if "crust_x64_" in checked(["nm", str(binary)]).decode():
            raise RuntimeError("The C stage unexpectedly links the x64 backend")
    return {"seed": seed, "optimized": optimized}, {
        "commands": records, "flags": C_FLAGS,
        "frozen_makefile": {**file_info(frozen_makefile), "text": frozen_makefile.read_text()},
        "bootstrap_compiler_and_libraries_ns": records[0]["wall_ns"],
        "seed_stage_construction_ns": sum(row["wall_ns"] for row in records[1:4]),
        "optimized_stage_construction_ns": records[4]["wall_ns"],
        "included_in_frontend_samples": False,
        "construction_scope": "All native preparation for each stage route is included above; existing OS tools are excluded",
        "bootstrap_compiler": BASE.binary_info(build / "crust0"),
        "seed_stage_assembly": file_info(Path(str(seed) + ".s")),
        "seed_stage_object": BASE.binary_info(Path(str(seed) + ".o")),
        "linked_libraries": {str(path): BASE.binary_info(path) for path in (library, host)},
    }


def frontend_commands(workload, binaries):
    flags = [] if workload["library"] else ["-Iinclude"]
    commands = {name: [tool, "-std=c99", "-pedantic-errors", "-O0", "-g0",
                      "-fsyntax-only", *flags, str(workload["paths"]["c"])]
                for name, tool in (("gcc-syntax", "gcc"), ("clang-syntax", "clang-20"))}
    mode = ["--library"] if workload["library"] else []
    for variant, binary in binaries.items():
        for phase, option in (("check", "--check"), ("prepare", "--prepare"), ("emit", "--emit-c")):
            extra = ["--symbols", "/dev/null"] if phase == "emit" else []
            commands[f"{variant}-{phase}"] = [str(binary), *mode, option, *extra,
                                             str(workload["paths"]["crust"])]
    return commands


def preflight(workload, binaries, directory, build):
    name = workload["name"]
    emitted = {}
    mode = ["--library"] if workload["library"] else []
    for variant, binary in binaries.items():
        c_path = directory / f"{name}-{variant}.c"
        response = directory / f"{name}-{variant}.rsp"
        command = [str(binary), *mode, "--emit-c", "--symbols", str(response),
                   str(workload["paths"]["crust"])]
        with c_path.open("wb") as output:
            checked(command, stdout=output)
        emitted[variant] = {"c": c_path, "response": response, "command": command}
    for kind in ("c", "response"):
        if emitted["seed"][kind].read_bytes() != emitted["optimized"][kind].read_bytes():
            raise RuntimeError(f"The two stage builds emit different {kind} bytes for {name}")
    text = emitted["optimized"]["c"].read_text()
    definitions = len(re.findall(r"^[^;\n]*\br_g[0-9]+\([^;\n]*\)\n\{", text, re.M))
    if definitions != workload["functions"]:
        raise RuntimeError(f"Incomplete C output for {name}: {definitions} function definitions")
    original = directory / f"{name}-raw.o"
    renamed = directory / f"{name}.o"
    backend = {
        "gcc-object": ["gcc", *C_FLAGS, "-c", "-x", "c", str(emitted["optimized"]["c"]),
                       "-o", str(original)],
        "objcopy-rename": ["objcopy", "@" + str(emitted["optimized"]["response"]),
                           str(original), str(renamed)],
    }
    preflight_cost = {endpoint: BASE.measure(command) for endpoint, command in backend.items()}
    witness = None
    if not workload["library"]:
        executable = directory / f"{name}-c-stage"
        checked(["gcc", "-no-pie", str(renamed), str(build / "libcrust0_host.a"), "-o", str(executable)])
        witness = checked([str(executable)]).decode().strip()
        if witness != "intrusive: ok":
            raise RuntimeError(f"Unexpected intrusive result: {witness!r}")
    return backend, {
        "identical_seed_and_optimized_bytes": True,
        "commands": {variant: entry["command"] for variant, entry in emitted.items()},
        "c": file_info(emitted["optimized"]["c"]),
        "rename_response": file_info(emitted["optimized"]["response"]),
        "function_definitions": definitions,
        "preflight_backend_wall_ns": preflight_cost, "executable_witness": witness,
        "c_header_dependencies": BASE.dependency_manifest(
            ["gcc", *C_FLAGS, "-fsyntax-only", str(emitted["optimized"]["c"])])}


def summarize(samples, workloads, count, draws, seed):
    result = {}
    for workload in workloads:
        name = workload["name"]
        rounds = [{row["endpoint"]: row["wall_ns"] for row in samples
                   if row["workload"] == name and row["round"] == index} for index in range(count)]
        if any(set(row) != set(ENDPOINTS) for row in rounds):
            raise RuntimeError("Incomplete paired frontend sample set")
        medians = {key: statistics.median(row[key] for row in rounds) for key in ENDPOINTS}
        fastest = min(C_ENDPOINTS, key=medians.get)
        comparisons = {}
        for endpoint in STAGE_ENDPOINTS:
            rng = random.Random(f"{seed}:{name}:{endpoint}")
            ratios = []
            selections = {key: 0 for key in C_ENDPOINTS}
            for _ in range(draws):
                selected = rng.choices(rounds, k=count)
                c_medians = {key: statistics.median(row[key] for row in selected) for key in C_ENDPOINTS}
                selected_fastest = min(C_ENDPOINTS, key=c_medians.get)
                selections[selected_fastest] += 1
                ratios.append(statistics.median(row[endpoint] for row in selected) / c_medians[selected_fastest])
            ratios.sort()
            interval = [BASE.percentile(ratios, .025), BASE.percentile(ratios, .975)]
            comparisons[endpoint] = {"over_fastest_c_median_ratio": medians[endpoint] / medians[fastest],
                "paired_bootstrap_percentile_95_ci": interval, "upper_ci_at_most_one": interval[1] <= 1,
                "fastest_c_observed": fastest, "fastest_c_bootstrap_selections": selections}
        rates = {}
        for endpoint, median in medians.items():
            size = workload["paths"]["c" if endpoint in C_ENDPOINTS else "crust"].stat().st_size
            rates[endpoint] = {"source_bytes_per_second": size * 1e9 / median,
                              "source_MiB_per_second": size * 1e9 / median / 1048576,
                              "functions_per_second": workload["functions"] * 1e9 / median}
        result[name] = {"samples_per_endpoint": count,
            "median_wall_ms": {key: value / 1e6 for key, value in medians.items()},
            "min_wall_ms": {key: min(row[key] for row in rounds) / 1e6 for key in ENDPOINTS},
            "max_wall_ms": {key: max(row[key] for row in rounds) / 1e6 for key in ENDPOINTS},
            "throughput": rates, "comparisons": comparisons}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/c-stage/results.json"))
    parser.add_argument("--build-dir", type=Path, default=Path("build/c-stage-perf"))
    parser.add_argument("--inputs", type=Path, default=Path(".profile-cache/c-stage-inputs"))
    parser.add_argument("--samples", type=int, default=25)
    parser.add_argument("--backend-samples", type=int, default=5)
    parser.add_argument("--bootstrap-draws", type=int, default=10000)
    parser.add_argument("--cpu", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()
    for path in (args.output, args.build_dir, args.inputs):
        BASE.relative(path)
    if args.samples < 20 or args.backend_samples < 3 or args.bootstrap_draws < 1000:
        parser.error("Use at least 20 frontend samples, 3 backend samples, and 1000 bootstrap draws")
    if args.output.exists():
        parser.error("Output exists; select a new path")
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("The selected CPU is outside the allowed affinity set")
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This experiment requires Linux x86-64")
    os.sched_setaffinity(0, {args.cpu})
    source_hashes = sources()
    binaries, preparation = prepare(args.build_dir)
    if sources() != source_hashes:
        raise RuntimeError("Compiler or stage source changed during preparation")
    workloads = [BASE.generate(args.inputs, count) for count in (1000, 8000)]
    intrusive = Path("examples/intrusive/program.crust")
    workloads.append({"name": "intrusive", "functions": len(re.findall(r"^fn ", intrusive.read_text(), re.M)),
                      "paths": {"c": Path("benchmarks/bootstrap/intrusive.c"), "crust": intrusive}, "library": False})
    commands = {workload["name"]: frontend_commands(workload, binaries) for workload in workloads}
    toolchains = {name: BASE.tool_info(command) for name, command in
                  (("gcc", "gcc"), ("clang", "clang-20"), ("assembler", "as"),
                   ("objcopy", "objcopy"), ("linker", "ld"))}
    cc1 = BASE.capture(["gcc", "-print-prog-name=cc1"])
    toolchains["gcc"]["cc1"] = BASE.binary_info(cc1)
    toolchains["gcc"]["cc1"]["shared_libraries"] = BASE.shared_libraries(cc1)
    stage_info = {name: {**BASE.binary_info(path), "shared_libraries": BASE.shared_libraries(path)}
                  for name, path in binaries.items()}
    backend_commands, artifacts, inputs = {}, {}, {}
    for workload in workloads:
        name = workload["name"]
        inputs[name] = {"functions": workload["functions"], "library": workload["library"],
                       "sources": {kind: file_info(path) for kind, path in workload["paths"].items()},
                       "c_header_dependencies": {key: BASE.dependency_manifest(commands[name][key]) for key in C_ENDPOINTS}}
        backend_commands[name], artifacts[name] = preflight(workload, binaries, args.inputs, args.build_dir)
        print(f"Verified complete C and rename output for {name}", flush=True)
    result = {"schema": 1, "status": "running", "environment": BASE.environment(args.cpu),
        "measurement_command": ["python3", "benchmarks/c-stage/measure.py", "--output", str(args.output),
            "--build-dir", str(args.build_dir), "--inputs", str(args.inputs), "--samples", str(args.samples),
            "--backend-samples", str(args.backend_samples), "--bootstrap-draws", str(args.bootstrap_draws),
            "--cpu", str(args.cpu), "--seed", str(args.seed)],
        "method": {"frontend_samples_per_endpoint": args.samples, "backend_samples_per_endpoint": args.backend_samples,
            "bootstrap_draws": args.bootstrap_draws, "seed": args.seed, "confidence": .95,
            "randomization": "shuffle workloads each round, and frontend endpoints within each workload",
            "bootstrap": "resample complete paired frontend rounds; ratio of medians; reselect fastest C in each draw",
            "intervals": "per comparison; no simultaneous coverage claim; backend reports median and range only",
            "timing": "perf_counter_ns around fresh process launch and completion, including startup and wait",
            "output": "frontend stdout and rename output go to DEVNULL; backend object files use the warm local filesystem",
            "warmup": "one discarded run per frontend command; backend preflight is its discarded warmup",
            "os_file_cache": "warm; no cache eviction", "compiler_cache": "none",
            "cpu_affinity": "controller and descendants pinned to one logical CPU; CPU is not reserved",
            "stage_preparation": "recorded separately; excluded from installed-stage samples; cold custom stages must add preparation",
            "backend_boundary": "prepare includes all C and rename text in separate memory buffers; emit also concatenates and writes them; GCC starts from saved exact C",
            "backend_scope": "GCC parsing generated C, optimization, machine lowering, assembly and object write; objcopy is measured separately; link excluded",
            "comparison_scope": "equivalent ordinary source functions and direct intrusive witness; no checked-language speed claim",
            "required_speed_gate": "optimized-emit upper 95% ratio bound <= 1 against fastest C syntax check for each workload"},
        "source_sha256": source_hashes, "preparation": preparation, "toolchains": toolchains,
        "stage_binaries": stage_info, "endpoints": ENDPOINTS, "commands": commands,
        "backend_commands": backend_commands, "inputs": inputs, "artifacts": artifacts,
        "warmups": [], "samples": [], "backend_samples": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    BASE.save(args.output, result)
    for name, endpoints in commands.items():
        for endpoint, command in endpoints.items():
            result["warmups"].append({"workload": name, "endpoint": endpoint, "wall_ns": BASE.measure(command)})
    rng = random.Random(args.seed)
    for index in range(args.samples):
        order = list(commands)
        rng.shuffle(order)
        for name in order:
            endpoints = list(commands[name])
            rng.shuffle(endpoints)
            for endpoint in endpoints:
                result["samples"].append({"round": index, "sequence": len(result["samples"]),
                    "workload": name, "endpoint": endpoint, "wall_ns": BASE.measure(commands[name][endpoint])})
        BASE.save(args.output, result)
        print(f"Frontend paired round {index + 1}/{args.samples}", flush=True)
    print("Frontend timing complete; measuring GCC and object renaming", flush=True)
    for index in range(args.backend_samples):
        order = list(backend_commands)
        rng.shuffle(order)
        for name in order:
            for endpoint, command in backend_commands[name].items():
                result["backend_samples"].append({"round": index, "sequence": len(result["backend_samples"]),
                    "workload": name, "endpoint": endpoint, "wall_ns": BASE.measure(command)})
        BASE.save(args.output, result)
        print(f"Backend paired round {index + 1}/{args.backend_samples}", flush=True)
    if sources() != source_hashes:
        raise RuntimeError("Compiler, stage, or harness source changed during measurement")
    for name, path in binaries.items():
        if BASE.binary_info(path) != {key: stage_info[name][key] for key in ("file_name", "bytes", "sha256")}:
            raise RuntimeError("Stage binary changed during measurement")
        if BASE.shared_libraries(path) != stage_info[name]["shared_libraries"]:
            raise RuntimeError("Stage shared libraries changed during measurement")
    for workload in workloads:
        name = workload["name"]
        for kind, path in workload["paths"].items():
            if file_info(path) != inputs[name]["sources"][kind]:
                raise RuntimeError("Workload source changed during measurement")
        for kind in ("c", "rename_response"):
            if file_info(Path(artifacts[name][kind]["path"])) != artifacts[name][kind]:
                raise RuntimeError("Generated backend input changed during measurement")
        for endpoint in C_ENDPOINTS:
            if BASE.dependency_manifest(commands[name][endpoint]) != inputs[name]["c_header_dependencies"][endpoint]:
                raise RuntimeError("C workload dependency changed during measurement")
    for name, metadata in toolchains.items():
        current = BASE.tool_info(metadata["command"])
        if any(current[key] != metadata[key] for key in ("sha256", "shared_libraries")):
            raise RuntimeError("A native tool changed during measurement")
    if (BASE.binary_info(cc1)["sha256"] != toolchains["gcc"]["cc1"]["sha256"] or
            BASE.shared_libraries(cc1) != toolchains["gcc"]["cc1"]["shared_libraries"]):
        raise RuntimeError("GCC frontend changed during measurement")
    result["summary"] = summarize(result["samples"], workloads, args.samples, args.bootstrap_draws, args.seed)
    failed = [name for name, summary in result["summary"].items()
              if not summary["comparisons"]["optimized-emit"]["upper_ci_at_most_one"]]
    result["speed_gate"] = {"endpoint": "optimized-emit", "passed": not failed, "failed_workloads": failed}
    result["backend_summary"] = {}
    for name in backend_commands:
        result["backend_summary"][name] = {}
        for endpoint in backend_commands[name]:
            values = [row["wall_ns"] for row in result["backend_samples"]
                      if row["workload"] == name and row["endpoint"] == endpoint]
            result["backend_summary"][name][endpoint] = {"samples": len(values),
                "median_wall_ms": statistics.median(values) / 1e6,
                "min_wall_ms": min(values) / 1e6, "max_wall_ms": max(values) / 1e6}
    result["environment"]["load_end"] = Path("/proc/loadavg").read_text().split()[:3]
    result["status"] = "complete"
    BASE.save(args.output, result)
    print(json.dumps({"summary": result["summary"], "backend_summary": result["backend_summary"]}, indent=2))
    if failed:
        raise SystemExit("The complete C output speed gate failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
