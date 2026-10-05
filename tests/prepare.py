#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare native test drivers through the source-selected Crust packages."""

import argparse
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "c": "c/package.crs",
    "asm": "asm/package.crs",
    "resource": "resources/package.crs",
    "ownership": "ownership/package.crs",
    "overload": "overload/package.crs",
    "overload-resource": "overload/resources-package.crs",
    "generics": "generics/package.crs",
    "ownership-generics": "generics/ownership/package.crs",
    "union": "union/package.crs",
    "parallel": "parallel/package.crs",
    "highlight": "highlight/package.crs",
    "ccn": "ccn/package.crs",
}
TOOLS = {
    "c": "stages/c/main.crs",
    "resource": "stages/resources/main.crs",
    "overload": "stages/overload/main.crs",
    "overload-resource": "stages/overload/resource_main.crs",
    "highlight": "stages/highlight/main.crs",
    "ccn": "stages/ccn/main.crs",
}


def package_query(build, operation, package):
    return subprocess.check_output(
        [
            build / "crust",
            ROOT / "stages/build/main.crs",
            operation,
            ROOT / "stages" / package,
            build / "stage-cache",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()


def sources(build, package):
    return [Path(path) for path in package_query(build, "sources", package)]


def compile_tool(build, name, cflags, ldflags, seed=False):
    inputs = sources(build, PACKAGES[name]) + [ROOT / TOOLS[name]]
    output = build / (f"crust-{name}-seed" if seed else f"crust-{name}")
    libraries = [build / "libcrust0.a", build / "libcrust0_host.a"]
    if name == "ccn":
        libraries.insert(0, build / "libcrust0_run.a")
        ldflags = [*ldflags, "-ldl", "-lffi"]
    root = ROOT / ("stages/c/bootstrap.crs" if seed else "stages/build/run.crs")
    target_inputs = [item for item in inputs if not seed or item != ROOT / "api/crust0.crs"]
    command = [
        build / "crust",
        root,
        *([] if seed else ["stages/c/tool.crs"]),
        "-o",
        output,
        *target_inputs,
        *[item for flag in cflags for item in ("--cflag", flag)],
        *[item for flag in [*libraries, *ldflags] for item in ("--ldflag", flag)],
    ]
    command = [str(item) for item in command]
    subprocess.run(command, cwd=ROOT, check=True)


def compile_package(build, manifest, output, cflags, ldflags):
    output = Path(output).resolve()
    source, symbols = output.with_suffix(".c"), output.with_suffix(".symbols")
    obj, renamed = output.with_suffix(".input.o"), output.with_suffix(".o")
    commands = [
        [
            build / "crust",
            ROOT / "stages/build/emit.crs",
            Path(manifest).resolve(),
            source,
            symbols,
        ],
        ["gcc", "-std=c99", "-pedantic-errors", *cflags, "-c", source, "-o", obj],
        ["objcopy", f"@{symbols}", obj, renamed],
        ["gcc", renamed, *ldflags, "-o", output],
    ]
    for command in commands:
        subprocess.run(list(map(str, command)), cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build"))
    parser.add_argument("--cflags", default="-O2 -g")
    parser.add_argument("--ldflags", default="")
    parser.add_argument("--sources")
    parser.add_argument("--exports")
    parser.add_argument("--compile-package", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    build = args.build.resolve()
    if args.compile_package:
        if not args.output:
            parser.error("--compile-package requires --output")
        compile_package(
            build,
            args.compile_package,
            args.output,
            shlex.split(args.cflags),
            shlex.split(args.ldflags),
        )
        return
    if args.sources:
        print("\n".join(map(str, sources(build, args.sources))))
        return
    if args.exports:
        print("\n".join(package_query(build, "exports", args.exports)))
        return
    for name, package in PACKAGES.items():
        if name in ("highlight", "ccn"):
            continue
        artifact = Path(package_query(build, "library", package)[0])
        destination = build / f"crust-{name}-library.so"
        if not destination.exists() or destination.read_bytes() != artifact.read_bytes():
            shutil.copyfile(artifact, destination)
    for name in TOOLS:
        compile_tool(build, name, shlex.split(args.cflags), shlex.split(args.ldflags))
    # The seed driver is emitted through interpretation for the generation test.
    compile_tool(build, "c", shlex.split(args.cflags), shlex.split(args.ldflags), seed=True)
    asm_sources = sources(build, PACKAGES["asm"])
    exports = package_query(build, "exports", PACKAGES["asm"])
    subprocess.run(
        [
            build / "crust-c",
            "--library",
            "--object",
            *[item for name in exports for item in ("--export", name)],
            "--cflag=-fPIC",
            *[item for flag in shlex.split(args.cflags) for item in ("--cflag", flag)],
            "-o",
            build / "crust-asm-library.o",
            *asm_sources,
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
