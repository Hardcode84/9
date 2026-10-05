#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure local ownership checking in fresh compiled-driver processes."""

import argparse
import hashlib
import importlib.util
import json
import os
import random
import resource
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ownership_support", ROOT / "tests/ownership_support.py"
)
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)
checked, execute = SUPPORT.command, SUPPORT.execute


WORKLOADS = {
    "intrusive": ("examples/intrusive/program.crs", "examples/intrusive/links.crs"),
    "tree": ("examples/ownership-graphs/program.crs", "examples/ownership-graphs/provider.crs"),
    "index": ("examples/ownership-index/program.crs", "examples/ownership-index/provider.crs"),
    "handles": ("examples/ownership-basics/handles.crs", None),
    "views": ("examples/ownership-basics/views.crs", None),
    "heap": ("examples/ownership-basics/heap.crs", None),
}


def run(command):
    usage_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter_ns()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    elapsed = time.perf_counter_ns() - start
    usage_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    if result.returncode:
        raise RuntimeError(f"{command}\n{result.stdout}{result.stderr}")
    fields = [int(x) for x in result.stderr.split()]
    if len(fields) not in (4, 5):
        raise RuntimeError(f"unexpected timing output: {result.stderr}")
    validation = fields.pop(0) if len(fields) == 5 else 0
    return dict(zip(("read_ns", "lower_ns", "check_ns", "emit_ns"), fields, strict=False)) | {
        "validation_ns": validation,
        "process_ns": elapsed,
        "user_ns": round((usage_end.ru_utime - usage_start.ru_utime) * 1e9),
        "system_ns": round((usage_end.ru_stime - usage_start.ru_stime) * 1e9),
        "frontend_ns": sum(fields),
    }


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(driver, work, name, client, provider, copies, pairs, rng, imported=None):
    declarations, body = client.read_text().split("fn main(", 1)
    source = work / f"{name}-{copies}.crs"
    source.write_text(declarations + "\n".join(f"fn workload_{i}(" + body for i in range(copies)))
    inputs = ["--library", str(source)]
    if provider:
        inputs = ["trusted", str(provider), *inputs]
    prefix = [str(driver)]
    if imported:
        prefix += ["import", *imported]
    commands = {mode: [*prefix, mode, *inputs] for mode in ("verify", "lower")}
    memory = {}
    for mode, command in commands.items():
        usage = work / f"{name}-{copies}-{mode}.usage"
        run(["/usr/bin/time", "-o", str(usage), "-f", "%M", *command])
        memory[mode] = int(usage.read_text())
    samples = []
    for _ in range(pairs):
        order = list(commands)
        rng.shuffle(order)
        samples.append({mode: run(commands[mode]) for mode in order})
    ratios = [x["verify"]["frontend_ns"] / x["lower"]["frontend_ns"] for x in samples]
    estimates = [statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(1000)]
    estimates.sort()
    return {
        "copies": copies,
        "commands": commands,
        "max_rss_kib": memory,
        "memory_observations": 1,
        "source_sha256": digest(source),
        "provider_sha256": digest(provider) if provider else None,
        "samples": samples,
        "median_frontend_ratio": statistics.median(ratios),
        "median_ratio_bootstrap_95_percent": [estimates[25], estimates[974]],
        "median_check_ns": statistics.median(x["verify"]["check_ns"] for x in samples),
        "median_verified_frontend_ns": statistics.median(
            x["verify"]["frontend_ns"] for x in samples
        ),
    }


