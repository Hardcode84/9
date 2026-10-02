#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Test the single-worker gate before building a parallel stage scheduler."""

import argparse
import importlib.util
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "source_order", Path(__file__).with_name("measure.py")
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
B = M.BASE
ROOT = M.ROOT


def source_roots(workload, directory, build, combined):
    quote = M.crust_string
    name = workload["name"]
    target = workload["paths"]["crust"]
    interpreted = directory / f"{name}-interpreted.crs"
    interpreted.write_text(
        f"host_source(run,{quote(combined)});\n"
        f'host_source(run,{quote(ROOT / "stages/c/build.crs")});\n'
        f"var target:*CrustSource=host_input(run,{quote(target)},1u64);\n"
        "return c_build(target,0usize,(*run).argc,(*run).argv);\n"
    )
    wrapper = directory / "entry.crs"
    wrapper.write_text("fn project_program(request:*CrustBuild)->i32{return c_program(request);}\n")
    library = directory / f"{name}-project.so"
    arguments = [
        "--library",
        "--export",
        "project_program",
        "-o",
        str(library),
        "--cflag=-fPIC",
        "--cflag=-fno-semantic-interposition",
        "--ldflag=-shared",
        "--ldflag=-Wl,-Bsymbolic,-z,text,-z,relro,-z,now",
        *map(str, M.LIBRARY_SOURCES[1:]),
        str(wrapper),
    ]
    native = directory / f"{name}-native.crs"
    native.write_text(
        "".join(f"host_source(run,{quote(path)});\n" for path in M.HOST_INTERFACES)
        + f'host_link(run,{quote(build / "crust-c-library.so")});\n'
        + f"var stage_source:*CrustSource=host_input(run,{quote(M.LIBRARY_SOURCES[0])},1u64);\n"
        + f"var arguments:[*u8;{len(arguments)}]=make [*u8;{len(arguments)}]{{"
        + ",".join(map(quote, arguments))
        + "};\n"
        + f"var preparation:i32=c_build(stage_source,0usize,{len(arguments)}i32,&arguments[0usize]);\n"
        + "if preparation!=0i32{return preparation;};\n"
        + f"host_link(run,{quote(library)});\n"
        + 'extern fn project_program(request:*CrustBuild)->i32="project_program";\n'
        + 'extern fn remove_project(path:*u8)->i32="unlink";\n'
        + f"var target:*CrustSource=host_input(run,{quote(target)},1u64);\n"
        + "var context:CrustContext=uninit; crust_context_init(&context,null(*CrustAllocator));\n"
        + "var request:CrustBuild=make CrustBuild{context:&context,source:target,target_begin:0usize,argc:(*run).argc,argv:(*run).argv};\n"
        + "var status:i32=project_program(&request);\n"
        + "if context.error_count!=0usize{crust_run_diagnostic(&context);};\n"
        + "crust_context_destroy(&context);\n"
        + f'if remove_project({quote(library)})!=0i32{{crust_set_error((*run).context,(*run).source,0usize,"cannot remove prepared stage");return 1i32;}};\n'
        + "return status;\n"
    )
    return {"source-interpreted": interpreted, "source-native": native}, library


