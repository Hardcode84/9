#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Capture the Linux hello bootstrap baseline before a Windows port."""

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import time
from pathlib import Path

CLOCK = """
record BaselineTime { seconds:i64; nanos:i64; }
extern fn baseline_clock(id:i32, value:*BaselineTime)->i32="clock_gettime";
fn baseline_now()->i64 {
    var value:BaselineTime=uninit;
    if baseline_clock(1i32,&value)!=0i32 { trap; }
    return value.seconds*1000000000i64+value.nanos;
}
fn baseline_pair(start:i64, end:i64)->unit {
    var pair:[i64;2]=make [i64;2]{start,end};
    if crust0_host_write_stream(2u32,&pair[0usize] as *u8,16usize)!=0i32 { trap; }
}
"""

EMITTER = """
fn baseline_emit(context:*CrustContext, entry:*CrustDecl, options:*BackendOptions)->i32 {
    var start:i64=baseline_now();
    var status:i32=c_backend_build(context,entry,options);
    baseline_pair(start,baseline_now());
    return status;
}
fn baseline_compile(target:*CrustSource, count:i32, arguments:**u8)->i32 {
    var start:i64=baseline_now();
    var status:i32=c_build(target,0usize,count,arguments,baseline_emit);
    baseline_pair(start,baseline_now());
    return status;
}
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, text):
    path.write_text("// SPDX-License-Identifier: Apache-2.0\n" + text)


def command(argv, cwd):
    start = time.perf_counter_ns()
    result = subprocess.run(list(map(str, argv)), cwd=cwd, capture_output=True, timeout=900)
    if result.returncode:
        raise RuntimeError((argv, result.returncode, result.stderr))
    return result, {"command": list(map(str, argv)), "elapsed_ns": time.perf_counter_ns() - start}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=0)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.sched_setaffinity(0, {args.cpu})
    build = source / "build"
    inputs = {
        str(path.relative_to(source)): digest(path)
        for path in source.rglob("*")
        if path.is_file() and "build" not in path.relative_to(source).parts
    }
    write(output / "clock.crs", CLOCK)
    write(output / "emitter.crs", EMITTER)
    hello = (
        (source / "examples/hello/main.crs")
        .read_text()
        .split("// The target program starts here.", 1)[1]
    )
    write(output / "target.crs", hello)

    def q(path):
        return json.dumps(str(path))

    write(
        output / "root.crs",
        f"""
host_source(run,{q(output / 'clock.crs')});
host_source(run,{q(source / 'stages/build/load.crs')});
if !application_setup(run,{q(source)}) {{return 1i32;}};
host_source(run,{q(output / 'emitter.crs')});
var begin:i64=baseline_now();
var session:*StageSession=stage_open(run,{q(source)},{q(output / 'cache')});
baseline_pair(begin,baseline_now());
if session==null(*StageSession) {{return 1i32;}};
var target:*CrustSource=host_input(run,{q(output / 'target.crs')},100u64);
return baseline_compile(target,run -> argc,run -> argv);
""",
    )
    report = {
        "scope": "Linux hello; one cold cache and one warm cache sample; no speed claim",
        "cpu": args.cpu,
        "source_hashes": inputs,
        "seed_sha256": digest(build / "crust"),
        "harness_sha256": digest(Path(__file__)),
        "flags": {
            "seed": "-O2 -g and repository STRICT",
            "target": "-O2 -g0 -fstack-clash-protection",
        },
        "boundaries": {
            "stage_ns": "stage_open, including native backend construction or cache validation and loading",
            "frontend_ns": "c_build excluding its emitter callback; includes target context setup and cleanup",
            "emission_ns": "c_backend_build in text mode; includes C and symbol output; excludes target GCC",
            "target_toolchain": "separate compile, rename, and link processes",
        },
        "tools": {},
        "samples": [],
    }
    for tool in ("gcc", "as", "ld", "objcopy"):
        path = Path(shutil.which(tool))
        version, _ = command([path, "--version"], source)
        report["tools"][tool] = {
            "path": str(path),
            "sha256": digest(path),
            "version": version.stdout.decode(),
        }
    for cache in ("cold", "warm"):
        emitted = output / f"{cache}.c"
        symbols = output / f"{cache}.rsp"
        result, sample = command(
            [
                build / "crust",
                output / "root.crs",
                "--emit",
                "-o",
                emitted,
                "--symbols",
                symbols,
            ],
            source,
        )
        assert not result.stdout and len(result.stderr) == 48, result
        stage_start, stage_end, emit_start, emit_end, front_start, front_end = struct.unpack(
            "=6q", result.stderr
        )
        sample.update(
            cache=cache,
            stage_ns=stage_end - stage_start,
            emission_ns=emit_end - emit_start,
            frontend_ns=front_end - front_start - (emit_end - emit_start),
            emitted_sha256=digest(emitted),
            symbols_sha256=digest(symbols),
        )
        report["samples"].append(sample)
    assert report["samples"][0]["emitted_sha256"] == report["samples"][1]["emitted_sha256"]
    obj = output / "hello.o"
    executable = output / "hello"
    report["target_toolchain"] = []
    for argv in (
        [
            "gcc",
            "-std=c99",
            "-O2",
            "-g0",
            "-fstack-clash-protection",
            "-Wno-overlength-strings",
            "-c",
            emitted,
            "-o",
            obj,
        ],
        ["objcopy", "@" + str(symbols), obj],
        ["gcc", obj, "-o", executable],
    ):
        result, measured = command(argv, source)
        report["target_toolchain"].append(measured)
    result, report["execution"] = command([executable], source)
    assert result.stdout == b"Hello, world!\n"
    for name, expected in inputs.items():
        assert digest(source / name) == expected, name
    report["generated_hashes"] = {
        str(path.relative_to(output)): digest(path) for path in output.iterdir() if path.is_file()
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(output / "report.json")


if __name__ == "__main__":
    main()
