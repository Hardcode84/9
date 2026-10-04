#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure the ownership generic tutorial against its handwritten provider."""

import argparse
import json
import platform
import random
import re
import shlex
import statistics
import time
from pathlib import Path

from generics_cost import fingerprint, run
from ownership_support import execute
from source_order import ROOT

PHASES = (
    "read_ns",
    "generic_proof_ns",
    "specialization_ns",
    "seed_and_cleanup_ns",
    "arguments_ns",
    "ownership_ns",
    "emit_ns",
    "destroy_ns",
)
METRICS = (
    "input_io_ns",
    "arena_bytes",
    "requests",
    "hits",
    "specializations",
    "proof_checks",
    "proof_arena_bytes",
)
INPUTS = {
    "generic": ("provider", "checked", "payloads", "program"),
    "handwritten": ("trusted-handwritten", "handwritten"),
}


def prepare(args, work):
    rule = "ownership-generic-cost-sources: ; @echo $(GENERIC_OWNERSHIP)"
    result = run(
        ["make", "--no-print-directory", "-s", "--eval", rule, "ownership-generic-cost-sources"]
    )
    sources = [ROOT / path for path in result.stdout.split()]
    sources.append(ROOT / "tests/ownership_generics_cost.crs")
    clock_source = ROOT / "benchmarks/ownership/clock_linux_x64.c"
    clock = work / "clock.o"
    binary = work / "ownership-generics-cost"
    cflags = shlex.split(args.cflags)
    commands = [
        [
            *shlex.split(args.cc),
            *cflags,
            "-std=c99",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-c",
            str(clock_source),
            "-o",
            str(clock),
        ]
    ]
    links = [clock, args.build / "libcrust0.a", args.build / "libcrust0_host.a"]
    compiler = [str(args.build / "crust-c"), "-o", str(binary), *map(str, sources)]
    compiler += [item for flag in cflags for item in ("--cflag", flag)]
    compiler += [
        item
        for flag in [*map(str, links), *shlex.split(args.ldflags)]
        for item in ("--ldflag", flag)
    ]
    commands.append(compiler)
    start = time.perf_counter_ns()
    for command in commands:
        run(command)
    return binary, {
        "commands": commands,
        "wall_ns": time.perf_counter_ns() - start,
        "sha256": {str(path): fingerprint(path) for path in [*sources, clock_source, *links[1:]]},
        "gcc": run(["gcc", "--version"]).stdout.splitlines()[0],
    }


def capture(work):
    directory = work / "inputs"
    directory.mkdir()
    result = {}
    for mode, names in INPUTS.items():
        result[mode] = []
        for name in names:
            source = ROOT / f"examples/generics/ownership/{name}.crs"
            target = directory / source.name
            target.write_bytes(source.read_bytes())
            result[mode].append(target)
    return result


def measure(command):
    start = time.perf_counter_ns()
    result = run(command)
    wall = time.perf_counter_ns() - start
    if result.stderr:
        raise RuntimeError(result.stderr)
    layouts, names, values = {}, {}, None
    for line in result.stdout.splitlines():
        fields = line.split()
        if fields[0] == "record":
            layouts[fields[1]] = [int(value) for value in fields[2:]]
        elif fields[0] in ("function", "type"):
            prefix = "r_g" if fields[0] == "function" else "r_t"
            names[prefix + fields[1]] = fields[2]
        elif fields[0] == "times":
            values = [int(value) for value in fields[1:]]
        else:
            raise RuntimeError(f"unexpected driver output: {line}")
    if values is None or len(values) != len(PHASES) + len(METRICS):
        raise RuntimeError(f"unexpected phase report: {result.stdout}")
    metrics = dict(zip((*PHASES, *METRICS), values, strict=True))
    metrics["process_wall_ns"] = wall
    metrics["frontend_ns"] = sum(metrics[name] for name in PHASES[:6])
    if metrics["requests"] != metrics["hits"] + metrics["specializations"]:
        raise RuntimeError(f"inconsistent specialization counts: {metrics}")
    if command[1] == "generic" and metrics["proof_checks"] != 2:
        raise RuntimeError(f"expected one check each for transfer and discard: {metrics}")
    return metrics, layouts, names


