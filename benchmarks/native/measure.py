#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure cold native handoff and separate its preparation and execution costs."""

import argparse
import importlib.util
import json
import os
import random
import statistics
import struct
import subprocess
import tempfile
import time
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "source_measure", Path(__file__).parents[1] / "source-order/measure.py"
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
ROOT = M.ROOT

CLOCK = """
record BenchTime { seconds:i64; nanoseconds:i64; }
extern fn bench_clock(id:i32, time:*BenchTime)->i32="clock_gettime";
"""
BOOTSTRAP = """
    var start:BenchTime=uninit;
    var ready:BenchTime=uninit;
    var done:BenchTime=uninit;
    if bench_clock(1i32,&start)!=0i32 {return 90i32;}
    var context:CrustContext=uninit;
    crust_context_init(&context,null(*CrustAllocator));
    var status:i32=1i32;
    var image:*NativeImage=native_image((*run).context,&session);
    if image!=null(*NativeImage) &&
       native_prepare(run,&context,&sources[0usize],17usize,&exports[0usize],3usize) &&
       native_asm_image(&context,&session,image) && crust_run_link(run,(*image).library) {
        if bench_clock(1i32,&ready)!=0i32 {return 90i32;}
        status=native_start(run,&session);
        if bench_clock(1i32,&done)!=0i32 {return 90i32;}
        var durations:[i64;2]=make [i64;2]{
            (ready.seconds-start.seconds)*1000000000i64+ready.nanoseconds-start.nanoseconds,
            (done.seconds-ready.seconds)*1000000000i64+done.nanoseconds-ready.nanoseconds
        };
        if crust0_host_write_stream(2u32,&durations as *u8,sizeof([i64;2]))!=0i32 {return 91i32;}
    }
    if context.error_count!=0usize {
        crust_set_error((*run).context,context.error_loc.source,context.error_loc.offset,&context.error[0usize]);
    }
    crust_context_destroy(&context);
    if !native_cleanup((*run).context,&session) {return 92i32;}
"""


def roots(workload, directory, build):
    quote = M.crust_string
    source = (ROOT / "examples/native/main.crs").read_text()
    source = source.replace('"../../', f'"{ROOT}/')
    source = source.replace(f'"{ROOT}/build"', quote(directory))
    source = source.replace("record BuildState", CLOCK + "record BuildState")
    old = "var status: i32 = native_bootstrap(run, &session, &sources[0usize], 17usize, &exports[0usize], 3usize);"
    assert source.count(old) == 1
    source = source.replace(old, BOOTSTRAP)
    source = source.replace(
        "var status: i32 = c_program(&request);",
        """
    var start:BenchTime=uninit;
    var done:BenchTime=uninit;
    if bench_clock(1i32,&start)!=0i32 {return 90i32;}
    var status:i32=c_program(&request);
    if bench_clock(1i32,&done)!=0i32 {return 90i32;}
    var duration:i64=(done.seconds-start.seconds)*1000000000i64+done.nanoseconds-start.nanoseconds;
    if crust0_host_write_stream(2u32,&duration as *u8,sizeof(i64))!=0i32 {return 91i32;}
""",
    )
    source = source.split("// The last native action gives these unread bytes", 1)[0]
    source += workload["paths"]["crust"].read_text()
    native = directory / (workload["name"] + "-native.crs")
    native.write_text(source)
    installed = directory / (workload["name"] + "-installed.crs")
    M.staged_source(workload["paths"]["crust"], installed, build / "crust-c-library.so")
    combined = directory / "interpreted-library.crs"
    combined.write_bytes(b"\n".join(path.read_bytes() for path in M.LIBRARY_SOURCES[2:]))
    interpreted = directory / (workload["name"] + "-interpreted.crs")
    interpreted.write_text(
        f"host_source(run,{quote(combined)});\n"
        f'host_source(run,{quote(ROOT / "stages/c/build.crs")});\n'
        f"var target:*CrustSource=host_input(run,{quote(workload['paths']['crust'])},1u64);\n"
        "return c_build(target,0usize,(*run).argc,(*run).argv);\n"
    )
    return {"native": native, "installed": installed, "interpreted": interpreted}


