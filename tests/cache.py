#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise artifact reuse through source programs and the native backend tutorial."""

import argparse
import concurrent.futures
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def quoted(path):
    return json.dumps(str(path))


class Suite:
    def __init__(self, build):
        self.build = build.resolve()
        self.work = self.build / "cache-tests"
        if self.work.exists():
            shutil.rmtree(self.work)
        self.work.mkdir()
        self.checks = 0
        self.prefix = "".join(
            f"host_source(run,{quoted(ROOT / path)});\n"
            for path in (
                "stages/native/model.crs",
                "stages/native/linux.crs",
                "stages/cache/model.crs",
                "stages/cache/linux.crs",
                "stages/cache/artifact.crs",
                "stages/cache/inputs.crs",
            )
        )

    def run(self, path, expected=0, arguments=(), **kwargs):
        result = subprocess.run(
            [str(self.build / "crust"), str(path), *map(str, arguments)],
            capture_output=True,
            timeout=60,
            **kwargs,
        )
        self.checks += 1
        assert result.returncode == expected, result
        return result

    def fixture(
        self, name, body="return cache_save(ctx, path, (*input).bytes, (*input).size);", before=""
    ):
        directory = self.work / name
        directory.mkdir()
        data = directory / "input"
        data.write_bytes(b"captured bytes\x00\xff\n")
        dependency = directory / "dependency"
        dependency.write_text("compiler and option identity\n")
        cache = directory / "cache"
        cache.mkdir()
        root = directory / "main.crs"
        root.write_text(
            self.prefix
            + f"""
extern fn report(text:*u8)->i32="puts";
fn produce(ctx:*CrustContext, request:*CacheBuild, path:*u8)->bool {{
    var file:*u8=native_fopen({quoted(directory / 'builds')},"ab");
    if file==null(*u8) {{return native_error(ctx,"cannot open effect log");}}
    var ok:bool=cache_write(ctx,file,"build\\n",6usize);
    if native_fclose(file)!=0i32 {{return native_error(ctx,"cannot close effect log");}}
    if !ok {{return false;}}
    var input:*CrustSource=(*request).inputs[0usize];
    {body}
}}
var input:*CrustSource=host_input(run,{quoted(data)},1u64);
var dependency:*CrustSource=host_input(run,{quoted(dependency)},2u64);
var inputs:[*CrustSource;3]=make [*CrustSource;3]{{input,dependency,(*run).source}};
var request:CacheBuild=make CacheBuild{{inputs:&inputs[0usize],count:3usize,build:produce,user:null(*u8)}};
var result:CacheArtifact=uninit;
{before}
{{
    if !cache_artifact((*run).context,{quoted(cache)},&request,&result) {{return 1i32;}}
    var actual:CrustSource=uninit;
    if !cache_read((*run).context,result.path,&actual) {{return 2i32;}}
    if actual.size!=(*input).size || cache_memcmp(actual.bytes,(*input).bytes,actual.size)!=0i32 {{return 3i32;}}
    if result.hit {{report("hit");}} else {{report("miss");}}
    return 0i32;
}};
"""
        )
        return root, cache, data, dependency

    @staticmethod
    def clean(cache):
        assert not list(cache.glob(".build-*")), list(cache.iterdir())


