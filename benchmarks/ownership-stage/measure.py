#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Test a bounded ownership and generics port of the production union stage."""

import argparse
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


class Experiment:
    def __init__(self, output):
        self.output = output
        self.commands = []
        self.hashes = {}

    def run(self, command, expected=0):
        command = list(map(str, command))
        self.commands.append(command)
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300)
        if result.returncode != expected:
            raise RuntimeError(f"{command}\n{result.stdout}{result.stderr}")
        return result

    def capture(self, path):
        path = Path(path).resolve()
        target = self.output / "inputs" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError(f"input changed during the experiment: {path}")
        target.write_bytes(data)
        self.hashes[str(path.relative_to(ROOT))] = hashlib.sha256(target.read_bytes()).hexdigest()
        return target

    def write(self, name, text):
        path = self.output / name
        path.write_text(text)
        return path

    def declarations(self, path):
        saved = self.capture(path)
        data = saved.read_bytes()
        result = self.run([ROOT / "build/crust", HERE / "inspect.crs", saved])
        declarations = []
        for line in result.stdout.splitlines():
            kind, begin, body, end, opaque, name = line.split()
            begin, body, end = map(int, (begin, body, end))
            declarations.append(
                {
                    "kind": int(kind),
                    "name": name,
                    "opaque": bool(int(opaque)),
                    "text": data[begin:end].decode(),
                    "header": data[begin:body].decode().strip(),
                    "body_lines": len(data[body:end].splitlines()) if int(kind) == 1 else 0,
                    "path": str(path.relative_to(ROOT)),
                }
            )
        return declarations


def opaque(declaration):
    return declaration["text"] + (" opaque;" if declaration["opaque"] else "")


def prepare(experiment, sources):
    dependencies, target, exports = [], [], []
    dependency_paths = []
    for path in sources:
        declarations = experiment.declarations(path)
        if path.parent == ROOT / "stages/union":
            target.extend(declarations)
            continue
        dependency_paths.append(experiment.output / "inputs" / path.relative_to(ROOT))
        for declaration in declarations:
            if declaration["kind"] == 1:
                exports.append(declaration["name"])
                declaration["text"] = (
                    "extern " + declaration["header"] + f' = "{declaration["name"]}";'
                )
            dependencies.append(declaration)
    raw = "\n".join(d["text"] for d in dependencies + target)
    port = "\n".join(opaque(d) for d in dependencies + target)
    experiment.write("raw.crs", raw)
    experiment.write("opaque.crs", port)
    experiment.write(
        "unannotated.crs",
        "\n".join([opaque(d) for d in dependencies] + [d["text"] for d in target]),
    )
    experiment.write(
        "main-imports.crs",
        "\n".join(d["text"] for d in dependencies if not d["name"].startswith("CRUST_ABI_")),
    )
    lookup = "crust_map_get(&stage->layouts,decl as usize) as *SuLayout"
    assert port.count(lookup) == 1
    helper = "\nfn su_cache_get!(Value)(cache:*CrustMap,key:usize)->*Value { return crust_map_get(cache,key) as *Value; }\n"
    generic = (
        port.replace(lookup, "su_cache_get!(SuLayout)(&stage->layouts,decl as usize)") + helper
    )
    experiment.write("generic.crs", generic)
    experiment.write(
        "generic-raw.crs",
        raw.replace(lookup, "su_cache_get!(SuLayout)(&stage->layouts,decl as usize)") + helper,
    )
    function = next(d["text"] for d in target if d["name"] == "su_layout_record")
    borrowed = function.replace("fn su_layout_record(", "fn probe_layout_record(")
    for before, after in (
        ("stage:*SuStage", "stage:mut SuStage"),
        ("decl:*CrustDecl", "decl:read CrustDecl"),
        ("stage->", "stage."),
        ("decl->", "decl."),
        ("decl as usize", "&decl as usize"),
        ("layout->declaration=decl", "layout->declaration=&decl"),
    ):
        borrowed = borrowed.replace(before, after)
    for name in ("su_error", "su_alloc", "su_layout_variants", "su_layout_fields", "su_round"):
        borrowed = borrowed.replace(name + "(stage,", name + "(&stage,")
    experiment.write("borrow.crs", port + "\n" + borrowed)
    experiment.write(
        "field.crs",
        port + "\nfn probe_serial(stage:read SuStage)->usize { return stage.serial; }\n",
    )
    return dependencies, target, dependency_paths, exports


