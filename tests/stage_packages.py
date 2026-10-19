#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise source-owned stage preparation from a seed-only source package."""

import argparse
import os
import shutil
from pathlib import Path

import package_toolchains
import stage_compilers
from host import WINDOWS, executable
from host import run as host_run

ROOT = Path(__file__).resolve().parents[1]


def run(command, expected=0, **kwargs):
    result = host_run(command, capture_output=True, text_output=True, **kwargs)
    assert result.returncode == expected, (command, result.returncode, result.stdout, result.stderr)
    return result


def symbol_export(work, seed):
    package = work / "symbol package"
    package.mkdir(exist_ok=True)
    (package / "provider.crs").write_text("fn answer()->i32{return 31i32;}\n")
    (package / "package.crs").write_text(
        'stage_api_from(stage,"..","crust0.crs");\n'
        'stage_source(stage,"provider.crs");\n'
        'stage_export_as(stage,"answer","native\\x1aanswer");\n'
    )
    root = package / "main.crs"
    root.write_text(
        'host_source(run,"../stages/build/load.crs");\n'
        'if !stage_setup(run,".."){return 1i32;};\n'
        'var stages:*StageSession=stage_open(run,"..","../build/stage-cache");\n'
        "if stages==null(*StageSession){return 1i32;};\n"
        'var artifact:*u8=stage_library(stages,"symbol package/package.crs");\n'
        "if artifact==null(*u8){return 1i32;};\n"
        'extern fn answer()->i32="native\\x1aanswer";\n'
        'if !host_bind(run,crust_run_open(run,artifact),"answer"){return 1i32;};\n'
        "return answer();\n"
    )
    run([seed, root], expected=31)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build"))
    args = parser.parse_args()
    build = args.build.resolve()
    work = build / "stage-package-tests"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    for part in ("api", "stages", "examples"):
        shutil.copytree(ROOT / part, work / part)
    (work / "build").mkdir()
    seed = work / ("build/crust.exe" if WINDOWS else "build/crust")
    shutil.copyfile(executable(build / "crust"), seed)
    if WINDOWS:
        shutil.copyfile(build / "crust.exe.a", work / "build/crust.exe.a")
        shutil.copytree(build / "profile", work / "build/profile")
    seed.chmod(0o755)
    run([seed, work / "examples/hello/main.crs"], cwd="/")
    assert run([work / "build/hello"]).stdout == b"Hello, world!\n"
    assert not list((work / "build").glob("*.so"))
    assert not [path for path in (work / "build").glob("*.a") if path.name != "crust.exe.a"]

    package = work / "custom package"
    package.mkdir()
    provider = package / "provider.crs"
    provider.write_text("fn answer()->i32{return 7i32;}\n")
    (package / "sources.crs").write_text(
        'stage_api_from(stage, "..", "crust0.crs");\nstage_source(stage, "provider.crs");\n'
    )
    manifest = package / "package.crs"
    manifest.write_text('stage_include(stage, "sources.crs");\nstage_export(stage, "answer");\n')
    root = work / "main.crs"
    root.write_text(
        """host_source(run, "stages/build/load.crs");
if !stage_setup(run, ".") {return 1i32;};
var stages:*StageSession=stage_open(run, ".", "build/stage-cache");
if stages==null(*StageSession) {return 1i32;};
var artifact:*u8=stage_library(stages, "custom package/package.crs");
if artifact==null(*u8) {return 1i32;};
if crust0_host_write_stream(1u32,artifact,native_strlen(artifact))!=0i32 {return 1i32;};
if crust_run_open(run,artifact)==null(*u8) {return 1i32;};
extern fn answer()->i32="answer";
if !host_bind(run,crust_run_open(run,artifact),"answer"){return 1i32;};
return answer();
"""
    )
    first = run([seed, root], expected=7, cwd="/").stdout
    assert run([seed, root], expected=7, cwd="/").stdout == first
    times = provider.stat()
    provider.write_text("fn answer()->i32{return 9i32;}\n")
    os.utime(provider, ns=(times.st_atime_ns, times.st_mtime_ns))
    changed = run([seed, root], expected=9, cwd="/").stdout
    assert changed != first
    provider.write_text("fn answer()->i32{return missing;}\n")
    rejected = run([seed, root], expected=1, cwd="/")
    assert b"unknown name 'missing'" in rejected.stderr
    assert not rejected.stdout
    provider.write_text("fn answer()->i32{return 9i32;}\n")
    assert run([seed, root], expected=9, cwd="/").stdout == changed

    # A package selection retains the exact source bytes through compilation.
    captured = root.read_text().replace(
        'var artifact:*u8=stage_library(stages, "custom package/package.crs");',
        """var package:StagePackage=uninit;
stage_init(&package,run,".");
if !stage_include(&package,"custom package/package.crs") {return 1i32;};
var replacement:*u8="fn answer()->i32{return 13i32;}\\n";
if !cache_save(run->context,host_path(run,"custom package/provider.crs"),replacement,native_strlen(replacement)) {return 1i32;};
var result:CacheArtifact=uninit;
if !stage_artifact(stages,&package,false,&result) {return 1i32;};
var artifact:*u8=result.path;""",
    )
    root.write_text(captured)
    assert run([seed, root], expected=9, cwd="/").stdout == changed
    stage_compilers.check(work, seed, run)
    package_toolchains.check(work, seed, run)
    # A damaged hit is an error, never an implicit use of an old stage.
    Path(os.fsdecode(changed)).write_bytes(b"damaged")
    provider.write_text("fn answer()->i32{return 9i32;}\n")
    rejected = run([seed, root], expected=1, cwd="/")
    assert b"cache artifact checksum mismatch" in rejected.stderr
    symbol_export(work, seed)
    print(
        "stage packages: seed-only hello, reuse, transitive source edits, rejection, snapshots, and corruption passed"
    )


if __name__ == "__main__":
    main()
