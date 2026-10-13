# SPDX-License-Identifier: Apache-2.0

"""Validate and execute the external Vulkan compute stage."""

import argparse
import os
import shlex
import struct
import subprocess
from pathlib import Path

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
    run(
        [
            *shlex.split(args.cc),
            *flags,
            "tests/shader_vulkan.c",
            "-Wl,-l:libvulkan.so.1",
            "-o",
            native,
        ]
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
        run([native, output, expected], env=environment)
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
    assert not list(work.glob(".crust-*")), "temporary output leaked"
    print(
        f"Shader: {len(cases)} Vulkan dispatches, {len(rejected)} source rejections and failed-tool output preservation passed"
    )


if __name__ == "__main__":
    main()
