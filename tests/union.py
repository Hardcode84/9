# SPDX-License-Identifier: Apache-2.0
"""Exercise external tagged unions through C, ASM, and the seed evaluator."""

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RUNTIME = """
record Point { x:u64; y:u32; }
union Item { Point:Point; Array:[u8;9]; Link:*Item; Callback:fn(u64)->u64; End:unit; }
union Outer { Item:Item; End:unit; }
union Flag { On:unit; Off:unit; }
union Tiny { Byte:u8; Word:u16; }
fn callback(value:u64)->u64 { return value+1u64; }
fn destination(value:*Item,count:*u32)->*Item { *count=*count*10u32+1u32;return value; }
fn payload(count:*u32)->u32 { *count=*count*10u32+2u32;return 7u32; }
fn get_item(value:*Item,count:*u32)->*Item { *count=*count+1u32;return value; }
fn verify()->i32 {
    if sizeof(Item)!=24usize || alignof(Item)!=8usize || sizeof(Outer)!=32usize { return 1i32; }
    if sizeof(Flag)!=4usize || sizeof(Tiny)!=8usize { return 2i32; }
    var item:Item=uninit;var trace:u32=0u32;
    construct Item.Point(*destination(&item,&trace),make Point{x:42u64,y:payload(&trace)});
    if trace!=12u32 { return 3i32; }
    trace=0u32;
    match Item(*get_item(&item,&trace)) {
        End { return 4i32; }
        Point(point) {
            construct Item.End(item);
            if point.x!=42u64 || point.y!=7u32 { return 5i32; }
        }
        Link { return 6i32; }
        Callback { return 7i32; }
        Array { return 8i32; }
    }
    if trace!=1u32 { return 9i32; }
    match Item(item) { Point { return 10i32; } Array { return 11i32; } Link { return 12i32; } Callback { return 13i32; } End {} }
    construct Item.Array(item,make [u8;9]{1u8,2u8,3u8,4u8,5u8,6u8,7u8,8u8,9u8});
    var outer:Outer=uninit;construct Outer.Item(outer,item);
    match Outer(outer) {
        Item(inner) {
            match Item(inner) {
                Array(bytes) { if bytes[8usize]!=9u8 { return 14i32; } }
                Point { return 15i32; } Link { return 16i32; } Callback { return 17i32; } End { return 18i32; }
            }
        }
        End { return 19i32; }
    }
    construct Item.Link(item,&item);
    match Item(item) { Link(link) { if link!=&item { return 20i32; } } Point { return 21i32; } Array { return 22i32; } Callback { return 23i32; } End { return 24i32; } }
    construct Item.Callback(item,callback);
    match Item(item) { Callback(call) { if call(41u64)!=42u64 { return 25i32; } } Point { return 26i32; } Array { return 27i32; } Link { return 28i32; } End { return 29i32; } }
    var flag:Flag=uninit;construct Flag.On(flag);
    match Flag(flag) { Off { return 30i32; } On {} }
    var tiny:Tiny=uninit;construct Tiny.Word(tiny,511u16);
    match Tiny(tiny) { Word(word) { if word!=511u16 { return 31i32; } } Byte { return 32i32; } }
    var count:u32=0u32;
    while count<3u32 {
        count=count+1u32;
        match Flag(flag) { On { if count<3u32 { continue; } break; } Off { return 33i32; } }
        return 34i32;
    }
    if count!=3u32 { return 35i32; }
    return 0i32;
}
fn main(argc:i32,argv:**u8)->i32 { return verify(); }
"""

HEADER = "union U { Value:u64; End:unit; }\n"
REJECT = {
    "missing": (HEADER + "fn f(p:*U)->unit { match U(*p) { Value(v) {} } }", "cover every"),
    "duplicate-arm": (
        HEADER + "fn f(p:*U)->unit { match U(*p) { Value {} Value {} End {} } }",
        "duplicate match",
    ),
    "unknown-arm": (
        HEADER + "fn f(p:*U)->unit { match U(*p) { Other {} End {} } }",
        "unknown union variant",
    ),
    "unit-binding": (
        HEADER + "fn f(p:*U)->unit { match U(*p) { Value {} End(v) {} } }",
        "unit variant has no binding",
    ),
    "wrong-payload": (HEADER + "fn f(p:*U)->unit { construct U.Value(*p,1u32); }", "type mismatch"),
    "missing-payload": (
        HEADER + "fn f(p:*U)->unit { construct U.Value(*p); }",
        "requires the variant payload",
    ),
    "extra-payload": (
        HEADER + "fn f(p:*U)->unit { construct U.End(*p,1u64); }",
        "requires the variant payload",
    ),
    "wrong-destination": (
        HEADER + "fn f(p:*u32)->unit { construct U.Value(*p,1u64); }",
        "type mismatch",
    ),
    "wrong-scrutinee": (
        HEADER + "fn f(p:*u32)->unit { match U(*p) { Value {} End {} } }",
        "type mismatch",
    ),
    "private-field": (HEADER + "fn f(p:*U)->u32 { return p->tag; }", "no field"),
    "bad-arm-body": (
        HEADER + "fn f(p:*U)->unit { match U(*p) { End {} Value(v) { var x:u32=v; } } }",
        "type mismatch",
    ),
    "not-a-place": (HEADER + "fn f()->unit { construct U.End(1u32); }", "address"),
    "unknown-union": ("fn f(p:*u32)->unit { construct Missing.End(*p); }", "unknown union type"),
    "unknown-variant": (
        HEADER + "fn f(p:*U)->unit { construct U.Missing(*p); }",
        "unknown union variant",
    ),
    "duplicate-variant": ("union U { A:u32; A:u64; }", "duplicate union variant"),
    "empty-union": ("union U {}", "at least one variant"),
    "empty-record": ("record R {} union U { A:[R;2]; }", "expected an identifier"),
    "by-value-cycle": ("union U { A:R; } record R { value:U; }", "by-value cycle"),
    "overflow": ("union U { A:[u64;9223372036854775807]; }", "exceeds isize limit"),
    "unknown-pointee": ("union U { A:*Missing; }", "unknown name"),
    "unit-pointee": ("union U { A:*unit; }", "unit is not a pointer target"),
    "invalid-callback": ("record R{x:u32;} union U { A:fn()->R; }", "results must be scalar"),
    "unknown-payload": ("union U { A:Missing; }", "unknown payload type"),
    "unit-array": ("union U { A:[unit;2]; }", "unit has no stored value"),
    "zero-array": ("union U { A:[u8;0]; }", "count must be positive"),
    "duplicate-type": (HEADER + HEADER, "duplicate"),
    "malformed-arm": (HEADER + "fn f(p:*U)->unit { match U(*p) { Value( {} } }", "expected"),
    "malformed-payload": ("union U { A:; }", "expected"),
    "layout-depth": ("union U { A:" + "[" * 260 + "u8" + ";1]" * 260 + "; }", "depth"),
}


