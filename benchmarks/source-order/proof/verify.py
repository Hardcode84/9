#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path.cwd()
HERE = Path(os.environ.get("RMD_PROOF_DIR", ROOT / ".profile-cache/source-order-proof-replay"))
APIS = [ROOT / p for p in ("api/rmd0.rmd", "api/rmd0_stage.rmd", "stages/c/api.rmd")]
APIS += [HERE / "model.rmd", HERE / "interface.rmd"]
TARGET = ROOT / "examples/intrusive.rmd"
PREFIX = b"set_backend(session, c_backend_build);\nset_reader(session, alternate);"
source = PREFIX + b"\0@include |" + str(TARGET).encode() + b"|\n@emit\n"
ENV = os.environ.copy()
ENV["ASAN_OPTIONS"] = "detect_stack_use_after_return=1:detect_leaks=0:abort_on_error=1"
ENV["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
observations = []


def command(root, directory, response, report):
    result = ["taskset", "-c", os.environ.get("RMD_PROOF_CPU", "6"), str(directory / "runner"), str(root)]
    for path in APIS:
        result += ["--api", str(path)]
    result += ["--load", str(directory / "reader.plugin"), "--load", str(directory / "output.plugin")]
    if report:
        result += ["--report", str(report)]
    return result + ["--", str(response)]


def run(name, contents, directory, status=0, diagnostic=None, emits=None, selections=None, reads=None):
    variant = "san" if directory.name == "san" else "native"
    root = HERE / f"{variant}-{name}.rmd"
    root.write_bytes(contents)
    response = HERE / f"{variant}-{name}.rsp"
    report = HERE / f"{variant}-{name}.json"
    response.unlink(missing_ok=True)
    report.unlink(missing_ok=True)
    cmd = command(root, directory, response, report)
    process = subprocess.run(cmd, env=ENV, capture_output=True, timeout=30)
    if process.returncode != status:
        raise AssertionError((name, variant, process.returncode, process.stderr.decode()))
    if diagnostic is None:
        assert not process.stderr, process.stderr
    else:
        assert diagnostic in process.stderr, process.stderr
    counters = json.loads(report.read_text())
    for field, value in (("emits", emits), ("selections", selections), ("reads", reads)):
        if value is not None:
            assert counters[field] == value, (name, counters)
    assert counters["allocations"] == counters["releases"], counters
    if status:
        assert not process.stdout, (name, "output after failure")
        assert not response.exists(), (name, "symbol output after failure")
    observations.append({"name": name, "variant": variant, "command": cmd,
                         "status": status, "counters": counters,
                         "diagnostic": process.stderr.decode(), "stdout_bytes": len(process.stdout)})
    return process, counters


for directory in (HERE, HERE / "san"):
    process, counters = run("success", source, directory, emits=1, selections=1, reads=3)
    assert counters["switch_offset"] == len(PREFIX)
    assert counters["cursor"] == counters["size"] == len(source)
    assert counters["root_done"] and counters["allocations"] > 0
    assert process.stdout == (HERE / "reference.c").read_bytes()
    assert (HERE / ("san-success.rsp" if directory.name == "san" else "native-success.rsp")).read_bytes() == (HERE / "reference.rsp").read_bytes()
    control = b'set_backend(session, c_backend_build);\ninclude_input(session, "' + str(TARGET).encode() + b'");\nqueue_emit(session);\n'
    process, _ = run("no-reader-change", control, directory, emits=1, selections=0, reads=0)
    assert process.stdout == (HERE / "reference.c").read_bytes()
    run("selection-failure", source.replace(b"set_reader(", b"reject_reader(", 1), directory,
        status=1, diagnostic=b"reader selection rejected", emits=0, selections=1, reads=0)
    bad = source.replace(b"@include", b"?include", 1)
    process, _ = run("bad-custom", bad, directory, status=1,
                     diagnostic=b"unknown alternate root form", emits=0, selections=1, reads=1)
    offset = bad.index(b"?include")
    line = bad[:offset].count(b"\n") + 1
    column = offset - bad.rfind(b"\n", 0, offset)
    assert f":{line}:{column}: unknown alternate root form".encode() in process.stderr
    run("bad-tail-after-queue", source + b"?", directory, status=1,
        diagnostic=b"unknown alternate root form", emits=0, selections=1, reads=3)
    run("wrong-reader-type", source.replace(b"set_reader(session, alternate)", b"set_reader(session, c_backend_build)"),
        directory, status=1, diagnostic=b"type mismatch", emits=0, selections=0, reads=0)
    run("unknown-root", b"missing_root(session);", directory, status=1,
        diagnostic=b"unknown root binding", emits=0, selections=0, reads=0)
    run("unsupported-argument", b"set_reader(session, 1i32);", directory, status=1,
        diagnostic=b"proof expected a name", emits=0, selections=0, reads=0)
    run("old-reader-hostile", source.replace(b"set_reader(session, alternate);", b""), directory,
        status=1, diagnostic=b"proof expected a name", emits=0, selections=0, reads=0)
    bad_target = HERE / "target-host-name.rmd"
    bad_target.write_text("fn main(argc:i32,argv:**u8)->i32 { return set_reader(); }\n")
    process, _ = run("host-name-not-target", source.replace(str(TARGET).encode(), str(bad_target).encode()), directory,
                     status=1, diagnostic=b"unknown name 'set_reader'", emits=0, selections=1, reads=3)
    column = bad_target.read_text().index("set_reader") + 1
    assert str(bad_target).encode() + f":1:{column}:".encode() in process.stderr, process.stderr
    forward = HERE / "forward-target.rmd"
    forward.write_text("fn main(argc:i32,argv:**u8)->i32 { return later(); }\nfn later()->i32 { return 0i32; }\n")
    process, _ = run("target-forward-reference", source.replace(str(TARGET).encode(), str(forward).encode()), directory,
                     emits=1, selections=1, reads=3)
    assert b"int main(" in process.stdout

target_run = subprocess.run([str(HERE / "target")], check=True, capture_output=True)
assert target_run.stdout == b"intrusive: ok\n" and not target_run.stderr
symbols = subprocess.run(["nm", str(HERE / "target")], check=True, capture_output=True).stdout
assert not re.search(rb"\b(?:rmd_(?:context|read|collect|resolve|check|x64)\w*|c_program|c_backend_build|ffi_\w*|set_backend|set_reader|alternate|include_input|queue_emit)\b", symbols)
dynamic = subprocess.run(["readelf", "-dW", str(HERE / "target")], check=True, capture_output=True).stdout
assert not re.search(rb"reader\.plugin|output\.plugin|libffi", dynamic)
result = {"status": "passed", "checks": len(observations), "observations": observations,
          "target_stdout": "intrusive: ok\n", "host_symbols_in_target": [],
          "source_cursor_at_switch": len(PREFIX), "sanitizers": ["address", "undefined"],
          "asan_options": ENV["ASAN_OPTIONS"], "ubsan_options": ENV["UBSAN_OPTIONS"],
          "leak_detector": "Not run: detect_leaks=0. Historical sandbox ptrace failure and minimal probe are archived in benchmarks/source-order/reader-proof.json. Explicit target allocation/release counts are checked."}
(HERE / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
print(f"Passed {len(observations)} native/sanitized source-order checks; executable and symbol isolation passed")
