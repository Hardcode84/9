# SPDX-License-Identifier: Apache-2.0
"""Build and execute the shared C core contracts on native Windows."""

import argparse
import shlex
import sys
from pathlib import Path

from c_generations import check_generations
from host import ROOT, run
from run import checked_command
from windows import STRICT
from windows_compile import WindowsCompiler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build/windows")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    build = args.build.resolve()
    compiler = WindowsCompiler(build, shlex.split(args.cc))
    assembly = compiler.emit_object(
        ROOT / "stages/asm/package.crs", build / "shared-asm", ["-O2", "-g1"]
    )
    compiler.run(["ar", "rcs", build / "libcrust_asm.a", assembly])
    libraries = [assembly, build / "libcrust0.a", build / "libcrust0_host.a", "-lbcrypt"]
    for name in ("core", "read", "check", "x64", "host", "eval", "parallel"):
        output = build / f"{name}_test.exe"
        sources = [ROOT / f"tests/{name}_test.c"]
        flags = ["-pthread"] if name == "parallel" else []
        if name == "eval":
            sources += [
                ROOT / "tests/eval_lookup_windows.c",
                ROOT / "tests/native.c",
                build / "eval.o",
                build / "eval_ffi.o",
            ]
            flags += ["-Wl,--export-all-symbols", "-lffi"]
        compiler.run(
            [
                *compiler.cc,
                *STRICT,
                "-O2",
                "-g1",
                "-I" + str(build / "profile/include"),
                "-I" + str(ROOT / "include"),
                *sources,
                *libraries,
                *flags,
                *shlex.split(args.ldflags),
                "-o",
                output,
            ]
        )
        if name == "eval":
            run([sys.executable, ROOT / "tests/eval.py", "--build", build], check=True)
        else:
            operands = [build / "host-test.tmp", build] if name == "host" else []
            if name == "x64":
                operands = ["coff"]
            result = compiler.run([output, *operands])
            print(result.stdout.decode(), end="", flush=True)
    for platform in ("driver", "driver_windows"):
        compiler.run(
            [
                *compiler.cc,
                *STRICT,
                "-O2",
                "-g1",
                "-I" + str(build / "profile/include"),
                "-I" + str(ROOT / "include"),
                "-c",
                ROOT / f"src/{platform}.c",
                "-o",
                build / f"{platform}.o",
            ]
        )
    compiler.run(
        [
            *compiler.cc,
            *STRICT,
            "-O2",
            "-g1",
            "-I" + str(build / "profile/include"),
            "-I" + str(ROOT / "include"),
            ROOT / "src/driver.c",
            ROOT / "src/driver_windows.c",
            *libraries,
            *shlex.split(args.ldflags),
            "-o",
            build / "crust0.exe",
        ]
    )
    for backend, tool in (("x64", "crust0.exe"), ("c", "crust-c.exe")):
        run(
            [
                sys.executable,
                ROOT / "tests/run.py",
                "--group",
                "semantic",
                "--backend",
                backend,
                "--compiler",
                build / tool,
                "--cc",
                args.cc,
            ],
            check=True,
        )

    check_generations(
        checked_command, build, build / "crust-c.exe", compiler.cc, [], shlex.split(args.ldflags)
    )


if __name__ == "__main__":
    main()
