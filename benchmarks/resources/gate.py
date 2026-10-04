#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare complete resource requests with matched C interfaces and frontend IR."""

import argparse
import contextlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

import measure as R

ROOT = R.ROOT
sys.path.insert(0, str(ROOT / "benchmarks/source-order"))
SPEC = importlib.util.spec_from_file_location(
    "application_gate", ROOT / "benchmarks/source-order/gate.py"
)
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


def matched_sqlite(work):
    header = ROOT / "benchmarks/resources/ffi.h"
    probe = work / "ffi-check.c"
    probe.write_text(
        '#include <stdlib.h>\n#include <unistd.h>\n#include "sqlite3.h"\n' f'#include "{header}"\n'
    )
    R.run(
        [
            "gcc",
            "-std=c99",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I.profile-cache/sources",
            "-fsyntax-only",
            probe,
        ]
    )
    common = (ROOT / "benchmarks/resources/common.h").read_text()
    common, count = re.subn(r"^#include [^\n]+\n", "", common, flags=re.M)
    if count != 5:
        raise RuntimeError("SQLite control includes changed")
    declarations = (
        "typedef unsigned long size_t;\ntypedef long ssize_t;\n"
        "typedef unsigned long uint64_t;\ntypedef struct sqlite3 sqlite3;\n"
        "typedef struct sqlite3_stmt sqlite3_stmt;\n#define NULL ((void *)0)\n"
    )
    (work / "common.h").write_text(declarations + '#include "ffi.h"\n' + common)
    shutil.copyfile(header, work / "ffi.h")
    for name in ("direct", "callbacks"):
        shutil.copyfile(ROOT / f"benchmarks/resources/{name}.c", work / f"{name}.c")
    return probe


def root_source(work, build):
    root = work / "root.crs"
    root.write_text(
        "\n".join(
            [
                f'host_source(run, {json.dumps(str(ROOT / "api/crust0_stage.crs"))});',
                f'host_source(run, {json.dumps(str(ROOT / "stages/resources/api.crs"))});',
                f'host_link(run, {json.dumps(str(build / "crust-resource-library.so"))});',
                "return resource_build(null(*CrustSource), 0usize, (*run).argc, (*run).argv);",
                "",
            ]
        )
    )
    return root


def compile_output(output, symbols, executable, libraries):
    raw = output.with_suffix(".o")
    renamed = output.with_suffix(".renamed.o")
    commands = [
        [
            "gcc",
            "-std=c99",
            "-pedantic-errors",
            "-O2",
            "-g0",
            "-Wno-overlength-strings",
            "-c",
            output,
            "-o",
            raw,
        ],
        ["objcopy", "@" + str(symbols), raw, renamed],
        ["gcc", renamed, *libraries, "-o", executable],
    ]
    for command in commands:
        R.run(command)
    return [list(map(str, command)) for command in commands]


