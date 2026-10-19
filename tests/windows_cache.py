#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Windows cache contracts, with each native process tree capped at 512 MiB."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from windows import ROOT, literal, native_path
from windows_bootstrap import Suite, process_arguments


class CacheSuite(Suite):
    def probe_stdio(self):
        args = process_arguments(self.build / "windows_process.exe")
        body = self.setup()
        body += "var inputs:CacheInputs=make CacheInputs{items:null(**CrustSource),count:0usize,capacity:0usize};\n"
        body += (
            "var arguments:[*u8;9]=make [*u8;9]{" + ",".join(map(literal, args)) + ",null(*u8)};\n"
        )
        body += f"return (!cache_probe(run -> context,&inputs,&arguments[0usize],{literal(native_path(self.work))})) as i32;\n"
        result = self.root("probe stdio", body, stdin=b"must not reach the probe\n")
        assert result.stdout.replace(b"\r\n", b"\n") == b"arguments and environment passed\n"

    def source_invalidation(self):
        cache = self.fresh_directory("source invalidation")
        provider = self.work / "cache-provider.crs"
        package = self.work / "cache-package.crs"
        provider.write_text(
            "// SPDX-License-Identifier: Apache-2.0\nfn answer()->i32{return 42i32;}\n"
        )
        package.write_text(
            '// SPDX-License-Identifier: Apache-2.0\nstage_api(stage,"crust0.crs");stage_source(stage,"cache-provider.crs");stage_export(stage,"answer");\n'
        )
        body = self.setup() + self.session(cache)
        body += 'extern fn answer()->i32="answer";\n'
        body += f"if !stage_import(stages,{literal(native_path(package))}){{return 1i32;}};return answer();\n"
        self.root("source invalidation", body, expected=42)
        self.root("source invalidation", body, expected=42)
        assert len(list(cache.glob("*/artifact.dll"))) == 2
        provider.write_text(
            "// SPDX-License-Identifier: Apache-2.0\nfn answer()->i32{return 43i32;}\n"
        )
        self.root("source invalidation", body, expected=43)
        assert len(list(cache.glob("*/artifact.dll"))) == 3

    def copy_toolchain(self, source, target):
        body = (
            self.setup()
            + """
var wide:*u16=win_env(run -> context,"SystemRoot");
if wide==null(*u16){return 1i32;};
var path:*u8=win_utf8(run -> context,wide);
if path==null(*u8){return 1i32;};
return crust0_host_write_stream(1u32,path,native_strlen(path));
"""
        )
        system = self.root("system directory", body).stdout.decode("utf-8")
        executable = system + "/System32/robocopy.exe"
        if os.name != "nt":
            executable = subprocess.check_output(["wslpath", "-u", executable], text=True).strip()
        # Native copy avoids thousands of metadata round trips through WSL.
        self.run(
            Path(executable),
            native_path(source),
            native_path(target),
            "/E",
            "/R:0",
            "/W:0",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            expected=tuple(range(8)),
        )

    def toolchain_invalidation(self):
        selected = shutil.which("gcc.exe")
        assert selected, "native Windows GCC is required"
        installed = Path(selected).resolve().parent.parent
        copied = self.fresh_directory("toolchain 雪")
        self.copy_toolchain(installed, copied)
        cache = self.fresh_directory("toolchain invalidation")
        environment = dict(os.environ, PATH=str(copied / "bin") + os.pathsep + os.environ["PATH"])
        body = self.setup() + self.session(cache) + "return 0i32;\n"

        def prepare(expected):
            self.root("toolchain invalidation", body, environment=environment)
            assert len(list(cache.glob("*/artifact.dll"))) == expected
            assert not list(cache.glob(".build-*"))

        prepare(1)
        prepare(1)
        # A valid PE overlay changes tool bytes without breaking the compiler.
        with (copied / "bin/gcc.exe").open("ab") as stream:
            stream.write(b"cache identity test\n")
        prepare(2)
        header = next(copied.rglob("stddef.h"))
        with header.open("ab") as stream:
            stream.write(b"\n/* cache header identity test */\n")
        prepare(3)
        # Environment changes must also invalidate, even with identical tool files.
        temporary = self.fresh_directory("tool temporary")
        environment["TEMP"] = native_path(temporary)
        if os.name != "nt":
            environment["WSLENV"] = environment.get("WSLENV", "") + ":TEMP"
        prepare(4)
        libraries = list(copied.rglob("libbcrypt.a"))
        assert libraries
        for library in libraries:
            library.unlink()
        failure = self.root("toolchain invalidation", body, expected=1, environment=environment)
        assert b"bcrypt" in failure.stderr
        assert not list(cache.glob(".build-*"))
        (copied / "bin/gcc.exe").unlink()
        # Keep PATH restricted so a different installed compiler cannot mask absence.
        environment["PATH"] = str(copied / "bin")
        failure = self.root("toolchain invalidation", body, expected=1, environment=environment)
        assert b"cannot find native tool" in failure.stderr

    def loaded_dependency(self):
        cache = self.fresh_directory("loaded dependency")
        library = self.work / "dependency.dll"
        shutil.copyfile(self.build / "windows_cache_fixture.dll", library)
        body = self.request(cache, 'return cache_save(context,path,"complete",8usize);')
        body = body.replace(
            "var result:CacheArtifact=uninit;",
            f"""
if crust_run_open(run,{literal(native_path(library))})==null(*u8){{return 1i32;}};
var inputs:CacheInputs=make CacheInputs{{items:null(**CrustSource),count:0usize,capacity:0usize}};
if !cache_loaded_inputs(run -> context,&inputs){{return 1i32;}};
request.inputs=inputs.items;request.count=inputs.count;
var result:CacheArtifact=uninit;
""",
        )
        self.root("loaded dependency", body)
        self.root("loaded dependency", body)
        assert len(list(cache.glob("*/artifact.dll"))) == 1
        with library.open("ab") as stream:
            stream.write(b"changed native dependency\n")
        self.root("loaded dependency", body)
        assert len(list(cache.glob("*/artifact.dll"))) == 2

    def loaded_order(self):
        cache = self.fresh_directory("loaded order")
        libraries = [self.work / f"order-{index}.dll" for index in (1, 2)]
        for library in libraries:
            shutil.copyfile(self.build / "windows_cache_fixture.dll", library)
        for order in (libraries, list(reversed(libraries))):
            body = self.request(cache, 'return cache_save(context,path,"complete",8usize);')
            loads = "".join(
                f"if crust_run_open(run,{literal(native_path(path))})==null(*u8){{return 1i32;}};"
                for path in order
            )
            body = body.replace(
                "var result:CacheArtifact=uninit;",
                loads
                + """
var inputs:CacheInputs=make CacheInputs{items:null(**CrustSource),count:0usize,capacity:0usize};
if !cache_value_input(run -> context,&inputs,"source-prefix","source",6usize){return 1i32;};
if !cache_loaded_inputs(run -> context,&inputs){return 1i32;};
if cache_strcmp(inputs.items[0usize] -> path,"source-prefix")!=0i32{return 1i32;};
request.inputs=inputs.items;request.count=inputs.count;
var result:CacheArtifact=uninit;
""",
            )
            self.root("loaded order", body)
        assert len(list(cache.glob("*/artifact.dll"))) == 1

    def publication(self):
        fixture = self.build / "windows_cache_fixture.exe"
        library = self.build / "windows_cache_fixture.dll"
        for interrupted in (False, True):
            cache = self.fresh_directory("publication " + str(interrupted))
            barrier = self.fresh_directory("barrier " + str(interrupted))
            commands = []
            for index in (1, 2):
                body = self.request(
                    cache,
                    f'if !cache_save(context,path,"complete",8usize){{return false;}}return cache_barrier({literal(native_path(barrier))},{index}i32)==0i32;',
                )
                prefix = f'extern fn cache_barrier(directory:*u8,index:i32)->i32="cache_barrier";\nhost_bind(run,crust_run_open(run,{literal(native_path(library))}),"cache_barrier");\n'
                source = self.work / f"publication-{index}.crs"
                source.write_text(prefix + body, encoding="utf-8")
                commands.append(
                    subprocess.list2cmdline([native_path(self.seed), native_path(source)])
                )
            if interrupted:
                self.run(fixture, "interrupt", commands[0], native_path(barrier / "1"))
                assert not list(cache.glob("[!.]*/artifact.dll"))
                assert list(cache.glob(".build-*/artifact.dll"))
                # A later request must ignore the interrupted private directory.
                self.root(
                    "after interruption",
                    self.request(cache, 'return cache_save(context,path,"complete",8usize);'),
                )
            else:
                self.run(fixture, "pair", *commands)
                assert not list(cache.glob(".build-*"))
            published = [
                path
                for path in cache.glob("*/artifact.dll")
                if not path.parent.name.startswith(".")
            ]
            assert len(published) == 1
            assert published[0].read_bytes() == b"complete"

    def failures(self):
        for case, producer in (
            ("partial", 'cache_save(context,path,"partial",7usize);return false;'),
            (
                "diagnostic",
                'cache_save(context,path,"partial",7usize);return native_error(context,"producer rejected");',
            ),
            ("missing", "return true;"),
        ):
            cache = self.fresh_directory("failure " + case)
            body = self.request(cache, producer)
            self.root("cache failure " + case, body, expected=1)
            assert not list(cache.iterdir())
        cache = self.fresh_directory("corrupt entry")
        body = self.request(cache, 'return cache_save(context,path,"complete",8usize);')
        self.root("corrupt entry", body)
        artifact = next(cache.glob("*/artifact.dll"))
        assert (
            artifact.parent.name == hashlib.sha256(b"crust-artifact-v1-windows-x64\n").hexdigest()
        )
        artifact.write_bytes(b"broken")
        failed = self.root("corrupt entry", body, expected=1)
        assert b"checksum mismatch" in failed.stderr
        assert not list(cache.glob(".build-*"))

    def request(self, cache, producer):
        return (
            self.setup()
            + f"""
fn produce(context:*CrustContext,request:*CacheBuild,path:*u8)->bool{{{producer}}}
var request:CacheBuild=make CacheBuild{{inputs:null(**CrustSource),count:0usize,build:produce,user:null(*u8)}};
var result:CacheArtifact=uninit;
return (!cache_artifact(run -> context,{literal(native_path(cache))},&request,&result)) as i32;
"""
        )

    def allocations(self):
        cache = self.fresh_directory("cache allocations")
        body = self.request(
            cache,
            'if !cache_save(context,path,"complete",8usize){return false;}return crust_try_alloc(context,1048576usize,8usize)!=null(*u8);',
        )
        body = body.split("var result:CacheArtifact=uninit;", 1)[0]
        body += f"host_source(run,{literal(native_path(ROOT / 'tests/cache_alloc.crs'))});\n"
        for fail_at in range(1, 100):
            self.fresh_directory("cache allocations")
            source = self.work / "cache allocation.crs"
            source.write_text(
                body
                + f"return cache_allocation(&request,{literal(native_path(cache))},{fail_at}usize);",
                encoding="utf-8",
            )
            result = self.run(self.seed, native_path(source), expected=(0, 42))
            assert not list(cache.glob(".build-*"))
            if result.returncode == 42:
                return
        raise AssertionError("allocation sweep did not reach publication")

    def reuse(self):
        cache = self.fresh_directory("reused backend")
        output = self.work / "cached hello.exe"
        body = self.setup() + self.session(cache)
        body += f"return application(stages,{literal(native_path(output))},c_backend_build);\n"
        body += 'extern fn puts(text:*u8)->i32="puts";fn main(argc:i32,argv:**u8)->i32{return (puts("cached hello")<0i32) as i32;}'
        started = time.monotonic()
        self.root("reuse backend", body)
        cold = time.monotonic() - started
        artifacts = list(cache.glob("*/artifact.dll"))
        assert len(artifacts) == 1
        before = artifacts[0].stat().st_mtime_ns
        started = time.monotonic()
        self.root("reuse backend", body)
        warm = time.monotonic() - started
        assert list(cache.glob("*/artifact.dll")) == artifacts
        assert artifacts[0].stat().st_mtime_ns == before
        assert self.run(output).stdout.replace(b"\r\n", b"\n") == b"cached hello\n"
        (self.work / f"cache-cost-{time.time_ns()}.json").write_text(
            json.dumps(
                {
                    "cold_seconds": cold,
                    "warm_seconds": warm,
                    "includes_target_compilation": True,
                    "memory_limit": 536870912,
                    "cache_key": artifacts[0].parent.name,
                    "seed_sha256": hashlib.sha256(self.seed.read_bytes()).hexdigest(),
                    "backend_sha256": hashlib.sha256(artifacts[0].read_bytes()).hexdigest(),
                },
                indent=2,
            )
        )
        self.root("reuse backend", body.replace('puts("cached hello")', 'puts("changed hello")'))
        assert len(list(cache.glob("*/artifact.dll"))) == 1
        assert self.run(output).stdout.replace(b"\r\n", b"\n") == b"changed hello\n"

    def toolchain(self):
        cache = self.fresh_directory("tool capture")
        body = (
            self.setup()
            + f"""
var toolchain:StageToolchain=make StageToolchain{{inputs:make CacheInputs{{items:null(**CrustSource),count:0usize,capacity:0usize}},context:run -> context,directory:{literal(native_path(cache))},object:null(fn(*StageObject)->bool),user:null(*u8)}};
if !stage_c_toolchain(&toolchain){{return 1i32;}};
if toolchain.inputs.count<10usize{{return 2i32;}};
return 0i32;
"""
        )
        self.root("tool capture", body)
        assert not list(cache.iterdir())

    def storage(self):
        cache = self.fresh_directory("cache storage")
        payload = self.work / "hash input 雪"
        payload.write_bytes(b"abc")
        body = (
            self.setup()
            + f"""
var digest:*u8=cache_digest(run -> context,{literal(native_path(payload))},null(*u8));
if digest==null(*u8)||cache_strcmp(digest,"{hashlib.sha256(b'abc').hexdigest()}")!=0i32{{return 2i32;}};
fn produce(context:*CrustContext,request:*CacheBuild,path:*u8)->bool{{
    var count:*usize=request -> user as *usize; *count=*count+1usize;
    return cache_save(context,path,request -> inputs[0usize] -> bytes,request -> inputs[0usize] -> size);
}}
var count:usize=0usize;
var input:CrustSource=make CrustSource{{path:"input",bytes:"one",size:3usize,identity:0u64}};
var inputs:[*CrustSource;1]=make [*CrustSource;1]{{&input}};
var request:CacheBuild=make CacheBuild{{inputs:&inputs[0usize],count:1usize,build:produce,user:&count as *u8}};
var result:CacheArtifact=uninit;
var directory:*u8={literal(native_path(cache))};
if !cache_artifact(run -> context,directory,&request,&result)||result.hit||count!=1usize{{return 3i32;}};
if !cache_artifact(run -> context,directory,&request,&result)||!result.hit||count!=1usize{{return 4i32;}};
input.bytes="two";
if !cache_artifact(run -> context,directory,&request,&result)||result.hit||count!=2usize{{return 5i32;}};
return 0i32;
"""
        )
        self.root("cache storage", body)
        assert len(list(cache.glob("*/artifact.dll"))) == 2
        assert not list(cache.glob(".build-*"))


def main():
    cases = (
        "probe_stdio",
        "storage",
        "failures",
        "allocations",
        "publication",
        "loaded_dependency",
        "loaded_order",
        "toolchain",
        "reuse",
        "source_invalidation",
        "toolchain_invalidation",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build/windows"))
    parser.add_argument(
        "--case",
        choices=cases,
    )
    args = parser.parse_args()
    suite = CacheSuite(args.build)
    if args.case:
        cases = (args.case,)
    for case in cases:
        getattr(suite, case)()
        print(f"Windows cache: {case} passed", flush=True)


if __name__ == "__main__":
    main()