def sample(command, native=False):
    start = time.perf_counter_ns()
    result = M.BASE.run_process(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = time.perf_counter_ns() - start
    if result.returncode or result.stdout:
        raise RuntimeError((command, result))
    phases = {}
    if native:
        if len(result.stderr) != 24:
            raise RuntimeError((command, result))
        target, preparation, continuation = struct.unpack("=qqq", result.stderr)
        phases = {
            "bootstrap_ns": preparation,
            "continuation_ns": continuation,
            "native_target_ns": target,
            "continuation_preparation_ns": continuation - target,
            "startup_cleanup_ns": elapsed - preparation - continuation,
        }
        if any(value < 0 for value in phases.values()):
            raise RuntimeError(phases)
    elif result.stderr:
        raise RuntimeError((command, result))
    return {"cold_ns": elapsed, **phases}


def comparison(rows, baseline):
    ratios = [row["native"]["cold_ns"] / row[baseline]["cold_ns"] for row in rows]
    rng = random.Random(20261002)
    draws = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(10000))
    interval = [M.BASE.percentile(draws, 0.025), M.BASE.percentile(draws, 0.975)]
    median = statistics.median(ratios)
    return {
        "paired_median_ratio": median,
        "ci95": interval,
        "pass": median <= 1 and interval[1] <= 1,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--cpu", type=int, default=0)
    args = parser.parse_args()
    if args.rounds < 20 or args.output.exists():
        parser.error("Use at least 20 rounds and a new output path")
    os.sched_setaffinity(0, {args.cpu})
    build = args.build.resolve()
    directory = Path(tempfile.mkdtemp(prefix="native-measure-", dir=build))
    inputs = M.source_hashes()
    inputs["benchmarks/native/measure.py"] = M.BASE.sha256(__file__)
    inputs["examples/native/main.crs"] = M.BASE.sha256(ROOT / "examples/native/main.crs")
    for name in ("crust", "crust-c-library.so", "libcrust0_host.a"):
        inputs[str(build / name)] = M.BASE.sha256(build / name)
    report = {
        "revision": M.BASE.capture(["git", "rev-parse", "HEAD"]),
        "scope": "Cold fresh processes; no stage-result cache; warm OS caches; one CPU; final target GCC excluded",
        "native_inputs": "crust seed, explicit Crust sources, GNU as, GCC toolchain; no installed stage library",
        "phase_contract": "bootstrap ends after loading the ASM-built backend/executor; continuation includes ASM/C compilation and loading of two complete native function actions; native_target is target frontend through complete C and symbol output; startup_cleanup includes remaining root setup and process teardown",
        "cpu": args.cpu,
        "platform": M.platform.platform(),
        "inputs": inputs,
        "tools": {name: M.BASE.tool_info(name) for name in ("gcc", "as", "ld", "objcopy")},
        "seed": M.artifact_info(build / "crust", dynamic=True),
        "installed_backend": M.artifact_info(build / "crust-c-library.so", dynamic=True),
        "workloads": [],
    }
    workloads = [M.BASE.generate(directory, count) for count in (1000, 8000)]
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
    rng = random.Random(20261002)
    for workload in workloads:
        paths = roots(workload, directory, build)
        original_c = M.file_info(workload["paths"]["c"])
        output = directory / (workload["name"] + "-emitted.c")
        assert output not in workload["paths"].values()
        symbols = output.with_suffix(".rsp")
        flags = ["--library"] if workload["library"] else []
        commands = {
            route: list(
                map(
                    str,
                    [build / "crust", path, *flags, "--emit-c", "-o", output, "--symbols", symbols],
                )
            )
            for route, path in paths.items()
        }
        commands["gcc"] = M.syntax_command(workload["paths"]["c"], not workload["library"])
        expected = None
        for route, command in commands.items():
            sample(command, route == "native")
            value = (M.BASE.sha256(output), M.BASE.sha256(symbols))
            if expected is not None and value != expected:
                raise RuntimeError((route, value, expected))
            expected = value
        rows = []
        for _ in range(args.rounds):
            order = list(commands)
            rng.shuffle(order)
            row = {}
            for route in order:
                row[route] = sample(commands[route], route == "native")
                if (M.BASE.sha256(output), M.BASE.sha256(symbols)) != expected:
                    raise RuntimeError(f"Output changed during timing: {route}")
            rows.append(row)
            if list(directory.glob("crust-*")):
                raise RuntimeError("Temporary native images remain after root completion")
        if M.BASE.sha256(workload["paths"]["c"]) != original_c["sha256"]:
            raise RuntimeError("The original C comparison input changed")
        entry = {
            "name": workload["name"],
            "commands": commands,
            "roots": {route: path.read_text() for route, path in paths.items()},
            "target_sha256": M.BASE.sha256(workload["paths"]["crust"]),
            "original_c": original_c,
            "output_sha256": expected,
            "samples": rows,
            "median_ms": {
                route: {
                    field.removesuffix("_ns"): statistics.median(row[route][field] for row in rows)
                    / 1e6
                    for field in rows[0][route]
                }
                for route in commands
            },
            "cold_native_over_interpreted": comparison(rows, "interpreted"),
            "cold_native_over_gcc": comparison(rows, "gcc"),
        }
        if not workload["library"]:
            obj = output.with_suffix(".o")
            renamed = output.with_suffix(".renamed.o")
            executable = output.with_suffix(".exe")
            toolchain = [
                ["gcc", *M.C_FLAGS, "-c", str(output), "-o", str(obj)],
                ["objcopy", "@" + str(symbols), str(obj), str(renamed)],
                [
                    "gcc",
                    "-no-pie",
                    str(renamed),
                    str(build / "libcrust0_host.a"),
                    "-o",
                    str(executable),
                ],
            ]
            start = time.perf_counter_ns()
            for command in toolchain:
                M.checked(command)
            entry["final_target_toolchain"] = {
                "commands": toolchain,
                "elapsed_ns": time.perf_counter_ns() - start,
                "observations": 1,
            }
            entry["executable_output"] = M.checked([str(executable)]).decode()
        report["workloads"].append(entry)
        print(workload["name"], json.dumps(entry["median_ms"]), flush=True)
    for path, digest in inputs.items():
        if M.BASE.sha256(ROOT / path) != digest:
            raise RuntimeError(f"Input changed: {path}")
    report["generated_inputs"] = {
        str(path.relative_to(directory)): M.BASE.sha256(path) for path in directory.glob("*.crs")
    }
    M.BASE.save(args.output, report)


if __name__ == "__main__":
    main()
