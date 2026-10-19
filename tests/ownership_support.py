#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Native execution and rejection checks for the ownership stage."""

import shlex
from pathlib import Path

from host import WINDOWS, run, sanitizer_compiler, status_matches

ROOT = Path(__file__).resolve().parents[1]


def command(arguments, expected=0, timeout=180):
    result = run(arguments, cwd=ROOT, capture_output=True, timeout=timeout, text_output=True)
    if not status_matches(result.returncode, expected):
        raise RuntimeError(
            f"{shlex.join(map(str, arguments))}: expected {expected}, got {result.returncode}\n{result.stdout.decode()}{result.stderr.decode()}"
        )
    return result


def execute(generated, symbols, directory, name, sanitize, output):
    for optimization in ("-O0", "-O2"):
        binary = directory / f"{name}{optimization}"
        flags = [optimization]
        compiler = sanitizer_compiler() if sanitize else "gcc"
        if sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
            if not WINDOWS:
                flags.append("-no-pie")
            else:
                flags.append("-fno-sanitize=function")
        raw = binary.with_suffix(".input.o")
        renamed = binary.with_suffix(".o")
        command([compiler, "-std=c99", "-pedantic-errors", *flags, "-c", generated, "-o", raw])
        command(["objcopy", f"@{symbols}", raw, renamed])
        command([compiler, *flags, renamed, "-o", binary])
        result = command([binary])
        if result.stdout != output:
            raise RuntimeError(f"{name}: expected {output!r}, got {result.stdout!r}")


def rejected(compiler, directory, cases):
    for name, (source, diagnostic) in cases.items():
        path = directory / f"{name}.crs"
        path.write_text(source)
        result = command([compiler, "--library", "--check", path], expected=1)
        assert diagnostic in result.stderr.decode(), f"{name}: {result.stderr}"


SCALAR_FLOW = (
    "fn clear(flag:mut bool)->unit {flag=false;} "
    "fn branch(flag:mut bool,test:bool)->unit {flag=true;if test {flag=false;}} "
    "fn finish(flag:mut bool)->unit {while flag {flag=false;}} "
    "fn main(argc:i32,argv:**u8)->i32 {var flag:bool=true;branch(mut flag,true);"
    "if flag {trap;}flag=true;while flag {clear(mut flag);}"
    "flag=true;finish(mut flag);if flag {trap;}return 0i32;}"
)
