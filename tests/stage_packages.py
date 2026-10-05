#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise source-owned stage preparation from a seed-only source package."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, expected=0, **kwargs):
    result = subprocess.run(command, capture_output=True, **kwargs)
    assert result.returncode == expected, (command, result.returncode, result.stdout, result.stderr)
    return result


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
    seed = work / "build/crust"
    shutil.copyfile(build / "crust", seed)
    seed.chmod(0o755)
    run([seed, work / "examples/hello/main.crs"], cwd="/")
    assert run([work / "build/hello"]).stdout == b"Hello, world!\n"
    assert not list((work / "build").glob("*.so"))
    assert not list((work / "build").glob("*.a"))

    package = work / "custom package"
    package.mkdir()
    provider = package / "provider.crs"
    provider.write_text("fn answer()->i32{return 7i32;}\n")
    (package / "sources.crs").write_text(
        'stage_source(stage, "../api/crust0.crs");\nstage_source(stage, "provider.crs");\n'
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
if !crust_run_link(run,artifact) {return 1i32;};
extern fn answer()->i32="answer";
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
    # A damaged hit is an error, never an implicit use of an old stage.
    Path(os.fsdecode(changed)).write_bytes(b"damaged")
    provider.write_text("fn answer()->i32{return 9i32;}\n")
    rejected = run([seed, root], expected=1, cwd="/")
    assert b"cache artifact checksum mismatch" in rejected.stderr
    print(
        "stage packages: seed-only hello, reuse, transitive source edits, rejection, snapshots, and corruption passed"
    )


if __name__ == "__main__":
    main()
