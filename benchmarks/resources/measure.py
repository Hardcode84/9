#!/usr/bin/env python3
"""Measure prepared resource frontend work and shared cleanup growth."""
import argparse
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENDPOINTS = {
    "gcc-syntax": "Fresh GCC process through C99 syntax and semantic checks; no target code generation.",
    "gcc-callback-syntax": "Fresh GCC process through callback C99 syntax and semantic checks; no target code generation.",
    "clang-syntax": "Fresh Clang 20 process through C99 syntax and semantic checks; no target code generation.",
    "clang-callback-syntax": "Fresh Clang 20 process through callback C99 syntax and semantic checks; no target code generation.",
    "resource-check": "Fresh resource compiler: read, source ownership checks, cleanup plans, scalar ABI lowering, and lowered seed checks; no C output.",
    "resource-prepare": "Fresh resource compiler through complete generated C and symbol-rename buffers; no target GCC or file emission.",
    "root-prepare": "Fresh source-order runner, prelude, root execution, API input, ordinary DSO load/calls, and resource preparation; no target GCC.",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def portable(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return "system/" + str(path).lstrip("/")


def run(argv, **kwargs):
    result = subprocess.run(
        list(map(str, argv)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=120,
        **kwargs,
    )
    if result.returncode:
        raise RuntimeError(
            {
                "command": list(map(str, argv)),
                "status": result.returncode,
                "stderr": result.stderr.decode(errors="replace"),
            }
        )
    return result


def timed(argv):
    with tempfile.TemporaryFile() as error:
        start = time.perf_counter_ns()
        process = subprocess.Popen(list(map(str, argv)), stdout=subprocess.DEVNULL, stderr=error)
        _, status, usage = os.wait4(process.pid, 0)
        elapsed = time.perf_counter_ns() - start
        process.returncode = os.waitstatus_to_exitcode(status)
        error.seek(0)
        diagnostic = error.read()
    if process.returncode or diagnostic:
        raise RuntimeError(
            {
                "command": list(map(str, argv)),
                "status": process.returncode,
                "stderr": diagnostic.decode(errors="replace"),
            }
        )
    return {
        "wall_ns": elapsed,
        "user_cpu_ns": round(usage.ru_utime * 1e9),
        "system_cpu_ns": round(usage.ru_stime * 1e9),
        "peak_rss_kib": usage.ru_maxrss,
    }


def stress_source(count):
    total = count * (count + 1) // 2 + count
    message = f"cleanup {count}: {count+1} exits, {total} drops"
    crust = [
        'extern fn output(text:*u8)->i32="puts";',
        "resource Token { count:*u64; } drop token_drop;",
        "fn token_drop(value:mut Token)->unit { unsafe { *value.count=*value.count+1u64; } }",
        "fn workload(stop:usize,count:*u64)->unit { unsafe {",
    ]
    c = [
        "typedef unsigned long Word;",
        "extern int puts(const char *);",
        "struct Token { Word *count; };",
        "static void token_drop(struct Token *value) { *value->count += 1; }",
        "static void workload(Word stop, Word *count) {",
    ]
    for index in range(count):
        crust += [
            f"var owner{index}:Token=make Token{{count:count}};",
            f"if stop=={index}usize {{return;}}",
        ]
        c += [f"struct Token owner{index}={{count}};", f"if (stop=={index}UL) goto cleanup{index};"]
    crust += [
        "} }",
        "fn main(argc:i32,argv:**u8)->i32 {",
        "var stop:usize=0usize;",
        "var total:u64=0u64;",
        f"while stop<={count}usize {{",
        "var count:u64=0u64;",
        "unsafe {workload(stop,&count);}",
        "var expected:u64=(stop as u64)+1u64;",
        f"if stop=={count}usize {{expected={count}u64;}}",
        "if count!=expected {return 1i32;}",
        "total=total+count;stop=stop+1usize;",
        "}",
        f"if total!={total}u64 {{return 2i32;}}",
        f'unsafe {{output("{message}");}}',
        "return 0i32;",
        "}",
    ]
    for index in reversed(range(count)):
        c += [f"cleanup{index}: token_drop(&owner{index});"]
    c += [
        "}",
        "int main(void) { Word total=0;",
        f"for (Word stop=0;stop<={count}UL;++stop) {{",
        "Word count=0; workload(stop,&count);",
        f"Word expected=stop=={count}UL?{count}UL:stop+1;",
        "if (count!=expected) return 1;",
        "total+=count;",
        "}",
        f"if (total!={total}UL) return 2;",
        f'puts("{message}");',
        "return 0;",
        "}",
    ]
    return "\n".join(crust) + "\n", "\n".join(c) + "\n", (message + "\n").encode()


def c_inputs(command):
    prefix = [arg for arg in command if arg != "-fsyntax-only"]
    dependencies = run([*prefix, "-M", "-MT", "dependencies"]).stdout.decode()
    dependencies = shlex.split(dependencies.replace("\\\n", " ").split(":", 1)[1])
    paths = sorted({Path(path) for path in dependencies})
    preprocessed = run([*prefix, "-E", "-P"]).stdout
    return {
        "files": [
            {"path": portable(path), "bytes": path.stat().st_size, "sha256": sha(path)}
            for path in paths
        ],
        "input_bytes_including_headers": sum(path.stat().st_size for path in paths),
        "preprocessed_bytes": len(preprocessed),
        "preprocessed_sha256": hashlib.sha256(preprocessed).hexdigest(),
    }


def generated_functions(generated):
    code = re.sub(
        r'/\*[\s\S]*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
        lambda match: re.sub(r"[^\n]", " ", match.group()),
        generated,
    )
    if '"' in code or "'" in code or "/*" in code:
        raise AssertionError("unterminated generated C literal or comment")
    bodies = {}
    end = 0
    for match in re.finditer(r"^[^\n;{}]*\b(r_g\d+)\([^\n;{}]*\)\n\{\n", code, re.M):
        name = match[1]
        if match.start() < end or name in bodies:
            raise AssertionError(f"duplicate or nested generated function: {name}")
        begin = end = match.end()
        depth = 1
        while end < len(code) and depth:
            depth += (code[end] == "{") - (code[end] == "}")
            end += 1
        if depth:
            raise AssertionError(f"unterminated generated function: {name}")
        bodies[name] = code[begin : end - 1]
    return bodies


def generated_calls(body, function):
    captures = {}
    for name, target in re.findall(r"\b(r_v\d+)\s*=\s*(r_g\d+)\s*;", body):
        if name in captures:
            raise AssertionError(f"duplicate callee capture in {function}: {name}")
        captures[name] = target
    calls = []
    for name in re.findall(r"\b(r_[gv]\d+)\s*\(", body):
        target = captures.get(name, name if name.startswith("r_g") else None)
        if target is None:
            raise AssertionError(f"unresolved callee in {function}: {name}")
        calls.append((name, target))
    return calls


def cleanup_sites(generated, response):
    symbols = dict(token.split("=", 1)[::-1] for token in shlex.split(response) if "=" in token)
    drop = symbols["token_drop"]
    work = symbols["workload"]
    bodies = generated_functions(generated)
    for name in (drop, work):
        if name not in bodies:
            raise AssertionError(f"generated function definition not found: {name}")
    calls = {name: generated_calls(body, name) for name, body in bodies.items()}
    declared = set(bodies) | set(symbols.values())
    callers = {}
    for name, sites in calls.items():
        for _, target in sites:
            if target not in declared:
                raise AssertionError(f"generated callee definition not found: {target}")
            callers.setdefault(target, set()).add(name)
    reaches_drop = {drop}
    pending = [drop]
    while pending:
        for name in callers.get(pending.pop(), ()):
            if name not in reaches_drop:
                reaches_drop.add(name)
                pending.append(name)
    cleanup_calls = [name for name, target in calls[work] if target in reaches_drop]
    if not cleanup_calls:
        raise AssertionError("generated workload has no recognized calls to token_drop")
    return {
        "drop_source_name": "token_drop",
        "drop_c_name": drop,
        "workload_c_name": work,
        "callee_capture_names": list(
            dict.fromkeys(name for name in cleanup_calls if name.startswith("r_v"))
        ),
        "cleanup_call_sites": len(cleanup_calls),
        "cleanup_labels": len(re.findall(r"^rs_exit_\d+:;", bodies[work], re.M)),
    }


def paired_stats(samples, denominator, numerator, seed):
    rng = random.Random(seed)
    ratios = []
    for _ in range(10000):
        selected = [samples[rng.randrange(len(samples))] for _ in samples]
        ratios.append(
            statistics.median(row[numerator] for row in selected)
            / statistics.median(row[denominator] for row in selected)
        )
    ratios.sort()
    return {
        "numerator": numerator,
        "denominator": denominator,
        "ratio_of_medians": statistics.median(row[numerator] for row in samples)
        / statistics.median(row[denominator] for row in samples),
        "bootstrap_95_percent": [ratios[250], ratios[9749]],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=Path(".profile-cache/resources-performance"))
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/resources/performance.json")
    )
    parser.add_argument("--cpu", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=21)
    args = parser.parse_args()
    if args.repeats < 20:
        raise SystemExit("At least twenty fresh-process samples are required.")
    os.chdir(ROOT)
    os.sched_setaffinity(0, {args.cpu})
    args.work.mkdir(parents=True, exist_ok=True)
    compiler = Path("build/crust-resource")
    runner = Path("build/crust")
    dso = Path("build/crust-resource-library.so")
    inputs = [
        *Path("src").rglob("*.c"),
        *Path("src").rglob("*.h"),
        *Path("runtime").glob("*.c"),
        *Path("include").glob("*.h"),
        *Path("stages/resources").glob("*.crs"),
        *Path("stages/reader").glob("*.crs"),
        *Path("stages/c").glob("*.crs"),
        *Path("api").glob("*.crs"),
        *Path("examples/resources/sqlite").glob("*.crs"),
        Path("benchmarks/resources/direct.c"),
        Path("benchmarks/resources/callbacks.c"),
        Path("benchmarks/resources/common.h"),
        Path(__file__).relative_to(ROOT),
        Path("Makefile"),
        Path("stages/host.crs"),
        Path("build/crust-c"),
        compiler,
        runner,
        dso,
    ]
    frozen = {str(path): sha(path) for path in sorted(inputs)}
    gcc = ["gcc", "-std=c99", "-pedantic-errors", "-fsyntax-only"]
    clang = ["clang-20", "-std=c99", "-pedantic-errors", "-fsyntax-only"]
    sqlite_crust = [
        "examples/resources/sqlite/library.crs",
        "examples/resources/sqlite/program.crs",
    ]
    workloads = [
        {
            "name": "sqlite",
            "commands": {
                "gcc-syntax": [*gcc, "-I.profile-cache/sources", "benchmarks/resources/direct.c"],
                "gcc-callback-syntax": [
                    *gcc,
                    "-I.profile-cache/sources",
                    "benchmarks/resources/callbacks.c",
                ],
                "clang-syntax": [
                    *clang,
                    "-I.profile-cache/sources",
                    "benchmarks/resources/direct.c",
                ],
                "clang-callback-syntax": [
                    *clang,
                    "-I.profile-cache/sources",
                    "benchmarks/resources/callbacks.c",
                ],
                "resource-check": [str(compiler), "--check", *sqlite_crust],
                "resource-prepare": [str(compiler), "--prepare", *sqlite_crust],
                "root-prepare": [str(runner), "examples/resources/sqlite/main.crs", "--prepare"],
            },
            "crust_input_bytes": sum(Path(path).stat().st_size for path in sqlite_crust),
            "crust_source_sha256": {path: sha(path) for path in sqlite_crust},
        }
    ]
    for count in (16, 64, 256):
        crust, c, expected = stress_source(count)
        crust_path = args.work / f"owners-{count}.crs"
        c_path = args.work / f"owners-{count}.c"
        root_path = args.work / f"owners-{count}.root.crs"
        crust_path.write_text(crust)
        c_path.write_text(c)

        def relative(path, root=root_path):
            return os.path.relpath(ROOT / path, root.parent.resolve())

        root_source = "\n".join(
            [
                f'host_source(run,"{relative("api/crust0_stage.crs")}");',
                f'host_source(run,"{relative("stages/resources/api.crs")}");',
                f'host_link(run,"{relative(dso)}");',
                f'var target:*CrustSource=host_input(run,"{crust_path.name}",1u64);',
                'var arguments:[*u8;1]=make [*u8;1]{"--prepare"};',
                "return resource_build(target,0usize,1i32,&arguments[0usize]);",
                "",
            ]
        )
        root_path.write_text(root_source)
        generated = args.work / f"owners-{count}.generated.c"
        response = args.work / f"owners-{count}.rsp"
        emit_command = [
            str(compiler),
            "--emit-c",
            "--export",
            "token_drop",
            "--export",
            "workload",
            "-o",
            str(generated),
            "--symbols",
            str(response),
            str(crust_path),
        ]
        run(emit_command)
        sites = cleanup_sites(generated.read_text(), response.read_text())
        c_binary = args.work / f"owners-{count}-c"
        crust_binary = args.work / f"owners-{count}-resource"
        runtime_commands = [
            ["gcc", "-std=c99", "-pedantic-errors", "-O2", "-g0", str(c_path), "-o", str(c_binary)],
            [str(compiler), "--cflag=-O2", "-o", str(crust_binary), str(crust_path)],
        ]
        for command in runtime_commands:
            run(command)
        for binary in (c_binary, crust_binary):
            result = run([binary])
            if result.stdout != expected or result.stderr:
                raise AssertionError((str(binary), result.stdout, result.stderr))
        workloads.append(
            {
                "name": f"owners-{count}",
                "owners": count,
                "early_exits": count,
                "commands": {
                    "gcc-syntax": [*gcc, str(c_path)],
                    "clang-syntax": [*clang, str(c_path)],
                    "resource-check": [str(compiler), "--check", str(crust_path)],
                    "resource-prepare": [str(compiler), "--prepare", str(crust_path)],
                    "root-prepare": [str(runner), str(root_path)],
                },
                "crust_input_bytes": len(crust.encode()),
                "c_input_bytes": len(c.encode()),
                "source": {"crust": crust, "c": c, "root": root_source},
                "source_sha256": {str(path): sha(path) for path in (crust_path, c_path, root_path)},
                "emission": {
                    "command": emit_command,
                    "bytes": generated.stat().st_size,
                    "sha256": sha(generated),
                    "rename_bytes": response.stat().st_size,
                    **sites,
                },
                "runtime": {
                    "commands": runtime_commands,
                    "run_commands": [[str(c_binary)], [str(crust_binary)]],
                    "stdout": expected.decode(),
                    "stderr": "",
                    "status": 0,
                    "paths_checked_per_implementation": count + 1,
                    "drop_count_per_implementation": count * (count + 1) // 2 + count,
                    "binary_sha256": {str(path): sha(path) for path in (c_binary, crust_binary)},
                },
            }
        )
    for workload in workloads:
        workload["c_inputs"] = {
            name: c_inputs(command)
            for name, command in workload["commands"].items()
            if name.startswith(("gcc", "clang"))
        }
        for command in workload["commands"].values():
            result = run(command)
            if result.stdout or result.stderr:
                raise AssertionError((command, result.stdout, result.stderr))
    print(
        "Resource measurement inputs and runtime checks passed; starting serial timed samples.",
        flush=True,
    )
    rng = random.Random(20261001)
    for workload in workloads:
        samples = []
        usage_samples = []
        orders = []
        for _ in range(args.repeats):
            order = list(workload["commands"])
            rng.shuffle(order)
            row = {}
            usage_row = {}
            for name in order:
                usage = timed(workload["commands"][name])
                row[name] = usage["wall_ns"]
                usage_row[name] = usage
            samples.append(row)
            usage_samples.append(usage_row)
            orders.append(order)
        workload["samples_ns"] = samples
        workload["orders"] = orders
        workload["usage_samples"] = usage_samples
        workload["median_ms"] = {
            name: statistics.median(row[name] for row in samples) / 1e6
            for name in workload["commands"]
        }
        workload["variation"] = {}
        for name in workload["commands"]:
            ordered = sorted(row[name] for row in samples)
            workload["variation"][name] = {
                "wall_p10_ms": ordered[(len(ordered) - 1) // 10] / 1e6,
                "wall_p90_ms": ordered[9 * (len(ordered) - 1) // 10] / 1e6,
                "median_total_cpu_ms": statistics.median(
                    row[name]["user_cpu_ns"] + row[name]["system_cpu_ns"] for row in usage_samples
                )
                / 1e6,
                "median_peak_rss_kib": statistics.median(
                    row[name]["peak_rss_kib"] for row in usage_samples
                ),
                "max_peak_rss_kib": max(row[name]["peak_rss_kib"] for row in usage_samples),
            }
        workload["ratios_to_direct_c"] = [
            paired_stats(samples, "gcc-syntax", name, 20261001)
            for name in workload["commands"]
            if name != "gcc-syntax"
        ]
        fastest = min(("gcc-syntax", "clang-syntax"), key=lambda name: workload["median_ms"][name])
        comparisons = [
            paired_stats(samples, fastest, name, 20261001)
            for name in ("resource-check", "resource-prepare", "root-prepare")
        ]
        for comparison in comparisons:
            comparison["ratio_rule_passed"] = (
                comparison["ratio_of_medians"] <= 1 and comparison["bootstrap_95_percent"][1] <= 1
            )
        workload["comparisons_to_fastest_direct_c"] = comparisons
        workload["check_gate"] = {
            "eligible": workload["name"] != "sqlite",
            "outcome": (
                "not established: full SQLite header versus used FFI subset"
                if workload["name"] == "sqlite"
                else "pass" if comparisons[0]["ratio_rule_passed"] else "fail"
            ),
            "boundary": "resource check includes cleanup and scalar ABI lowering; C syntax stops after semantic checks",
        }
        print(workload["name"], workload["median_ms"], flush=True)
    makefile = Path("Makefile").read_text()

    def make_words(name):
        value = re.search(r"^" + name + r"\s*=\s*(.*)$", makefile, re.M).group(1)
        while "$(" in value:
            value = re.sub(r"\$\((\w+)\)", lambda item: " ".join(make_words(item.group(1))), value)
        return value.split()

    stage_sources = make_words("RESOURCE_LIBRARY")
    exports = make_words("RESOURCE_EXPORTS")
    stage_object = args.work / "prepared-resource-stage.o"
    stage_library = args.work / "prepared-resource-stage.so"
    prepare_commands = [
        [
            "build/crust-c",
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
    print(
        "Frontend timing complete; measuring separate native resource-stage preparation.",
        flush=True,
    )
    prepare_samples = [timed(command) for command in prepare_commands]
    native_preparation = {
        "commands": prepare_commands,
        "observations": prepare_samples,
        "total_wall_ms": sum(item["wall_ns"] for item in prepare_samples) / 1e6,
        "scope": "one construction of the native resource/reader/C library from CRUST source using an installed CRUST C compiler; includes target GCC optimization, object assembly, renaming, and shared linking",
        "statistic": "one observation per command; not a median or confidence interval",
        "source_bytes": sum(Path(path).stat().st_size for path in stage_sources),
        "source_sha256": {path: sha(path) for path in stage_sources},
        "artifacts_sha256": {str(path): sha(path) for path in (stage_object, stage_library)},
    }
    if any(sha(path) != digest for path, digest in frozen.items()):
        raise SystemExit("Measured sources or tools changed; discard this timing batch.")
    stress = workloads[1:]
    growth = [
        {
            "from": earlier["owners"],
            "to": later["owners"],
            "owner_ratio": later["owners"] / earlier["owners"],
            "emitted_c_byte_ratio": later["emission"]["bytes"] / earlier["emission"]["bytes"],
            "median_time_ratios": {
                name: later["median_ms"][name] / earlier["median_ms"][name]
                for name in later["median_ms"]
            },
        }
        for earlier, later in zip(stress, stress[1:], strict=False)
    ]
    passed = all(
        item["emission"]["cleanup_call_sites"] == item["owners"] for item in stress
    ) and all(item["emitted_c_byte_ratio"] <= 5 for item in growth)
    model = next(
        (
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("model name")
        ),
        "unknown",
    )
    siblings = (
        Path(f"/sys/devices/system/cpu/cpu{args.cpu}/topology/thread_siblings_list")
        .read_text()
        .strip()
    )
    report = {
        "schema_version": 1,
        "method": {
            "samples_per_endpoint": args.repeats,
            "order": "deterministic shuffled endpoints within paired rounds",
            "seed": 20261001,
            "cpu": args.cpu,
            "smt_siblings": siblings,
            "workers": 1,
            "clock": "perf_counter_ns around fresh child launch and completion",
            "cache": "fresh processes; OS file cache warm; no compiler cache",
            "preparation": "installed reader/resource/C stages were built before timing; their native compilation is excluded",
            "target_backend": "all target GCC code generation, assembly, linking, and runtime checks excluded from samples",
            "warmup": "one untimed invocation per endpoint",
            "bootstrap": "10000 resamples of complete paired rounds; ratio-of-medians 95 percent interval",
            "usage": "wait4 child user/system CPU time and peak resident set per invocation",
            "noise": "one logical CPU pinned; no isolation from shared caches, kernel work, or machine-wide load",
        },
        "platform": {
            "system": os.uname().sysname,
            "release": os.uname().release,
            "machine": os.uname().machine,
            "cpu": model,
            "memory_total_kib": int(
                re.search(r"^MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text(), re.M).group(1)
            ),
        },
        "repository_revision": run(["git", "rev-parse", "HEAD"]).stdout.decode().strip(),
        "repository_state": "uncommitted implementation measured by exact source and binary hashes",
        "versions": {
            "gcc": run(["gcc", "--version"]).stdout.decode().splitlines()[0],
            "clang": run(["clang-20", "--version"]).stdout.decode().splitlines()[0],
            "resource": run([compiler, "--version"]).stdout.decode().strip(),
        },
        "endpoints": ENDPOINTS,
        "source_and_binary_sha256": frozen,
        "gcc_binary_sha256": sha(shutil.which("gcc")),
        "clang_binary_sha256": sha(shutil.which("clang-20")),
        "workloads": workloads,
        "native_stage_preparation": native_preparation,
        "speed_pass_rule": {
            "source": "docs/exploration/language-exploration.md sections 10.3 and 10.4",
            "samples": "at least 20 paired fresh processes",
            "criterion": "candidate/fastest eligible C median <=1.00 and upper95% confidence bound <=1.00 for each comparable workload and boundary",
            "handoff": "complete generated C is measured, but no matching C frontend-only handoff baseline is measured; its formal handoff gate is not established",
            "project_stage": "a project that must build this native stage adds the separately recorded preparation cost to its cold critical path",
        },
        "hypothesis": {
            "claim": "Shared cleanup emits one token_drop call site per owner; fourfold owner/exit growth emits at most fivefold C bytes.",
            "passed": passed,
            "growth": growth,
            "observed_cleanup_calls_per_owner": [
                item["emission"]["cleanup_call_sites"] / item["owners"] for item in stress
            ],
            "observed_mechanism": "early returns target the function epilogue; natural block completion targets a distinct scope continuation, producing two shared linear cleanup chains",
            "scope": "16/64/256 owners with the same number of early exits; static cleanup sharing and observed timing only",
        },
        "overall_language_speed_gate": "not established: SQLite reads unequal interfaces, complete C handoff has no matching C handoff baseline here, and the small generated inputs contain substantial process startup cost",
        "interpretation": "SQLite C reads its full public header and system headers; CRUST declares only the used FFI. Tiny stress inputs include large fixed process costs. These measurements do not establish a general faster-than-C frontend or runtime result.",
        "complete": True,
    }
    args.output.write_text((json.dumps(report, indent=2) + "\n").replace(str(ROOT), "@REPO@"))
    print("cleanup growth hypothesis:", passed, flush=True)
    print(args.output, flush=True)


if __name__ == "__main__":
    main()
