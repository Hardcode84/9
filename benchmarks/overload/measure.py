#!/usr/bin/env python3
"""Freeze explicit and overloaded sources, then measure the available frontend."""
import argparse
import hashlib
import importlib.util
import json
import os
import platform
import random
import re
import shutil
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "resource_measure", ROOT / "benchmarks/resources/measure.py"
)
HELPERS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPERS)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_words(makefile, name):
    value = re.search(r"^" + name + r"\s*=\s*(.*)$", makefile, re.M).group(1)
    while "$(" in value:
        value = re.sub(
            r"\$\((\w+)\)", lambda item: " ".join(make_words(makefile, item.group(1))), value
        )
    return value.split()


def source_pair(count, calls, overloaded, short):
    def name(index):
        if overloaded:
            return "format" if short else "format____"
        return ("f__" if short else "format_") + f"{index:03}"

    declarations = []
    for index in range(count):
        declarations += [
            f"record Tag{index:03} {{ value:u64; }}",
            f"fn {name(index)}(value:*Tag{index:03})->u64 {{ return (*value).value+{index}u64; }}",
        ]
    caller = ['extern fn output(text:*u8)->i32="puts";', "fn main(argc:i32,argv:**u8)->i32 {"]
    for index in range(count):
        caller.append(
            f"var value{index:03}:Tag{index:03}=make Tag{index:03}{{value:{index+1}u64}};"
        )
    caller.append("var result:u64=0u64;")
    expected = 0
    for index in range(calls):
        member = index % count
        caller.append(f"result=result+{name(member)}(&value{member:03});")
        expected += 2 * member + 1
    caller += [
        f"if result!={expected}u64 {{return 1i32;}}",
        f'output("overload {count}: {calls} calls, checksum {expected}");',
        "return 0i32;",
        "}",
    ]
    return "\n".join(declarations) + "\n", "\n".join(caller) + "\n", expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, default=Path("build/crust-c"))
    parser.add_argument("--stage-compiler", type=Path)
    parser.add_argument("--work", type=Path, default=Path(".profile-cache/overload-baseline"))
    parser.add_argument(
        "--output", type=Path, default=Path(".profile-cache/overload-baseline/results.json")
    )
    parser.add_argument("--calls", type=int, default=4096)
    parser.add_argument("--counts", default="1,16,64,256")
    parser.add_argument("--repeats", type=int, default=21)
    parser.add_argument("--cpu", type=int, default=6)
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--measure-stage-preparation", action="store_true")
    args = parser.parse_args()
    counts = [int(value) for value in args.counts.split(",")]
    if (
        args.repeats < 20
        or not counts
        or min(counts) < 1
        or max(counts) > 999
        or args.calls < max(counts)
    ):
        raise SystemExit("Require >=20 repeats, 1..999 members, and at least one call per member.")
    if args.measure_stage_preparation and not args.stage_compiler:
        raise SystemExit("Native stage preparation requires --stage-compiler.")
    os.chdir(ROOT)
    os.sched_setaffinity(0, {args.cpu})
    args.work.mkdir(parents=True, exist_ok=True)
    makefile = Path("Makefile").read_text()
    frozen_paths = [
        args.compiler,
        Path(__file__).resolve().relative_to(ROOT),
        Path("benchmarks/resources/measure.py"),
        Path("runtime/host.c"),
        Path("runtime/host_posix.c"),
        Path("src/core.c"),
        Path("src/read.c"),
        Path("src/check.c"),
        Path("src/profile_linux_x64.c"),
        Path("include/crust0.h"),
        Path("include/crust0_host.h"),
        Path("include/crust0_stage.h"),
        Path("Makefile"),
        Path("build/libcrust0.a"),
        Path("build/libcrust0_host.a"),
        *map(Path, make_words(makefile, "C_STAGE")),
    ]
    if args.stage_compiler:
        frozen_paths.append(args.stage_compiler)
        frozen_paths += [
            *map(Path, make_words(makefile, "OVERLOAD_LIBRARY")),
            Path("stages/overload/main.crs"),
        ]
    frozen = {str(path): sha(path) for path in frozen_paths}
    workloads = []
    for count in counts:
        variants = {}
        commands = {}
        for overloaded in (False, True):
            for short in (False, True):
                label = ("overloaded" if overloaded else "explicit") + (
                    "-short" if short else "-padded"
                )
                directory = args.work / f"family-{count}" / label
                directory.mkdir(parents=True, exist_ok=True)
                provider, caller, expected = source_pair(count, args.calls, overloaded, short)
                paths = [directory / "provider.crs", directory / "caller.crs"]
                for path, text in zip(paths, (provider, caller), strict=False):
                    path.write_text(text)
                variants[label] = {
                    "sources": {
                        str(path): {"bytes": path.stat().st_size, "sha256": sha(path)}
                        for path in paths
                    },
                    "source_bytes": sum(path.stat().st_size for path in paths),
                    "callee_name_bytes": 6 if short else 10,
                    "files": list(map(str, paths)),
                    "checksum": expected,
                }
                if not overloaded:
                    for endpoint in ("check", "prepare"):
                        commands[label + "." + endpoint] = [
                            str(args.compiler),
                            "--" + endpoint,
                            *map(str, paths),
                        ]
                    generated = directory / "output.c"
                    renames = directory / "output.rsp"
                    emit = [
                        str(args.compiler),
                        "--emit-c",
                        "-o",
                        str(generated),
                        "--symbols",
                        str(renames),
                        *map(str, paths),
                    ]
                    HELPERS.run(emit)
                    variants[label]["emission"] = {
                        "command": emit,
                        "c_bytes": generated.stat().st_size,
                        "rename_bytes": renames.stat().st_size,
                        "c_sha256": sha(generated),
                        "rename_sha256": sha(renames),
                    }
                if args.stage_compiler:
                    for endpoint in ("check", "prepare"):
                        commands["stage-" + label + "." + endpoint] = [
                            str(args.stage_compiler),
                            "--" + endpoint,
                            *map(str, paths),
                        ]
                    generated = directory / "stage-output.c"
                    renames = directory / "stage-output.rsp"
                    emit = [
                        str(args.stage_compiler),
                        "--emit-c",
                        "-o",
                        str(generated),
                        "--symbols",
                        str(renames),
                        *map(str, paths),
                    ]
                    HELPERS.run(emit)
                    variants[label]["stage_emission"] = {
                        "command": emit,
                        "c_bytes": generated.stat().st_size,
                        "rename_bytes": renames.stat().st_size,
                        "c_sha256": sha(generated),
                        "rename_sha256": sha(renames),
                    }
        for suffix in ("-short", "-padded"):
            assert (
                variants["explicit" + suffix]["source_bytes"]
                == variants["overloaded" + suffix]["source_bytes"]
            )
        runtime = None
        if not args.skip_runtime and count in (min(counts), max(counts)):
            binary = args.work / f"family-{count}" / "explicit-runtime"
            files = variants["explicit-padded"]["files"]
            command = [str(args.compiler), "--cflag=-O2", "-o", str(binary), *files]
            HELPERS.run(command)
            result = HELPERS.run([binary])
            expected = variants["explicit-padded"]["checksum"]
            assert (
                result.stdout
                == f"overload {count}: {args.calls} calls, checksum {expected}\n".encode()
                and not result.stderr
            )
            runtime = {
                "compile": command,
                "run": [str(binary)],
                "status": 0,
                "stdout": result.stdout.decode(),
                "binary_sha256": sha(binary),
                "timed": False,
            }
            if args.stage_compiler:
                for variant in ("explicit-padded", "overloaded-padded"):
                    binary = args.work / f"family-{count}" / ("stage-" + variant + "-runtime")
                    command = [
                        str(args.stage_compiler),
                        "--cflag=-O2",
                        "-o",
                        str(binary),
                        *variants[variant]["files"],
                    ]
                    HELPERS.run(command)
                    result = HELPERS.run([binary])
                    assert result.stdout == runtime["stdout"].encode() and not result.stderr
                    variants[variant]["stage_runtime"] = {
                        "compile": command,
                        "run": [str(binary)],
                        "status": 0,
                        "stdout": result.stdout.decode(),
                        "binary_sha256": sha(binary),
                        "timed": False,
                    }
        for command in commands.values():
            result = HELPERS.run(command)
            assert not result.stdout and not result.stderr
        workloads.append(
            {
                "family_members": count,
                "call_sites": args.calls,
                "source_functions": count + 1,
                "source_records": count,
                "source_files": 2,
                "variants": variants,
                "commands": commands,
                "runtime": runtime,
            }
        )
        if args.stage_compiler:
            expected_c = variants["explicit-padded"]["emission"]["c_sha256"]
            workloads[-1]["generated_c_matches_explicit_control"] = {
                label: value["stage_emission"]["c_sha256"] == expected_c
                for label, value in variants.items()
            }
    print(
        "Overload sources and explicit-name checks passed; beginning serial timed samples.",
        flush=True,
    )
    rng = random.Random(20261002)
    for workload in workloads:
        samples = []
        usage = []
        orders = []
        for _ in range(args.repeats):
            order = list(workload["commands"])
            rng.shuffle(order)
            row = {}
            usage_row = {}
            for endpoint in order:
                observation = HELPERS.timed(workload["commands"][endpoint])
                row[endpoint] = observation["wall_ns"]
                usage_row[endpoint] = observation
            samples.append(row)
            usage.append(usage_row)
            orders.append(order)
        workload["samples_ns"] = samples
        workload["usage_samples"] = usage
        workload["orders"] = orders
        workload["median_ms"] = {
            key: statistics.median(row[key] for row in samples) / 1e6
            for key in workload["commands"]
        }
        workload["comparisons"] = []
        for endpoint in ("check", "prepare"):
            workload["comparisons"].append(
                HELPERS.paired_stats(
                    samples, "explicit-short." + endpoint, "explicit-padded." + endpoint, 20261002
                )
            )
            if args.stage_compiler:
                for variant in workload["variants"]:
                    baseline = "explicit-" + variant.split("-", 1)[1] + "." + endpoint
                    workload["comparisons"].append(
                        HELPERS.paired_stats(
                            samples, baseline, "stage-" + variant + "." + endpoint, 20261002
                        )
                    )
                for suffix in ("padded", "short"):
                    workload["comparisons"].append(
                        HELPERS.paired_stats(
                            samples,
                            "stage-explicit-" + suffix + "." + endpoint,
                            "stage-overloaded-" + suffix + "." + endpoint,
                            20261002,
                        )
                    )
        print(workload["family_members"], workload["median_ms"], flush=True)
    native_preparation = None
    if args.measure_stage_preparation:
        stage_sources = make_words(makefile, "OVERLOAD_LIBRARY")
        exports = make_words(makefile, "OVERLOAD_EXPORTS")
        stage_object = args.work / "prepared-overload-stage.o"
        stage_library = args.work / "prepared-overload-stage.so"
        commands = [
            [
                str(args.compiler),
                "--library",
                "--object",
                *[arg for name in exports for arg in ("--export", name)],
                "--cflag=-fPIC",
                "--cflag=-fno-semantic-interposition",
                "--cflag=-O2",
                "--cflag=-g",
                "-o",
                str(stage_object),
                *stage_sources,
            ],
            [
                "gcc",
                "-shared",
                "-Wl,-Bsymbolic,-z,text,-z,relro,-z,now",
                str(stage_object),
                "-o",
                str(stage_library),
            ],
        ]
        print("Frontend samples complete; measuring separate native stage preparation.", flush=True)
        observations = [HELPERS.timed(command) for command in commands]
        native_preparation = {
            "commands": commands,
            "observations": observations,
            "total_wall_ms": sum(item["wall_ns"] for item in observations) / 1e6,
            "scope": "one construction of the native overload/reader/C stage from CRUST source with an installed CRUST C compiler; includes GCC optimization, object assembly, symbol renaming, and shared linking",
            "statistic": "one observation per command; no confidence interval",
            "source_bytes": sum(Path(path).stat().st_size for path in stage_sources),
            "source_sha256": {path: sha(path) for path in stage_sources},
            "artifacts_sha256": {str(path): sha(path) for path in (stage_object, stage_library)},
        }
    if any(sha(path) != digest for path, digest in frozen.items()):
        raise SystemExit("Baseline inputs changed during the run; discard the measurements.")
    report = {
        "schema_version": 1,
        "stage_available": bool(args.stage_compiler),
        "frozen_sha256": frozen,
        "revision": HELPERS.run(["git", "rev-parse", "HEAD"]).stdout.decode().strip(),
        "environment": {
            "platform": platform.platform(),
            "cpu_model": next(
                (
                    line.split(":", 1)[1].strip()
                    for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")
                ),
                "not reported",
            ),
            "gcc_version": HELPERS.run(["gcc", "--version"]).stdout.decode().splitlines()[0],
            "gcc_binary_sha256": sha(shutil.which("gcc")),
            "objcopy_version": HELPERS.run(["objcopy", "--version"])
            .stdout.decode()
            .splitlines()[0],
            "objcopy_binary_sha256": sha(shutil.which("objcopy")),
            "smt_siblings": Path(
                f"/sys/devices/system/cpu/cpu{args.cpu}/topology/thread_siblings_list"
            )
            .read_text()
            .strip(),
            "python": platform.python_version(),
        },
        "method": {
            "cpu": args.cpu,
            "workers": 1,
            "paired_rounds": args.repeats,
            "seed": 20261002,
            "processes": "fresh per invocation, one untimed check per endpoint; filesystem cache warm",
            "backend": "target GCC compile/link and runtime are outside timed samples",
            "stage_preparation": "installed native stage binary; its construction cost is not in these samples",
            "check": "existing C-stage parsing and ordinary semantic checks",
            "prepare": "existing C-stage checks plus complete C text and symbol-rename construction in memory",
            "stage_check": "CRUST reader, overload selection and mangling, then ordinary seed semantic checks",
            "stage_prepare": "stage_check plus complete C text and symbol-rename construction in memory",
            "usage": "wait4 process user/system CPU and peak RSS; wall time includes launch and completion",
            "bootstrap": "10000 resamples of complete paired rounds; ratio-of-medians 95 percent interval",
            "noise": "one logical CPU pinned; shared caches, kernel activity, and machine-wide load remain uncontrolled",
            "symbols": "paired callee spellings have equal byte length; short and padded controls differ by four bytes per declaration/call",
        },
        "workloads": workloads,
        "native_stage_preparation": native_preparation,
        "complete": True,
        "conclusion": "This is an explicit-name CRUST baseline; no overload-stage cost or C-speed result is established unless its candidate is measured separately.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text((json.dumps(report, indent=2) + "\n").replace(str(ROOT), "@REPO@"))
    print(args.output, flush=True)


if __name__ == "__main__":
    main()
