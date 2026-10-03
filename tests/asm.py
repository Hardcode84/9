#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build three assembly stage generations without a seed backend."""

import argparse
import re
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    build = args.build.resolve()
    work = build / "asm-generations"
    work.mkdir(exist_ok=True)
    cc = shlex.split(args.cc)
    ldflags = shlex.split(args.ldflags)

    def run(command):
        result = subprocess.run(list(map(str, command)), cwd=ROOT, capture_output=True, timeout=60)
        assert result.returncode == 0, (command, result)
        return result.stdout

    for artifact in ("crust", "libcrust0.a"):
        names = run(["nm", "-g", build / artifact])
        assert not re.search(rb"\bcrust_x64_", names), artifact
    sources = [ROOT / "api/crust0.crs"] + [
        ROOT / "stages/asm" / (part + ".crs")
        for part in ("model", "output", "plan", "emit", "program")
    ]
    exports = re.findall(r"\b(crust_x64_\w+)\s*\(", (ROOT / "include/crust0_x64.h").read_text())
    exports.append("crust_x64_default_ops")
    options = [item for name in exports for item in ("--export", name)]
    compiler = build / "crust0"
    outputs = []
    for generation in range(1, 4):
        assembly = work / f"backend-{generation}.s"
        obj = assembly.with_suffix(".o")
        output = work / f"crust0-{generation}"
        run([compiler, "--library", *options, "-S", "-o", assembly, *sources])
        outputs.append(assembly.read_bytes())
        run(["as", "--64", assembly, "-o", obj])
        run(
            [
                *cc,
                "-no-pie",
                obj,
                build / "driver.o",
                build / "driver_posix.o",
                build / "libcrust0.a",
                build / "libcrust0_host.a",
                *ldflags,
                "-o",
                output,
            ]
        )
        compiler = output
    assert outputs[0] == outputs[1] == outputs[2], "assembly generations differ"
    assembly = work / "intrusive.s"
    obj = assembly.with_suffix(".o")
    output = work / "intrusive"
    run([compiler, "-o", assembly, ROOT / "examples/intrusive/raw.crs"])
    run(["as", "--64", assembly, "-o", obj])
    run([*cc, "-no-pie", obj, build / "libcrust0_host.a", *ldflags, "-o", output])
    assert run([output]) == b"intrusive: ok\n"
    print("assembly bootstrap: backend-free seed, three equal generations, intrusive output passed")


if __name__ == "__main__":
    main()
