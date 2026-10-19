# SPDX-License-Identifier: Apache-2.0
"""Compare source-built C compiler generations and execute their final output."""

import re

from host import ROOT, WINDOWS, executable
from prepare import sources


def check_generations(command, build, compiler, cc, c_options, ldflags):
    work = build / "c-generations"
    work.mkdir(exist_ok=True)
    inputs = [*sources(build, "c/package.crs"), ROOT / "stages/c/main.crs"]
    libraries = [build / "libcrust0.a", build / "libcrust0_host.a", *ldflags]
    if WINDOWS:
        libraries.append("-lbcrypt")
    allowed = {
        "crust_context_init",
        "crust_context_destroy",
        "crust_read",
        "crust_read_range",
        "crust_collect",
        "crust_resolve",
        "crust_check",
        "crust_try_alloc",
        "crust_try_copy_string",
        "crust_set_error",
    }
    artifacts = []
    compilers = [] if WINDOWS else [build / "crust-c-seed"]
    compilers.append(compiler)
    for generation in range(3):
        current = compilers[generation]
        generated, response = work / f"stage-{generation}.c", work / f"stage-{generation}.rsp"
        command([current, "--emit", "-o", generated, "--symbols", response, *inputs])
        artifacts.append((generated.read_bytes(), response.read_bytes()))
        names = command(["nm", executable(current)]).stdout
        assert not re.search(rb"\bcrust_x64_", names), "C stage depends on the ASM backend"
        if len(compilers) > generation + 1:
            continue
        obj = work / f"stage-{generation}.o"
        command([current, "--object", "-o", obj, *c_options, *inputs])
        references = command(["nm", "-u", obj]).stdout.decode()
        for name in re.findall(r"\bU\s+(\S+)", references):
            assert not name.startswith("crust_") or name in allowed, name
        if generation < 2:
            successor = work / f"compiler-{generation + 1}"
            entry = []
            if WINDOWS:
                command(["objcopy", "--redefine-sym", "main=crust_run_main", obj])
                entry = ["-municode", build / "run_entry_windows.o", build / "windows_io.o"]
            command([*cc, obj, *entry, *libraries, "-o", successor])
            compilers.append(successor)
    assert artifacts[0] == artifacts[1] == artifacts[2], "C compiler generations differ"
    obj, program = work / "intrusive.o", work / "intrusive"
    command([current, "--object", "-o", obj, *c_options, ROOT / "examples/intrusive/raw.crs"])
    command(
        [
            *cc,
            obj,
            build / "libcrust0_host.a",
            *ldflags,
            *(["-lbcrypt"] if WINDOWS else []),
            "-o",
            program,
        ]
    )
    assert command([program]).stdout == b"intrusive: ok\n"
    print("C bootstrap: three equal generations, backend-free tools, intrusive output passed")