def compile_driver(experiment, sources):
    clock = experiment.output / "clock.o"
    experiment.run(
        [
            "gcc",
            "-std=c99",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-c",
            experiment.capture(ROOT / "benchmarks/ownership/clock_linux_x64.c"),
            "-o",
            clock,
        ]
    )
    driver = experiment.output / "driver"
    experiment.run(
        [
            ROOT / "build/crust-c",
            "-o",
            driver,
            *[experiment.capture(p) for p in sources],
            experiment.capture(HERE / "driver.crs"),
            "--cflag=-O2",
            "--ldflag",
            clock,
            "--ldflag",
            ROOT / "build/libcrust0.a",
            "--ldflag",
            ROOT / "build/libcrust0_host.a",
        ]
    )
    return driver


def probe(experiment, driver, source, selected="*", mode="checked", expected=0):
    return experiment.run(
        [
            driver,
            mode,
            selected,
            experiment.output / f"{source}.crs",
            experiment.output / f"{source}.c",
            experiment.output / f"{source}.rsp",
        ],
        expected,
    )


def compile_object(experiment, name, flags):
    work = experiment.output
    experiment.run(
        [
            "gcc",
            "-std=c99",
            "-pedantic-errors",
            *flags,
            "-c",
            work / f"{name}.c",
            "-o",
            work / f"{name}.input.o",
        ]
    )
    result = work / f"{name}.o"
    experiment.run(["objcopy", f"@{work / (name + '.rsp')}", work / f"{name}.input.o", result])
    return result


