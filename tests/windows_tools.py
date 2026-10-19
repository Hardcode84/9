#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise native Windows formatter and jobs under the 512 MiB job limit."""

import argparse
import os
from pathlib import Path

from windows import ROOT, literal, native_path
from windows_bootstrap import Suite


class ToolsSuite(Suite):
    def editor(self):
        runtime = os.environ.get("CRUST_JS_RUNTIME")
        if runtime:
            result = self.run(
                Path(runtime),
                native_path(ROOT / "tests/windows_editor.cjs"),
                native_path(self.seed),
                native_path(ROOT),
            )
            print(result.stdout.decode().strip())
            return True
        else:
            print(
                "Windows editor launch skipped: set CRUST_JS_RUNTIME to a native JavaScript runtime"
            )
            return False

    def formatter(self):
        cache = self.fresh_directory("formatter cache")
        target = self.work / "format input 雪.crs"
        original = b"fn answer()->i32{return 42i32;}\n"
        target.write_bytes(original)
        body = self.setup() + self.session(cache)
        body += """
var library:*u8=stage_library(stages,"stages/format/tool.crs");
if library==null(*u8){return 1i32;};
extern fn format_main(argc:i32,argv:**u8)->i32="crust_tool_main";
if !host_bind(run,crust_run_open(run,library),"format_main"){return 1i32;};
"""
        body += (
            'var args:[*u8;3]=make [*u8;3]{"format","--write",'
            + literal(native_path(target))
            + "};return format_main(3i32,&args[0usize]);"
        )
        self.root("format write", body)
        formatted = target.read_bytes()
        assert formatted != original and b"42i32" in formatted
        self.root("format idempotent", body)
        assert target.read_bytes() == formatted
        alias = self.work / "format alias.crs"
        if alias.exists():
            alias.unlink()
        # Native Windows hard links must also be rejected through WSL-mounted files.
        alias.hardlink_to(target)
        failure = self.root("format hardlink", body, expected=2)
        assert b"one link" in failure.stderr
        alias.unlink()
        target.write_bytes(original)

        def readonly(flag):
            command = 'extern fn seed_readonly(path:*u8,enabled:i32)->i32="seed_readonly";'
            command += f'if !host_bind(run,crust_run_open(run,{literal(native_path(self.build / "windows_library.dll"))}),"seed_readonly"){{return 1i32;}};'
            command += (
                f'return seed_readonly({literal(native_path(target))},{int(flag == "+R")}i32);'
            )
            self.root("format attributes", command)

        readonly("+R")
        try:
            self.root("format readonly", body, expected=2)
            assert target.read_bytes() == original
        finally:
            readonly("-R")
        target.write_bytes(b"fn broken( {\n")
        self.root("format invalid", body, expected=2)
        assert target.read_bytes() == b"fn broken( {\n"
        assert not list(self.work.glob(".crust-format-*"))
        custom = self.work / "custom grammar.crs"
        custom.write_bytes((ROOT / "examples/reader-switch/main.crs").read_bytes())
        for mode in ("--write", "--check"):
            self.run(
                self.seed,
                native_path(ROOT / "examples/format/reader-switch.crs"),
                mode,
                "--",
                native_path(custom),
            )

    def parallel(self):
        cache = self.fresh_directory("parallel cache")
        source = self.work / "jobs.crs"
        source.write_text(
            """// SPDX-License-Identifier: Apache-2.0
fn increment(data:*u8)->unit { var value:*usize=data as *usize; *value=*value+1usize; }
fn reject_all(user:*u8,size:usize)->*u8 {return null(*u8);}
fn release_none(user:*u8,bytes:*u8)->unit {trap;}
fn exercise(context:*CrustContext)->i32 {
    var values:[usize;9]=make [usize;9]{0usize,0usize,0usize,0usize,0usize,0usize,0usize,0usize,0usize};
    var jobs:[ParallelJob;9]=uninit;
    var index:usize=0usize;
    while index<9usize { jobs[index]=make ParallelJob{execute:increment,user:&values[index] as *u8}; index=index+1usize; }
    if !parallel_run(context,&jobs[0usize],9usize,3usize) || !parallel_run(context,&jobs[0usize],9usize,1usize) || !parallel_run(context,&jobs[0usize],0usize,4usize){return 1i32;}
    index=0usize;
    while index<9usize { if values[index]!=2usize {return 2i32;} index=index+1usize; }
    var rejected:CrustContext=uninit;
    var allocator:CrustAllocator=make CrustAllocator{allocate:reject_all,release:release_none,user:null(*u8)};
    crust_context_init(&rejected,&allocator);
    var failed:bool=parallel_run(&rejected,&jobs[0usize],9usize,3usize);
    crust_context_destroy(&rejected);
    if failed{return 4i32;}
    if parallel_run(context,&jobs[0usize],9usize,0usize){return 3i32;}
    return 0i32;
}
""",
            encoding="utf-8",
        )
        package = self.work / "jobs-package.crs"
        package.write_text(
            "// SPDX-License-Identifier: Apache-2.0\n"
            + f'stage_include(stage,{literal(native_path(ROOT / "stages/parallel/sources.crs"))});'
            + 'stage_source(stage,"jobs.crs");stage_export(stage,"exercise");\n',
            encoding="utf-8",
        )
        body = self.setup() + self.session(cache)
        body += f"var library:*u8=stage_library(stages,{literal(native_path(package))});"
        body += """if library==null(*u8){return 1i32;};
extern fn exercise(context:*CrustContext)->i32="exercise";
if !host_bind(run,crust_run_open(run,library),"exercise"){return 1i32;};
var context:CrustContext=uninit;crust_context_init(&context,null(*CrustAllocator));
var result:i32=exercise(&context);crust_context_destroy(&context);return result;
"""
        self.root("parallel jobs", body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build/windows"))
    parser.add_argument("--case", choices=("formatter", "parallel", "editor"))
    args = parser.parse_args()
    suite = ToolsSuite(args.build)
    for case in (args.case,) if args.case else ("formatter", "parallel", "editor"):
        if getattr(suite, case)() is not False:
            print(f"Windows tools: {case} passed")


if __name__ == "__main__":
    main()
