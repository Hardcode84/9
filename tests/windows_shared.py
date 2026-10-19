#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build native Windows drivers and run the shared regression suites."""

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from host import ROOT, run
from prepare import compile_tool, package_query
from windows_compile import WindowsCompiler


def prepare(build, ldflags, suite="all"):
    ownership = suite in ("all", "ownership")
    work = build / "shared-tests"
    work.mkdir(exist_ok=True)
    host = WindowsCompiler(build, ["gcc"])
    libraries = [build / "libcrust0.a", build / "libcrust0_host.a", *ldflags]
    tools = ["c"]
    if ownership:
        tools += ["resource", "overload", "overload-resource"]
    if suite in ("all", "tooling"):
        tools += ["highlight", "ccn"]
    for tool in tools:
        compile_tool(build, tool, ["-O2", "-g1"], ldflags)
    drivers = {
        "crust-ownership-test": (
            ["ownership"],
            ["tests/ownership_input", "tests/ownership_driver"],
        ),
        "crust-ownership-erasure": (
            ["ownership"],
            ["tests/ownership_input", "tests/ownership_erasure"],
        ),
        "crust-ownership-import-test": (
            ["ownership"],
            ["tests/ownership_input", "tests/ownership_import_driver"],
        ),
        "crust-ownership-generics-test": (
            ["generics/ownership"],
            ["tests/ownership_input", "tests/ownership_generics_driver"],
        ),
        "crust-ownership-generics-clone": (
            ["generics/ownership"],
            ["tests/ownership_generics_clone"],
        ),
        "kind_composition": (["resources"], ["tests/kind_wrapper", "tests/kind_composition"]),
        "composition-test": (
            ["ownership", "overload/local"],
            ["examples/composition/build", "tests/composition_driver"],
        ),
    }
    for name, (includes, paths) in drivers.items() if ownership else []:
        package = work / f"{name}.crs"
        includes = [
            (
                ROOT / f"stages/{name}/sources.crs"
                if name != "overload/local"
                else ROOT / "stages/overload/local-sources.crs"
            )
            for name in includes
        ]
        paths = [ROOT / f"{name}.crs" for name in paths]
        package.write_text(
            "// SPDX-License-Identifier: Apache-2.0\n"
            + "".join(f"stage_include(stage,{json.dumps(path.as_posix())});\n" for path in includes)
            + "".join(f"stage_source(stage,{json.dumps(path.as_posix())});\n" for path in paths)
            + 'stage_export(stage,"main");\n',
            encoding="utf-8",
        )
        host.compile(build, package, build / name, ["-O2", "-g1"], libraries)
        if name == "crust-ownership-import-test":
            # Let Windows settle first-launch compatibility images before receipts.
            result = host.run([build / name], expected=1)
            assert (
                b"expected publish CACHE SOURCES or import CACHE ARTIFACT DIGEST SOURCES"
                in result.stderr
            )
    packages = ["c"]
    if ownership:
        packages += ["ownership", "overload", "union", "resources"]
    if suite in ("all", "core"):
        packages += ["parallel", "generics", "asm"]
    for name in packages:
        artifact = package_query(build, "library", f"{name}/package.crs")[0]
        shutil.copyfile(
            artifact, build / f"crust-{'resource' if name == 'resources' else name}-library.so"
        )
    assembly = host.emit_object(
        ROOT / "stages/asm/package.crs", build / "shared-asm", ["-O2", "-g1"]
    )
    host.run(["ar", "rcs", build / "libcrust_asm.a", assembly])
    fixtures = []
    if suite in ("all", "ownership", "llvm"):
        fixtures.append(("resource-backends", "resource_backends_package"))
    if ownership:
        fixtures.append(("crust-union-test", "union-package"))
    for name, package in fixtures:
        host.compile(
            build,
            ROOT / f"tests/{package}.crs",
            build / name,
            ["-O2", "-g1"],
            [build / "libcrust0_run.a", build / "libcrust_asm.a", *libraries, "-lffi"],
        )

    if suite not in ("all", "llvm"):
        return
    wrapper = build / "llvm-alloc-wrap.o"
    host.run(
        [
            "gcc",
            "-std=c99",
            "-pedantic-errors",
            "-O2",
            "-g1",
            "-I" + str(build / "profile/include"),
            "-I" + str(ROOT / "include"),
            "-c",
            ROOT / "tests/c_stage_alloc.c",
            "-o",
            wrapper,
        ]
    )
    host.compile(
        build,
        ROOT / "tests/llvm_driver_package.crs",
        build / "llvm-test-driver",
        ["-O2", "-g1"],
        [wrapper, "-Wl,--wrap=crust0_host_alloc", "-Wl,--wrap=crust0_host_free", *libraries],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("all", "core", "split-core", "ownership", "tooling", "llvm"),
        default="all",
    )
    parser.add_argument("--amalgamation", default="1", choices=("0", "1"))
    parser.add_argument("--llvm", type=Path)
    parser.add_argument("--build", type=Path, default=ROOT / "build/windows")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--skip-prepare", action="store_true")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    build = args.build.resolve()
    os.environ["CRUST_TEST_LIMITER"] = str(build / "windows_limit.exe")
    if not args.skip_prepare:
        prepare(build, shlex.split(args.ldflags), args.suite)
    if args.prepare_only:
        return
    run_suites(args, build)


