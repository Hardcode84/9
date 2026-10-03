#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the intrusive program with exact-address reuse and allocation failures."""

import os
import subprocess

from memory import command


def check_runtime(build, directory, root, sanitize, source_path=None, outputs=None):
    if source_path is None:
        source_path = root / "examples/intrusive/program.crs"
    if outputs is None:
        outputs = (b"OK\n", b"", b"", b"")
    source = directory / "allocator-program.crs"
    source.write_text(
        source_path.read_text()
        .replace('= "malloc";', '= "ownership_test_allocate";')
        .replace('= "free";', '= "ownership_test_release";')
    )
    generated = directory / "allocator-program.c"
    symbols = directory / "allocator-program.rsp"
    command(
        [
            build / "crust-ownership-test",
            "--emit-c",
            "--symbols",
            symbols,
            "-o",
            generated,
            root / "examples/intrusive/links.crs",
            source,
        ]
    )
    for optimization in ("-O0", "-O2"):
        flags = ["-std=c99", "-pedantic-errors", optimization]
        if sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-no-pie"]
        original = directory / "allocator-input.o"
        renamed = directory / "allocator.o"
        executable = directory / f"allocator{optimization}"
        command(["gcc", *flags, "-c", generated, "-o", original])
        command(["objcopy", f"@{symbols}", original, renamed])
        command(["gcc", *flags, renamed, root / "tests/ownership_runtime.c", "-o", executable])
        for failure, output in enumerate(outputs):
            environment = dict(os.environ, CRUST_TEST_ALLOCATION_FAILURE=str(failure))
            result = subprocess.run([executable], env=environment, capture_output=True, timeout=15)
            expected = 1 if failure else 0
            if result.returncode != expected or result.stdout != output or result.stderr:
                raise RuntimeError(
                    f"allocation {failure}: {result.returncode}, {result.stdout!r}, {result.stderr!r}"
                )
