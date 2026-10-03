#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure fresh compilation of wide and deep module graphs with native stages."""

import argparse
import concurrent.futures
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
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "source_measure", ROOT / "benchmarks/source-order/measure.py"
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
B = M.BASE


def generate(directory, count, functions, deep):
    # Keep the direct list operations identical to the executable seed witness.
    provider = (ROOT / "examples/intrusive/raw.crs").read_text()
    hook = provider[provider.index("record Hook") : provider.index("record Node")]
    bodies = provider[provider.index("fn init") : provider.index("fn node_of")]
    (directory / "provider.crs").write_text(hook + bodies)
    (directory / "provider.h").write_text(
        "typedef struct Hook Hook;\nstruct Hook {Hook *prev;Hook *next;};\n"
        "void bench_init(Hook*);void bench_insert(Hook*,Hook*);void bench_unlink(Hook*);\n"
    )
    c = (ROOT / "benchmarks/bootstrap/intrusive.c").read_text()
    bodies = c[c.index("static void init") : c.index("static Node *node_of")]
    bodies = bodies.replace("static void", "void").replace("init(", "bench_init(")
    bodies = bodies.replace("insert_after(", "bench_insert(").replace(
        "unlink_node(", "bench_unlink("
    )
    (directory / "provider.c").write_text('#include "provider.h"\n' + bodies)
    expected = []
    for i in range(count):
        c = ['#include "provider.h"\n']
        crust = []
        if deep and i:
            c.append(f"unsigned long work_{i-1}(void);\n")
        for j in range(functions):
            c.append(
                f"static unsigned long step_{j}(unsigned long x){{if(x>{j}ul)return x+1ul;return x ^ {j}ul;}}\n"
            )
            crust.append(
                f"fn step_{j}(x:u64)->u64{{if x>{j}u64 {{return x+1u64;}} return x ^ {j}u64;}}\n"
            )
        initial_c, initial_crust = f"{i}ul", f"{i}u64"
        value = i
        if deep and i:
            initial_c, initial_crust = f"work_{i-1}()", f"work_{i-1}()"
            value = expected[-1]
        c.append(
            f"unsigned long work_{i}(void){{Hook head,node;unsigned long value={initial_c};\n"
            "bench_init(&head);bench_init(&node);bench_insert(&head,&node);\n"
            "if(head.next!=&node || node.prev!=&head)return 1000000;bench_unlink(&node);\n"
            "if(head.next!=&head || head.prev!=&head)return 2000000;\n"
        )
        crust.append(
            f"fn work_{i}()->u64 {{var head:Hook=uninit;var node:Hook=uninit;var value:u64={initial_crust};\n"
            "init(&head);init(&node);insert_after(&head,&node);\n"
            "if head.next!=&node || node.prev!=&head {return 1000000u64;} unlink(&node);\n"
            "if head.next!=&head || head.prev!=&head {return 2000000u64;}\n"
        )
        for j in range(functions):
            c.append(f"value=step_{j}(value);\n")
            crust.append(f"value=step_{j}(value);\n")
            value = value + 1 if value > j else value ^ j
        c.append("return value;}\n")
        crust.append("return value;}\n")
        expected.append(value)
        (directory / f"job-{i}.c").write_text("".join(c))
        (directory / f"job-{i}.crs").write_text("".join(crust))
    c = ["extern int puts(const char*);\n"]
    crust = ['extern fn puts(text:*u8)->i32="puts";\n']
    for i in range(count):
        c.append(f"unsigned long work_{i}(void);\n")
        crust.append(f'extern fn work_{i}()->u64="work_{i}";\n')
    c.append("int main(void){\n")
    crust.append("fn main(argc:i32,argv:**u8)->i32{\n")
    for i, value in enumerate(expected):
        c.append(f"if(work_{i}()!={value}ul)return 1;\n")
        crust.append(f"if work_{i}()!={value}u64 {{return 1i32;}}\n")
    c.append('if(puts("parallel: ok")<0)return 2;return 0;}\n')
    crust.append('if puts("parallel: ok")<0i32 {return 2i32;}return 0i32;}\n')
    (directory / "main.c").write_text("".join(c))
    (directory / "main.crs").write_text("".join(crust))