def run_suites(args, build):
    def test(name, *options):
        print("Windows shared: " + name, flush=True)
        run([sys.executable, ROOT / name, "--build", build, *options], check=True)

    if args.suite in ("all", "core", "split-core"):
        test("tests/windows_core.py", "--ldflags=" + args.ldflags)
    if args.suite in ("all", "core"):
        for name in (
            "c_body",
            "asm",
            "source_order",
            "modules",
            "generics",
            "generics_source",
            "parallel",
        ):
            test(f"tests/{name}.py", "--ldflags=" + args.ldflags)
        test("stages/reader/test.py", "--ldflags=" + args.ldflags)
        test("tests/abi.py", "--ldflags=" + args.ldflags, "--amalgamation", args.amalgamation)
        test("tests/stage_packages.py")
    if args.suite in ("all", "ownership"):
        for name in (
            "resources",
            "resource_returns",
            "resource_backends",
            "extension_kinds",
            "ownership",
            "ownership_index",
            "ownership_views",
            "ownership_native",
            "ownership_arrays",
            "ownership_ergonomics",
            "ownership_imports",
            "overload",
            "overload_resources",
            "overload_hooks",
            "nesting",
            "composition",
            "union",
        ):
            test(f"tests/{name}.py")
        test("tests/union.py", "--sanitize-stage")
        run([build / "crust-ownership-generics-clone"], check=True)
        test("tests/ownership_generics.py", "--sanitize")
        test("tests/generics_ownership_imports.py", "--ldflags=" + args.ldflags)
        for name in (
            "ownership_alloc",
            "resources_alloc",
            "overload_alloc",
            "ownership_generics_alloc",
        ):
            test(f"tests/{name}.py", "--amalgamation", args.amalgamation)
    if args.suite in ("all", "tooling"):
        for name in ("tests/format.py", "stages/highlight/test.py", "tests/ccn.py"):
            test(name)
        env = dict(
            os.environ,
            CRUST_HIGHLIGHT=str(build / "crust-highlight.exe"),
            CRUST_LAUNCHER=str(build / "crust.exe"),
        )
        run(
            [os.environ.get("CRUST_JS_RUNTIME", "bun"), "test", "./editors/vscode"],
            env=env,
            check=True,
            cwd=ROOT,
        )
    if args.suite in ("all", "llvm"):
        llvm = args.llvm or Path(os.environ["CRUST_LLVM_DIRECTORY"])
        for name in ("llvm", "llvm_packages", "tutorials"):
            test(f"tests/{name}.py", "--llvm", llvm)
        test("tests/c_body.py", "--wasm-clang", llvm / "bin/clang.exe")


if __name__ == "__main__":
    main()