def normalized_bodies(source, names):
    names = dict(names)
    for match in re.finditer(r"^typedef (.+?) \(\*(r_t[0-9]+)\)\((.*)\);$", source, re.MULTILINE):
        signature = match[1] + "(" + match[3] + ")"
        names[match[2]] = re.sub(r"\br_t[0-9]+\b", lambda item: names[item.group()], signature)
    result = {}
    headers = re.finditer(r"^([^\n;{}]*\b(r_g[0-9]+)\([^\n]*\))\n\{", source, re.MULTILINE)
    for match in headers:
        start = match.start()
        end = match.end()
        depth = 1
        while depth:
            depth += (source[end] == "{") - (source[end] == "}")
            end += 1
        body = source[start:end]
        body = re.sub(r"\br_[gt][0-9]+\b", lambda item: names[item.group()], body)
        local = {}

        def rename(item, local=local):
            text = item.group()
            if text not in local:
                local[text] = "local_" + str(len(local))
            return local[text]

        body = re.sub(r"\b(?:r_[lv]|rs_exit_)[0-9]+\b", rename, body)
        result[names[match[2]]] = body
    if not result:
        raise RuntimeError("no generated function definitions found")
    return result


def machine_instructions(source, symbol, names):
    start = source.index(symbol + ":\n") + len(symbol) + 2
    end = source.index("\n\t.size\t" + symbol + ",", start)
    labels, instructions = {}, []
    for line in source[start:end].splitlines():
        line = line.strip()
        if line.endswith(":"):
            labels[line[:-1]] = len(instructions)
        elif line and not line.startswith("."):
            instructions.append(" ".join(line.split()))
    result = []
    for line in instructions:
        line = re.sub(r"\br_g[0-9]+\b", lambda item: names[item.group()], line)
        line = re.sub(r"\.L[0-9]+\b", lambda item: "instruction_" + str(labels[item.group()]), line)
        result.append(line)
    return result


def compare_bodies(work, bodies, names):
    mismatches = [
        name for name, body in bodies["generic"].items() if body != bodies["handwritten"].get(name)
    ]
    commands, assembly = [], {}
    if mismatches:
        for mode in bodies:
            output = work / f"{mode}.s"
            command = [
                "gcc",
                "-std=c99",
                "-pedantic-errors",
                "-O0",
                "-S",
                "-fno-asynchronous-unwind-tables",
                "-fno-unwind-tables",
                str(work / f"{mode}.c"),
                "-o",
                str(output),
            ]
            run(command)
            commands.append(command)
            assembly[mode] = output.read_text()
        for name in mismatches:
            observed = {}
            for mode in bodies:
                inverse = {value: key for key, value in names[mode].items()}
                if name not in inverse:
                    raise RuntimeError(f"generated function has no handwritten equivalent: {name}")
                observed[mode] = machine_instructions(assembly[mode], inverse[name], names[mode])
            if observed["generic"] != observed["handwritten"]:
                (work / "function-bodies.json").write_text(json.dumps(bodies, indent=2) + "\n")
                raise RuntimeError(f"generated operations differ: {name}: {observed}")
    return {
        "equal_normalized_c_bodies": len(bodies["generic"]) - len(mismatches),
        "equal_o0_instruction_bodies": mismatches,
        "unused_handwritten_functions_not_specialized": sorted(
            set(bodies["handwritten"]) - set(bodies["generic"])
        ),
        "untimed_commands": commands,
    }


