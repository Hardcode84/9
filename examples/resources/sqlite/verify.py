#!/usr/bin/env python3
"""Compare the resource-stage SQLite application with the frozen C results."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = Path("examples/resources/sqlite")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, default=Path("build/crust-resource"))
    parser.add_argument("--runner", type=Path, default=Path("build/crust"))
    parser.add_argument("--work", type=Path, default=Path(".profile-cache/resources-sqlite"))
    parser.add_argument("--output", type=Path, default=EXAMPLE / "validation.json")
    parser.add_argument("--sanitizers", action="store_true")
    args = parser.parse_args()
    baseline_work = Path(".profile-cache/resources-baseline")
    os.chdir(ROOT)
    args.work.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(Path("benchmarks/resources/baseline.json").read_text())
    for name, digest in baseline["source_sha256"].items():
        if sha(name) != digest:
            raise SystemExit(f"Frozen baseline source changed: {name}")
    report = {"schema_version": 1, "performance_samples": False,
              "baseline": "benchmarks/resources/baseline.json",
              "baseline_sha256": sha("benchmarks/resources/baseline.json"),
              "commands": [], "cases": [], "rejections": []}
    report["gcc"] = subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]

    def command(argv, expected=0, stdout=subprocess.PIPE):
        argv = list(map(str, argv))
        environment = None
        if args.sanitizers:
            environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:detect_stack_use_after_return=1:abort_on_error=1",
                               UBSAN_OPTIONS="halt_on_error=1")
        result = subprocess.run(argv, stdout=stdout, stderr=subprocess.PIPE, timeout=120, env=environment)
        record = {"command": argv, "status": result.returncode,
                  "stdout": (result.stdout or b"").decode(), "stderr": result.stderr.decode()}
        if argv[0] == "nm":
            record["stdout"] = ""
            record["stdout_sha256"] = hashlib.sha256(result.stdout).hexdigest()
            record["symbol_lines"] = len(result.stdout.splitlines())
        report["commands"].append(record)
        if result.returncode != expected:
            raise AssertionError(record)
        return result

    library = EXAMPLE / "library.crs"
    program = EXAMPLE / "program.crs"
    sqlite = baseline_work / "sqlite3.o"
    if not sqlite.is_file():
        raise SystemExit("Run benchmarks/resources/verify.py before this check.")
    compiler_target = args.work / "sqlite-resource-cli"
    root_target = Path("build/sqlite-resource")
    command([args.compiler, "--check", library, program])
    command([args.compiler, "--cflag=-O2", "-o", compiler_target, library, program,
             "--ldflag", sqlite, "--ldflag=-ldl", "--ldflag=-lm", "--ldflag=-pthread"])
    command([args.runner, EXAMPLE / "main.crs"])
    command([args.runner, EXAMPLE / "main.crs", "--check"])
    executables = [compiler_target, root_target]
    if args.sanitizers:
        sanitized = args.work / "sqlite-resource-sanitize"
        command([args.compiler, "--cflag=-O1", "--cflag=-g", "--cflag=-fsanitize=address,undefined",
                 "--cflag=-fno-omit-frame-pointer", "-o", sanitized, library, program,
                 "--ldflag", sqlite, "--ldflag=-ldl", "--ldflag=-lm", "--ldflag=-pthread",
                 "--ldflag=-fsanitize=address,undefined"])
        executables.append(sanitized)
        report["sanitizers"] = {"instrumented": "resource target generated C",
                                 "sqlite_object_instrumented": False,
                                 "ASAN_OPTIONS": "detect_leaks=0:detect_stack_use_after_return=1:abort_on_error=1",
                                 "UBSAN_OPTIONS": "halt_on_error=1",
                                 "leak_check_reason": "LeakSanitizer fails under the execution environment's ptrace monitor."}
    fixtures = {
        "values": [baseline_work / "normal.db"],
        "empty-table": [baseline_work / "empty.db"],
        "open-failure": [baseline_work / "missing-parent/input.db"],
        "prepare-failure": [baseline_work / "missing-table.db"],
        "step-and-finalize-failure": [baseline_work / "step-failure.db"],
        "usage": [],
        "output-failure": [baseline_work / "normal.db"],
    }
    for case in baseline["cases"]:
        name = case["name"]
        for executable in executables:
            if name == "output-failure":
                with open("/dev/full", "wb") as output:
                    result = command([executable, *fixtures[name]], case["status"], output)
            else:
                result = command([executable, *fixtures[name]], case["status"])
                assert result.stdout == case["stdout"].encode(), (name, executable, result.stdout)
            assert result.stderr == case["stderr"].encode(), (name, executable, result.stderr)
        report["cases"].append({"name": name, "status": case["status"],
                                "implementations": list(map(str, executables))})
    negatives = {
        "copy-borrowed-bytes": ("fn bad(value:read Bytes)->Bytes { return value; }", "copy of a resource"),
        "move-borrowed-bytes": ("fn bad(value:read Bytes)->Bytes { return move value; }", "whole local owner"),
        "store-loan": ("record Bad { value:read Bytes; }", "borrowed views cannot be record fields"),
        "step-borrowed-statement": ("fn bad(value:mut Statement)->i32 { var loan:read Statement=read value; return statement_step(mut value); }", "active borrow"),
        "close-borrowed-database": ("fn bad(value:mut Db)->i32 { var loan:read Db=read value; return db_close(mut value); }", "active borrow"),
        "callback-mode": ("fn wrong(value:mut Bytes, context:mut QueryContext)->i32 { return 0i32; } fn bad(value:mut Statement, context:mut QueryContext)->i32 { return with_blob(mut value,0i32,mut context,wrong); }", "incompatible type or borrow mode"),
    }
    for name, (text, diagnostic) in negatives.items():
        path = args.work / (name + ".crs")
        path.write_text(text + "\n")
        result = command([args.compiler, "--library", "--check", library, path], expected=1)
        assert diagnostic.encode() in result.stderr, (name, result.stderr)
        report["rejections"].append({"name": name, "diagnostic": result.stderr.decode(),
                                     "source": text, "source_sha256": sha(path)})
    format_source = args.work / "format.crs"
    format_source.write_text('''fn main(argc:i32,argv:**u8)->i32 {
    if write_number(1i32,0u64)!=0i32 {return 1i32;}
    unsafe {if write_bytes(1i32," ",1usize)!=0i32 {return 1i32;}}
    if write_number(1i32,9u64)!=0i32 {return 1i32;}
    unsafe {if write_bytes(1i32," ",1usize)!=0i32 {return 1i32;}}
    if write_number(1i32,10u64)!=0i32 {return 1i32;}
    unsafe {if write_bytes(1i32," ",1usize)!=0i32 {return 1i32;}}
    if write_number(1i32,18446744073709551615u64)!=0i32 {return 1i32;}
    unsafe {return write_bytes(1i32,"\\n",1usize);}
}
''')
    format_c = args.work / "format.c"
    format_c.write_text('''#define main baseline_main
#include "callbacks.c"
#undef main
int main(void) {
    if (write_number(1,0) || write_bytes(1,(const unsigned char *)" ",1) ||
        write_number(1,9) || write_bytes(1,(const unsigned char *)" ",1) ||
        write_number(1,10) || write_bytes(1,(const unsigned char *)" ",1) ||
        write_number(1,UINT64_MAX) || write_bytes(1,(const unsigned char *)"\\n",1)) return 1;
    return 0;
}
''')
    format_c_binary = args.work / "format-c"
    command(["gcc", "-std=c99", "-pedantic-errors", "-O2", "-g0",
             "-Ibenchmarks/resources", "-I.profile-cache/sources", format_c, sqlite,
             "-ldl", "-lm", "-pthread", "-o", format_c_binary])
    format_binary = args.work / "format-resource"
    command([args.compiler, "--cflag=-O2", "-o", format_binary, library, format_source,
             "--ldflag", sqlite, "--ldflag=-ldl", "--ldflag=-lm", "--ldflag=-pthread"])
    format_binaries = [format_c_binary, format_binary]
    if args.sanitizers:
        format_sanitized = args.work / "format-resource-sanitize"
        command([args.compiler, "--cflag=-O1", "--cflag=-g", "--cflag=-fsanitize=address,undefined",
                 "--cflag=-fno-omit-frame-pointer", "-o", format_sanitized, library, format_source,
                 "--ldflag", sqlite, "--ldflag=-ldl", "--ldflag=-lm", "--ldflag=-pthread",
                 "--ldflag=-fsanitize=address,undefined"])
        format_binaries.append(format_sanitized)
    for executable in format_binaries:
        result = command([executable])
        assert result.stdout == b"0 9 10 18446744073709551615\n" and result.stderr == b"", result
    report["format_checks"] = len(format_binaries)
    forbidden = {"resource_program", "resource_build", "rs_prepare", "crust_context_init", "crust_read", "crust_run_main"}
    for executable in executables:
        symbols = command(["nm", "-g", executable]).stdout.decode().splitlines()
        found = {line.split()[-1] for line in symbols if line.split()} & forbidden
        assert not found, (executable, sorted(found))
    declaration_names = re.findall(r"^(?:(?:unsafe |extern )?fn|record|resource|const)\s+([A-Za-z_]\w*)", library.read_text(), re.M)
    native_name = "_crust0_u1_d" + str(declaration_names.index("write_number") + 1)
    disassembly = command(["objdump", "-d", "--disassemble=" + native_name, compiler_target]).stdout
    assert ("<" + native_name + ">:").encode() in disassembly, "write_number native identity was not found"
    assembly = args.work / "write-number.asm"
    assembly.write_bytes(disassembly)
    report["application_process_checks"] = len(executables) * len(baseline["cases"])
    report["compile_rejection_checks"] = len(negatives)
    report["target_compiler_symbols_absent"] = sorted(forbidden)
    report["initialization"] = {"number_buffer_bytes": 20,
                                 "resource_source": "raw pointer writes initialize only the emitted decimal suffix",
                                 "c_baseline_source": "only the emitted decimal suffix is initialized",
                                 "storage_contract": "u64 needs one to twenty decimal digits; each byte in the output suffix is written before the synchronous write call",
                                 "disassembly": str(assembly), "disassembly_sha256": sha(assembly),
                                 "native_symbol": native_name,
                                 "observed_instructions": [line.strip() for line in disassembly.decode().splitlines()
                                                           if any(op in line for op in ("pxor", "movaps", "movl   $0x0"))]}
    paths = [*sorted(EXAMPLE.glob("*.crs")), EXAMPLE / "verify.py",
             *sorted(Path("stages/resources").glob("*.crs")),
             *sorted(Path("stages/reader").glob("*.crs")),
             *sorted(Path("stages/c").glob("*.crs"))]
    report["source_sha256"] = {str(path): sha(path) for path in paths}
    report["binary_sha256"] = {str(path): sha(path) for path in
                               [args.compiler, args.runner, Path("build/crust-resource-library.so"),
                                sqlite, *executables, *format_binaries]}
    report["complete"] = True
    encoded = json.dumps(report, indent=2) + "\n"
    args.output.write_text(encoded.replace(str(ROOT), "@REPO@"))
    print(f"SQLite resource application: {report['application_process_checks']} process checks passed")
    print(f"SQLite ownership boundary: {report['compile_rejection_checks']} rejection checks passed")
    print(f"Decimal storage boundary: {report['format_checks']} process checks passed")
    print(args.output)


if __name__ == "__main__":
    main()