def run(command, **kwargs):
    result = subprocess.run(
        [str(x) for x in command], cwd=ROOT, capture_output=True, text=True, timeout=180, **kwargs
    )
    if result.returncode:
        raise AssertionError(f"{command}\n{result.stdout}{result.stderr}")
    return result.stdout


def sanitized_compiler(build, work):
    target = work / "stage-sanitizers"
    flags = "-O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer"
    libraries = [target / f"libcrust0{suffix}.a" for suffix in ("", "_run", "_host")]
    run(["make", f"BUILD={target}", f"CFLAGS={flags}", *libraries])
    sources = run(
        [
            "make",
            "-s",
            "--no-print-directory",
            "--eval",
            'union-inputs:;@printf "%s\\n" $(UNION_LIBRARY)',
            "union-inputs",
        ]
    ).splitlines()
    executable = target / "crust-union-test"
    run(
        [
            build / "crust-c",
            *sources,
            "api/crust0_x64.crs",
            "api/crust0_eval.crs",
            "tests/union_alloc.crs",
            "tests/union_driver.crs",
            *[f"--cflag={flag}" for flag in flags.split()],
            "--ldflag=-fsanitize=address,undefined",
            "--ldflag=-no-pie",
            f"--ldflag={libraries[1]}",
            f"--ldflag={build / 'libcrust_asm.a'}",
            f"--ldflag={libraries[0]}",
            f"--ldflag={libraries[2]}",
            "--ldflag=-ldl",
            "--ldflag=-lffi",
            "-o",
            executable,
        ]
    )
    return executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize-stage", action="store_true")
    args = parser.parse_args()
    build = args.build.resolve()
    work = build / "union-tests"
    work.mkdir(parents=True, exist_ok=True)
    compiler = build / "crust-union-test"
    if args.sanitize_stage:
        os.environ.update(
            ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1"
        )
        compiler = sanitized_compiler(build, work)
    source = work / "runtime.crs"
    source.write_text(RUNTIME)
    run([compiler, "--verify", source])
    for backend in ("c", "asm"):
        output = work / backend
        if backend == "c":
            run([compiler, source, "--cflag=-O2", "-o", output])
        else:
            assembly = output.with_suffix(".s")
            run([compiler, "--asm", source, "-o", assembly])
            run(["cc", assembly, "-o", output])
        run([output])
    for name, (text, diagnostic) in REJECT.items():
        path = work / f"{name}.crs"
        path.write_text(text)
        result = subprocess.run(
            [str(compiler), "--check", str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 1 and diagnostic in result.stderr, (
            name,
            result.returncode,
            result.stderr,
        )
    run([build / "crust", "examples/union/main.crs"])
    assert run([ROOT / "build/union"]) == "union: OK\n"
    root = work / "same-file.crs"
    root.write_text(
        'host_source(run,"../../api/crust0_stage.crs");\n'
        'host_source(run,"../../stages/union/api.crs");\n'
        'host_source(run,"../../stages/union/build.crs");\n'
        'host_link(run,"../crust-union-library.so");\n'
        'var arguments:[*u8;2]=make [*u8;2]{"-o",host_path(run,"same-file")};\n'
        "return union_build(run->source,run->cursor,2i32,&arguments[0usize]);\n" + RUNTIME
    )
    run([build / "crust", root])
    run([work / "same-file"])
    sanitized = work / "sanitized"
    run(
        [
            compiler,
            source,
            "--cflag=-O1",
            "--cflag=-fsanitize=address,undefined",
            "--ldflag=-fsanitize=address,undefined",
            "--ldflag=-no-pie",
            "-o",
            sanitized,
        ]
    )
    run(
        [sanitized],
        env=dict(
            os.environ,
            ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
            UBSAN_OPTIONS="halt_on_error=1",
        ),
    )
    print(
        f"union: C + ASM + evaluator + allocation sweep, {len(REJECT)} rejections, root example, ASan/UBSan passed"
    )


if __name__ == "__main__":
    main()