def sqlite_runtime(executables, baseline):
    fixtures = Path(".profile-cache/resources-baseline")
    arguments = {
        "values": [fixtures / "normal.db"],
        "empty-table": [fixtures / "empty.db"],
        "open-failure": [fixtures / "missing-parent/input.db"],
        "prepare-failure": [fixtures / "missing-table.db"],
        "step-and-finalize-failure": [fixtures / "step-failure.db"],
        "usage": [],
        "output-failure": [fixtures / "normal.db"],
    }
    # The frozen verifier is the authority for fixture paths, exit status, and bytes.
    checks = 0
    for case in baseline["cases"]:
        name = case["name"]
        if name not in arguments:
            continue
        for executable in executables:
            with (
                open("/dev/full", "wb")
                if name == "output-failure"
                else contextlib.nullcontext(subprocess.PIPE)
            ) as output:
                result = subprocess.run(
                    [str(executable), *map(str, arguments[name])],
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
            if (result.returncode, result.stdout or b"", result.stderr) != (
                case["status"],
                b"" if name == "output-failure" else case["stdout"].encode(),
                case["stderr"].encode(),
            ):
                raise RuntimeError(
                    (name, executable, result.returncode, result.stdout, result.stderr)
                )
            checks += 1
    if checks != len(arguments) * len(executables):
        raise RuntimeError("SQLite baseline fixture set changed")
    return checks


def prepare(work, build, root, name, sources, controls, baseline=None, expected=None):
    output, symbols = work / f"{name}.generated.c", work / f"{name}.rsp"
    exports = [] if baseline else ["--export", "token_drop", "--export", "workload"]
    prefix = [str(build / "crust"), str(root), *exports, *map(str, sources)]
    commands = {
        "check": [*prefix, "--check"],
        "handoff": [*prefix, "--emit-c", "-o", str(output), "--symbols", str(symbols)],
    }
    dependencies = {}
    for label, control in controls.items():
        for compiler in ("gcc", "clang-20"):
            route = ("gcc" if compiler == "gcc" else "clang") + label
            commands[route] = [
                compiler,
                "-std=c99",
                "-pedantic-errors",
                "-O0",
                "-g0",
                "-I.profile-cache/sources",
                "-fsyntax-only",
                str(control),
            ]
            dependencies[route] = R.c_inputs(commands[route])
        commands["clang_ir" + label] = [
            "clang-20",
            "-std=c99",
            "-pedantic-errors",
            "-O0",
            "-g0",
            "-I.profile-cache/sources",
            str(control),
            "-S",
            "-emit-llvm",
            "-Xclang",
            "-disable-llvm-passes",
            "-o",
            str(work / f"{name}{label}.ll"),
        ]
    for command in commands.values():
        R.run(command)
    libraries = (
        [str(ROOT / ".profile-cache/resources-baseline/sqlite3.o"), "-ldl", "-lm", "-pthread"]
        if baseline
        else []
    )
    executables = [work / f"{name}.crust"]
    compilation = compile_output(output, symbols, executables[0], libraries)
    for label, control in controls.items():
        executable = work / f"{name}{label}.c-program"
        command = [
            "gcc",
            "-std=c99",
            "-pedantic-errors",
            "-O2",
            "-g0",
            "-I.profile-cache/sources",
            str(control),
            *libraries,
            "-o",
            str(executable),
        ]
        R.run(command)
        compilation.append(command)
        executables.append(executable)
    if baseline:
        checks = sqlite_runtime(executables, baseline)
    else:
        for executable in executables:
            result = R.run([executable])
            if result.stdout != expected or result.stderr:
                raise RuntimeError((executable, result.stdout, result.stderr))
        checks = len(executables)
    files = [*sources, *controls.values(), output, symbols, *work.glob(f"{name}*.ll")]
    facts = {
        "files": {str(path): G.M.file_info(path) for path in files},
        "dependencies": dependencies,
        "runtime_checks": checks,
        "target_build_commands": compilation,
        "outputs": {str(path): R.sha(path) for path in (output, symbols)},
        "llvm_definitions": {
            str(path): len(re.findall(r"^define ", path.read_text(), re.M))
            for path in work.glob(f"{name}*.ll")
        },
    }
    if not all(facts["llvm_definitions"].values()):
        raise RuntimeError("Clang emitted no function definitions")
    if not baseline:
        facts["cleanup"] = R.cleanup_sites(output.read_text(), symbols.read_text())
    return commands, facts


def columns(build, work, rounds):
    source = ROOT / "benchmarks/resources/columns.crs"
    control = ROOT / "benchmarks/resources/columns.c"
    output, symbols = work / "columns.generated.c", work / "columns.rsp"
    library = ROOT / "examples/resources/sqlite/library.crs"
    sqlite = ROOT / ".profile-cache/resources-baseline/sqlite3.o"
    libraries = [str(sqlite), "-ldl", "-lm", "-pthread"]
    c_binary, crs_binary = work / "columns-c", work / "columns-crust"
    commands = [
        [
            str(build / "crust-resource"),
            str(library),
            str(source),
            "--emit-c",
            "-o",
            str(output),
            "--symbols",
            str(symbols),
        ],
        [
            "gcc",
            "-std=c99",
            "-pedantic-errors",
            "-O2",
            "-g0",
            "-I.profile-cache/sources",
            str(control),
            *libraries,
            "-o",
            str(c_binary),
        ],
    ]
    for command in commands:
        R.run(command)
    commands += compile_output(output, symbols, crs_binary, libraries)
    for binary in (c_binary, crs_binary):
        result = R.run([binary])
        if result.stdout != b"rows 60000000\n" or result.stderr:
            raise RuntimeError((binary, result.stdout, result.stderr))
        assembly = binary.with_suffix(".asm")
        assembly.write_bytes(R.run(["objdump", "-d", binary]).stdout)
    rng = random.Random(491)
    samples = []
    for _ in range(rounds):
        modes = ["c", "crust"]
        rng.shuffle(modes)
        samples.append({mode: R.timed([c_binary if mode == "c" else crs_binary]) for mode in modes})
    ratio = R.paired_stats(
        [{mode: sample["wall_ns"] for mode, sample in row.items()} for row in samples],
        "c",
        "crust",
        491,
    )
    ratio["pass"] = ratio["ratio_of_medians"] <= 1 and ratio["bootstrap_95_percent"][1] <= 1
    return {
        "commands": commands,
        "samples": samples,
        "ratio": ratio,
        "hashes": {
            str(path): R.sha(path)
            for path in (source, control, output, symbols, c_binary, crs_binary)
        },
        "checksum": 60000000,
        "column_reads": 500000,
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "scope": "In-memory SQLite row, validated column view, synchronous checksum callback, finalization and close; one summary output after the hot loop.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument(
        "--baseline", type=Path, default=ROOT / "build/benchmarks/resources/baseline.json"
    )
    parser.add_argument("--cpu", type=int, default=6)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Measure the column checksum instead of frontend work",
    )
    args = parser.parse_args()
    if args.rounds < 20 or args.work.exists():
        parser.error("use at least 20 rounds and a new work directory")
    os.chdir(ROOT)
    os.sched_setaffinity(0, {args.cpu})
    work, build = args.work.resolve(), args.build.resolve()
    work.mkdir(parents=True)
    if args.runtime:
        report = columns(build, work, args.rounds)
        report["environment"] = G.B.environment(args.cpu)
        report["command"] = sys.argv
        (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(report["ratio"])
        if not report["ratio"]["pass"]:
            raise SystemExit(2)
        return
    matched_sqlite(work)
    root = root_source(work, build)
    baseline_path = args.baseline.resolve()
    baseline = json.loads(baseline_path.read_text())
    for path, digest in baseline["source_sha256"].items():
        if R.sha(path) != digest:
            raise RuntimeError("Frozen SQLite baseline changed: " + path)
    configurations = [
        (
            "sqlite",
            [
                ROOT / "examples/resources/sqlite/library.crs",
                ROOT / "examples/resources/sqlite/program.crs",
            ],
            {
                "": work / "direct.c",
                "-callback": work / "callbacks.c",
                "-full-direct": ROOT / "benchmarks/resources/direct.c",
                "-full-callback": ROOT / "benchmarks/resources/callbacks.c",
            },
            baseline,
            None,
        )
    ]
    for count in (16, 64, 256):
        source, control, expected = R.stress_source(count)
        crs, c = work / f"owners-{count}.crs", work / f"owners-{count}.c"
        crs.write_text(source)
        c.write_text(control)
        configurations.append((f"owners-{count}", [crs], {"": c}, None, expected))
    report = {
        "revision": G.B.capture(["git", "rev-parse", "HEAD"]),
        "environment": G.B.environment(args.cpu),
        "command": sys.argv,
        "build_flags": G.B.capture(["make", "-s", "ownership-benchmark-config"]),
        "tools": {name: G.B.tool_info(name) for name in ("gcc", "clang-20", "objcopy")},
        "method": {
            "rounds": args.rounds,
            "seed": 417,
            "workers": 1,
            "endpoint": "Fresh root, interfaces, DSO loading, source checks and complete C/symbol file output; final GCC/linking excluded.",
            "interfaces": "Used SQLite/POSIX declarations on both sides; C declarations checked against pinned real headers before timing. Ordinary full-header C is reported separately.",
            "policy": "Resource checking and cleanup; trusted unsafe SQLite wrappers. Optional checking has a measured cost and no automatic C-speed claim.",
            "cache": "Compiled stage, warm filesystem, no application result cache.",
        },
        "commands": {},
        "preflight": {},
        "samples": [],
    }
    for name, sources, controls, baseline_data, expected in configurations:
        commands, facts = prepare(
            work, build, root, name, sources, controls, baseline_data, expected
        )
        report["commands"][name], report["preflight"][name] = commands, facts
    frozen = G.M.source_hashes()
    for path in [
        *work.glob("*.crs"),
        *work.glob("*.h"),
        *work.glob("*.c"),
        *[
            path
            for path in Path("benchmarks/resources").iterdir()
            if path.suffix in (".c", ".h", ".crs", ".py")
        ],
        baseline_path,
        ROOT / ".profile-cache/sources/sqlite3.h",
        ROOT / ".profile-cache/resources-baseline/sqlite3.o",
        build / "crust",
        build / "crust-resource-library.so",
    ]:
        frozen[str(path)] = R.sha(path)
    frozen[str(Path(G.__file__).resolve())] = R.sha(G.__file__)
    report["hashes"] = frozen
    report["captured_inputs"] = {}
    for path, digest in frozen.items():
        original = Path(path).resolve()
        relative = (
            original.relative_to(ROOT)
            if original.is_relative_to(ROOT)
            else Path("system") / str(original).lstrip("/")
        )
        capture = work / "captured" / relative
        capture.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, capture)
        if R.sha(capture) != digest:
            raise RuntimeError("Input changed during capture: " + path)
        report["captured_inputs"][path] = str(capture)
    rng = random.Random(417)
    for index in range(args.rounds):
        names = list(report["commands"])
        rng.shuffle(names)
        for name in names:
            order = list(report["commands"][name])
            rng.shuffle(order)
            values = {route: R.timed(report["commands"][name][route]) for route in order}
            report["samples"].append({"round": index, "workload": name, "values": values})
            for path, digest in report["preflight"][name]["outputs"].items():
                if R.sha(path) != digest:
                    raise RuntimeError("Output changed: " + path)
        print(f"paired round {index + 1}/{args.rounds}", flush=True)
    report["summary"] = {}
    for name, _, controls, _, _ in configurations:
        rows = [row["values"] for row in report["samples"] if row["workload"] == name]
        report["summary"][name] = {}
        for label in controls:
            selected = [
                {
                    key: row[key + label] if key in ("gcc", "clang", "clang_ir") else row[key]
                    for key in ("check", "handoff", "gcc", "clang", "clang_ir")
                }
                for row in rows
            ]
            report["summary"][name][label or "direct"] = G.summary(selected, name + label) | {
                "matched_interfaces": not label.startswith("-full-")
            }
    for path, digest in frozen.items():
        if R.sha(path) != digest:
            raise RuntimeError("Input changed during measurement: " + path)
    report["frontend_pass"] = all(
        ratio["pass"]
        for cases in report["summary"].values()
        for label, case in cases.items()
        if case["matched_interfaces"]
        for ratio in case["ratios"].values()
    )
    (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))
    if not report["frontend_pass"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