def summary(rows, seed):
    names = list(rows[0])
    medians = {name: statistics.median(row[name] for row in rows) for name in names}
    baseline = min(("gcc", "clang"), key=medians.get)
    ratios = {}
    for name in ("installed", "source-interpreted", "source-native"):
        paired = [row[name] / row[baseline] for row in rows]
        rng = random.Random(f"{seed}:{name}")
        draws = sorted(statistics.median(rng.choices(paired, k=len(rows))) for _ in range(10000))
        interval = [B.percentile(draws, 0.025), B.percentile(draws, 0.975)]
        median = statistics.median(paired)
        ratios[name] = {
            "median": median,
            "ci95": interval,
            "pass": median <= 1 and interval[1] <= 1,
        }
    return {
        "median_ms": {name: value / 1e6 for name, value in medians.items()},
        "baseline": baseline,
        "ratios": ratios,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--perf", type=Path, help="Native perf executable for an untimed profile")
    args = parser.parse_args()
    if args.rounds < 20 or args.output.exists():
        parser.error("Use at least 20 rounds and a new output path")
    os.sched_setaffinity(0, {args.cpu})
    build = args.build.resolve()
    directory = Path(tempfile.mkdtemp(prefix="source-gate-", dir=build))
    combined = directory / "backend.crs"
    combined.write_bytes(b"\n".join(path.read_bytes() for path in M.LIBRARY_SOURCES[2:]))
    workloads = M.workloads_in(directory, build / "crust-c-library.so")
    binaries = {"launcher": build / "crust", "prepared": build / "crust-c"}
    inputs = M.source_hashes()
    inputs[str(Path(__file__).relative_to(ROOT))] = B.sha256(__file__)
    inputs.update(
        {
            str(path): B.sha256(path)
            for path in [
                *binaries.values(),
                build / "crust-c-library.so",
                build / "libcrust0_host.a",
            ]
        }
    )
    tools = {name: B.tool_info(name) for name in ("gcc", "clang-20", "as", "ld", "objcopy")}
    if args.perf:
        tools[str(args.perf.resolve())] = B.tool_info(str(args.perf.resolve()))
    cc1 = Path(B.capture(["gcc", "-print-prog-name=cc1"])).resolve()
    inputs[str(cc1)] = B.sha256(cc1)
    installed = {
        str(path): M.artifact_info(path, path.suffix != ".a")
        for path in [
            *binaries.values(),
            build / "crust-c-library.so",
            build / "libcrust0_host.a",
            cc1,
        ]
    }
    result = {
        "revision": B.capture(["git", "rev-parse", "HEAD"]),
        "environment": B.environment(args.cpu),
        "command": sys.argv,
        "source_and_binary_hashes": inputs,
        "tools": tools,
        "installed_artifacts": installed,
        "method": {
            "rounds": args.rounds,
            "seed": 20261002,
            "bootstrap_draws": 10000,
            "starting_state": "Installed crust, crust-c, native C backend, and system tools; fresh root/context each process; one worker; no compilation-result cache; warm OS file cache",
            "installed": "Root through complete C and symbol output with an installed native C backend",
            "source-interpreted": "Root checks the complete C backend source and executes it in the evaluator; no prepared backend code is loaded",
            "source-native": "Root builds the complete C backend source into a new native library, loads it, emits target C and symbols, and removes the library; preparation includes GCC -O2 and linking",
            "baselines": "Installed GCC and Clang C99 syntax checks on matching original C; fastest median per workload; these tool versions do not claim release-current coverage",
            "excluded": "Final target GCC compilation/linking, input generation, preflight correctness checks, and construction of installed compilers",
            "decision": "A failed one-worker case stops scheduler and language expansion; this experiment alone does not complete the full specification matrix",
        },
        "inputs": {},
        "commands": {},
        "preflight": {},
        "warmup": {},
        "samples": [],
    }
    libraries = []
    for workload in workloads:
        name = workload["name"]
        commands, artifacts = M.preflight(workload, binaries, directory, build)
        roots, library = source_roots(workload, directory, build, combined)
        libraries.append(library)
        selected = {
            "installed": commands["source-order-c-output"],
            "gcc": commands["gcc-original-syntax"],
            "clang": ["clang-20", *commands["gcc-original-syntax"][1:]],
        }
        for route, root in roots.items():
            selected[route] = [
                str(binaries["launcher"]),
                str(root),
                *(["--library"] if workload["library"] else []),
                "--emit-c",
                "--symbols",
                "/dev/null",
            ]
            response = directory / f"{name}-{route}.rsp"
            check = [*selected[route][:-1], str(response)]
            output = M.checked(check)
            assert output == Path(artifacts["c"]["path"]).read_bytes(), (name, route, "C")
            assert (
                response.read_bytes() == Path(artifacts["rename_response"]["path"]).read_bytes()
            ), (name, route, "symbols")
            assert not library.exists(), library
        M.checked(selected["clang"])
        result["inputs"][name] = {
            kind: M.file_info(path) for kind, path in {**workload["paths"], **roots}.items()
        }
        result["preflight"][name] = artifacts
        result["preflight"][name]["all_routes_identical"] = True
        result["preflight"][name]["clang_headers"] = B.dependency_manifest(selected["clang"])
        result["commands"][name] = selected
        result["warmup"][name] = {route: B.measure(command) for route, command in selected.items()}
        print(f"preflight: {name}", flush=True)
    generated = {str(path): B.sha256(path) for path in directory.iterdir() if path.suffix == ".crs"}
    result["generated_hashes"] = generated
    result["root_sources"] = {
        str(path): path.read_text()
        for path in directory.glob("*-*.crs")
        if path.name.endswith(("-interpreted.crs", "-native.crs"))
    }
    rng = random.Random(20261002)
    for index in range(args.rounds):
        order = list(result["commands"])
        rng.shuffle(order)
        for name in order:
            routes = list(result["commands"][name])
            rng.shuffle(routes)
            values = {route: B.measure(result["commands"][name][route]) for route in routes}
            result["samples"].append({"round": index, "workload": name, "ns": values})
        assert not any(path.exists() for path in libraries), "prepared stage was retained"
        print(f"paired round {index + 1}/{args.rounds}", flush=True)
    for path, expected in {**inputs, **generated}.items():
        assert B.sha256(path) == expected, f"input changed: {path}"
    for name, info in tools.items():
        assert B.tool_info(name) == info, f"tool changed: {name}"
    for path, info in installed.items():
        assert (
            M.artifact_info(Path(path), Path(path).suffix != ".a") == info
        ), f"installed artifact changed: {path}"
    for name, commands in result["commands"].items():
        facts = result["preflight"][name]
        assert (
            B.dependency_manifest(commands["gcc"])
            == facts["c_header_dependencies"]["gcc-original-syntax"]
        )
        assert B.dependency_manifest(commands["clang"]) == facts["clang_headers"]
    result["summary"] = {
        name: summary([row["ns"] for row in result["samples"] if row["workload"] == name], name)
        for name in result["commands"]
    }
    result["single_worker_pass"] = all(
        item["pass"] for value in result["summary"].values() for item in value["ratios"].values()
    )
    if args.perf:
        path = directory / "interpreter.perf"
        command = [
            str(args.perf.resolve()),
            "record",
            "-q",
            "-e",
            "cycles:u",
            "-F",
            "499",
            "-o",
            str(path),
            "--",
            *result["commands"]["ordinary-8000"]["source-interpreted"],
        ]
        M.checked(command, stdout=subprocess.DEVNULL)
        report_command = [
            str(args.perf.resolve()),
            "report",
            "--stdio",
            "--no-children",
            "--call-graph",
            "none",
            "--percent-limit",
            "1",
            "-i",
            str(path),
        ]
        result["profile"] = {
            "tool": tools[str(args.perf.resolve())],
            "command": command,
            "report_command": report_command,
            "report": M.checked(report_command).decode(),
            "data": M.file_info(path),
            "timing": "Separate untimed control after paired samples",
        }
    B.save(args.output, result)
    print(json.dumps(result["summary"], indent=2))
    return 0 if result["single_worker_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