def root_file(directory, library, workers, count, check, deep):
    quote = M.crust_string
    arguments = [
        directory / "provider.crs",
        directory / "provider.out.c",
        directory / "provider.rsp",
    ]
    for i in range(count):
        arguments += [
            directory / f"job-{i}.crs",
            directory / f"job-{i}.out.c",
            directory / f"job-{i}.rsp",
            f"work_{i}",
        ]
    source = directory / f"root-{workers}-{'check' if check else 'handoff'}.crs"
    source.write_text(
        f"host_link(run,{quote(library)});\n"
        'extern fn compile_graph(ctx:*CrustContext,workers:usize,count:usize,arguments:**u8,check:bool,deep:bool)->i32="compile_graph";\n'
        f"var arguments:[*u8;{len(arguments)}]=make [*u8;{len(arguments)}]{{{','.join(map(quote,arguments))}}};\n"
        f"return compile_graph((*run).context,{workers}usize,{count}usize,&arguments[0usize],{str(check).lower()},{str(deep).lower()});\n"
    )
    return source


def build_driver(build, directory):
    library = directory / "driver.so"
    sources = [
        ROOT / p
        for p in (
            "api/crust0.crs",
            "api/crust0_host.crs",
            "api/crust0_eval.crs",
            "api/crust0_run.crs",
            "api/crust0_stage.crs",
            "stages/c/api.crs",
            "stages/modules/library.crs",
            "stages/parallel/model.crs",
            "stages/parallel/api.crs",
            "benchmarks/parallel/driver.crs",
        )
    ]
    command = [
        str(build / "crust-c"),
        "--library",
        "--export",
        "compile_graph",
        "--cflag=-O2",
        "--cflag=-g",
        "--cflag=-fPIC",
        "--cflag=-fno-semantic-interposition",
        "--ldflag=-shared",
        "--ldflag=-Wl,-Bsymbolic,-z,text,-z,relro,-z,now",
        "--ldflag=" + str(build / "crust-c-library.so"),
        "--ldflag=" + str(build / "crust-parallel-library.so"),
        "-o",
        str(library),
        *map(str, sources),
    ]
    start = time.perf_counter_ns()
    M.checked(command)
    return library, {
        "command": command,
        "elapsed_ns": time.perf_counter_ns() - start,
        "included_in_application_samples": False,
        "sources": {str(p): B.sha256(p) for p in sources},
    }


def outputs(directory):
    return {
        p.name: B.sha256(p) for pattern in ("*.out.c", "*.rsp") for p in directory.glob(pattern)
    }


def executable_check(build, directory, count):
    objects = []
    commands = []
    for name in ["provider", *[f"job-{i}" for i in range(count)]]:
        raw, obj = directory / (name + ".raw.o"), directory / (name + ".o")
        commands += [
            ["gcc", *M.C_FLAGS, "-c", str(directory / (name + ".out.c")), "-o", str(raw)],
            ["objcopy", "@" + str(directory / (name + ".rsp")), str(raw), str(obj)],
        ]
        objects.append(obj)
    commands += [
        [
            str(build / "crust-c"),
            "-o",
            str(directory / "target"),
            str(directory / "main.crs"),
            *["--ldflag=" + str(p) for p in objects],
        ],
        [
            "gcc",
            *M.C_FLAGS,
            str(directory / "main.c"),
            str(directory / "provider.c"),
            *[str(directory / f"job-{i}.c") for i in range(count)],
            "-o",
            str(directory / "reference"),
        ],
    ]
    for command in commands:
        M.checked(command)
    for name in ("target", "reference"):
        if M.checked([str(directory / name)]) != b"parallel: ok\n":
            raise RuntimeError("Module graph executable mismatch")
    return {"commands": commands, "stdout": "parallel: ok\n"}