def check_artifacts(suite):
    root, cache, data, dependency = suite.fixture("ordinary")
    assert suite.run(root).stdout == b"miss\n"
    assert suite.run(root).stdout == b"hit\n"
    assert (root.parent / "builds").read_bytes() == b"build\n"
    data.write_bytes(b"edited source\n")
    assert suite.run(root).stdout == b"miss\n"
    dependency.write_bytes(b"changed option or tool\n")
    assert suite.run(root).stdout == b"miss\n"
    assert suite.run(root).stdout == b"hit\n"
    assert len(list(cache.iterdir())) == 3
    suite.clean(cache)
    data.unlink()
    result = suite.run(root, expected=1)
    assert b"cannot read source input" in result.stderr
    suite.clean(cache)

    root, cache, _, _ = suite.fixture("corrupt")
    suite.run(root)
    artifact = next(cache.glob("*/artifact"))
    artifact.write_bytes(b"bad executable bytes\n")
    result = suite.run(root, expected=1)
    assert b"cache artifact checksum mismatch" in result.stderr
    assert (root.parent / "builds").read_bytes() == b"build\n"
    suite.clean(cache)
    artifact.unlink()
    assert b"cache tool failed" in suite.run(root, expected=1).stderr
    suite.clean(cache)

    for name, body, message in (
        ("silent", "return false;", b"cache build failed without a diagnostic"),
        ("diagnosed", 'return native_error(ctx,"producer rejected");', b"producer rejected"),
        (
            "partial",
            'cache_save(ctx,path,"partial",7usize); return false;',
            b"without a diagnostic",
        ),
        ("absent", "return true;", b"cache tool failed"),
    ):
        root, cache, _, _ = suite.fixture(name, body)
        assert message in suite.run(root, expected=1).stderr
        assert not list(cache.iterdir())

    root, cache, data, _ = suite.fixture("snapshot")
    # The producer must use the bytes captured before this write.
    source = root.read_text().replace(
        "var result:CacheArtifact=uninit;",
        "var result:CacheArtifact=uninit;\n"
        f'cache_save((*run).context,{quoted(data)},"new bytes",9usize);',
    )
    root.write_text(source)
    suite.run(root)
    assert next(cache.glob("*/artifact")).read_bytes() == b"captured bytes\x00\xff\n"
    assert data.read_bytes() == b"new bytes"
    suite.clean(cache)

    root, cache, _, _ = suite.fixture("parallel")
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: suite.run(root), range(6)))
    assert all(result.stdout in (b"hit\n", b"miss\n") for result in results)
    assert len(list(cache.iterdir())) == 1
    suite.clean(cache)
    assert suite.run(root).stdout == b"hit\n"


def check_producer_snapshot(suite):
    directory = suite.work / "producer-snapshot"
    directory.mkdir()
    cache = directory / "cache"
    cache.mkdir()
    helper = directory / "producer.crs"
    producer = """
fn version()->*u8{return "one";}
fn produce(ctx:*CrustContext, request:*CacheBuild, path:*u8)->bool {
    return cache_save(ctx,path,version(),3usize);
}
"""
    helper.write_text(producer)
    replacement = producer.replace('"one"', '"two"')
    root = directory / "main.crs"
    root.write_text(
        suite.prefix
        + f"""
extern fn report(text:*u8)->i32="puts";
host_source(run,{quoted(helper)});
cache_save((*run).context,{quoted(helper)},{json.dumps(replacement)},{len(replacement.encode())}usize);
var inputs:CacheInputs=make CacheInputs{{items:null(**CrustSource),count:0usize,capacity:0usize}};
cache_input((*run).context,&inputs,{quoted(helper)});
cache_add((*run).context,&inputs,(*run).source);
cache_loaded_sources(run,&inputs);
var request:CacheBuild=make CacheBuild{{inputs:inputs.items,count:inputs.count,build:produce,user:null(*u8)}};
var result:CacheArtifact=uninit;
{{
    if !cache_artifact((*run).context,{quoted(cache)},&request,&result) {{return 1i32;}}
    var actual:CrustSource=uninit;
    if !cache_read((*run).context,result.path,&actual) {{return 2i32;}}
    if actual.size!=3usize || cache_memcmp(actual.bytes,version(),3usize)!=0i32 {{return 3i32;}}
    if result.hit {{report("hit");}} else {{report("miss");}}
    return 0i32;
}};
"""
    )
    assert suite.run(root).stdout == b"miss\n"
    assert suite.run(root).stdout == b"miss\n"
    assert suite.run(root).stdout == b"hit\n"
    assert len(list(cache.iterdir())) == 2
    suite.clean(cache)


