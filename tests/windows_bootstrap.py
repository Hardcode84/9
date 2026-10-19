#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Test source-owned Windows bootstrap. All native children share a 512 MiB job."""

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

from windows import ROOT, literal, native_path


def process_arguments(fixture):
    return [native_path(fixture), "", "two words", 'a"b', "end\\", '\\"', "line\nbreak", "雪"]


class Suite:
    def __init__(self, build):
        self.build = build.resolve()
        self.work = self.build / "bootstrap tests 雪"
        self.work.mkdir(exist_ok=True)
        self.seed = self.build / "crust.exe"
        self.limiter = self.build / "windows_limit.exe"

    def run(self, executable, *arguments, expected=0, environment=None, stdin=None):
        result = subprocess.run(
            [str(self.limiter), native_path(executable), *map(str, arguments)],
            cwd=ROOT,
            capture_output=True,
            timeout=120,
            env=environment,
            input=stdin,
        )
        allowed = expected if isinstance(expected, tuple) else (expected,)
        assert result.returncode in allowed, (result.returncode, result.stdout, result.stderr)
        return result

    def root(self, name, body, expected=0, environment=None, stdin=None):
        source = self.work / f"{name}.crs"
        source.write_text("// SPDX-License-Identifier: Apache-2.0\n" + body, encoding="utf-8")
        return self.run(
            self.seed, native_path(source), expected=expected, environment=environment, stdin=stdin
        )

    def setup(self):
        return (
            f"host_source(run,{literal(native_path(ROOT / 'stages/build/load.crs'))});\n"
            f"if !application_setup(run,{literal(native_path(ROOT))}){{return 1i32;}};\n"
        )

    def session(self, directory):
        return (
            f"var stages:*StageSession=stage_open(run,{literal(native_path(ROOT))},"
            f"{literal(native_path(directory))});\n"
            "if stages==null(*StageSession){return 1i32;};\n"
        )

    def fresh_directory(self, name):
        directory = self.work / name
        assert self.work.resolve().is_relative_to(self.build)
        assert directory.resolve().parent == self.work.resolve()
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir()
        return directory

    def bootstrap(self):
        cache = self.fresh_directory("generations")
        output = self.work / "hello.exe"
        source = self.setup() + self.session(cache)
        source += """
extern fn witness_backend(context:*CrustContext,entry:*CrustDecl,options:*BackendOptions)->i32="c_backend_build";
var first:*u8=crust_run_open(run,stages -> backend);
if first==null(*u8)||!host_bind(run,first,"witness_backend"){return 1i32;};
if c_backend_build!=witness_backend{return 2i32;};
var loaded_path:*u16=win_wide(run -> context,stages -> backend);
if loaded_path==null(*u16)||win_delete(loaded_path)!=0i32{return 3i32;};
if crust0_host_write_stream(1u32,"native handoff\\n",15usize)!=0i32{return 1i32;};
var second:*u8=stage_library(stages,"stages/c/package.crs");
if second==null(*u8){return 1i32;};
extern fn second_backend(context:*CrustContext,entry:*CrustDecl,options:*BackendOptions)->i32="c_backend_build";
if !host_bind(run,crust_run_open(run,second),"second_backend"){return 1i32;};
"""
        source += f"return application(stages,{literal(native_path(output))},second_backend);\n"
        source += 'extern fn puts(text:*u8)->i32="puts";\n'
        source += 'fn main(argc:i32,argv:**u8)->i32{return (puts("Hello, world!")<0i32) as i32;}\n'
        assert self.root("generations", source).stdout == b"native handoff\n"
        assert self.run(output).stdout.replace(b"\r\n", b"\n") == b"Hello, world!\n"
        artifacts = list(cache.glob("*/artifact.dll"))
        assert len(artifacts) == 2
        assert len(list(cache.glob("*/*"))) == 4, "build scratch survived"
        # Deletion must succeed after runner destruction releases both DLLs.
        for artifact in artifacts:
            artifact.unlink()
            (artifact.parent / "checksum").unlink()
            artifact.parent.rmdir()
        output.unlink()

    def failed_package(self):
        cache = self.fresh_directory("failed package")
        provider = self.work / "unresolved.crs"
        provider.write_text(
            '// SPDX-License-Identifier: Apache-2.0\nextern fn absent()->i32="crust_missing_dependency";\nfn answer()->i32{return absent();}\n'
        )
        package = self.work / "unresolved-package.crs"
        package.write_text(
            '// SPDX-License-Identifier: Apache-2.0\nstage_source(stage,"unresolved.crs");stage_export(stage,"answer");\n'
        )
        source = self.setup() + self.session(cache)
        source += f"if stage_library(stages,{literal(native_path(package))})==null(*u8){{return 1i32;}};return 0i32;"
        failure = self.root("unresolved-run", source, expected=1)
        assert b"crust_missing_dependency" in failure.stderr
        assert len(list(cache.glob("*/artifact.dll"))) == 1
        assert len(list(cache.iterdir())) == 1, "failed build directory survived"

    def processes(self, fixture):
        capture = self.work / "captured output.txt"
        args = process_arguments(fixture)
        source = self.setup()
        source += (
            "var arguments:[*u8;9]=make [*u8;9]{" + ",".join(map(literal, args)) + ",null(*u8)};\n"
        )
        source += "var status:u32=1u32;\n"
        source += f"if !win_tool(run -> context,&arguments[0usize],{literal(native_path(capture))},&status)||status!=0u32{{return 1i32;}};\n"
        source += 'arguments[1usize]="fail";arguments[2usize]=null(*u8);\n'
        source += "if !win_tool(run -> context,&arguments[0usize],null(*u8),&status)||status!=37u32{return 1i32;};return 0i32;\n"
        self.root("process", source)
        assert capture.read_bytes().replace(b"\r\n", b"\n") == b"arguments and environment passed\n"

    def cleanup_allocation(self):
        path = self.work / "cleanup without allocation.txt"
        path.write_bytes(b"temporary")
        source = (
            self.setup()
            + """
fn reject_allocation(user:*u8,size:usize)->*u8{return null(*u8);}
fn reject_release(user:*u8,bytes:*u8)->unit{trap;}
var allocator:CrustAllocator=make CrustAllocator{user:null(*u8),allocate:reject_allocation,release:reject_release};
var context:CrustContext=uninit;
crust_context_init(&context,&allocator);
"""
        )
        source += f"var success:bool=win_remove(&context,{literal(native_path(path))},false);\n"
        source += "crust_context_destroy(&context);return (!success) as i32;\n"
        self.root("cleanup-allocation", source)
        assert not path.exists()

    def artifact_rejections(self):
        for name, path in (("relative", '"relative"'), ("null", "null(*u8)")):
            source = (
                self.setup()
                + """
fn unexpected_build(context:*CrustContext,request:*CacheBuild,path:*u8)->bool{trap;}
var request:CacheBuild=make CacheBuild{inputs:null(**CrustSource),count:0usize,build:unexpected_build,user:null(*u8)};
var result:CacheArtifact=uninit;
"""
            )
            source += f"return (!cache_artifact(run -> context,{path},&request,&result)) as i32;\n"
            failure = self.root("artifact-" + name, source, expected=1)
            assert b"absolute directory" in failure.stderr

    def runtime_directory(self):
        """Copy PATH-resolved runtime DLLs for a seed already verified to start."""
        directory = self.fresh_directory("runtime DLLs")
        search = [self.build, *map(Path, os.environ["PATH"].split(os.pathsep))]
        system = Path(os.environ["SystemRoot"]).resolve()
        pending, seen = [self.seed], set()
        while pending:
            binary = pending.pop()
            imports = subprocess.check_output(
                ["objdump", "-p", binary.name], cwd=binary.parent, timeout=30
            )
            for name in re.findall(rb"DLL Name:\s*(\S+)", imports):
                if name in seen:
                    continue
                seen.add(name)
                candidates = (path / os.fsdecode(name) for path in search)
                source = next((path.resolve() for path in candidates if path.is_file()), None)
                if source is None or source.is_relative_to(system):
                    continue
                target = directory / source.name
                shutil.copy2(source, target)
                pending.append(target)
        return directory

    def missing_dependencies(self):
        cache = self.fresh_directory("missing tools")
        # Remove compiler tools from PATH while retaining the seed's DLL dependencies.
        runtime = self.runtime_directory()
        environment = dict(os.environ, PATH=str(runtime))
        failed = self.root(
            "missing-tools", self.setup() + self.session(cache), expected=1, environment=environment
        )
        assert b"cannot find native tool" in failed.stderr
        assert not list(cache.iterdir())
        invalid = self.fresh_directory("invalid tools") / "bin"
        invalid.mkdir()
        for name in ("gcc.exe", "objcopy.exe"):
            (invalid / name).write_bytes(b"invalid executable")
        environment["PATH"] = os.pathsep.join(map(str, (invalid, runtime)))
        failed = self.root(
            "invalid-tool", self.setup() + self.session(cache), expected=1, environment=environment
        )
        assert b"cannot start native tool" in failed.stderr
        assert not list(cache.iterdir())
        installed = self.fresh_directory("missing import")
        shutil.copy2(self.seed, installed / "crust.exe")
        shutil.copytree(self.build / "profile", installed / "profile")
        previous = self.seed
        self.seed = installed / "crust.exe"
        try:
            failed = self.root("missing-import", self.setup() + self.session(cache), expected=1)
            assert b"cannot read cache file" in failed.stderr
            assert not list(cache.iterdir())
        finally:
            self.seed = previous

    def outputs(self):
        cache = self.fresh_directory("output failures")
        destination = self.work / "preserved.c"
        destination.write_bytes(b"original output")
        common = self.setup() + self.session(cache)

        def compile_case(name, arguments, expected):
            count = len(arguments)
            source = common + f"var arguments:[*u8;{count}]=make [*u8;{count}]{{"
            source += ",".join(map(literal, arguments)) + "};\n"
            source += f"return c_build(run -> source,run -> cursor,{count}i32,&arguments[0usize],c_backend_build);\n"
            source += "fn main(argc:i32,argv:**u8)->i32{return 0i32;}\n"
            return self.root(name, source, expected=expected)

        compile_case(
            "bad-compiler-option",
            ["-o", native_path(destination), "--cflag", "-fcrust-invalid-option"],
            1,
        )
        assert destination.read_bytes() == b"original output"
        alias = self.work / "hardlink.c"
        alias.unlink(missing_ok=True)
        os.link(destination, alias)
        for name, path in (("hardlink", alias), ("same-path", destination)):
            failure = compile_case(
                name, ["--emit", "-o", native_path(destination), "--symbols", native_path(path)], 1
            )
            assert b"separate" in failure.stderr
            assert destination.read_bytes() == b"original output"
        alias.unlink()
        symbols = self.work / "symbols.rsp"
        compile_case(
            "replace-output",
            ["--emit", "-o", native_path(destination), "--symbols", native_path(symbols)],
            0,
        )
        assert b"#include" in destination.read_bytes()
        assert symbols.exists()
        assert not list(self.work.glob(".crust-*")), "driver temporary survived"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build/windows"))
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    suite = Suite(args.build)
    os.environ["CRUST_UNEXPECTED"] = "must not reach tools"
    if os.name != "nt":
        os.environ["WSLENV"] = os.environ.get("WSLENV", "") + ":CRUST_UNEXPECTED"
    suite.processes(args.fixture or suite.build / "windows_process.exe")
    suite.cleanup_allocation()
    suite.artifact_rejections()
    suite.bootstrap()
    suite.failed_package()
    suite.missing_dependencies()
    suite.outputs()
    print("Windows bootstrap, successor, process, failure, and unload checks passed")


if __name__ == "__main__":
    main()