def native_checks(experiment, dependency_paths, exports, corpus):
    work = experiment.output
    flags = ["-O2", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie"]
    dependencies = work / "dependencies.o"
    experiment.run(
        [
            ROOT / "build/crust-c",
            "--library",
            "--object",
            "-o",
            dependencies,
            *dependency_paths,
            *[arg for name in exports for arg in ("--export", name)],
            *[arg for flag in flags for arg in ("--cflag", flag)],
        ]
    )
    main = experiment.capture(HERE / "main.crs")
    main_object = work / "main.o"
    experiment.run(
        [
            ROOT / "build/crust-c",
            "--object",
            "-o",
            main_object,
            work / "main-imports.crs",
            experiment.capture(ROOT / "stages/union/api.crs"),
            main,
        ]
    )
    runtime = experiment.write("runtime.crs", corpus.RUNTIME)
    artifacts = []
    for name in ("raw", "opaque", "generic-raw", "generic"):
        obj = compile_object(experiment, name, flags)
        compiler = work / f"{name}-union"
        experiment.run(
            [
                "gcc",
                *flags,
                "-no-pie",
                main_object,
                obj,
                dependencies,
                ROOT / "build/libcrust0.a",
                ROOT / "build/libcrust0_host.a",
                "-o",
                compiler,
            ]
        )
        c_output, symbols = work / f"{name}-target.c", work / f"{name}-target.rsp"
        experiment.run([compiler, "--emit-c", "-o", c_output, "--symbols", symbols, runtime])
        artifacts.append((c_output.read_bytes(), symbols.read_bytes()))
        obj = compile_object(experiment, name + "-target", flags)
        binary = work / f"{name}-target"
        experiment.run(["gcc", *flags, "-no-pie", obj, "-o", binary])
        experiment.run([binary])
        for case, (text, diagnostic) in corpus.REJECT.items():
            path = experiment.write(f"reject-{case}.crs", text)
            result = experiment.run([compiler, "--check", path], expected=1)
            assert diagnostic in result.stderr, (case, result.stderr)
    assert all(
        artifact == artifacts[0] for artifact in artifacts
    ), "stage transformation changed target output"
    return {
        "sanitizers": "address,undefined",
        "target_bytes_equal": True,
        "runtime_cases": len(artifacts),
        "rejections_per_compiler": len(corpus.REJECT),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--cpu", type=int, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build") or args.rounds < 3:
        parser.error("use a new directory under build/ and at least three rounds")
    os.sched_setaffinity(0, {args.cpu})
    output.mkdir(parents=True)
    sys.path.insert(0, str(ROOT / "tests"))
    import prepare as packages
    import union as corpus

    experiment = Experiment(output)
    for path in (
        HERE / "inspect.crs",
        Path(__file__),
        ROOT / "tests/union.py",
        ROOT / "tests/prepare.py",
    ):
        experiment.capture(path)
    dependencies, target, paths, exports = prepare(
        experiment, packages.sources(ROOT / "build", "union/package.crs")
    )
    driver = compile_driver(
        experiment, packages.sources(ROOT / "build", "generics/ownership/package.crs")
    )
    attempts = {}
    for name, selected, expected in (
        ("raw", "*", "persistent pointers require"),
        ("unannotated", "*", "persistent pointers require"),
        ("borrow", "probe_layout_record", "pointer argument requires a declared domain interface"),
        ("field", "probe_serial", "opaque fields are private to the trusted implementation"),
    ):
        result = probe(experiment, driver, name, selected, expected=1)
        assert expected in result.stderr, result.stderr
        attempts[name] = result.stderr
    functions = [d for d in target if d["kind"] == 1]
    rejected = {}
    for declaration in functions:
        result = probe(experiment, driver, "opaque", declaration["name"], expected=1)
        rejected[declaration["name"]] = result.stderr
    rng = random.Random(0)
    samples = []
    for _ in range(args.rounds):
        modes = ["raw", "opaque", "generic-raw", "generic"]
        rng.shuffle(modes)
        sample = {}
        for mode in modes:
            frontend = {
                "raw": "raw",
                "opaque": "checked",
                "generic-raw": "generic",
                "generic": "checked",
            }[mode]
            result = probe(experiment, driver, mode, mode=frontend)
            sample[mode] = dict(
                zip(
                    ("read_ns", "check_ns", "emit_ns"), map(int, result.stdout.split()), strict=True
                )
            )
        samples.append(sample)
    report = {
        "status": "generic cache argument accepted; arena client contracts still require repair",
        "scope": "union stage; raw reader and C backend dependencies behind native interfaces",
        "cpu": args.cpu,
        "attempts": attempts,
        "body_rejections": rejected,
        "burden": {
            "functions": len(functions),
            "trusted_functions": len(rejected),
            "function_lines": sum(d["body_lines"] for d in functions),
            "trusted_function_lines": sum(
                d["body_lines"] for d in functions if d["name"] in rejected
            ),
            "opaque_records": sum(d["opaque"] for d in target),
            "opaque_dependency_records": sum(d["opaque"] for d in dependencies),
            "borrow_parameters": 2,
            "generic_parameters": 1,
            "generic_applications": 1,
            "restructuring": "one typed cache helper; borrow probe keeps layout control flow",
            "client_budget_comparison": "tutorial client budgets exclude providers; no compiler-stage budget exists",
        },
        "samples": samples,
        "checked_generic_frontend_ns": None,
        "cost_scope": "fresh native process; read/copy and root trust selection, checks, emission timed separately; initialization, naming, teardown, file IO, GCC and linking excluded; opaque is a trust-only control",
        "control_frontend_ratio": statistics.median(
            sum(s["opaque"].values()) / sum(s["raw"].values()) for s in samples
        ),
        "generic_trust_only_frontend_ratio": statistics.median(
            sum(s["generic"].values()) / sum(s["raw"].values()) for s in samples
        ),
        "standalone_generic_frontend_ratio": statistics.median(
            sum(s["generic-raw"].values()) / sum(s["raw"].values()) for s in samples
        ),
        "validation": native_checks(experiment, paths, exports, corpus),
        "commands": experiment.commands,
        "sha256": experiment.hashes,
    }
    ratios = [sum(s["opaque"].values()) / sum(s["raw"].values()) for s in samples]
    estimates = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(2000))
    report["control_ratio_bootstrap_95"] = [estimates[50], estimates[1949]]
    report["toolchain"] = experiment.run(["gcc", "--version"]).stdout
    report["binary_sha256"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            driver,
            ROOT / "build/crust",
            ROOT / "build/crust-c",
            ROOT / "build/libcrust0.a",
            ROOT / "build/libcrust0_host.a",
        )
    }
    experiment.write("report.json", json.dumps(report, indent=2) + "\n")
    print(report["status"])
    print(json.dumps(report["burden"], indent=2))
    print(f"Report: {output / 'report.json'}")


if __name__ == "__main__":
    main()
