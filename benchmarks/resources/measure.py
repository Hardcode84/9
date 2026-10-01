#!/usr/bin/env python3
"""Measure prepared resource frontend work and shared cleanup growth."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shlex
import shutil
import statistics
import subprocess
import tempfile
import time

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
    result = subprocess.run(list(map(str, argv)), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            check=False, timeout=120, **kwargs)
    if result.returncode:
        raise RuntimeError({"command": list(map(str, argv)), "status": result.returncode,
                            "stderr": result.stderr.decode(errors="replace")})
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
        raise RuntimeError({"command": list(map(str, argv)), "status": process.returncode,
                            "stderr": diagnostic.decode(errors="replace")})
    return {"wall_ns": elapsed, "user_cpu_ns": round(usage.ru_utime * 1e9),
            "system_cpu_ns": round(usage.ru_stime * 1e9), "peak_rss_kib": usage.ru_maxrss}


def stress_source(count):
    total = count * (count + 1) // 2 + count
    message = f"cleanup {count}: {count+1} exits, {total} drops"
    rmd = ['extern fn output(text:*u8)->i32="puts";',
           'resource Token { count:*u64; } drop token_drop;',
           'fn token_drop(value:mut Token)->unit { unsafe { *value.count=*value.count+1u64; } }',
           'fn workload(stop:usize,count:*u64)->unit { unsafe {']
    c = ['typedef unsigned long Word;', 'extern int puts(const char *);',
         'struct Token { Word *count; };',
         'static void token_drop(struct Token *value) { *value->count += 1; }',
         'static void workload(Word stop, Word *count) {']
    for index in range(count):
        rmd += [f'var owner{index}:Token=make Token{{count:count}};',
                f'if stop=={index}usize {{return;}}']
        c += [f'struct Token owner{index}={{count}};', f'if (stop=={index}UL) goto cleanup{index};']
    rmd += ['} }', 'fn main(argc:i32,argv:**u8)->i32 {', 'var stop:usize=0usize;',
            'var total:u64=0u64;', f'while stop<={count}usize {{',
            'var count:u64=0u64;', 'unsafe {workload(stop,&count);}',
            'var expected:u64=(stop as u64)+1u64;',
            f'if stop=={count}usize {{expected={count}u64;}}',
            'if count!=expected {return 1i32;}', 'total=total+count;stop=stop+1usize;', '}',
            f'if total!={total}u64 {{return 2i32;}}',
            f'unsafe {{output("{message}");}}', 'return 0i32;', '}']
    for index in reversed(range(count)):
        c += [f'cleanup{index}: token_drop(&owner{index});']
    c += ['}', 'int main(void) { Word total=0;', f'for (Word stop=0;stop<={count}UL;++stop) {{',
          'Word count=0; workload(stop,&count);', f'Word expected=stop=={count}UL?{count}UL:stop+1;',
          'if (count!=expected) return 1;', 'total+=count;', '}',
          f'if (total!={total}UL) return 2;', f'puts("{message}");', 'return 0;', '}']
    return "\n".join(rmd) + "\n", "\n".join(c) + "\n", (message + "\n").encode()


def c_inputs(command):
    prefix = [arg for arg in command if arg != "-fsyntax-only"]
    dependencies = run([*prefix, "-M", "-MT", "dependencies"]).stdout.decode()
    dependencies = shlex.split(dependencies.replace("\\\n", " ").split(":", 1)[1])
    paths = sorted({Path(path) for path in dependencies})
    preprocessed = run([*prefix, "-E", "-P"]).stdout
    return {"files": [{"path": portable(path), "bytes": path.stat().st_size, "sha256": sha(path)}
                       for path in paths],
            "input_bytes_including_headers": sum(path.stat().st_size for path in paths),
            "preprocessed_bytes": len(preprocessed), "preprocessed_sha256": hashlib.sha256(preprocessed).hexdigest()}


def cleanup_sites(source, generated, response):
    declarations = re.findall(r"^(?:(?:unsafe |extern )?fn|record|resource|const)\s+([A-Za-z_]\w*)", source, re.M)
    symbols = dict(token.split("=", 1)[::-1] for token in shlex.split(response) if "=" in token)
    drop = symbols["_rmd0_u1_d" + str(declarations.index("token_drop") + 1)]
    work = symbols["_rmd0_u1_d" + str(declarations.index("workload") + 1)]
    match = re.search(r"^.*\b" + re.escape(work) + r"\([^;\n]*\)\n\{\n", generated, re.M)
    if not match:
        raise AssertionError("generated workload definition not found")
    begin = match.end()
    depth = 1
    end = begin
    while depth:
        if generated[end] == "{": depth += 1
        if generated[end] == "}": depth -= 1
        end += 1
    body = generated[begin:end]
    callees = re.findall(r"\b(r_v\d+)\s*=\s*" + re.escape(drop) + ";", body)
    calls = sum(len(re.findall(r"\b" + name + r"\s*\(", body)) for name in callees)
    return {"drop_source_name": "token_drop", "drop_c_name": drop, "workload_c_name": work,
            "callee_capture_names": callees, "cleanup_call_sites": calls,
            "cleanup_labels": len(re.findall(r"^rs_exit_\d+:;", body, re.M))}


def paired_stats(samples, denominator, numerator, seed):
    rng = random.Random(seed)
    ratios = []
    for _ in range(10000):
        selected = [samples[rng.randrange(len(samples))] for _ in samples]
        ratios.append(statistics.median(row[numerator] for row in selected) /
                      statistics.median(row[denominator] for row in selected))
    ratios.sort()
    return {"numerator": numerator, "denominator": denominator,
            "ratio_of_medians": statistics.median(row[numerator] for row in samples) /
                                statistics.median(row[denominator] for row in samples),
            "bootstrap_95_percent": [ratios[250], ratios[9749]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=Path(".profile-cache/resources-performance"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/resources/performance.json"))
    parser.add_argument("--cpu", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=21)
    args = parser.parse_args()
    if args.repeats < 20:
        raise SystemExit("At least twenty fresh-process samples are required.")
    os.chdir(ROOT)
    os.sched_setaffinity(0, {args.cpu})
    args.work.mkdir(parents=True, exist_ok=True)
    compiler = Path("build/rmd-resource")
    runner = Path("build/rmd")
    dso = Path("build/rmd-resource-library.so")
    inputs = [*Path("src").glob("*.c"), *Path("include").glob("*.h"),
              *Path("stages/resources").glob("*.rmd"), *Path("stages/reader").glob("*.rmd"),
              *Path("stages/c").glob("*.rmd"), *Path("api").glob("*.rmd"),
              *Path("examples/resources/sqlite").glob("*.rmd"),
              Path("benchmarks/resources/direct.c"), Path("benchmarks/resources/callbacks.c"),
              Path("benchmarks/resources/common.h"), Path(__file__).relative_to(ROOT),
              Path("Makefile"), Path("stages/host.rmd"), Path("build/rmd-c"), compiler, runner, dso]
    frozen = {str(path): sha(path) for path in sorted(inputs)}
    gcc = ["gcc", "-std=c99", "-pedantic-errors", "-fsyntax-only"]
    clang = ["clang-20", "-std=c99", "-pedantic-errors", "-fsyntax-only"]
    sqlite_rmd = ["examples/resources/sqlite/library.rmd", "examples/resources/sqlite/program.rmd"]
    workloads = [{"name": "sqlite", "commands": {
        "gcc-syntax": [*gcc, "-I.profile-cache/sources", "benchmarks/resources/direct.c"],
        "gcc-callback-syntax": [*gcc, "-I.profile-cache/sources", "benchmarks/resources/callbacks.c"],
        "clang-syntax": [*clang, "-I.profile-cache/sources", "benchmarks/resources/direct.c"],
        "clang-callback-syntax": [*clang, "-I.profile-cache/sources", "benchmarks/resources/callbacks.c"],
        "resource-check": [str(compiler), "--check", *sqlite_rmd],
        "resource-prepare": [str(compiler), "--prepare", *sqlite_rmd],
        "root-prepare": [str(runner), "examples/resources/sqlite/main.rmd", "--prepare"]},
        "rmd_input_bytes": sum(Path(path).stat().st_size for path in sqlite_rmd),
        "rmd_source_sha256": {path: sha(path) for path in sqlite_rmd}}]
    for count in (16, 64, 256):
        rmd, c, expected = stress_source(count)
        rmd_path = args.work / f"owners-{count}.rmd"
        c_path = args.work / f"owners-{count}.c"
        root_path = args.work / f"owners-{count}.root.rmd"
        rmd_path.write_text(rmd)
        c_path.write_text(c)
        relative = lambda path: os.path.relpath(ROOT / path, root_path.parent.resolve())
        root_source = '\n'.join([
            f'host_source(run,"{relative("api/rmd0_stage.rmd")}");',
            f'host_source(run,"{relative("stages/resources/api.rmd")}");',
            f'host_link(run,"{relative(dso)}");',
            f'var target:*RmdSource=host_input(run,"{rmd_path.name}",1u64);',
            'var arguments:[*u8;1]=make [*u8;1]{"--prepare"};',
            'return resource_build(target,0usize,1i32,&arguments[0usize]);', ''])
        root_path.write_text(root_source)
        generated = args.work / f"owners-{count}.generated.c"
        response = args.work / f"owners-{count}.rsp"
        emit_command = [str(compiler), "--emit-c", "-o", str(generated), "--symbols", str(response), str(rmd_path)]
        run(emit_command)
        sites = cleanup_sites(rmd, generated.read_text(), response.read_text())
        c_binary = args.work / f"owners-{count}-c"
        rmd_binary = args.work / f"owners-{count}-resource"
        runtime_commands = [["gcc", "-std=c99", "-pedantic-errors", "-O2", "-g0", str(c_path), "-o", str(c_binary)],
                            [str(compiler), "--cflag=-O2", "-o", str(rmd_binary), str(rmd_path)]]
        for command in runtime_commands:
            run(command)
        for binary in (c_binary, rmd_binary):
            result = run([binary])
            if result.stdout != expected or result.stderr:
                raise AssertionError((str(binary), result.stdout, result.stderr))
        workloads.append({"name": f"owners-{count}", "owners": count, "early_exits": count,
                          "commands": {"gcc-syntax": [*gcc, str(c_path)],
                                       "clang-syntax": [*clang, str(c_path)],
                                       "resource-check": [str(compiler), "--check", str(rmd_path)],
                                       "resource-prepare": [str(compiler), "--prepare", str(rmd_path)],
                                       "root-prepare": [str(runner), str(root_path)]},
                          "rmd_input_bytes": len(rmd.encode()), "c_input_bytes": len(c.encode()),
                          "source": {"rmd": rmd, "c": c, "root": root_source},
                          "source_sha256": {str(path): sha(path) for path in (rmd_path, c_path, root_path)},
                          "emission": {"command": emit_command, "bytes": generated.stat().st_size,
                                       "sha256": sha(generated), "rename_bytes": response.stat().st_size, **sites},
                          "runtime": {"commands": runtime_commands, "run_commands": [[str(c_binary)], [str(rmd_binary)]],
                                      "stdout": expected.decode(), "stderr": "", "status": 0,
                                      "paths_checked_per_implementation": count + 1,
                                      "drop_count_per_implementation": count * (count + 1) // 2 + count,
                                      "binary_sha256": {str(path): sha(path) for path in (c_binary, rmd_binary)}}})
    for workload in workloads:
        workload["c_inputs"] = {name: c_inputs(command) for name, command in workload["commands"].items()
                                if name.startswith(("gcc", "clang"))}
        for command in workload["commands"].values():
            result = run(command)
            if result.stdout or result.stderr:
                raise AssertionError((command, result.stdout, result.stderr))
    print("Resource measurement inputs and runtime checks passed; starting serial timed samples.", flush=True)
    rng = random.Random(20261001)
    for workload in workloads:
        samples = []
        usage_samples = []
        orders = []
        for repeat in range(args.repeats):
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
        workload["median_ms"] = {name: statistics.median(row[name] for row in samples) / 1e6
                                 for name in workload["commands"]}
        workload["variation"] = {}
        for name in workload["commands"]:
            ordered = sorted(row[name] for row in samples)
            workload["variation"][name] = {
                "wall_p10_ms": ordered[(len(ordered) - 1) // 10] / 1e6,
                "wall_p90_ms": ordered[9 * (len(ordered) - 1) // 10] / 1e6,
                "median_total_cpu_ms": statistics.median(row[name]["user_cpu_ns"] + row[name]["system_cpu_ns"]
                                                          for row in usage_samples) / 1e6,
                "median_peak_rss_kib": statistics.median(row[name]["peak_rss_kib"] for row in usage_samples),
                "max_peak_rss_kib": max(row[name]["peak_rss_kib"] for row in usage_samples)}
        workload["ratios_to_direct_c"] = [paired_stats(samples, "gcc-syntax", name, 20261001)
                                           for name in workload["commands"] if name != "gcc-syntax"]
        fastest = min(("gcc-syntax", "clang-syntax"), key=lambda name: workload["median_ms"][name])
        comparisons = [paired_stats(samples, fastest, name, 20261001)
                       for name in ("resource-check", "resource-prepare", "root-prepare")]
        for comparison in comparisons:
            comparison["ratio_rule_passed"] = comparison["ratio_of_medians"] <= 1 and comparison["bootstrap_95_percent"][1] <= 1
        workload["comparisons_to_fastest_direct_c"] = comparisons
        workload["check_gate"] = {
            "eligible": workload["name"] != "sqlite",
            "outcome": "not established: full SQLite header versus used FFI subset" if workload["name"] == "sqlite"
                       else "pass" if comparisons[0]["ratio_rule_passed"] else "fail",
            "boundary": "resource check includes cleanup and scalar ABI lowering; C syntax stops after semantic checks"}
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
    prepare_commands = [["build/rmd-c", "--library", "--object",
                         *[arg for name in exports for arg in ("--export", name)],
                         "--cflag=-fPIC", "--cflag=-fno-semantic-interposition", "--cflag=-O2", "--cflag=-g",
                         "-o", str(stage_object), *stage_sources],
                        ["gcc", "-shared", "-Wl,-Bsymbolic,-z,text,-z,relro,-z,now", str(stage_object), "-o", str(stage_library)]]
    print("Frontend timing complete; measuring separate native resource-stage preparation.", flush=True)
    prepare_samples = [timed(command) for command in prepare_commands]
    native_preparation = {"commands": prepare_commands, "observations": prepare_samples,
                          "total_wall_ms": sum(item["wall_ns"] for item in prepare_samples) / 1e6,
                          "scope": "one construction of the native resource/reader/C library from RMD source using an installed RMD C compiler; includes target GCC optimization, object assembly, renaming, and shared linking",
                          "statistic": "one observation per command; not a median or confidence interval",
                          "source_bytes": sum(Path(path).stat().st_size for path in stage_sources),
                          "source_sha256": {path: sha(path) for path in stage_sources},
                          "artifacts_sha256": {str(path): sha(path) for path in (stage_object, stage_library)}}
    if any(sha(path) != digest for path, digest in frozen.items()):
        raise SystemExit("Measured sources or tools changed; discard this timing batch.")
    stress = workloads[1:]
    growth = [{"from": earlier["owners"], "to": later["owners"],
               "owner_ratio": later["owners"] / earlier["owners"],
               "emitted_c_byte_ratio": later["emission"]["bytes"] / earlier["emission"]["bytes"],
               "median_time_ratios": {name: later["median_ms"][name] / earlier["median_ms"][name]
                                      for name in later["median_ms"]}}
              for earlier, later in zip(stress, stress[1:])]
    passed = all(item["emission"]["cleanup_call_sites"] == item["owners"] for item in stress) and all(item["emitted_c_byte_ratio"] <= 5 for item in growth)
    model = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                  if line.startswith("model name")), "unknown")
    siblings = Path(f"/sys/devices/system/cpu/cpu{args.cpu}/topology/thread_siblings_list").read_text().strip()
    report = {"schema_version": 1, "method": {"samples_per_endpoint": args.repeats,
              "order": "deterministic shuffled endpoints within paired rounds", "seed": 20261001,
              "cpu": args.cpu, "smt_siblings": siblings,
              "workers": 1,
              "clock": "perf_counter_ns around fresh child launch and completion",
              "cache": "fresh processes; OS file cache warm; no compiler cache",
              "preparation": "installed reader/resource/C stages were built before timing; their native compilation is excluded",
              "target_backend": "all target GCC code generation, assembly, linking, and runtime checks excluded from samples",
              "warmup": "one untimed invocation per endpoint",
              "bootstrap": "10000 resamples of complete paired rounds; ratio-of-medians 95 percent interval",
              "usage": "wait4 child user/system CPU time and peak resident set per invocation",
              "noise": "one logical CPU pinned; no isolation from shared caches, kernel work, or machine-wide load"},
              "platform": {"system": os.uname().sysname, "release": os.uname().release, "machine": os.uname().machine, "cpu": model,
                           "memory_total_kib": int(re.search(r"^MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text(), re.M).group(1))},
              "repository_revision": run(["git", "rev-parse", "HEAD"]).stdout.decode().strip(),
              "repository_state": "uncommitted implementation measured by exact source and binary hashes",
              "versions": {"gcc": run(["gcc", "--version"]).stdout.decode().splitlines()[0],
                           "clang": run(["clang-20", "--version"]).stdout.decode().splitlines()[0],
                           "resource": run([compiler, "--version"]).stdout.decode().strip()},
              "endpoints": ENDPOINTS, "source_and_binary_sha256": frozen,
              "gcc_binary_sha256": sha(shutil.which("gcc")), "clang_binary_sha256": sha(shutil.which("clang-20")),
              "workloads": workloads, "native_stage_preparation": native_preparation,
              "speed_pass_rule": {"source": "docs/language-exploration.md sections 10.3 and 10.4",
                                  "samples": "at least 20 paired fresh processes",
                                  "criterion": "candidate/fastest eligible C median <=1.00 and upper95% confidence bound <=1.00 for each comparable workload and boundary",
                                  "handoff": "complete generated C is measured, but no matching C frontend-only handoff baseline is measured; its formal handoff gate is not established",
                                  "project_stage": "a project that must build this native stage adds the separately recorded preparation cost to its cold critical path"},
              "hypothesis": {"claim": "Shared cleanup emits one token_drop call site per owner; fourfold owner/exit growth emits at most fivefold C bytes.",
                             "passed": passed, "growth": growth,
                             "observed_cleanup_calls_per_owner": [item["emission"]["cleanup_call_sites"] / item["owners"] for item in stress],
                             "observed_mechanism": "early returns target the function epilogue; natural block completion targets a distinct scope continuation, producing two shared linear cleanup chains",
                             "scope": "16/64/256 owners with the same number of early exits; static cleanup sharing and observed timing only"},
              "overall_language_speed_gate": "not established: SQLite reads unequal interfaces, complete C handoff has no matching C handoff baseline here, and the small generated inputs contain substantial process startup cost",
              "interpretation": "SQLite C reads its full public header and system headers; RMD declares only the used FFI. Tiny stress inputs include large fixed process costs. These measurements do not establish a general faster-than-C frontend or runtime result.",
              "complete": True}
    args.output.write_text((json.dumps(report, indent=2) + "\n").replace(str(ROOT), "@REPO@"))
    print("cleanup growth hypothesis:", passed, flush=True)
    print(args.output, flush=True)


if __name__ == "__main__":
    main()
