#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prove Windows source-built LLVM and ASM packages under bounded native jobs."""

import argparse
import difflib
import hashlib
import os
import re
import struct
from pathlib import Path

from windows import ROOT, literal, native_path
from windows_bootstrap import Suite

PROGRAM = """
fn mixed(a:i8,b:f32,c:u64,d:bool,e:f32,f:i32,g:u8,h:f32)->f32 {
    var flag:f32=0f32;if d{flag=1f32;}
    return a as f32+b+c as f32+flag+e+f as f32+g as f32+h;
}
fn wide(a:u64,b:u64,c:u64,d:u64,e:u64,f:u64,g:u64,h:u64)->u64 {
    return a+b+c+d+e+f+g+h;
}
fn relay(callback:fn(i8,f32,u64,bool,f32,i32,u8,f32)->f32)->f32 {
    return callback(-8i8,0.5f32,16u64,true,1.25f32,-32i32,255u8,2.5f32);
}
fn unwind(callback:fn()->i32)->i32 {
    var storage:[u8;16384]=uninit;storage[0usize]=19u8;storage[16383usize]=23u8;
    var status:i32=callback();
    return status+storage[0usize] as i32+storage[16383usize] as i32-42i32;
}
fn large()->u64 {var bytes:[u8;16384]=uninit; bytes[0usize]=19u8;bytes[16383usize]=23u8;return bytes[0usize] as u64+bytes[16383usize] as u64;}
fn answer()->i32 {
    if mixed(-8i8,0.5f32,16u64,true,1.25f32,-32i32,255u8,2.5f32)!=236.25f32 {return 1i32;}
    if wide(1u64,2u64,3u64,4u64,5u64,6u64,7u64,8u64)!=36u64 || large()!=42u64{return 2i32;}
    var bits:u32=2143289344u32;var nan:f32=*(&bits as *f32);
    if nan==nan || !(nan!=nan) || nan<0f32 || nan>=0f32 || nan as i32!=0i32{return 3i32;}
    if 1e30f32 as i8!=127i8 || -1e30f32 as i8!= -128i8 || -1f32 as u64!=0u64 || 1e30f32 as u64!=~0u64{return 4i32;}
    if 9223372036854775808f32 as u64!=9223372036854775808u64 || (~0u64 as f32)!=18446744073709551616f32{return 5i32;}
    return 42i32;
}
"""