def edit_checks(case, command, frozen):
    provider = case / "provider.crs"
    original = provider.read_text()
    variants = {
        "body": original.replace("(*h).prev = at;", "(*h).prev = at; (*h).prev = at;"),
        "layout": original.replace("record Hook {", "record Hook {\n    extra: u64;"),
        "signature": original.replace("at: *Hook, h: *Hook)", "at: *Hook, h: *Hook, extra: u64)"),
    }
    observations = {}
    try:
        for name, source in variants.items():
            if source == original:
                raise RuntimeError("Edit did not change the provider")
            provider.write_text(source)
            result = B.run_process(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if name == "signature":
                if result.returncode != 1 or not result.stderr or result.stdout:
                    raise RuntimeError("A changed signature reused obsolete consumer facts")
            else:
                if result.returncode or result.stdout or result.stderr:
                    raise RuntimeError(result)
                changed = outputs(case)
                if changed["provider.out.c"] == frozen["provider.out.c"]:
                    raise RuntimeError("A changed provider reused obsolete output")
                if name == "layout" and any(
                    changed[p] == h
                    for p, h in frozen.items()
                    if p.startswith("job-") and p.endswith(".out.c")
                ):
                    raise RuntimeError("A changed layout reused obsolete consumer facts")
            observations[name] = {
                "source_sha256": B.sha256(provider),
                "returncode": result.returncode,
                "stderr": result.stderr.decode(),
            }
    finally:
        provider.write_text(original)
    M.checked(command)
    if outputs(case) != frozen:
        raise RuntimeError("Restoring provider source did not restore output")
    return observations


def c_commands(directory, count, route):
    common = ["gcc" if route == "gcc" else "clang-20", "-std=c99", "-pedantic-errors", "-O0", "-g0"]
    common += (
        ["-S", "-emit-llvm", "-Xclang", "-disable-llvm-passes"]
        if route == "clang_ir"
        else ["-fsyntax-only"]
    )
    result = []
    for name in ["provider", *[f"job-{i}" for i in range(count)]]:
        command = [*common, str(directory / (name + ".c"))]
        if route == "clang_ir":
            command += ["-o", str(directory / (name + ".ll"))]
        result.append(command)
    return result


def measure(commands, workers, deep):
    start_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    start_controller = resource.getrusage(resource.RUSAGE_SELF)
    start = time.perf_counter_ns()
    M.checked(commands[0])
    if deep or workers == 1:
        for command in commands[1:]:
            M.checked(command)
    elif len(commands) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(M.checked, commands[1:]))
    elapsed = time.perf_counter_ns() - start
    end = resource.getrusage(resource.RUSAGE_CHILDREN)
    end_controller = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "wall_ns": elapsed,
        "user_ns": round((end.ru_utime - start_usage.ru_utime) * 1e9),
        "system_ns": round((end.ru_stime - start_usage.ru_stime) * 1e9),
        "controller_user_ns": round((end_controller.ru_utime - start_controller.ru_utime) * 1e9),
        "controller_system_ns": round((end_controller.ru_stime - start_controller.ru_stime) * 1e9),
    }


def memory_observation(commands, workers, deep, directory, prefix):
    files = [directory / f"{prefix}-{i}.rss" for i in range(len(commands))]
    wrapped = [
        ["/usr/bin/time", "-f", "%M", "-o", str(path), *command]
        for path, command in zip(files, commands, strict=True)
    ]
    measure(wrapped, workers, deep)
    peaks = [int(path.read_text()) for path in files]
    return {
        "job_max_rss_kib": peaks,
        "max_job_rss_kib": max(peaks),
        "observations_per_job": 1,
        "scope": "GNU time peak for each compiler job; excludes the Python controller. These are not simultaneous process-tree RSS measurements.",
    }


