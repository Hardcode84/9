# SPDX-License-Identifier: Apache-2.0

"""Validate and execute the external Vulkan compute stage."""

import argparse
import os
import shlex
import struct
import subprocess
from pathlib import Path

from prepare import compile_package
from vulkan.abi import check_abi

ROOT = Path(__file__).resolve().parent.parent


def run(command, *, expected=0, env=None):
    result = subprocess.run(
        [str(value) for value in command],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != expected:
        raise AssertionError(f"{command}\n{result.stdout.decode()}\n{result.stderr.decode()}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, default=Path("build"))
    parser.add_argument("--llvm", type=Path, required=True)
    parser.add_argument("--spirv-tools", type=Path, required=True)
    parser.add_argument("--vulkan-include", type=Path)
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    build = args.build.resolve()
    work = build / "shader-tests"
    work.mkdir(parents=True, exist_ok=True)
    llvm = args.llvm.resolve()
    tools = args.spirv_tools.resolve()
    compiler = build / "crust"
    source = work / "program.crs"
    output = work / "program.spv"
    root = ROOT / "examples/shader/main.crs"
    command = [compiler, root, llvm, tools / "spirv-val", output, source]
    native = work / "dispatch"
    flags = [
        "-std=c99",
        "-pedantic-errors",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wstrict-prototypes",
        "-Wmissing-prototypes",
        "-Wshadow",
        "-Wvla",
    ]
    if args.vulkan_include:
        flags += [f"-I{args.vulkan_include.resolve()}"]
    check_abi(run, build, work, shlex.split(args.cc), flags)
    compile_package(
        build,
        ROOT / "tests/vulkan/package.crs",
        native,
        ["-O2", "-g"],
        ["-Wl,-l:libvulkan.so.1"],
    )
    environment = os.environ.copy()
    run(
        [build / "shader-alloc", llvm, tools / "spirv-val", work / "allocation.spv"],
        env=environment,
    )
    cases = {
        "exchange": (
            (ROOT / "examples/shader/program.crs").read_text(),
            [4, 3, 6, 5],
            [0, 0, 0, 0],
        ),
        "failed-lane": (
            """
fn compute()->unit {
 var i:u32=shader_global_x(); var lane:u32=shader_local_x();
 shader_require(lane!=2u32);
 scratch_store(lane,values_load(i)+2f32);
 shader_barrier(); values_store(i,scratch_load(lane^1u32));
}
""",
            [4, 3, 3, 0],
            [0, 0, 1, 0],
        ),
        "bounds": (
            """
fn compute()->unit {
 var i:u32=shader_global_x();
 var x:f32=values_load(i+1u32);
 shader_barrier(); values_store(i,x);
}
""",
            [2, 3, 4, 4],
            [0, 0, 0, 1],
        ),
        "integer-failure": (
            """
fn divide(a:i32,b:i32)->i32{return a/b;}
fn compute()->unit {
 var i:u32=shader_global_x(); var x:i32=divide(6i32,i as i32-2i32);
 shader_barrier(); values_store(i,x as f32);
}
""",
            [-3, -6, 3, 6],
            [0, 0, 1, 0],
        ),
        "failed-loop": (
            """
fn compute()->unit {
 var i:u32=shader_global_x();
 while true {shader_require(false);}
 shader_barrier(); values_store(i,99f32);
}
""",
            [1, 2, 3, 4],
            [1, 1, 1, 1],
        ),
        "image": (
            """
fn compute()->unit {
 var i:u32=shader_global_x(); pixels_store(i,0u32,values_load(i)+2f32);
 shader_barrier(); values_store(i,pixels_load(i^1u32,0u32));
}
""",
            [4, 3, 6, 5],
            [0, 0, 0, 0],
        ),
        "image-bounds": (
            """
fn compute()->unit {
 var i:u32=shader_global_x(); pixels_store(i,0u32,values_load(i));
 shader_barrier(); var x:f32=pixels_load(i,1u32);
 shader_barrier(); values_store(i,x);
}
""",
            [1, 2, 3, 4],
            [1, 1, 1, 1],
        ),
        "sqrt": (
            """
fn compute()->unit {
 var i:u32=shader_global_x(); var value:f32=(i*i) as f32;
 if i==1u32 {value=0.25f32;}
 values_store(i,shader_sqrt(value));
}
""",
            [0, 0.5, 2, 3],
            [0, 0, 0, 0],
        ),
        "float-casts": (
            """
fn compute()->unit {
 var i:u32=shader_global_x(); var value:f32=values_load(i);
 var negative:bool=-(value+1f32)<0f32;
 if negative && ((0f32/0f32) as i32)==0i32 {values_store(i,((value*2f32) as u32) as f32);}
}
""",
            [2, 4, 6, 8],
            [0, 0, 0, 0],
        ),
        "helper-exits": (
            """
fn choose(i:u32)->f32 {
 if i==0u32{return 11f32;}
 if i==1u32{return 13f32;}
 var j:u32=0u32;
 while j<4u32 {
  if j==i{return (j+20u32) as f32;}
  j=j+1u32;
 }
 return 99f32;
}
fn compute()->unit {var i:u32=shader_global_x();values_store(i,choose(i));}
""",
            [11, 13, 22, 23],
            [0, 0, 0, 0],
        ),
        "sticky-status": (
            """
fn compute()->unit {
 var i:u32=shader_global_x();
 if values_load(i)>0f32 {values_store(i,0f32);shader_require(i!=0u32);}
}
""",
            [0, 0, 0, 0],
            [1, 0, 0, 0],
        ),
        "zero-shared": (
            """
fn compute()->unit {
 var i:u32=shader_global_x(); values_store(i,scratch_load(i));
}
""",
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ),
    }
    for name, (program, values, status) in cases.items():
        source.write_text(program)
        run(command)
        assembly = run([tools / "spirv-dis", output]).stdout
        assert b"OpEntryPoint GLCompute" in assembly
        assert b"OpCapability Kernel" not in assembly
        assert b"OpTypeInt 64" not in assembly
        expected = work / f"{name}.expected"
        expected.write_bytes(struct.pack("=4f4I", *values, *status))
        run(
            [native, output, expected, *(["--twice"] if name == "sticky-status" else [])],
            env=environment,
        )
    fault_library = work / "faults.so"
    compile_package(
        build,
        ROOT / "tests/vulkan/faults-package.crs",
        fault_library,
        ["-O2", "-fPIC"],
        ["-shared", "-Wl,-l:libvulkan.so.1"],
    )
    fixture = work / "zero-shared.expected"
    for fault, status, diagnostic in (
        ("incomplete", 0, "injected VK_INCOMPLETE"),
        ("empty", 1, "no Vulkan physical device"),
        ("enumerate-error", 1, "vkEnumeratePhysicalDevices"),
        ("pool", 1, "vkCreateDescriptorPool"),
    ):
        injected = environment | {
            "LD_PRELOAD": str(fault_library),
            "CRUST_VULKAN_TEST_FAULT": fault,
        }
        result = run([native, output, fixture], expected=status, env=injected)
        assert diagnostic.encode() in result.stdout, fault
    malformed = work / "malformed.bin"
    for data, diagnostic in ((b"bad", "aligned input"), (bytes(20), "SPIR-V header")):
        malformed.write_bytes(data)
        result = run([native, malformed, fixture], expected=2, env=environment)
        assert diagnostic.encode() in result.stdout
    result = run([native, output, malformed], expected=2, env=environment)
    assert b"expected data must contain" in result.stdout
    rejected = {
        "divergent barrier": (
            "fn compute()->unit{if shader_local_x()==0u32{shader_barrier();}}",
            "top-level",
        ),
        "helper barrier": (
            "fn helper()->unit{shader_barrier();}fn compute()->unit{helper();}",
            "top-level",
        ),
        "early return": (
            "fn compute()->unit{if shader_local_x()==0u32{return;}shader_barrier();}",
            "final top-level",
        ),
        "trap": ("fn compute()->unit{trap;}", "shader_require"),
        "pointer": ("fn compute()->unit{var p:*u32=null(*u32);}", "shader values"),
        "usize": ("fn compute()->unit{var i:usize=1usize;}", "shader values"),
        "uninitialized": ("fn compute()->unit{var f:f32=uninit;}", "initializer"),
        "recursion": (
            "fn recurse()->unit{recurse();}fn compute()->unit{recurse();}",
            "cannot recurse",
        ),
        "entry call": ("fn compute()->unit{}fn helper()->unit{compute();}", "cannot be called"),
        "foreign": ('extern fn other()->unit="other";fn compute()->unit{other();}', "foreign"),
    }
    previous = output.read_bytes()
    for name, (program, diagnostic) in rejected.items():
        source.write_text(program)
        result = run(command, expected=1)
        assert diagnostic.encode() in result.stdout + result.stderr, (name, result)
        assert output.read_bytes() == previous, name
    source.write_text(cases["exchange"][0])
    run([compiler, root, llvm, "/bin/false", output, source], expected=1)
    assert output.read_bytes() == previous
    failed_tools = work / "failed-tools" / "bin"
    failed_tools.mkdir(parents=True, exist_ok=True)
    normalizer = failed_tools / "opt"
    normalizer.write_text("#!/bin/sh\nexit 1\n")
    normalizer.chmod(0o755)
    run([compiler, root, failed_tools.parent, tools / "spirv-val", output, source], expected=1)
    assert output.read_bytes() == previous
    assert not list(work.glob(".crust-*")), "temporary output leaked"
    print(
        f"Shader: {len(cases)} Vulkan dispatches, 4 injected enumeration/setup cases, "
        f"3 malformed inputs, {len(rejected)} source rejections and failed-tool output preservation passed"
    )


if __name__ == "__main__":
    main()