def run_samples(args, work, binary, captured):
    commands = {
        mode: [
            str(binary),
            mode,
            "measured",
            str(work / f"{mode}.c"),
            str(work / f"{mode}.rsp"),
            *map(str, sources),
        ]
        for mode, sources in captured.items()
    }
    layouts, erasure, bodies, bindings = {}, {}, {}, {}
    for mode, command in commands.items():
        before = [*command[:2], "erasure", *command[3:]]
        _, layouts[mode], bindings[mode] = measure(before)
        bodies[mode] = normalized_bodies(Path(command[3]).read_text(), bindings[mode])
        erasure[mode] = {
            "command": before,
            "c_sha256": fingerprint(Path(command[3])),
            "symbols_sha256": fingerprint(Path(command[4])),
        }
        execute(Path(command[3]), Path(command[4]), work, mode, args.sanitize, b"HFBFOK\n")
    if layouts["generic"] != layouts["handwritten"]:
        raise RuntimeError(f"record layout mismatch: {layouts}")
    comparison = compare_bodies(work, bodies, bindings)
    samples = []
    rng = random.Random(0)
    for _ in range(args.samples):
        order = list(commands)
        rng.shuffle(order)
        pair = {}
        for mode in order:
            pair[mode], observed, _ = measure(commands[mode])
            if (
                observed != layouts[mode]
                or fingerprint(Path(commands[mode][3])) != erasure[mode]["c_sha256"]
            ):
                raise RuntimeError(f"compiler output changed across fresh compilations: {mode}")
        pair["frontend_ratio"] = pair["generic"]["frontend_ns"] / pair["handwritten"]["frontend_ns"]
        samples.append(pair)
    return commands, erasure, layouts, samples, comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--work", type=Path, default=ROOT / "build/ownership-generics-cost")
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--cflags", default="-O2 -g")
    parser.add_argument("--ldflags", default="")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    args.build = args.build.resolve()
    work = args.work.resolve()
    if args.samples < 1:
        parser.error("samples must be positive")
    if work.exists() or not work.is_relative_to(ROOT / "build"):
        parser.error("select a new work directory under ignored build/ to retain earlier reports")
    work.mkdir(parents=True)
    captured = capture(work)
    binary, preparation = prepare(args, work)
    commands, erasure, layouts, samples, comparison = run_samples(args, work, binary, captured)
    report = {
        "scope": (
            "Fresh native compiler process for each input pair. Input file reads precede compiler clocks. "
            "Read includes context setup, parsing, and generic source copies. Generic proof checks all "
            "parameter contracts and untrusted template bodies. Specialization includes family domain "
            "expansion. Seed and cleanup includes collection, resolution, resource lowering, and seed "
            "checks. Argument validation is separate. Ownership verifies ordinary application bodies. "
            "C emission writes in-memory buffers; output file writes and teardown are outside frontend "
            "and emission clocks. Output binding setup is outside phase clocks. Each erasure run compares exact C header, body, and native symbol "
            "buffers before and after ownership verification. Handwritten sources use OsStage directly. "
            "All record layouts match. Generated C bodies are compared after type/function and "
            "local name normalization. Differences require equal O0 instruction streams, with local "
            "assembly branch labels resolved to instruction positions. This assembly check is untimed. "
            "Unused handwritten helper definitions may be absent from demand specialization. "
            "The two inputs execute the same cleanup sequence. "
            "Proof workspace is destroyed inside proof time; proof arena bytes are reported separately "
            "from retained output context arenas and exclude borrowed source storage. "
            "Target GCC compilation and linking happen only in untimed runtime and instruction checks."
        ),
        "machine": platform.platform(),
        "preparation": preparation,
        "commands": commands,
        "input_sha256": {
            str(path): fingerprint(path) for sources in captured.values() for path in sources
        },
        "erasure": erasure,
        "layouts": layouts,
        "function_operations": comparison,
        "runtime_stdout": "HFBFOK\n",
        "runtime_optimizations": ["-O0", "-O2"],
        "samples": samples,
        "median_frontend_ratio": statistics.median(row["frontend_ratio"] for row in samples),
        "median_ns": {
            mode: {
                phase: statistics.median(row[mode][phase] for row in samples)
                for phase in (*PHASES, "frontend_ns")
            }
            for mode in commands
        },
    }
    path = work / "report.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"report: {path}")
    print(f"median generic/handwritten frontend: {report['median_frontend_ratio']:.3f}")
    print(
        "identical ownership proof output; equal function operations and record layouts; runtime HFBFOK"
    )


if __name__ == "__main__":
    main()
