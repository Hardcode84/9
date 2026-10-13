#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise LLVM package caching and successive source-built emitter generations."""

import hashlib
import json
from pathlib import Path

from llvm import ROOT, check


def run_packages(build, llvm=None):
    suffix = (
        "" if llvm is None else "-" + hashlib.sha256(str(llvm.resolve()).encode()).hexdigest()[:12]
    )
    work = build / ("llvm-packages" + suffix)
    work.mkdir(exist_ok=True)

    def quote(path):
        return json.dumps(str(path))

    first = ROOT / "stages/llvm/compiler-package.crs"
    sources = f'stage_include(stage,{quote(ROOT / "stages/llvm/configured-sources.crs")});\n'
    if llvm is not None:
        factory = work / "toolchain.crs"
        factory.write_text(
            f"fn llvm_stage_toolchain(tools:*StageToolchain)->bool{{return llvm_toolchain(tools,{quote(llvm.resolve())},2u32);}}\n"
        )
        sources = (
            f'stage_include(stage,{quote(ROOT / "stages/llvm/compiler-sources.crs")});\n'
            f"stage_source(stage,{quote(factory)});\n"
        )
        first = work / "selected-compiler.crs"
        first.write_text(
            sources
            + 'stage_export(stage,"llvm_stage_compile");\nstage_export(stage,"llvm_stage_toolchain");\n'
        )
    for generation in (2, 3):
        previous = first if generation == 2 else work / f"generation-{generation - 1}.crs"
        compile_name = (
            "llvm_stage_compile" if generation == 2 else f"llvm_generation{generation - 1}_compile"
        )
        tools_name = (
            "llvm_stage_toolchain"
            if generation == 2
            else f"llvm_generation{generation - 1}_toolchain"
        )
        (work / f"generation-{generation}.crs").write_text(
            sources
            + f'stage_export_as(stage,"llvm_stage_compile","llvm_generation{generation}_compile");\n'
            f'stage_export_as(stage,"llvm_stage_toolchain","llvm_generation{generation}_toolchain");\n'
            f"stage_compiler(stage,{quote(previous)},{quote(compile_name)});\n"
            f"stage_toolchain(stage,{quote(tools_name)});\n"
        )
    source = work / "program.crs"
    source.write_text("fn answer()->i32{return 42i32;}\n")
    for generation in (1, 2, 3):
        compiler = first if generation == 1 else work / f"generation-{generation}.crs"
        compile_name = (
            "llvm_stage_compile" if generation == 1 else f"llvm_generation{generation}_compile"
        )
        tools_name = (
            "llvm_stage_toolchain" if generation == 1 else f"llvm_generation{generation}_toolchain"
        )
        (work / f"package-{generation}.crs").write_text(
            f'stage_source(stage,{quote(ROOT / "api/crust0.crs")});\n'
            'stage_source(stage,"program.crs");\nstage_export(stage,"answer");\n'
            f"stage_compiler(stage,{quote(compiler)},{quote(compile_name)});\n"
            f"stage_toolchain(stage,{quote(tools_name)});\n"
        )
    root = work / "main.crs"
    root.write_text(
        f'host_source(run,{quote(ROOT / "stages/build/load.crs")});\n'
        f"if !stage_setup(run,{quote(ROOT)}){{return 1i32;}};\n"
        f'var session:*StageSession=stage_open(run,{quote(ROOT)},{quote(build / "stage-cache")});\n'
        "if session==null(*StageSession){return 1i32;};\n"
        "var library:*u8=stage_library(session,run->argv[0usize]);\n"
        "if library==null(*u8) || !crust_run_link(run,library){return 1i32;};\n"
        "if crust0_host_write_stream(1u32,library,native_strlen(library))!=0i32{return 1i32;};\n"
        'extern fn answer()->i32="answer";\nreturn answer();\n'
    )
    artifacts = []
    for generation in (1, 2, 3):
        command = [build / "crust", root, work / f"package-{generation}.crs"]
        path = Path(check(command, 42, cwd="/").stdout.decode())
        before = path.stat().st_mtime_ns
        assert check(command, 42, cwd="/").stdout.decode() == str(path)
        assert path.stat().st_mtime_ns == before
        artifacts.append(path)
    source.write_text("fn answer()->i32{return 43i32;}\n")
    command = [build / "crust", root, work / "package-3.crs"]
    assert Path(check(command, 43, cwd="/").stdout.decode()) != artifacts[-1]
    source.write_text("fn answer()->i32{return missing;}\n")
    assert b"unknown name" in check(command, 1, cwd="/").stderr
    if llvm is not None:
        source.write_text("fn answer()->i32{return 43i32;}\n")
        original = factory.read_text()
        try:
            factory.write_text(original.replace("2u32", "4u32"))
            assert b"optimization level must be 0..3" in check(command, 1, cwd="/").stderr
            factory.write_text(
                original.replace(quote(llvm.resolve()), quote(work / "missing-llvm"))
            )
            assert b"cannot read cache file" in check(command, 1, cwd="/").stderr
        finally:
            factory.write_text(original)
    assert not list((build / "stage-cache").glob("crust-*"))
    print(
        "LLVM packages: three emitter generations, native loading, reuse, source invalidation and diagnostics passed"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--llvm", type=Path)
    args = parser.parse_args()
    run_packages(args.build.resolve(), args.llvm)
