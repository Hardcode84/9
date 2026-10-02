#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check cold native bootstrap, source order, publication, and cleanup."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from source_order import ROOT, string


class NativeSuite:
    def __init__(self, build):
        self.build = build.resolve()
        self.work = self.build / "native-tests"
        self.work.mkdir(exist_ok=True)
        self.example = (ROOT / "examples/native/main.crs").read_text()
        self.source = self.example.replace('"../../', f'"{ROOT}/').replace(
            f'"{ROOT}/build"', string(self.work)
        )
        self.checks = 0

    def command(self, command, expected=0, **options):
        result = subprocess.run(
            list(map(str, command)),
            cwd=options.pop("cwd", self.work),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            **options,
        )
        self.checks += 1
        assert result.returncode == expected, (command, result)
        return result

    def run(self, name, source=None, expected=0, diagnostic=None, arguments=(), **options):
        root = self.work / (name + ".crs")
        root.write_text(self.source if source is None else source)
        result = self.command([self.build / "crust", root, *arguments], expected, **options)
        if diagnostic:
            assert diagnostic in result.stderr, result
        else:
            assert not result.stderr, result
        assert not list(self.work.glob("crust-*")), "native temporary images leaked"
        return result


def check_output(suite):
    output = suite.work / "hello"
    suite.run("cold", arguments=["-o", output])
    assert suite.command([output]).stdout == b"Hello from a bootstrapped native stage!\n"
    dependencies = suite.command(["readelf", "-d", output]).stdout
    assert b"unit.so" not in dependencies and b"libffi" not in dependencies, dependencies

    # Use the unchanged tutorial in another checkout path and working directory.
    copied = suite.work / "copy with spaces"
    for directory in ("api", "stages", "examples/native"):
        shutil.copytree(ROOT / directory, copied / directory, dirs_exist_ok=True)
    (copied / "build").mkdir(exist_ok=True)
    result = suite.command([suite.build / "crust", copied / "examples/native/main.crs"], cwd="/")
    assert not result.stderr, result
    assert suite.command([copied / "build/native-hello"]).stdout.startswith(b"Hello from")
    assert not list((copied / "build").glob("crust-*"))


def check_boundaries(suite):
    prefix, _ = suite.source.split("// This complete function", 1)
    # Linux Dl_info preserves the foreign ABI's member order.
    probe = """
record ImageInfo { path:*u8; base:*u8; name:*u8; address:*u8; }
extern fn image_info(address:*u8, info:*ImageInfo)->i32="dladdr";
"""
    source = suite.source.replace("record BuildState", probe + "record BuildState")
    source = (
        source.replace(
            "(*state).first = select_c;",
            """
    var self:fn(*CrustRun,*u8)->i32=select_c;
    var address:*u8=null(*u8);
    native_memcpy(&address as *u8,&self as *u8,sizeof(*u8));
    var info:ImageInfo=uninit;
    if image_info(address,&info)==0i32 || info.name==null(*u8) {return 84i32;}
    (*state).first = select_c;
""",
        )
        .replace(
            "var state: *BuildState = user as *BuildState;\n    if (*state).callback",
            "var state: *BuildState = user as *BuildState;\n"
            "    if *(*state).counter == 3usize { return 37i32; }\n    if (*state).callback",
            1,
        )
        .replace(
            "return status;\n};",
            "if status == 0i32 && state.first(run, &state as *u8) != 37i32 {return 85i32;}\n"
            "    return status;\n};",
            1,
        )
    )
    source = source.replace(
        "fn build_target(root: *CrustRun, user: *u8) -> i32 {",
        """fn build_target(root: *CrustRun, user: *u8) -> i32 {
    var self:fn(*CrustRun,*u8)->i32=build_target;
    var address:*u8=null(*u8);
    native_memcpy(&address as *u8,&self as *u8,sizeof(*u8));
    var info:ImageInfo=uninit;
    if image_info(address,&info)==0i32 || info.name==null(*u8) {return 86i32;}
""",
    )
    suite.run("native-address-and-post-cleanup-call", source, arguments=["--check"])

    cases = [
        ("statement", "return 0i32;", b"expects a complete function action"),
        ("signature", "fn bad()->i32{return 0i32;}", b"must be a defined fn(*CrustRun, *u8)"),
        (
            "signature-record",
            "fn bad(root:*NativeSession,user:*u8)->i32{return 0i32;}",
            b"must be a defined fn(*CrustRun, *u8)",
        ),
        (
            "signature-user",
            "fn bad(root:*CrustRun,user:*u32)->i32{return 0i32;}",
            b"must be a defined fn(*CrustRun, *u8)",
        ),
        (
            "bad-body",
            "fn bad(root:*CrustRun,user:*u8)->i32{return absent;}",
            b"unknown name 'absent'",
        ),
        (
            "local-conflict",
            "fn counter(root:*CrustRun,user:*u8)->i32{return 0i32;}",
            b"conflicts with a root local",
        ),
        ("syntax", "fn broken(", b"expected"),
        (
            "interpreted-callee",
            "fn bad(root:*CrustRun,user:*u8)->i32{var n:usize=0usize;increment(&n);return 0i32;}",
            b"link name",
        ),
        (
            "invalid-status",
            "fn bad(root:*CrustRun,user:*u8)->i32{return 256i32;}",
            b"between zero and 255",
        ),
    ]
    for name, tail, diagnostic in cases:
        suite.run(name, prefix + tail, expected=1, diagnostic=diagnostic)

    success_prefix = prefix.replace("counter != 3usize", "counter != 1usize")
    suite.run("empty", success_prefix)
    suite.run(
        "stop-with-unread-syntax",
        prefix + "fn stop(root:*CrustRun,user:*u8)->i32{return 23i32;}\n@ unread bytes",
        expected=23,
    )
    result = suite.run(
        "later-parse-failure",
        prefix
        + 'fn first(root:*CrustRun,user:*u8)->i32{crust0_host_write_stream(1u32,"once\\n",5usize);return 0i32;}\n@',
        expected=1,
        diagnostic=b"invalid source byte",
    )
    assert result.stdout == b"once\n", result

    switch = """
    (*root).read = (*state).reader;
    (*root).execute = (*state).executor;
    (*root).user = user;
    return 0i32;
}
@ these bytes have no seed grammar
"""
    source = suite.source.split("    var session: *NativeSession =", 1)[0] + switch
    source = source.replace(
        "record BuildState {",
        """
fn read_tail(root:*CrustRun,user:*u8,action:**u8)->bool {
    if (*(*root).source).bytes[(*root).cursor+1usize]!=64u8 {trap;}
    (*root).cursor=(*(*root).source).size;
    *action=user;
    return true;
}
fn execute_tail(root:*CrustRun,user:*u8,action:*u8)->bool {
    var state:*BuildState=action as *BuildState;
    (*state).callback((*state).counter);
    (*root).returned=true;
    return true;
}
record BuildState {
    reader:fn(*CrustRun,*u8,**u8)->bool;
    executor:fn(*CrustRun,*u8,*u8)->bool;
""",
    )
    # host_source gives these mutually dependent declarations one checked unit.
    start = source.index("fn read_tail")
    end = source.index("var counter:")
    declarations = suite.work / "switch-declarations.crs"
    declarations.write_text(source[start:end])
    source = source[:start] + f"host_source(run,{string(declarations)});\n" + source[end:]
    source = source.replace(
        "counter: &counter, callback:",
        "reader:read_tail, executor:execute_tail, counter: &counter, callback:",
    )
    suite.run("reader-change", source)


