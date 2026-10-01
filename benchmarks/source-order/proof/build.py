#!/usr/bin/env python3
"""Build and check the bounded reader-transfer proof without running timings."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", default="build")
    parser.add_argument("--workdir", default=".profile-cache/source-order-proof-replay")
    parser.add_argument("--cpu", type=int, default=6)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    source = Path(__file__).resolve().parent
    work = (root / args.workdir).resolve()
    build = (root / args.build_dir).resolve()
    os.chdir(root)
    if args.cpu not in os.sched_getaffinity(0):
        raise SystemExit("selected CPU is not allowed")
    os.sched_setaffinity(0, {args.cpu})
    for name in ("rmd-c", "rmd-c-library.so", "core.o", "read.o", "check.o", "host.o", "librmd0_host.a"):
        if not (build / name).is_file():
            raise SystemExit("missing input " + str(build / name) + "; run make all c-stage first")
    work.mkdir(parents=True, exist_ok=True)
    (work / "san").mkdir(exist_ok=True)
    for name in ("runner.c", "proof.h", "model.rmd", "interface.rmd", "plugin.rmd", "verify.py", "measure.py"):
        shutil.copyfile(source / name, work / name)
    env = os.environ.copy()
    env["RMD_PROOF_DIR"] = str(work)
    env["RMD_PROOF_CPU"] = str(args.cpu)
    env["RMD_PROOF_BUILD"] = str(build)
    commands = []

    def run(command, output=None):
        command = [str(item) for item in command]
        start = time.monotonic_ns()
        result = subprocess.run(command, env=env, capture_output=True)
        commands.append({"command": command, "wall_ns": time.monotonic_ns() - start,
                         "status": result.returncode, "stderr": result.stderr.decode()})
        (work / "replay-build.json").write_text(json.dumps({"cpu": args.cpu, "commands": commands}, indent=2) + "\n")
        if result.returncode or result.stderr:
            raise RuntimeError((command, result.returncode, result.stderr.decode()))
        if output is not None:
            output.write_bytes(result.stdout)
        return result.stdout

    strict = ["-std=c99", "-pedantic-errors", "-Wall", "-Wextra", "-Werror",
              "-Wstrict-prototypes", "-Wmissing-prototypes", "-Wshadow", "-Wvla"]
    interfaces = [root / item for item in ("api/rmd0.rmd", "api/rmd0_host.rmd", "api/rmd0_stage.rmd", "stages/c/api.rmd")]
    exports = []
    for name in ("set_backend", "set_reader", "alternate", "include_input", "queue_emit", "reject_reader"):
        exports += ["--export", name]
    run([build / "rmd-c", "--library", "--emit-c", "--symbols", work / "plugin.rsp", *exports,
         *interfaces, work / "model.rmd", work / "plugin.rmd"], work / "plugin.c")
    backend_sources = [root / item for item in (
        "api/rmd0.rmd", "api/rmd0_host.rmd", "api/rmd0_stage.rmd", "stages/c/model.rmd",
        "stages/c/base.rmd", "stages/c/types.rmd", "stages/c/emit.rmd", "stages/c/driver.rmd", "stages/c/program.rmd")]
    run([build / "rmd-c", "--library", "--emit-c", "--symbols", work / "backend.rsp",
         "--export", "c_backend_build", "--export", "c_program", *backend_sources], work / "backend.c")

    def library(name, destination, flags, directory):
        run(["gcc", *flags, "-std=c99", "-pedantic-errors", "-Wno-overlength-strings", "-fPIC",
             "-c", work / (name + ".c"), "-o", directory / (name + "-raw.o")])
        run(["objcopy", "@" + str(work / (name + ".rsp")), directory / (name + "-raw.o"), directory / (name + ".o")])
        run(["gcc", "-shared", *flags, "-Wl,-Bsymbolic,-z,text,-z,relro,-z,now",
             directory / (name + ".o"), "-o", directory / destination])

    library("plugin", "reader.plugin", ["-O2", "-g0", "-fstack-clash-protection"], work)
    shutil.copyfile(build / "rmd-c-library.so", work / "output.plugin")
    run(["gcc", "-O2", "-g0", *strict, "-Iinclude", work / "runner.c",
         *[build / item for item in ("core.o", "read.o", "check.o", "host.o")],
         "-rdynamic", "-ldl", "-lffi", "-o", work / "runner"])
    sanitized = ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    run(["gcc", *sanitized, *strict, "-Iinclude", work / "runner.c", "src/core.c", "src/read.c",
         "src/check.c", "runtime/host.c", "-rdynamic", "-ldl", "-lffi", "-no-pie", "-o", work / "san/runner"])
    library("plugin", "reader.plugin", sanitized, work / "san")
    library("backend", "output.plugin", sanitized, work / "san")
    run([build / "rmd-c", "--emit-c", "--symbols", work / "reference.rsp", "examples/intrusive.rmd"], work / "reference.c")
    prefix = b"set_backend(session, c_backend_build);\nset_reader(session, alternate);"
    (work / "main.rmd").write_bytes(prefix + b"\0@include |" + str(root / "examples/intrusive.rmd").encode() + b"|\n@emit\n")
    command = [work / "runner", work / "main.rmd"]
    for path in (root / "api/rmd0.rmd", root / "api/rmd0_stage.rmd", root / "stages/c/api.rmd", work / "model.rmd", work / "interface.rmd"):
        command += ["--api", path]
    command += ["--load", work / "reader.plugin", "--load", work / "output.plugin", "--", work / "output.rsp"]
    run(command, work / "output.c")
    run(["gcc", "-std=c99", "-pedantic-errors", "-O2", "-g0", "-fstack-clash-protection", "-Wno-overlength-strings",
         "-c", work / "output.c", "-o", work / "target-raw.o"])
    run(["objcopy", "@" + str(work / "output.rsp"), work / "target-raw.o", work / "target.o"])
    run(["gcc", "-no-pie", work / "target.o", build / "librmd0_host.a", "-o", work / "target"])
    if run([work / "target"]) != b"intrusive: ok\n":
        raise RuntimeError("incorrect target output")
    print(run(["python3", work / "verify.py"]).decode(), end="")
    print("Timing was not run. Use measure.py with the same RMD_PROOF_DIR and RMD_PROOF_BUILD.")


if __name__ == "__main__":
    main()