def check_loaded_inputs(suite):
    root, cache, _, _ = suite.fixture("loaded-library")
    library = root.parent / "provider.so"
    source = root.read_text()
    source = f"host_link(run,{quoted(library)});\n" + source
    source = source.replace(
        "var result:CacheArtifact=uninit;",
        """
var loaded:CacheInputs=make CacheInputs{items:null(**CrustSource),count:0usize,capacity:0usize};
cache_add((*run).context,&loaded,input);
cache_add((*run).context,&loaded,dependency);
cache_add((*run).context,&loaded,(*run).source);
cache_loaded_inputs((*run).context,&loaded);
request.inputs=loaded.items;
request.count=loaded.count;
var result:CacheArtifact=uninit;
""",
    )
    root.write_text(source)
    for version in (1, 2):
        subprocess.run(
            [
                "cc",
                "-std=c99",
                "-pedantic-errors",
                "-shared",
                "-fPIC",
                "-x",
                "c",
                "-",
                "-o",
                library,
            ],
            input=f"int provider(void){{return {version};}}\n".encode(),
            check=True,
        )
        assert suite.run(root).stdout == b"miss\n"
        assert suite.run(root).stdout == b"hit\n"
    assert len(list(cache.iterdir())) == 2
    suite.clean(cache)


def check_allocations(suite):
    root, cache, _, _ = suite.fixture(
        "allocation",
        "if !cache_save(ctx,path,(*input).bytes,(*input).size) {return false;} "
        "return crust_try_alloc(ctx,1048576usize,8usize)!=null(*u8);",
    )
    source = root.read_text().split("var result:CacheArtifact=uninit;", 1)[0]
    source += f'host_source(run,{quoted(ROOT / "tests/cache_alloc.crs")});\n'
    for fail_at in range(1, 100):
        shutil.rmtree(cache)
        cache.mkdir()
        root.write_text(
            source + f"return cache_allocation(&request,{quoted(cache)},{fail_at}usize);\n"
        )
        result = subprocess.run(
            [str(suite.build / "crust"), str(root)], capture_output=True, timeout=60
        )
        suite.checks += 1
        assert result.returncode in (0, 42), result
        suite.clean(cache)
        if result.returncode == 42:
            return
    raise AssertionError("allocation sweep did not reach successful publication")


def check_backend(suite):
    package = suite.work / "package with spaces"
    for part in ("api", "stages", "examples/cached-backend"):
        shutil.copytree(ROOT / part, package / part)
    output = package / "build"
    output.mkdir()
    root = package / "examples/cached-backend/main.crs"
    # State and callback checks in the tutorial execute on both calls.
    suite.run(root, cwd="/")
    cache = output / "backend-cache"
    first = next(cache.glob("*/artifact"))
    stamp = first.stat().st_mtime_ns
    suite.run(root, cwd="/")
    assert list(cache.glob("*/artifact")) == [first]
    assert first.stat().st_mtime_ns == stamp
    result = subprocess.run([output / "cached-hello"], capture_output=True, check=True)
    assert result.stdout == b"Hello from a bootstrapped native stage!\n"
    dynamic = subprocess.run(["readelf", "-d", first], capture_output=True, check=True).stdout
    needed = [line for line in dynamic.splitlines() if b"(NEEDED)" in line]
    assert len(needed) == 1 and b"[libc.so.6]" in needed[0], dynamic
    suite.run(
        root,
        arguments=["--emit-c", "-o", output / "paired.c", "--symbols", output / "paired.rsp"],
        cwd="/",
    )
    assert (output / "paired.c").exists() and (output / "paired.rsp").exists()
    source = package / "stages/asm/emit.crs"
    source.write_text(source.read_text() + "\n// Source edit invalidates the prepared backend.\n")
    suite.run(root, arguments=["--check"], cwd="/")
    assert len(list(cache.glob("*/artifact"))) == 2
    suite.clean(cache)
    assert not [p for p in output.glob("crust-*") if p.is_dir()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    args = parser.parse_args()
    suite = Suite(args.build)
    check_artifacts(suite)
    check_producer_snapshot(suite)
    check_loaded_inputs(suite)
    check_allocations(suite)
    check_backend(suite)
    print(f"artifact cache: {suite.checks} process checks passed")


if __name__ == "__main__":
    main()