def check_failures(suite):
    suite.run(
        "missing-source",
        suite.source.replace('"' + str(ROOT) + '/stages/c/model.crs"', '"/no-such-crust-input"'),
        expected=1,
        diagnostic=b"cannot read source input",
    )
    suite.run(
        "missing-export",
        suite.source.replace('"native_start", "native_c_image"', '"absent", "native_c_image"'),
        expected=1,
        diagnostic=b"export must name a defined function",
    )
    suite.run(
        "missing-temp-directory",
        suite.source.replace(
            "temporary: host_path(run, " + string(suite.work) + ")",
            'temporary:"/no-such-native-directory"',
        ),
        expected=1,
        diagnostic=b"cannot create native temporary directory",
    )
    env = {**os.environ, "PATH": "/no-such-native-tools"}
    suite.run("missing-assembler", expected=1, diagnostic=b"native tool failed: as", env=env)
    tools = suite.work / "tools"
    tools.mkdir(exist_ok=True)
    assembler = tools / "as"
    if not assembler.exists():
        assembler.symlink_to(shutil.which("as"))
    env["PATH"] = str(tools)
    suite.run("missing-linker", expected=1, diagnostic=b"native tool failed: gcc", env=env)
    compiler = tools / "gcc"
    compiler.write_text(
        "#!/bin/sh\nfor argument; do\n"
        '  if [ "$argument" = "-std=c99" ]; then exit 42; fi\ndone\n'
        f'exec {shutil.which("gcc")} "$@"\n'
    )
    compiler.chmod(0o755)
    env["PATH"] = str(tools) + os.pathsep + os.environ["PATH"]
    suite.run("failed-c-compiler", expected=1, diagnostic=b"gcc failed with status 42", env=env)
    compiler.unlink()
    broken = suite.work / "unresolved.crs"
    broken.write_text(
        (ROOT / "stages/native/c.crs").read_text()
        + '\nextern fn unavailable()->unit="crust_native_unavailable";\n'
        + "fn references_unavailable()->unit{unavailable();}\n"
    )
    suite.run(
        "failed-loader",
        suite.source.replace(string(ROOT / "stages/native/c.crs"), string(broken)),
        expected=1,
        diagnostic=b"undefined symbol: crust_native_unavailable",
    )
    suite.run(
        "null-compiler",
        suite.source.replace(
            "(*session).compile = native_c_image;",
            "(*session).compile = null(fn(*CrustContext,*NativeSession,*NativeImage)->bool);",
        ),
        expected=1,
        diagnostic=b"native compiler must be callable",
    )
    suite.run(
        "target-error",
        suite.source.replace('puts("Hello', 'absent("Hello'),
        expected=1,
        diagnostic=b"unknown name 'absent'",
    )


def check_allocations(suite):
    source = suite.work / "allocation-input.crs"
    source.write_text("fn answer()->i32{return 42i32;}\n")
    prefix = suite.source.split("record BuildState", 1)[0]
    suite.run(
        "allocation-failure-sweep",
        prefix
        + f'host_source(run,{string(ROOT / "tests/native_alloc.crs")});\n'
        + f"return allocation_sweep(run,{string(source)},{string(suite.work)});\n",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    args = parser.parse_args()
    suite = NativeSuite(args.build)
    check_output(suite)
    check_boundaries(suite)
    check_failures(suite)
    check_allocations(suite)
    print(f"native bootstrap: {suite.checks} process checks passed")


if __name__ == "__main__":
    main()