class BackendSuite(Suite):
    def cache_inputs(self, path):
        data = path.read_bytes()
        offset = data.index(b"\n") + 1
        inputs = []
        while offset < len(data):
            size = struct.unpack_from("<Q", data, offset)[0]
            offset += 8
            name = data[offset : offset + size].decode("utf-8")
            offset += size
            size = struct.unpack_from("<Q", data, offset)[0]
            offset += 8
            digest = hashlib.sha256(data[offset : offset + size]).hexdigest()
            offset += size
            inputs.append(f"{name}: {size} bytes, {digest}\n")
        return inputs

    def trace_inputs(self, backend):
        body = ""
        for name, field in (("host", "inputs"), ("gcc", "toolchain.inputs")):
            path = self.work / f"{backend}-{name}.inputs"
            body += f"""
var {name}_trace:CacheBuild=make CacheBuild{{inputs:stages -> {field}.items,count:stages -> {field}.count,build:null(fn(*CrustContext,*CacheBuild,*u8)->bool),user:null(*u8)}};
if !cache_manifest(run -> context,&{name}_trace,{literal(native_path(path))}){{return 1i32;}};
"""
        return body

    def asm_api(self):
        cache = self.fresh_directory("asm API cache")
        body = self.setup() + self.session(cache)
        body += 'var library:*u8=stage_library(stages,"stages/asm/package.crs");'
        body += "if library==null(*u8){return 1i32;};return (crust_run_open(run,library)==null(*u8)) as i32;"
        self.root("asm API", body)

    def packages(self, backend):
        cache = self.fresh_directory(backend + " package cache")
        source = self.work / (backend + " program.crs")
        signature = "fn(fn(f32)->f32,i32," + ",".join(["f32"] * 9) + ")->f32"
        floats = (ROOT / "tests/float.crs").read_text(encoding="utf-8")
        declaration = re.search(r"extern fn native_float\([\s\S]+?;", floats).group()
        floats = floats.replace(declaration, "")
        floats = floats.replace("bits(", "float_bits(")
        floats = floats.replace("fn arithmetic()", f"fn arithmetic(native_float:{signature})")
        floats = floats.replace(
            "fn main(argc: i32, argv: **u8)", f"fn float_test(native_float:{signature})"
        )
        floats = floats.replace("!arithmetic()", "!arithmetic(native_float)")
        source.write_text(
            "// SPDX-License-Identifier: Apache-2.0\n" + PROGRAM + floats, encoding="utf-8"
        )
        package = self.work / (backend + " program-package.crs")
        package.write_text(
            "// SPDX-License-Identifier: Apache-2.0\n"
            + f'stage_api(stage,"crust0.crs");stage_source(stage,{literal(source.name)});'
            + f"stage_compiler(stage,{literal(native_path(ROOT / ('stages/' + backend + '/compiler-package.crs')))},\"{backend}_stage_compile\");"
            + f'stage_toolchain(stage,"{backend}_stage_toolchain");stage_export(stage,"answer");stage_export(stage,"mixed");stage_export(stage,"relay");stage_export(stage,"unwind");stage_export(stage,"float_test");\n',
            encoding="utf-8",
        )
        body = self.setup() + self.session(cache)
        body += self.trace_inputs(backend)
        body += f"var library:*u8=stage_library(stages,{literal(native_path(package))});"
        body += """if library==null(*u8){return 1i32;};
extern fn answer()->i32="answer";
extern fn mixed(a:i8,b:f32,c:u64,d:bool,e:f32,f:i32,g:u8,h:f32)->f32="mixed";
extern fn relay(callback:fn(i8,f32,u64,bool,f32,i32,u8,f32)->f32)->f32="relay";
extern fn seed_mixed(a:i8,b:f32,c:u64,d:bool,e:f32,f:i32,g:u8,h:f32)->f32="seed_mixed";
extern fn seed_callback(callback:fn(i8,f32,u64,bool,f32,i32,u8,f32)->f32)->f32="seed_callback";
extern fn unwind(callback:fn()->i32)->i32="unwind";
extern fn seed_unwind()->i32="seed_unwind";
var handle:*u8=crust_run_open(run,library);
if !host_bind(run,handle,"answer") || !host_bind(run,handle,"mixed") || !host_bind(run,handle,"relay") || !host_bind(run,handle,"unwind"){return 1i32;};
if mixed(-8i8,0.5f32,16u64,true,1.25f32,-32i32,255u8,2.5f32)!=236.25f32{return 10i32;};
"""
        body += f'extern fn float_test(callback:{signature})->i32="float_test";'
        body += declaration
        body += f"var foreign:*u8=crust_run_open(run,{literal(native_path(self.build / 'windows_library.dll'))});"
        body += 'if !host_bind(run,handle,"float_test") || !host_bind(run,foreign,"native_float"){return 1i32;};if float_test(native_float)!=0i32{return 13i32;};'
        body += """if !host_bind(run,foreign,"seed_mixed") || !host_bind(run,foreign,"seed_callback") || !host_bind(run,foreign,"seed_unwind"){return 1i32;};
if seed_callback(mixed)!=236.25f32 || relay(seed_mixed)!=236.25f32{return 11i32;};
if unwind(seed_unwind)!=0i32{return 12i32;};return answer();"""
        self.root(backend + " packages", body, expected=42)
        artifacts = {path: path.stat().st_mtime_ns for path in cache.glob("*/artifact.dll")}
        traces = [self.work / f"{backend}-{name}.inputs" for name in ("host", "gcc")]
        before = {path: self.cache_inputs(path) for path in traces}
        self.root(backend + " reuse", body, expected=42)
        current = {path: path.stat().st_mtime_ns for path in cache.glob("*/artifact.dll")}
        if artifacts != current:
            details = "".join(
                line
                for path in traces
                for line in difflib.unified_diff(
                    before[path],
                    self.cache_inputs(path),
                    fromfile=f"first/{path.name}",
                    tofile=f"reuse/{path.name}",
                )
            )
            raise AssertionError(
                f"{backend} cache reuse changed artifacts:\n"
                f"added: {sorted(str(path) for path in current.keys() - artifacts.keys())}\n"
                f"removed: {sorted(str(path) for path in artifacts.keys() - current.keys())}\n"
                f"modified: {sorted(str(path) for path in artifacts.keys() & current.keys() if artifacts[path] != current[path])}\n"
                f"Host and GCC input differences:\n{details or '(none)'}"
            )
        print(backend + " native ABI, large frame, floats, and reuse passed", flush=True)
        compiler = ROOT / f"stages/{backend}/compiler-package.crs"
        successor = self.work / f"{backend} successor-package.crs"
        successor.write_text(
            "// SPDX-License-Identifier: Apache-2.0\n"
            + f"stage_include(stage,{literal(native_path(compiler))});"
            + f'stage_compiler(stage,{literal(native_path(compiler))},"{backend}_stage_compile");'
            + f'stage_toolchain(stage,"{backend}_stage_toolchain");\n',
            encoding="utf-8",
        )
        package.write_text(
            package.read_text(encoding="utf-8").replace(
                literal(native_path(compiler)), literal(native_path(successor))
            ),
            encoding="utf-8",
        )
        self.root(backend + " successor", body, expected=42)
        print(backend + " successor compiler passed", flush=True)

    def llvm_application(self):
        cache = self.fresh_directory("llvm application cache")
        output = self.work / "llvm hello.exe"
        body = self.setup() + self.session(cache)
        body += """var library:*u8=stage_library(stages,"stages/llvm/compiler-package.crs");
if library==null(*u8){return 1i32;};
extern fn llvm_backend_build(context:*CrustContext,entry:*CrustDecl,options:*BackendOptions)->i32="llvm_backend_build";
if !host_bind(run,crust_run_open(run,library),"llvm_backend_build"){return 1i32;};
"""
        body += f"return application(stages,{literal(native_path(output))},llvm_backend_build);\n"
        body += 'extern fn puts(text:*u8)->i32="puts";fn main(argc:i32,argv:**u8)->i32{return (puts("LLVM Windows")<0i32) as i32;}\n'
        self.root("llvm application", body)
        assert self.run(output).stdout.replace(b"\r\n", b"\n") == b"LLVM Windows\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build/windows"))
    parser.add_argument("--backend", choices=("llvm", "asm"), required=True)
    parser.add_argument("--llvm", type=Path)
    args = parser.parse_args()
    if args.llvm:
        os.environ["CRUST_LLVM_DIRECTORY"] = native_path(args.llvm)
        if os.name != "nt":
            os.environ["WSLENV"] = os.environ.get("WSLENV", "") + ":CRUST_LLVM_DIRECTORY"
    suite = BackendSuite(args.build)
    if args.backend == "asm":
        suite.asm_api()
    suite.packages(args.backend)
    if args.backend == "llvm":
        suite.llvm_application()


if __name__ == "__main__":
    main()
