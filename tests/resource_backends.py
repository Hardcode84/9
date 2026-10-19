#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run lowered cleanup with ordinary backends after the frontend stage leaves scope."""

import argparse
import signal
from pathlib import Path

from host import disable_core_dumps, exit_status
from host import run as host_run
from resources import ROOT, runtime_cases


def run(command, expected=0, output=None):
    result = host_run(command, cwd=ROOT, capture_output=True, timeout=120, text_output=True)
    if result.returncode != exit_status(expected) or result.stderr:
        raise RuntimeError(f"{command}\n{result.returncode}\n{result.stdout!r}\n{result.stderr!r}")
    if output is not None and result.stdout != output:
        raise RuntimeError(f"{command}: expected {output!r}, got {result.stdout!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    args = parser.parse_args()
    build = args.build.resolve()
    work = build / "resource-backends-cases"
    work.mkdir(exist_ok=True)
    driver = build / "resource-backends"
    disable_core_dumps()
    cases = runtime_cases()
    for name, text, expected in cases:
        source, assembly, binary = (work / (name + suffix) for suffix in (".crs", ".s", ".exe"))
        source.write_text(text)
        run([driver, "asm", "resources", "-o", assembly, source])
        run(["gcc", "-no-pie", assembly, "-o", binary])
        run(
            [binary],
            -signal.SIGILL if expected is None else 0,
            b"" if expected is None else expected,
        )
    for backend in ("c", "asm"):
        output = work / ("intrusive." + ("s" if backend == "asm" else "exe"))
        run(
            [
                driver,
                backend,
                "ownership",
                "trusted",
                "examples/intrusive/links.crs",
                "-o",
                output,
                "examples/intrusive/program.crs",
            ]
        )
        if backend == "asm":
            binary = work / "intrusive-asm.exe"
            run(["gcc", "-no-pie", output, "-o", binary])
            output = binary
        run([output], output=b"OK\n")
    source = work / "evaluate.crs"
    source.write_text(
        """
resource Token { count: *i32; } drop dispose;
fn dispose(value: mut Token)->unit { unsafe { *value.count = *value.count + 1i32; } }
fn add(count: *i32, value: i32)->unit { unsafe { *count = *count + value; } }
fn early(count: *i32)->i32 { unsafe {
    var token: Token = make Token { count: count };
    defer add(count, 10i32);
    return *count;
} }
fn main(argc: i32, argv: **u8)->i32 { unsafe {
    var count: i32 = 0i32;
    if early(&count) != 0i32 || count != 11i32 { return 1i32; }
    var index: i32 = 0i32;
    while index < 3i32 {
        var token: Token = make Token { count: &count };
        defer add(&count, 10i32);
        index = index + 1i32;
        if index == 1i32 { continue; }
        break;
    }
    if count != 33i32 { return 2i32; }
    return 0i32;
} }
"""
    )
    run([driver, "eval", "resources", source], output=b"")
    print(
        f"Resource backends: {len(cases)} ASM cases, C/ASM checked intrusive list, seed evaluation passed"
    )


if __name__ == "__main__":
    main()
