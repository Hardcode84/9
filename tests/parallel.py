#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check native jobs, borrowed state, partial thread startup, and allocation failure."""

import argparse
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRELUDE = """
record Cell { input:*usize; observed:usize; runs:usize; }
fn step(data:*u8)->unit {
    var cell:*Cell=data as *Cell;
    (*cell).observed=*(*cell).input;
    (*cell).runs=(*cell).runs+1usize;
}
fn no_allocate(user:*u8,size:usize)->*u8 {return null(*u8);}
fn no_release(user:*u8,data:*u8)->unit {trap;}
"""
SETUP = """
    var context:CrustContext=uninit;
    crust_context_init(&context,null(*CrustAllocator));
    var value:usize=42usize;
    var cells:[Cell;8]=uninit;
    var jobs:[ParallelJob;8]=uninit;
    var index:usize=0usize;
    while index<8usize {
        cells[index]=make Cell{input:&value,observed:0usize,runs:0usize};
        jobs[index]=make ParallelJob{execute:step,user:&cells[index] as *u8};
        index=index+1usize;
    }
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--cflags", default="-O2 -g")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    build = args.build.resolve()
    work = build / "parallel-tests"
    work.mkdir(exist_ok=True)
    flags = [f"--cflag={value}" for value in shlex.split(args.cflags)]
    ldflags = [f"--ldflag={value}" for value in shlex.split(args.ldflags)]
    checks = 0

    def command(argv):
        nonlocal checks
        result = subprocess.run(list(map(str, argv)), cwd=ROOT, capture_output=True, timeout=120)
        checks += 1
        if result.returncode or result.stdout or result.stderr:
            raise RuntimeError((argv, result))

    wrapper = work / "create.o"
    command(
        [
            *shlex.split(args.cc),
            "-std=c99",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            *shlex.split(args.cflags),
            "-c",
            ROOT / "tests/parallel_create_linux_x64.c",
            "-o",
            wrapper,
        ]
    )

    def case(name, body, wrapped=False):
        source = work / (name + ".crs")
        source.write_text(
            PRELUDE
            + "fn main(argc:i32,argv:**u8)->i32 {\n"
            + SETUP
            + body
            + "\ncrust_context_destroy(&context);return 0i32;}\n"
        )
        binary = work / name
        sources = [ROOT / "api/crust0.crs", ROOT / "stages/parallel/model.crs"]
        if wrapped:
            sources += [ROOT / "stages/parallel/linux_x64.crs"]
            libraries = [str(wrapper), "-Wl,--wrap=pthread_create"]
        else:
            sources += [ROOT / "stages/parallel/api.crs"]
            libraries = [str(build / "crust-parallel-library.so")]
        libraries += [str(build / "libcrust0.a"), str(build / "libcrust0_host.a"), "-pthread"]
        command(
            [
                build / "crust-c",
                *flags,
                *ldflags,
                "-o",
                binary,
                *sources,
                source,
                *[f"--ldflag={value}" for value in libraries],
            ]
        )
        command([binary])

    for workers in (1, 2, 4, 8, 16):
        case(
            f"workers-{workers}",
            f"""
    if !parallel_run(&context,&jobs[0usize],8usize,{workers}usize) {{return 1i32;}}
    index=0usize;
    while index<8usize {{
        if cells[index].observed!=42usize || cells[index].runs!=1usize {{return 2i32;}}
        index=index+1usize;
    }}
""",
        )
    case(
        "empty",
        """
    if !parallel_run(&context,null(*ParallelJob),0usize,8usize) {return 1i32;}
    if parallel_run(&context,&jobs[0usize],8usize,0usize) || context.error_count!=1usize {return 2i32;}
    if cells[0usize].runs!=0usize {return 3i32;}
""",
    )
    case(
        "allocation",
        """
    crust_context_destroy(&context);
    var allocator:CrustAllocator=make CrustAllocator{allocate:no_allocate,release:no_release,user:null(*u8)};
    crust_context_init(&context,&allocator);
    if parallel_run(&context,&jobs[0usize],8usize,4usize) || context.error_count!=1usize {return 1i32;}
    if cells[0usize].runs!=0usize {return 2i32;}
""",
    )
    case(
        "partial-start",
        """
    if parallel_run(&context,&jobs[0usize],8usize,4usize) || context.error_count!=1usize {return 1i32;}
    index=0usize;
    while index<8usize {
        var expected:usize=0usize;
        if index%4usize<2usize {expected=1usize;}
        if cells[index].runs!=expected || cells[index].observed!=42usize*expected {return 2i32;}
        index=index+1usize;
    }
""",
        wrapped=True,
    )
    print(f"parallel checks: {checks}")


if __name__ == "__main__":
    main()