def ratio(rows, candidate, controls):
    def value(sample):
        control = min(
            controls, key=lambda name: statistics.median(row[name]["wall_ns"] for row in sample)
        )
        return statistics.median(
            row[candidate]["wall_ns"] / row[control]["wall_ns"] for row in sample
        )

    rng = random.Random(20261003)
    draws = sorted(value(rng.choices(rows, k=len(rows))) for _ in range(10000))
    median = value(rows)
    interval = [B.percentile(draws, 0.025), B.percentile(draws, 0.975)]
    return {"median": median, "ci95": interval, "pass": median <= 1 and interval[1] <= 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--modules", type=int, default=16)
    parser.add_argument("--functions", type=int, default=256)
    args = parser.parse_args()
    if args.rounds < 20 or args.output.exists() or args.modules < 2 or args.functions < 1:
        parser.error("Use at least 20 rounds, two modules, one function and a new report path")
    cpus = set(range(args.cpu, args.cpu + 8))
    if not cpus <= os.sched_getaffinity(0):
        parser.error("Eight selected CPUs must be in the allowed affinity set")
    os.chdir(ROOT)
    build = args.build.resolve()
    directory = Path(tempfile.mkdtemp(prefix="parallel-gate-", dir=build))
    library, preparation = build_driver(build, directory)
    hashes = {
        **M.source_hashes(),
        **{str(p): B.sha256(p) for p in Path(__file__).parent.glob("*") if p.is_file()},
    }
    installed = {
        str(p): M.artifact_info(p, p.suffix != ".a")
        for p in (
            build / "crust",
            build / "crust-c",
            build / "crust-c-library.so",
            build / "crust-parallel-library.so",
            build / "libcrust0_host.a",
            library,
            Path(B.capture(["gcc", "-print-prog-name=cc1"])).resolve(),
        )
    }
    tools = {name: B.tool_info(name) for name in ("gcc", "clang-20", "objcopy", "/usr/bin/time")}
    report = {
        "command": sys.argv,
        "revision": B.capture(["git", "rev-parse", "HEAD"]),
        "environment": B.environment(args.cpu),
        "cpus": sorted(cpus),
        "preparation": preparation,
        "hashes": hashes,
        "installed": installed,
        "tools": tools,
        "cases": {},
        "method": {
            "rounds": args.rounds,
            "seed": 20261003,
            "endpoint": "Fresh root, native stage load, provider source/check/export, consumer inputs/bindings/checks, optional complete C and symbol files, ordered diagnostics and cleanup",
            "cache": "Compiled stage libraries; no target results; fresh contexts; warm OS file caches",
            "scheduling": "Wide graph: check provider then independent consumers. Deep graph: consumer i borrows consumer i-1; no parallel work is available.",
            "c_scheduler": "The same CPU set and concurrency limit. The controller and Python thread startup are timed, but Python process startup is excluded. Each C compiler process is fresh.",
            "excluded": "Stage library construction and final target compilation/linking; automatic cache validation is a separate benchmark",
        },
    }
    rng = random.Random(20261003)
    for graph in ("wide", "deep"):
        case = directory / graph
        case.mkdir()
        deep = graph == "deep"
        generate(case, args.modules, args.functions, deep)
        commands = {}
        for workers in (1, 2, 4, 8):
            for route in ("check", "handoff"):
                root = root_file(case, library, workers, args.modules, route == "check", deep)
                commands[f"{route}_{workers}"] = [[str(build / "crust"), str(root)]]
            for route in ("gcc", "clang", "clang_ir"):
                commands[f"{route}_{workers}"] = c_commands(case, args.modules, route)
        frozen = None
        for workers in (1, 2, 4, 8):
            os.sched_setaffinity(0, set(range(args.cpu, args.cpu + workers)))
            for route in ("check", "handoff", "gcc", "clang", "clang_ir"):
                measure(commands[f"{route}_{workers}"], workers, deep)
            emitted = outputs(case)
            if frozen is not None and emitted != frozen:
                raise RuntimeError("Worker count changed emitted bytes or names")
            frozen = emitted
        for name in ["provider", *[f"job-{i}" for i in range(args.modules)]]:
            expected = 3 if name == "provider" else args.functions + 1
            if len(re.findall(r"^define ", (case / (name + ".ll")).read_text(), re.M)) != expected:
                raise RuntimeError("Clang omitted requested function bodies")
        runtime = executable_check(build, case, args.modules)
        edits = edit_checks(case, commands["handoff_8"][0], frozen)
        # Worker failures are collected in source order. Providers stay live through cleanup.
        bad = [case / "job-0.crs", case / f"job-{args.modules - 1}.crs"]
        saved = {path: path.read_bytes() for path in bad}
        diagnostics = []
        try:
            for path in bad:
                path.write_bytes(b"@invalid source\n")
            for workers in (1, 2, 4, 8):
                result = B.run_process(
                    commands[f"check_{workers}"][0], stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                if result.returncode != 1 or result.stdout or not result.stderr:
                    raise RuntimeError(result)
                diagnostics.append(result.stderr)
            if len(set(diagnostics)) != 1:
                raise RuntimeError("Worker count changed diagnostics")
            if not deep and diagnostics[0].find(str(bad[1]).encode()) <= diagnostics[0].find(
                str(bad[0]).encode()
            ):
                raise RuntimeError("Independent diagnostics are not in source order")
        finally:
            for path, data in saved.items():
                path.write_bytes(data)
        inputs = {
            str(p): B.sha256(p)
            for p in case.iterdir()
            if p.suffix in (".c", ".crs", ".h") and not p.name.endswith(".out.c")
        }
        headers = {
            route: [B.dependency_manifest(cmd) for cmd in commands[f"{route}_1"]]
            for route in ("gcc", "clang")
        }
        rss = {}
        for workers in (1, 2, 4, 8):
            os.sched_setaffinity(0, set(range(args.cpu, args.cpu + workers)))
            usage = case / f"usage-{workers}"
            M.checked(
                ["/usr/bin/time", "-f", "%M", "-o", str(usage), *commands[f"handoff_{workers}"][0]]
            )
            rss[f"handoff_{workers}"] = {"max_rss_kib": int(usage.read_text()), "observations": 1}
            for route in ("gcc", "clang", "clang_ir"):
                name = f"{route}_{workers}"
                rss[name] = memory_observation(commands[name], workers, deep, case, name)
        rows = []
        for index in range(args.rounds):
            order = list(commands)
            rng.shuffle(order)
            row = {}
            for name in order:
                workers = int(name.rsplit("_", 1)[1])
                os.sched_setaffinity(0, set(range(args.cpu, args.cpu + workers)))
                row[name] = measure(commands[name], workers, deep)
                if name.startswith("handoff") and outputs(case) != frozen:
                    raise RuntimeError("Target output changed during timing")
            rows.append(row)
            print(graph, "paired round", index + 1, flush=True)
        comparisons = {}
        for workers in (1, 2, 4, 8):
            comparisons[f"check_{workers}"] = ratio(
                rows, f"check_{workers}", [f"gcc_{workers}", f"clang_{workers}"]
            )
            comparisons[f"handoff_{workers}"] = ratio(
                rows, f"handoff_{workers}", [f"clang_ir_{workers}"]
            )
            comparisons[f"scaling_{workers}"] = ratio(rows, f"handoff_{workers}", ["handoff_1"])
        report["cases"][graph] = {
            "commands": commands,
            "inputs": inputs,
            "outputs": frozen,
            "headers": headers,
            "runtime": runtime,
            "samples": rows,
            "edits": edits,
            "module_count": args.modules + 1,
            "function_count": 3 + args.modules * (args.functions + 1),
            "diagnostics": diagnostics[0].decode(),
            "resource_observations": rss,
            "comparisons": comparisons,
            "median_ms": {
                name: statistics.median(row[name]["wall_ns"] for row in rows) / 1e6
                for name in commands
            },
        }
        for path, digest in inputs.items():
            if B.sha256(path) != digest:
                raise RuntimeError(f"Input changed: {path}")
        for route in ("gcc", "clang"):
            if [B.dependency_manifest(cmd) for cmd in commands[f"{route}_1"]] != headers[route]:
                raise RuntimeError("C header inputs changed")
    for path, digest in hashes.items():
        if B.sha256(ROOT / path) != digest:
            raise RuntimeError(f"Compiler or harness source changed: {path}")
    for path, info in installed.items():
        if M.artifact_info(Path(path), Path(path).suffix != ".a") != info:
            raise RuntimeError(f"Installed artifact changed: {path}")
    if any(B.tool_info(name) != info for name, info in tools.items()):
        raise RuntimeError("Tool changed")
    report["pass"] = all(
        result["pass"]
        for case in report["cases"].values()
        for name, result in case["comparisons"].items()
        if not name.startswith("scaling")
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    B.save(args.output, report)
    print(
        json.dumps({name: case["comparisons"] for name, case in report["cases"].items()}, indent=2)
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