def application(build, work, name, source, provider, pairs, rng):
    root = work / f"{name}-root.crs"
    target, symbols = work / f"{name}.c", work / f"{name}.rsp"
    interfaces = [
        ROOT / path
        for path in (
            "api/crust0_stage.crs",
            "stages/ownership/api.crs",
            "stages/ownership/build.crs",
        )
    ]
    lines = [f"host_source(run, {json.dumps(str(path))});" for path in interfaces]
    lines += [f"host_link(run, {json.dumps(str(build / 'crust-ownership-library.so'))});"]
    if provider:
        lines += [
            f"var provider:*CrustSource=host_input(run,{json.dumps(str(provider))},100u64);",
            "if provider == null(*CrustSource) {return 1i32;};",
        ]
    count = "provider,1usize" if provider else "null(*CrustSource),0usize"
    lines += [
        "return ownership_build(null(*CrustSource),0usize,(*run).argc,(*run).argv," + count + ");"
    ]
    root.write_text("\n".join(lines) + "\n")
    prefix = [str(build / "crust"), str(root), str(source)]
    commands = {
        "check": [*prefix, "--check"],
        "handoff": [*prefix, "--emit-c", "-o", str(target), "--symbols", str(symbols)],
    }
    samples = []
    memory = {}
    for mode, command in commands.items():
        usage = work / f"{name}-{mode}.usage"
        result = subprocess.run(
            ["/usr/bin/time", "-o", str(usage), "-f", "%M", *command],
            cwd=ROOT,
            capture_output=True,
            timeout=120,
        )
        memory[mode] = int(usage.read_text())
        if result.returncode or result.stdout or result.stderr:
            raise RuntimeError((command, result))
    expected_output = {"handles": b"OK\nSFF", "heap": b"AB\n"}.get(name, b"OK\n")
    execute(target, symbols, work, name, False, expected_output)
    erasure = [build / "crust-ownership-erasure"]
    if provider:
        erasure += ["trusted", provider]
    checked([*erasure, source])
    frozen = {str(path): digest(path) for path in (target, symbols, root, source, *interfaces)}
    if provider:
        frozen[str(provider)] = digest(provider)
    for _ in range(pairs):
        order = list(commands)
        rng.shuffle(order)
        row = {}
        for mode in order:
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            start = time.perf_counter_ns()
            result = subprocess.run(commands[mode], cwd=ROOT, capture_output=True, timeout=120)
            elapsed = time.perf_counter_ns() - start
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            if result.returncode or result.stdout or result.stderr:
                raise RuntimeError((commands[mode], result))
            row[mode] = {
                "process_ns": elapsed,
                "user_ns": round((after.ru_utime - before.ru_utime) * 1e9),
                "system_ns": round((after.ru_stime - before.ru_stime) * 1e9),
            }
        samples.append(row)
        for path, expected in frozen.items():
            if digest(Path(path)) != expected:
                raise RuntimeError("Application input or output changed: " + path)
    return {
        "commands": commands,
        "hashes": frozen,
        "samples": samples,
        "max_rss_kib": memory,
        "memory_observations": 1,
        "runtime_stdout": expected_output.decode(),
        "runtime_optimizations": ["-O0", "-O2"],
        "erasure_command": list(map(str, [*erasure, source])),
        "median_process_ns": {
            mode: statistics.median(row[mode]["process_ns"] for row in samples) for mode in commands
        },
        "scope": "Fresh compilation root, interfaces, explicit trust, DSO load, check, full C/symbol files, cleanup; no target GCC or linking.",
        "comparison": "Selected ownership policy cost; no equivalent independent C implementation or C-speed claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--copies", type=int, default=64)
    parser.add_argument("--pairs", type=int, default=20)
    args = parser.parse_args()
    if args.copies < 1 or args.pairs < 20:
        parser.error("copies must be positive and pairs must be at least twenty")
    args.work.mkdir(parents=True, exist_ok=False)
    driver = args.build.resolve() / "ownership-cost"
    rng = random.Random(173)
    report = {
        "driver_sha256": digest(driver),
        "build_command": "make build/ownership-cost",
        "build_flags": subprocess.check_output(
            ["make", "-s", "ownership-benchmark-config"], cwd=ROOT, text=True
        ).strip(),
        "compiler_version": subprocess.check_output(["cc", "--version"], text=True).splitlines()[0],
        "source_hashes": {
            str(p.relative_to(ROOT)): digest(p)
            for folder in ("stages", "api", "benchmarks/ownership")
            for p in (ROOT / folder).rglob("*")
            if p.suffix in (".crs", ".c", ".py")
        },
        "scope": "fresh compiled driver, read/lower/check/C emission; no target GCC or linking",
        "baseline": "same input and lowering with ownership verification omitted in benchmark only",
        "budget": 2.0,
        "pairs": args.pairs,
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "workloads": {},
        "applications": {},
        "root_binary_sha256": digest(args.build.resolve() / "crust"),
        "stage_binary_sha256": digest(args.build.resolve() / "crust-ownership-library.so"),
    }
    report["source_hashes"].update(
        {
            str(Path(path)): digest(ROOT / path)
            for pair in WORKLOADS.values()
            for path in pair
            if path
        }
    )
    passed = True
    for name, (client, provider) in WORKLOADS.items():
        results = [
            measure(
                driver,
                args.work.resolve(),
                name,
                ROOT / client,
                ROOT / provider if provider else None,
                args.copies * factor,
                args.pairs,
                rng,
            )
            for factor in (1, 2, 4)
        ]
        report["workloads"][name] = results
        report["applications"][name] = application(
            args.build.resolve(),
            args.work.resolve(),
            name,
            ROOT / client,
            ROOT / provider if provider else None,
            args.pairs,
            rng,
        )
        passed = passed and all(x["median_frontend_ratio"] <= 2.0 for x in results)
        print(name, "ratios", [round(x["median_frontend_ratio"], 3) for x in results])
    report["branch_loan_stress"] = []
    for count in (32, 64, 128):
        source = args.work.resolve() / f"loans-{count}.crs"
        lines = ["fn main(argc:i32,argv:**u8)->i32 {var total:u64=0u64;"]
        for index in range(count):
            lines += [
                f"var value{index}:u64={index}u64;var view{index}:read u64=read value{index};",
                f"if argc>{index}i32 {{total=total+view{index};}} else {{total=total ^ view{index};}}",
            ]
        lines += ["return (total & 0u64) as i32;}"]
        source.write_text("\n".join(lines) + "\n")
        result = measure(
            driver, args.work.resolve(), f"loans-{count}", source, None, 1, args.pairs, rng
        )
        result["branches_and_live_loans"] = count
        report["branch_loan_stress"].append(result)
    report["stress_scope"] = (
        "One growing body with simultaneous loans and branch joins. Report scaling separately from the independent-body acceptance budget; no C-level claim."
    )
    cache = args.work.resolve() / "cache"
    cache.mkdir()
    checked = args.work.resolve() / "provider.crs"
    checked.write_text(
        "fn observed(owner:read Owner)->read i64 access(read,Graph) from owner {return owner_value(read owner);}"
    )
    publish = [
        str(driver),
        "publish",
        str(cache),
        str(ROOT / "examples/intrusive/links.crs"),
        str(checked),
    ]
    started = time.perf_counter_ns()
    result = subprocess.run(publish, cwd=ROOT, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr)
    publication_ns = time.perf_counter_ns() - started
    artifact, receipt = result.stderr.splitlines()
    report["independent_library"] = {
        "publication_command": publish,
        "publication_includes_target_gcc_ns": publication_ns,
        "client": measure(
            driver,
            args.work.resolve(),
            "imported-intrusive",
            ROOT / "examples/intrusive/program.crs",
            None,
            args.copies * 4,
            args.pairs,
            rng,
            [str(cache), artifact, receipt],
        ),
    }
    passed = passed and report["independent_library"]["client"]["median_frontend_ratio"] <= 2.0
    for path, expected in report["source_hashes"].items():
        if digest(ROOT / path) != expected:
            raise RuntimeError("Measured source changed: " + path)
    for path, expected in (
        (driver, report["driver_sha256"]),
        (args.build.resolve() / "crust", report["root_binary_sha256"]),
        (args.build.resolve() / "crust-ownership-library.so", report["stage_binary_sha256"]),
    ):
        if digest(path) != expected:
            raise RuntimeError("Measured binary changed: " + str(path))
    report["passed"] = passed
    (args.work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if not passed:
        raise SystemExit("ownership frontend budget exceeded")


if __name__ == "__main__":
    main()
