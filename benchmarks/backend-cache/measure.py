#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare source bootstrap misses, artifact hits, and explicit native backends."""

import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import struct
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timed_cache(source):
    source = source.replace(
        "record BuildState",
        "record CacheClock { seconds:i64; nanoseconds:i64; }\n"
        'extern fn cache_clock(id:i32,time:*CacheClock)->i32="clock_gettime";\n'
        "record BuildState",
    )
    source = source.replace(
        "    var inputs: CacheInputs",
        "    var capture_start:CacheClock=uninit;\n"
        "    var capture_end:CacheClock=uninit;\n"
        "    var lookup_end:CacheClock=uninit;\n"
        "    if cache_clock(1i32,&capture_start)!=0i32 {return 90i32;}\n"
        "    var inputs: CacheInputs",
    )
    old = """    if !cache_artifact(ctx, directory, &request, &artifact) ||
       !crust_run_link(run, artifact.path) { return 1i32; }"""
    if source.count(old) != 1:
        raise RuntimeError("Cache tutorial lookup boundary changed")
    return source.replace(
        old,
        """    if cache_clock(1i32,&capture_end)!=0i32 {return 90i32;}
    if !cache_artifact(ctx,directory,&request,&artifact) {return 1i32;}
    if cache_clock(1i32,&lookup_end)!=0i32 {return 90i32;}
    var durations:[i64;3]=make [i64;3]{
        (capture_end.seconds-capture_start.seconds)*1000000000i64+capture_end.nanoseconds-capture_start.nanoseconds,
        (lookup_end.seconds-capture_end.seconds)*1000000000i64+lookup_end.nanoseconds-capture_end.nanoseconds,
        artifact.hit as i64
    };
    if crust0_host_write_stream(2u32,&durations as *u8,sizeof([i64;3]))!=0i32 {return 91i32;}
    if !crust_run_link(run,artifact.path) {return 1i32;}""",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--before", type=Path, help="Frozen checkout built with make all")
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--cpu", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 20:
        parser.error("use at least 20 paired rounds")
    if args.output.exists():
        parser.error("output must be a new report path")
    if args.cpu is not None:
        os.sched_setaffinity(0, {args.cpu})
    build = args.build.resolve()
    work = Path(tempfile.mkdtemp(prefix="backend-cache-measure-", dir=build))
    rng = random.Random(722)
    report = {"rounds": args.rounds, "cpu": args.cpu, "cases": {}, "hashes": {}}
    template = (ROOT / "examples/cached-backend/main.crs").read_text()
    template = template.split("// The last native action", 1)[0]
    template = template.replace('"../../', '"' + str(ROOT) + "/")
    template = template.replace(
        '"build.crs"', json.dumps(str(ROOT / "examples/cached-backend/build.crs"))
    )
    template = timed_cache(template)
    report["phases"] = {
        "input_capture": "Source snapshots, loaded sources and native images, assembler/linker binaries and their dependencies. Includes the tutorial's input-provider calls.",
        "lookup_or_build": "Cache manifest, key hashing, artifact lookup and checksum verification. A miss includes complete backend construction and publication.",
        "hit_validation": "Input capture plus lookup on a verified hit. Excludes native library loading, continuation preparation and target frontend work.",
        "implementation": "The tutorial's interpreted cache prefix and source-bootstrap recipe. Compiled-backend application timings are a separate configuration.",
    }
    inputs = {"intrusive": (ROOT / "examples/intrusive/program.crs").read_text()}
    for count in (1000, 8000):
        inputs[str(count)] = (
            "\n".join(
                f"fn f{i}(x:u64)->u64{{var y:u64=x+{i}u64; if y>9u64 {{y=y*3u64;}} return y;}}"
                for i in range(count)
            )
            + "\nfn main(argc:i32,argv:**u8)->i32{return f0(0u64) as i32;}\n"
        )

    def run(command, cache=False):
        start = time.perf_counter_ns()
        result = subprocess.run(list(map(str, command)), cwd=ROOT, capture_output=True, timeout=60)
        elapsed = time.perf_counter_ns() - start
        assert result.returncode == 0, (command, result)
        phases = None
        if cache:
            if len(result.stderr) != 24:
                raise RuntimeError((command, result.stderr))
            capture, lookup, hit = struct.unpack("<qqq", result.stderr)
            if capture < 0 or lookup < 0 or hit not in (0, 1):
                raise RuntimeError("Invalid cache phase sample")
            phases = {"input_capture_ns": capture, "lookup_or_build_ns": lookup, "hit": bool(hit)}
        elif result.stderr:
            raise RuntimeError((command, result.stderr))
        return elapsed, result.stdout, phases

    tracked = [
        *ROOT.glob("src/*.c"),
        *ROOT.glob("include/*.h"),
        *ROOT.glob("api/*.crs"),
        *ROOT.glob("runtime/*.c"),
        *ROOT.glob("stages/**/*.crs"),
        *ROOT.glob("examples/cached-backend/*.crs"),
        ROOT / "Makefile",
        Path(__file__),
        build / "crust",
        build / "crust0",
        build / "crust-c",
        build / "crust-c-library.so",
        build / "crust-asm-library.so",
        build / "libcrust0_host.a",
        *[
            Path(shutil.which(name)).resolve()
            for name in ("gcc", "as", "ld", "objcopy", "sha256sum", "ldd")
        ],
    ]
    original_hashes = {str(path): digest(path) for path in tracked}
    for name, source in inputs.items():
        case = work / name
        case.mkdir(exist_ok=True)
        target = case / "target.crs"
        target.write_text(source)
        commands = {}
        for mode in ("miss", "hit"):
            cache = case / (mode + "-cache")
            root = case / (mode + ".crs")
            root.write_text(
                template.replace(str(ROOT / "build/backend-cache"), str(cache)) + source
            )
            commands[mode] = [
                build / "crust",
                root,
                "--emit-c",
                "-o",
                case / (mode + ".c"),
                "--symbols",
                case / (mode + ".rsp"),
            ]
        commands["prepared_c"] = [
            build / "crust-c",
            "--emit-c",
            "-o",
            case / "prepared_c.c",
            "--symbols",
            case / "prepared_c.rsp",
            target,
        ]
        commands["asm"] = [build / "crust0", "-S", "-o", case / "asm.s", target]
        if args.before:
            commands["before_asm"] = [
                args.before.resolve() / "build/crust0",
                "-S",
                "-o",
                case / "before_asm.s",
                target,
            ]
        if name == "intrusive":
            commands["gcc_check"] = [
                "gcc",
                "-std=c99",
                "-pedantic-errors",
                "-fsyntax-only",
                "-Iinclude",
                ROOT / "benchmarks/bootstrap/intrusive.c",
            ]
        run(commands["hit"], cache=True)
        samples = {key: [] for key in commands}
        phases = {key: [] for key in ("hit", "miss")}
        for _ in range(args.rounds):
            order = list(commands)
            rng.shuffle(order)
            for mode in order:
                if mode == "miss":
                    if (case / "miss-cache").exists():
                        shutil.rmtree(case / "miss-cache")
                elapsed, _, phase = run(commands[mode], cache=mode in phases)
                samples[mode].append(elapsed)
                if mode in ("hit", "miss"):
                    if phase["hit"] != (mode == "hit"):
                        raise RuntimeError("Measured cache state differs from requested state")
                    phases[mode].append(phase)
                    assert not list((case / (mode + "-cache")).glob(".build-*"))
            for suffix in (".c", ".rsp"):
                expected = (case / ("prepared_c" + suffix)).read_bytes()
                assert (case / ("miss" + suffix)).read_bytes() == expected
                assert (case / ("hit" + suffix)).read_bytes() == expected
            if args.before:
                assert (case / "before_asm.s").read_bytes() == (case / "asm.s").read_bytes()
        if name == "intrusive":
            # Final target GCC/objcopy/link execution is outside all samples.
            run(
                [
                    "gcc",
                    "-std=c99",
                    "-O2",
                    "-fstack-clash-protection",
                    "-c",
                    case / "hit.c",
                    "-o",
                    case / "raw.o",
                ]
            )
            run(["objcopy", "@" + str(case / "hit.rsp"), case / "raw.o", case / "target.o"])
            run(
                [
                    "gcc",
                    "-no-pie",
                    case / "target.o",
                    build / "libcrust0_host.a",
                    "-o",
                    case / "program",
                ]
            )
            assert run([case / "program"])[1] == b"intrusive: ok\n"
        ratios = [hit / miss for hit, miss in zip(samples["hit"], samples["miss"], strict=False)]
        medians = {key: statistics.median(values) for key, values in samples.items()}
        intervals = sorted(
            statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(3000)
        )
        report["cases"][name] = {
            "commands": {key: list(map(str, values)) for key, values in commands.items()},
            "samples_ns": samples,
            "median_ns": medians,
            "cache_samples": phases,
            "hit_validation_median_ns": statistics.median(
                sample["input_capture_ns"] + sample["lookup_or_build_ns"]
                for sample in phases["hit"]
            ),
            "paired_hit_miss_ratio": statistics.median(ratios),
            "paired_hit_miss_95_percent": [intervals[75], intervals[2924]],
            "input": source,
            "roots": {mode: (case / (mode + ".crs")).read_text() for mode in ("hit", "miss")},
            "outputs": {
                path.name: digest(path)
                for path in case.iterdir()
                if path.suffix in (".c", ".rsp", ".s")
            },
        }
        print(name, json.dumps(medians), flush=True)
    assert original_hashes == {
        str(path): digest(path) for path in tracked
    }, "measured inputs changed"
    paths = [
        *ROOT.glob("src/*.c"),
        *ROOT.glob("include/*.h"),
        *ROOT.glob("api/*.crs"),
        *ROOT.glob("stages/**/*.crs"),
        *ROOT.glob("runtime/*.c"),
        *ROOT.glob("examples/cached-backend/*.crs"),
        ROOT / "Makefile",
        build / "crust",
        build / "crust0",
        build / "crust-c",
    ]
    if args.before:
        before = args.before.resolve()
        paths += [
            before / "build/crust0",
            before / "Makefile",
            *before.glob("src/*.c"),
            *before.glob("include/*.h"),
        ]
    report["hashes"] = {**original_hashes, **{str(path): digest(path) for path in paths}}
    variables = subprocess.run(
        ["make", "-pn"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    selected = ("CC ", "CFLAGS ", "CPPFLAGS ", "LDFLAGS ", "STRICT ", "AS ", "ASFLAGS ", "PROFILE ")
    report["flags"] = [line for line in variables.splitlines() if line.startswith(selected)]
    for name in ("gcc", "as", "ld", "objcopy", "sha256sum"):
        path = Path(shutil.which(name))
        report["hashes"][str(path)] = digest(path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
