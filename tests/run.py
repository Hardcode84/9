#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile, link, and execute the CRUST0 semantic and native interface cases."""

import argparse
import os
import random
import re
import resource
import shlex
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = {f"{sign}{bits}": (bits, sign == "i") for bits in (8, 16, 32, 64) for sign in "iu"}
TYPES.update({"isize": (64, True), "usize": (64, False)})
STRICT = [
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


def wrapped(value, bits, signed):
    value %= 1 << bits
    return value - (1 << bits) if signed and value >= (1 << (bits - 1)) else value


def integer_cases(kind, bits, signed):
    rng = random.Random(927 + bits + signed)
    low = -(1 << (bits - 1)) if signed else 0
    high = (1 << (bits - signed)) - 1
    values = [low, high, 0, 1, -1 if signed else high - 1]
    values += [rng.randint(low, high) for _ in range(9)]
    cases = []

    def literal(value):
        return f"{value}{kind}"

    for a in values:
        for op, value in [("-", -a), ("~", ~a)]:
            cases.append((f"{op}({literal(a)})", literal(wrapped(value, bits, signed))))
        for b in [low, high, 1, rng.randint(low, high)]:
            for op, value in [
                ("+", a + b),
                ("-", a - b),
                ("*", a * b),
                ("&", a & b),
                ("|", a | b),
                ("^", a ^ b),
            ]:
                cases.append(
                    (f"({literal(a)}) {op} ({literal(b)})", literal(wrapped(value, bits, signed)))
                )
            for op, value in [
                ("<", a < b),
                ("<=", a <= b),
                (">", a > b),
                (">=", a >= b),
                ("==", a == b),
                ("!=", a != b),
            ]:
                cases.append((f"({literal(a)}) {op} ({literal(b)})", str(value).lower()))
            if b != 0 and not (signed and a == low and b == -1):
                quotient = abs(a) // abs(b) * (-1 if (a < 0) != (b < 0) else 1)
                cases.append((f"({literal(a)}) / ({literal(b)})", literal(quotient)))
                cases.append((f"({literal(a)}) % ({literal(b)})", literal(a - quotient * b)))
        for shift in (0, 1, bits - 1):
            for op, value in [("<<", a << shift), (">>", a >> shift)]:
                cases.append(
                    (f"({literal(a)}) {op} {literal(shift)}", literal(wrapped(value, bits, signed)))
                )
        for target, (width, sign) in TYPES.items():
            cases.append((f"({literal(a)}) as {target}", f"{wrapped(a, width, sign)}{target}"))
    return cases


def check_temporary_errors(command, compiler, backend, work, cc):
    shim = work / "driver-entropy.so"
    command([*cc, *STRICT, "-fPIC", "-shared", ROOT / "tests/driver_entropy.c", "-o", shim])
    linked = command(["ldd", compiler]).stdout.decode()
    sanitizer = re.findall(r"^\s*libasan\S* => (\S+)", linked, re.M)
    environment = {**os.environ, "LD_PRELOAD": ":".join([*sanitizer, str(shim)])}
    source = work / "permissions.crs"
    output, victim = work / "entropy-output", work / "entropy-victim"
    occupied = work / (".crust-" + "00" * 16)
    victim.write_text("retained victim\n")
    variants = [["--emit-c"], ["--object"]] if backend == "c" else [[]]
    for options in variants:
        for mode in ("fail", "collision"):
            environment["CRUST_TEST_ENTROPY"] = mode
            output.write_text("retained output\n")
            if mode == "collision":
                occupied.symlink_to(victim)
            result = command(
                [compiler, *options, "-o", output, source], expected=1, env=environment
            )
            assert b"temporary" in result.stderr or b"cannot create output" in result.stderr
            assert output.read_text() == "retained output\n"
            assert victim.read_text() == "retained victim\n"
            if mode == "collision":
                assert occupied.is_symlink() and occupied.readlink() == victim
                occupied.unlink()
            assert not list(work.glob(".crust-*"))


def check_output_permissions(command, compiler, backend, work, tool_flags):
    source = work / "permissions.crs"
    source.write_text(
        'extern fn imported()->unit="permission_probe"; fn main(argc:i32,argv:**u8)->i32{return 0i32;}'
    )
    modes = [("assembly", [], 0o666)]
    if backend == "c":
        modes = [
            ("text", ["--emit-c"], 0o666),
            ("object", ["--object"], 0o666),
            ("executable", [], 0o777),
        ]
    for mask in (0o002, 0o027):
        for name, options, creation in modes:
            output = work / f"permissions-{name}-{mask}"
            symbols = output.with_suffix(".rsp")
            output.unlink(missing_ok=True)
            symbols.unlink(missing_ok=True)
            flags = options + (["--symbols", symbols] if name == "text" else [])
            if name in ("object", "executable"):
                flags += tool_flags
            argv = [compiler, *flags, "-o", output, source]
            command(argv, umask=mask)
            assert stat.S_IMODE(output.stat().st_mode) == creation & ~mask
            if name == "executable":
                command([output])
            previous = 0o7751 if name == "executable" else 0o7604
            output.chmod(previous)
            assert stat.S_IMODE(output.stat().st_mode) == previous
            if name == "text":
                assert stat.S_IMODE(symbols.stat().st_mode) == 0o666 & ~mask
                symbols.chmod(0o7640)
            command(argv, umask=mask)
            assert stat.S_IMODE(output.stat().st_mode) == (0o751 if name == "executable" else 0o604)
            if name == "text":
                assert stat.S_IMODE(symbols.stat().st_mode) == 0o640

    output = work / "temporary-collision"
    for occupied in (2, 128):
        output.write_text("retained destination\n")
        output.chmod(0o640)

        def occupy(occupied=occupied):
            for index in range(occupied):
                path = Path(f"{output}.tmp.{os.getpid()}.{index}")
                if index == 1:
                    path.symlink_to(output)
                else:
                    path.write_text("retained temporary\n")

        options = ["--emit-c"] if backend == "c" else []
        command([compiler, *options, "-o", output, source], preexec_fn=occupy)
        assert output.read_text() != "retained destination\n"
        assert stat.S_IMODE(output.stat().st_mode) == 0o640
        candidates = list(work.glob("temporary-collision.tmp.*"))
        assert len(candidates) == occupied
        for path in candidates:
            if path.is_symlink():
                assert path.readlink() == output
            else:
                assert path.read_text() == "retained temporary\n"
            path.unlink()

    for name, options, creation in modes:
        output = work / (name[0] * os.pathconf(work, "PC_NAME_MAX"))
        output.unlink(missing_ok=True)
        flags = options + (tool_flags if name in ("object", "executable") else [])
        command([compiler, *flags, "-o", output, source], umask=0o027)
        assert stat.S_IMODE(output.stat().st_mode) == creation & ~0o027
        if name == "executable":
            command([output])
        output.unlink()

    if backend == "c":
        tools = work / "permission-tools"
        tools.mkdir(exist_ok=True)
        output = work / "private-output"
        output.write_text("private destination\n")
        output.chmod(0o600)
        probe = tools / "checked"
        probe.unlink(missing_ok=True)
        wrapper = tools / "gcc"
        wrapper.write_text(
            f"#!{sys.executable}\n"
            "import subprocess, sys\nfrom pathlib import Path\n"
            "def check():\n"
            f"    paths = list(Path({str(work)!r}).glob('.crust-*'))\n"
            "    assert len(paths) == 5, paths\n"
            "    for path in paths:\n        assert path.stat().st_mode & 0o077 == 0, path\n"
            "check()\n"
            f"result = subprocess.run([{shutil.which('gcc')!r}, *sys.argv[1:]])\n"
            "if result.returncode: sys.exit(result.returncode)\n"
            "check()\n"
            f"with open({str(probe)!r}, 'a') as stream: stream.write('checked\\n')\n"
        )
        wrapper.chmod(0o755)
        environment = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"]}
        command([compiler, *tool_flags, "-o", output, source], env=environment, umask=0o002)
        assert probe.read_text() == "checked\nchecked\n"
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not list(work.glob(".crust-*")), "driver left temporary files"


def check_c_runtime(command, compiler, work, cc):
    source = work / "runtime-copy.crs"
    source.write_text(
        "record Big { values:[u64;2048]; }\n" "fn copy_big(dst:*Big,src:*Big)->unit{*dst=*src;}\n"
    )
    runtime = work / "runtime-memcpy.crs"
    runtime.write_text(
        'extern fn note_copy()->unit="note_copy";\n'
        "fn memcpy(dst:*u8,src:*u8,count:usize)->*u8{\n"
        "note_copy(); var i:usize=0usize;\n"
        "while i<count {dst[i]=src[i]; i=i+1usize;} return dst;}\n"
    )
    runtime_object = runtime.with_suffix(".o")
    command(
        [compiler, "--library", "--object", "--export", "memcpy", "-o", runtime_object, runtime]
    )
    undefined = command(["nm", "-u", runtime_object]).stdout
    assert not re.search(rb"\bU memcpy\b", undefined), "runtime memcpy calls itself"
    harness = work / "runtime-copy.c"
    harness.write_text(
        "#include <stddef.h>\n#include <stdint.h>\n"
        "struct Big {uint64_t values[2048];};\n"
        "void copy_big(struct Big *dst,struct Big *src);\n"
        "void note_copy(void);\nstatic unsigned calls;\n"
        "void note_copy(void){++calls;}\n"
        "int main(void){struct Big src,dst;size_t i;\n"
        "for(i=0;i<2048;++i){src.values[i]=i*53+1;dst.values[i]=0;}\n"
        "copy_big(&dst,&src);if(calls==0)return 1;\n"
        "for(i=0;i<2048;++i){if(dst.values[i]!=src.values[i])return 2;}\n"
        "return 0;}\n"
    )
    for mode, options in (("hosted", []), ("freestanding", ["--cflag=-ffreestanding"])):
        object_path = work / f"runtime-copy-{mode}.o"
        command(
            [
                compiler,
                "--library",
                "--object",
                "--export",
                "copy_big",
                "--cflag=-fstack-protector-all",
                *options,
                "-o",
                object_path,
                source,
            ]
        )
        undefined = command(["nm", "-u", object_path]).stdout
        assert re.search(rb"\bU memcpy\b", undefined), undefined
        assert re.search(rb"\bU __stack_chk_fail\b", undefined), undefined
        output = work / f"runtime-copy-{mode}"
        command([*cc, *STRICT, "-O2", harness, object_path, runtime_object, "-o", output])
        command([output])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--backend", choices=("x64", "c"), default="x64")
    parser.add_argument("--library-dir", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--cflags", default="-O2")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--assembler", default="as --64")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    build = (args.library_dir or compiler.parent).resolve()
    work = (args.work_dir or build / ("tests-c" if args.backend == "c" else "tests")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    cc = shlex.split(args.cc)
    assembler = shlex.split(args.assembler)
    ldflags = shlex.split(args.ldflags)
    cflags = shlex.split(args.cflags)
    c_options = [item for flag in cflags for item in ("--cflag", flag)]
    c_link_options = [item for flag in ldflags for item in ("--ldflag", flag)]
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    checks = 0

    def command(argv, expected=0, **options):
        nonlocal checks
        result = subprocess.run(
            [str(arg) for arg in argv],
            cwd=options.pop("cwd", ROOT),
            capture_output=True,
            timeout=30,
            **options,
        )
        checks += 1
        if result.returncode != expected:
            raise AssertionError(
                f"{shlex.join(map(str, argv))}: status {result.returncode}, expected {expected}\n"
                f"{result.stdout.decode(errors='replace')}\n{result.stderr.decode(errors='replace')}"
            )
        return result

    def assemble(source):
        output = source.with_suffix(".s.o")
        command([*assembler, source, "-o", output])
        return output

    def executable(name, source=None, inputs=None, libraries=(), entry=None, exports=()):
        if source is not None:
            path = work / f"{name}.crs"
            path.write_text(source)
            inputs = [path]
        output = work / name
        entry_options = ["--entry", entry] if entry is not None else []
        entry_options += [item for name in exports for item in ("--export", name)]
        if args.backend == "c":
            obj = work / f"{name}.crs.o"
            command([compiler, "--object", "-o", obj, *c_options, *entry_options, *inputs])
        else:
            assembly = work / f"{name}.s"
            command([compiler, "-S", "-o", assembly, *entry_options, *inputs])
            obj = assemble(assembly)
        command(
            [*cc, "-no-pie", obj, *libraries, build / "libcrust0_host.a", *ldflags, "-o", output]
        )
        return output

    native = work / "native.o"
    command([*cc, *STRICT, "-O2", "-c", "tests/native.c", "-o", native])
    command([executable("runtime", inputs=["tests/runtime.crs"], libraries=[native])])
    intrusive = executable("intrusive", inputs=["examples/intrusive/program.crs"])
    assert command([intrusive]).stdout == b"intrusive: ok\n"

    dynamic = """
extern fn native_i32(value:i32)->i32="native_i32";
extern fn native_i64(value:i64)->i64="native_i64";
extern fn native_u16(value:u16)->u16="native_u16";
extern fn native_i8(value:i8)->i8="native_i8";
extern fn native_pointer(value:*u8)->*u8="native_pointer";
record union { volatile:u32; restrict:u8; }
fn switch(inline:u32)->u32 {return inline+1u32;}
fn first()->i32{return 1i32;}
fn second()->i32{return 2i32;}
fn changed(a:*u64,b:*u32)->u64 {*a=0u64;*b=1u32;return *a;}
fn main(argc:i32,argv:**u8)->i32 {
    var high:i32=native_i32(2147483647i32);
    if !(high+1i32<high) {return 1i32;}
    var minimum:i64=native_i64(-9223372036854775808i64);
    if -minimum!=minimum {return 2i32;}
    var narrow:u16=native_u16(65535u16);
    if narrow*narrow!=1u16 || (narrow<<15u16)!=32768u16 {return 3i32;}
    var negative:i64=native_i64(-1i64);
    if (negative<<1i64)!=-2i64 || (negative>>63i64)!=-1i64 {return 4i32;}
    if (native_i8(-1i8) as u64)!=18446744073709551615u64 {return 5i32;}
    var wide:u64=99u64;
    var alias:*u32=native_pointer(&wide as *u8) as *u32;
    if changed(&wide,alias)!=1u64 {return 6i32;}
    *alias=2u32;
    if wide!=2u64 {return 8i32;}
    var byte:u8=42u8;
    var pointer:*u8=null(*u8);
    var pointer_slot:**u8=native_pointer(&pointer as *u8) as **u8;
    *pointer_slot=&byte;
    if pointer!=&byte {return 9i32;}
    var function:fn()->i32=first;
    var function_slot:*fn()->i32=native_pointer(&function as *u8) as *fn()->i32;
    *function_slot=second;
    if function!=second || function()!=2i32 {return 10i32;}
    var truth:bool=false;
    *native_pointer(&truth as *u8)=1u8;
    if !truth {return 11i32;}
    var register:union=make union{volatile:41u32,restrict:1u8};
    if switch(register.volatile)!=42u32 || register.restrict!=1u8 {return 7i32;}
    return 0i32;
}
"""
    command([executable("dynamic-values", dynamic, libraries=[native])])
    owned_alias = """
fn target()->u64{return 42u64;}
extern fn alias()->u64="target";
const captured:fn()->u64=target;
fn main(argc:i32,argv:**u8)->i32 {
    if target!=alias || captured!=alias {return 1i32;}
    if alias()!=42u64 || captured()!=42u64 {return 2i32;}
    return 0i32;
}
"""
    command([executable("owned-native-alias", owned_alias, exports=["target"])])

    private_objects = []
    for name, value in (("first", 19), ("second", 23)):
        source = work / f"private-{name}.crs"
        source.write_text(
            f"const value:i32={value}i32; fn helper()->i32{{return value;}}\n"
            f"const {name}_callback:fn()->i32=helper;\n"
            f"fn {name}()->i32{{return helper();}}\n"
        )
        exports = ["--export", name, "--export", name + "_callback"]
        if args.backend == "c":
            obj = work / f"private-{name}.o"
            command([compiler, "--library", "--object", *exports, "--cflag=-O0", "-o", obj, source])
        else:
            assembly = work / f"private-{name}.s"
            command([compiler, "--library", *exports, "-o", assembly, source])
            obj = assemble(assembly)
        defined = command(["nm", "-g", "--defined-only", obj]).stdout
        assert set(re.findall(rb"\b[TDRB]\s+(\S+)", defined)) == {
            name.encode(),
            (name + "_callback").encode(),
        }, defined
        private_objects.append(obj)
    caller = work / "private-caller.c"
    caller.write_text(
        "#include <stdint.h>\nint32_t first(void); int32_t second(void);\n"
        "extern int32_t (*const first_callback)(void);\n"
        "extern int32_t (*const second_callback)(void);\n"
        "int main(void){return first()+second()!=42 || first_callback()!=19 || "
        "second_callback()!=23 || first_callback==second_callback;}\n"
    )
    private_program = work / "private-program"
    command([*cc, *STRICT, "-no-pie", caller, *private_objects, *ldflags, "-o", private_program])
    command([private_program])
    command(
        [
            executable(
                "selected-entry", "fn start(argc:i32,argv:**u8)->i32{return 17i32;}", entry="start"
            )
        ],
        expected=17,
    )
    long_string = 'fn main(argc:i32,argv:**u8)->i32{var text:*u8="' + "x" * 5000 + '";'
    long_string += "if text[0usize]!=120u8 || text[4999usize]!=120u8 || text[5000usize]!=0u8{return 1i32;}return 0i32;}"
    command([executable("long-string", long_string)])
    byte_string = "".join(f"\\x{byte:02x}" for byte in range(256))
    command(
        [
            executable(
                "all-string-bytes",
                'fn main(argc:i32,argv:**u8)->i32{var empty:*u8="";'
                f'var text:*u8="{byte_string}";var index:usize=0usize;'
                "while index<256usize {if text[index]!=index as u8 {return 1i32;}"
                "index=index+1usize;}"
                "if text[256usize]!=0u8 || empty[0usize]!=0u8 {return 2i32;}return 0i32;}",
            )
        ]
    )

    allocation_wrapper = work / "c-stage-alloc.o"
    command(
        [
            *cc,
            *STRICT,
            *cflags,
            "-Iinclude",
            "-c",
            "tests/c_stage_alloc.c",
            "-o",
            allocation_wrapper,
        ]
    )
    foundation = executable(
        "c-stage-foundation",
        inputs=[
            "api/crust0.crs",
            "api/crust0_host.crs",
            "stages/c/model.crs",
            "stages/c/base.crs",
            "stages/c/types.crs",
            "tests/c_types.crs",
            "tests/c_stage.crs",
        ],
        libraries=[
            allocation_wrapper,
            build / "libcrust0.a",
            "-Wl,--wrap=crust0_host_alloc,--wrap=crust0_host_free",
        ],
    )
    quoted_source = work / "c-stage-quoted.c"
    quoted_source.write_bytes(command([foundation]).stdout)
    command([*cc, *STRICT, "-O3", quoted_source, "-o", work / "c-stage-quoted"])
    command([work / "c-stage-quoted"])
    allocation_environment = os.environ.copy()
    allocation_environment["ASAN_OPTIONS"] = ":".join(
        filter(None, [allocation_environment.get("ASAN_OPTIONS"), "allocator_may_return_null=1"])
    )
    command([foundation, "oom"], env=allocation_environment)

    native_names = [
        ".Lcrust_0_string_1",
        ".Lcrust_1_label_1",
        "line\nbreak",
        'quote"back\\name',
        "1",
        ".",
        "\x7fend",
        ".LFE0",
        ".LC0",
        ".LFB0",
        ".Ltext0",
        "".join(chr(value) for value in range(1, 128)),
    ]
    native_source = work / "native-names.c"
    native_source.write_text(
        "#include <stdint.h>\n"
        + "\n".join(
            f"int32_t native_{index}(void);\nint32_t native_{index}(void) {{return {index + 10};}}"
            for index in range(len(native_names))
        )
        + "\n"
    )
    native_original = work / "native-names-original.o"
    native_renamed = work / "native-names.o"
    command([*cc, *STRICT, "-O2", "-c", native_source, "-o", native_original])
    rename_options = []
    declarations = []
    calls = []
    for index, name in enumerate(native_names):
        rename_options += ["--redefine-sym", f"native_{index}={name}"]
        encoded = "".join(f"\\x{ord(byte):02x}" for byte in name)
        declarations.append(f'extern fn named_{index}()->i32="{encoded}";')
        calls.append(f"if named_{index}()!={index + 10}i32{{return {index + 1}i32;}}")
    command(["objcopy", *rename_options, native_original, native_renamed])
    named_source = (
        "\n".join(declarations)
        + "\nfn main(argc:i32,argv:**u8)->i32{"
        + "".join(calls)
        + "return 0i32;}\n"
    )
    command([executable("native-names", named_source, libraries=[native_renamed])])

    specification = (ROOT / "docs" / "crust0-spec.md").read_text()
    example_section = specification.split("## 13 Complete seed examples\n", 1)[1].split(
        "\n## 14 ", 1
    )[0]
    examples = re.findall(r"^~~~text\n(.*?)^~~~\s*$", example_section, re.M | re.S)
    if len(examples) != 2:
        raise AssertionError(f"expected two complete specification examples, found {len(examples)}")
    assert command([executable("spec-list", examples[0])]).stdout == b"ok\n"
    example_main = (
        "\nfn main(argc:i32,argv:**u8)->i32{if apply()!=18u32{return 1i32;}return 0i32;}\n"
    )
    command([executable("spec-values", examples[1] + example_main)])

    stack_arguments = """
fn sum(a:i8,b:u8,c:i16,d:u16,e:i32,f:u32,g:i8,h:u16)->i64 {
    var large:[u8;8192]=uninit;
    large[0usize]=g as u8;
    large[8191usize]=b;
    return (a as i64)+(b as i64)+(c as i64)+(d as i64)+(e as i64)+(f as i64)+(g as i64)+(h as i64);
}
fn main(argc:i32,argv:**u8)->i32 {
    if sum(-1i8,2u8,-3i16,4u16,-5i32,6u32,-7i8,8u16)!=4i64 {return 1i32;}
    return 0i32;
}
"""
    stack_arguments_executable = executable("stack-arguments", stack_arguments)
    command([stack_arguments_executable])
    parameters = ",".join(f"p{index}:i8" for index in range(600))
    values = [index % 127 - 63 for index in range(600)]
    observed = (0, 5, 6, 511, 599)
    total = "+".join(f"(p{index} as i64)" for index in observed)
    arguments = ",".join(f"{value}i8" for value in values)
    expected_total = sum(values[index] for index in observed)
    stack_outgoing = (
        f"fn sum({parameters})->i64{{return {total};}}\n"
        f"fn main(argc:i32,argv:**u8)->i32{{if sum({arguments})!={expected_total}i64"
        "{return 1i32;}return 0i32;}\n"
    )
    command([executable("stack-outgoing", stack_outgoing)])
    if args.backend == "x64":
        stack_limit = executable(
            "stack-limit",
            """
fn exhaust()->unit {var large:[u8;1048576]=uninit;}
fn main(argc:i32,argv:**u8)->i32 {exhaust();return 0i32;}
""",
        )
        stack_environment = os.environ.copy()
        # This child must expose the native guard-page signal, including in sanitizer runs.
        stack_environment["ASAN_OPTIONS"] = ":".join(
            filter(None, [stack_environment.get("ASAN_OPTIONS"), "handle_segv=0"])
        )
        for program, expected_status in (
            (stack_arguments_executable, 0),
            (stack_limit, -signal.SIGSEGV),
        ):
            command(
                [program],
                expected=expected_status,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_STACK, (131072, 131072)),
                env=stack_environment,
            )

    arithmetic_checks = 0
    for kind, (bits, signed) in TYPES.items():
        cases = integer_cases(kind, bits, signed)
        arithmetic_checks += len(cases)
        functions = []
        for start in range(0, len(cases), 200):
            function = f"case_{start}"
            body = [f"fn {function}() -> i32 {{"]
            for index, (expression, value) in enumerate(cases[start : start + 200], 1):
                body.append(f"if ({expression}) != ({value}) {{ return {index}i32; }}")
            body.append("return 0i32; }")
            functions.append((function, "\n".join(body)))
        main_body = "\n".join(
            f"var status_{index}:i32={name}(); if status_{index}!=0i32 {{return status_{index};}}"
            for index, (name, _) in enumerate(functions)
        )
        source = (
            "\n".join(body for _, body in functions)
            + "\nfn main(argc:i32,argv:**u8)->i32{\n"
            + main_body
            + "\nreturn 0i32;}\n"
        )
        command([executable(f"integer-{kind}", source)])
    print(f"integer values: {arithmetic_checks} comparisons passed")

    traps = ["trap;"]
    for kind, (bits, signed) in TYPES.items():
        traps.extend(f"1{kind} {op} 0{kind};" for op in ("/", "%"))
        traps.extend(f"1{kind} {op} {bits}{kind};" for op in ("<<", ">>"))
        if signed:
            traps.extend(f"1{kind} {op} -1{kind};" for op in ("<<", ">>"))
            traps.extend(f"-{1 << (bits - 1)}{kind} {op} -1{kind};" for op in ("/", "%"))
    for index, statement in enumerate(traps):
        source = f"fn main(argc:i32,argv:**u8)->i32{{{statement} return 0i32;}}"
        command([executable(f"trap-{index}", source)], expected=-signal.SIGILL)
    dynamic_traps = [
        "1i32 / native_i32(0i32);",
        "-2147483648i32 / native_i32(-1i32);",
        "1i32 << native_i32(-1i32);",
        "1i32 >> native_i32(32i32);",
    ]
    for index, statement in enumerate(dynamic_traps):
        source = (
            'extern fn native_i32(value:i32)->i32="native_i32";'
            f"fn main(argc:i32,argv:**u8)->i32{{{statement} return 0i32;}}"
        )
        command(
            [executable(f"dynamic-trap-{index}", source, libraries=[native])],
            expected=-signal.SIGILL,
        )
    print(f"required traps: {len(traps) + len(dynamic_traps)} processes passed")

    for name, source in {
        "flat-depth": "fn f()->u32{return " + "+".join(["1u32"] * 10000) + ";}",
        "record-depth": "".join(f"record R{i}{{field:R{i + 1};}}" for i in range(2000))
        + "record R2000{field:u8;}",
        "unknown-value": "fn f()->u32{return absent;}",
        "native-conflict": 'extern fn a()->u8="shared"; extern fn b()->u64="shared";',
        "wrong-entry": "fn main()->u32{return 0u32;}",
    }.items():
        path = work / f"reject-{name}.crs"
        path.write_text(source)
        result = command([compiler, "--prepare", path], expected=1)
        if not result.stderr or b"error" not in result.stderr and b"entry" not in result.stderr:
            raise AssertionError(f"missing diagnostic for {name}: {result.stderr!r}")

    api_stems = ("crust0", "crust0_host", "crust0_x64", "crust0_stage", "crust0_eval", "crust0_run")
    api_paths = [ROOT / "api" / f"{stem}.crs" for stem in api_stems]
    probe = [
        *(f'#include "{stem}.h"' for stem in api_stems),
        "#include <stdio.h>",
        "int main(void) {",
    ]
    for path in api_paths:
        for record, body in re.findall(r"record (\w+) \{(.*?)\}", path.read_text(), re.S):
            for query, expression in [
                (f"sizeof({record})", f"sizeof({record})"),
                (f"alignof({record})", f"CRUST_ALIGNOF({record})"),
            ]:
                probe.append(f'printf("if {query} != %zuusize {{return 1i32;}}\\n", {expression});')
            for field in re.findall(r"^    (\w+):", body, re.M):
                probe.append(
                    f'printf("if offsetof({record},{field}) != %zuusize {{return 2i32;}}\\n", offsetof({record},{field}));'
                )
    probe.append("return 0; }")
    probe_path = work / "layout.c"
    probe_path.write_text("\n".join(probe) + "\n")
    command([*cc, *STRICT, "-Iinclude", probe_path, "-o", work / "layout-probe"])
    layout_checks = command([work / "layout-probe"]).stdout.decode()
    layout_path = work / "layout.crs"
    layout_path.write_text(
        "fn main(argc:i32,argv:**u8)->i32{\n" + layout_checks + "return 0i32;}\n"
    )
    command(
        [
            executable(
                "api-layout", inputs=[*api_paths, layout_path], libraries=[build / "libcrust0.a"]
            )
        ]
    )
    print(f"public layouts: {len(layout_checks.splitlines())} C/CRUST0 comparisons passed")

    stat_fields = {
        "device": "st_dev",
        "inode": "st_ino",
        "links": "st_nlink",
        "mode": "st_mode",
        "uid": "st_uid",
        "gid": "st_gid",
        "padding": "__pad0",
        "special_device": "st_rdev",
        "size": "st_size",
        "block_size": "st_blksize",
        "blocks": "st_blocks",
        "access_seconds": "st_atim.tv_sec",
        "access_nanoseconds": "st_atim.tv_nsec",
        "modify_seconds": "st_mtim.tv_sec",
        "modify_nanoseconds": "st_mtim.tv_nsec",
        "change_seconds": "st_ctim.tv_sec",
        "change_nanoseconds": "st_ctim.tv_nsec",
        "reserved": "__glibc_reserved",
    }
    stat_record = re.search(
        r"^record CDriverStat \{.*?^\}", (ROOT / "stages/c/driver.crs").read_text(), re.M | re.S
    ).group()
    probe = [
        "#define _POSIX_C_SOURCE 200809L",
        "#include <sys/stat.h>",
        "#include <stddef.h>",
        "#include <stdio.h>",
        "struct Alignment {char byte; struct stat value;};",
        "int main(void) {",
    ]
    for expression, native_expression in [
        ("sizeof(CDriverStat)", "sizeof(struct stat)"),
        ("alignof(CDriverStat)", "offsetof(struct Alignment,value)"),
    ]:
        probe.append(f'printf("if {expression}!=%zuusize{{return 1i32;}}\\n",{native_expression});')
    for field, native_field in stat_fields.items():
        probe.append(
            f'printf("if offsetof(CDriverStat,{field})!=%zuusize{{return 2i32;}}\\n",'
            f"offsetof(struct stat,{native_field}));"
        )
    probe.append("return 0;}")
    stat_source = work / "stat-layout.c"
    stat_source.write_text("\n".join(probe) + "\n")
    command([*cc, *STRICT, stat_source, "-o", work / "stat-layout-probe"])
    stat_checks = command([work / "stat-layout-probe"]).stdout.decode()
    command(
        [
            executable(
                "stat-layout",
                stat_record + "\nfn main(argc:i32,argv:**u8)->i32{" + stat_checks + "return 0i32;}",
            )
        ]
    )
    print(f"driver stat layout: {len(stat_checks.splitlines())} C/CRUST0 comparisons passed")

    if (ROOT / "examples" / "custom-stage" / "stage.crs").exists():
        stage = executable(
            "stage",
            inputs=[*api_paths, "examples/custom-stage/stage.crs"],
            libraries=[build / "libcrust0.a"],
        )
        custom_input = work / "answer.txt"
        custom_input.write_text("42\n")
        custom_assembly = work / "answer.s"
        command([stage, custom_input, custom_assembly])
        if "stage: add zero" not in custom_assembly.read_text():
            raise AssertionError("custom backend lowering did not run")
        custom_object = assemble(custom_assembly)
        command(
            [
                *cc,
                *STRICT,
                "-no-pie",
                custom_object,
                "examples/custom-stage/answer_main.c",
                *ldflags,
                "-o",
                work / "answer",
            ]
        )
        command([work / "answer"], expected=42)
        saved_registers = [
            ("rbp", 0x3141592653589793),
            ("rbx", 0x2718281828459045),
            ("r12", 0x123456789ABCDEF0),
            ("r13", 0xFEDCBA9876543210),
            ("r14", 0x1122334455667788),
            ("r15", 0x8877665544332211),
        ]
        register_probe = [
            ".text",
            ".globl _start",
            ".type _start,@function",
            "_start:",
            "\tandq $-16, %rsp",
        ]
        register_probe += [
            f"\tmovabsq $0x{value:016x}, %{register}" for register, value in saved_registers
        ]
        register_probe += [
            "\txorl %edi, %edi",
            "\txorl %esi, %esi",
            "\tcall crust_stage_answer",
            "\tcmpl $42, %eax",
            "\tjne .Lregister_failure",
        ]
        for register, value in saved_registers:
            register_probe += [
                f"\tmovabsq $0x{value:016x}, %r10",
                f"\tcmpq %r10, %{register}",
                "\tjne .Lregister_failure",
            ]
        register_probe += [
            "\txorl %edi, %edi",
            "\tjmp .Lregister_exit",
            ".Lregister_failure:",
            "\tmovl $1, %edi",
            ".Lregister_exit:",
            "\tmovl $60, %eax",
            "\tsyscall",
            '.section .note.GNU-stack,"",@progbits',
        ]
        register_source = work / "stage-registers.s"
        register_source.write_text("\n".join(register_probe) + "\n")
        register_executable = work / "stage-registers"
        command(
            [
                *cc,
                "-nostdlib",
                "-no-pie",
                custom_object,
                assemble(register_source),
                "-Wl,-e,_start",
                "-o",
                register_executable,
            ]
        )
        command([register_executable])
        custom_input.write_text("not a number\n")
        command([stage, custom_input, custom_assembly], expected=1)
        custom_input.write_text("42\n")
        command([stage, custom_input, "/dev/full"], expected=1)
    else:
        raise AssertionError("missing ordinary CRUST0 stage example")

    valid = work / "valid.crs"
    invalid = work / "invalid.crs"
    output = work / ("atomic.c" if args.backend == "c" else "atomic.s")
    dump_options = ["--emit-c"] if args.backend == "c" else []
    valid.write_text(
        'extern fn native()->unit="validation_native"; fn main(argc:i32,argv:**u8)->i32{return 0i32;}'
    )
    invalid.write_bytes(b"fn\x00")
    check_output_permissions(command, compiler, args.backend, work, [*c_options, *c_link_options])
    check_temporary_errors(command, compiler, args.backend, work, cc)
    output.write_text("retained output\n")
    output.chmod(0o640)
    command([compiler, *dump_options, "-o", output, invalid], expected=1)
    assert output.read_text() == "retained output\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    command(
        [compiler, *dump_options, "-o", work / "absent-directory" / "output", valid], expected=1
    )
    command([compiler, "--check", work / "absent.crs"], expected=1)
    for arguments in ([*dump_options, valid], ["--help"], ["--version"]):
        with open("/dev/full", "wb") as failed_output:
            result = subprocess.run(
                [str(compiler), *map(str, arguments)],
                stdout=failed_output,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            checks += 1
            assert result.returncode == 1 and result.stderr, (
                arguments,
                result.returncode,
                result.stderr,
            )
    for device, expected_status in (("/dev/null", 0), ("/dev/full", 1)):
        before = Path(device).stat()
        assert stat.S_ISCHR(before.st_mode)
        result = command([compiler, *dump_options, "-o", device, valid], expected=expected_status)
        after = Path(device).stat()
        assert stat.S_ISCHR(after.st_mode)
        assert (after.st_dev, after.st_ino, after.st_rdev) == (
            before.st_dev,
            before.st_ino,
            before.st_rdev,
        )
        if expected_status != 0:
            assert result.stderr
    target = work / "symlink-target"
    link = work / "symlink-output"
    target.write_text("replace this output\n")
    link.unlink(missing_ok=True)
    link.symlink_to(target.name)
    command([compiler, *dump_options, "-o", output, valid])
    command([compiler, *dump_options, "-o", link, valid])
    assert link.is_symlink() and link.readlink() == Path(target.name)
    assert target.read_bytes() == output.read_bytes()
    if args.backend == "c":
        assert command([compiler, "--emit-c", valid]).stdout == output.read_bytes()
        assert command([compiler, "--prepare", valid]).stdout == b""
        symbols = work / "atomic.rsp"
        command([compiler, "--emit-c", "-o", output, "--symbols", symbols, valid])
        assert b"validation_native" in symbols.read_bytes()
        expected_c, expected_symbols = output.read_bytes(), symbols.read_bytes()
        command([compiler, "--emit-c", "-o", output, "--symbols", symbols, invalid], expected=1)
        assert output.read_bytes() == expected_c and symbols.read_bytes() == expected_symbols
        command([compiler, "--emit-c", "-o", output, "--symbols", output, valid], expected=1)
        assert output.read_bytes() == expected_c
        command(
            [
                compiler,
                "--emit-c",
                "-o",
                output,
                "--symbols",
                str(output.parent) + "/./" + output.name,
                valid,
            ],
            expected=1,
        )
        assert output.read_bytes() == expected_c
        directory_link = work / "artifact-directory"
        directory_link.unlink(missing_ok=True)
        directory_link.symlink_to(".", target_is_directory=True)
        unpublished = work / "same-new-artifact"
        unpublished.unlink(missing_ok=True)
        command(
            [
                compiler,
                "--emit-c",
                "-o",
                unpublished,
                "--symbols",
                directory_link / unpublished.name,
                valid,
            ],
            expected=1,
        )
        assert not unpublished.exists()
        command([compiler, "--emit-c", "-o", target, "--symbols", link, valid], expected=1)
        assert link.is_symlink() and target.read_bytes() == expected_c
        hardlink = work / "hardlink-target"
        hardlink.unlink(missing_ok=True)
        hardlink.hardlink_to(target)
        hardlink_alias = work / "hardlink-output"
        hardlink_alias.unlink(missing_ok=True)
        hardlink_alias.symlink_to(hardlink.name)
        command([compiler, "--emit-c", "-o", link, "--symbols", hardlink_alias, valid], expected=1)
        assert target.read_bytes() == expected_c and hardlink.read_bytes() == expected_c
        assert link.is_symlink() and hardlink_alias.is_symlink()
        dangling = work / "dangling-artifact"
        dangling.unlink(missing_ok=True)
        dangling.symlink_to("absent-artifact-target")
        command([compiler, "--emit-c", "-o", unpublished, "--symbols", dangling, valid], expected=1)
        assert dangling.is_symlink() and not unpublished.exists() and not dangling.exists()
        command([compiler, "--emit-c", "--symbols", "/dev/null", valid])
        command([compiler, "--emit-c", "-o", output, "--symbols", "/dev/full", valid], expected=1)
        assert output.read_bytes() == expected_c

        for arguments in (
            [valid],
            ["--object", valid],
            ["--symbols", symbols, "-o", output, valid],
            ["--unknown", valid],
            ["--object", "-o", output, invalid],
        ):
            result = command([compiler, *arguments], expected=1)
            assert result.stderr
        native_output = work / "atomic-object.o"
        retained = b"retain native output\n"
        native_output.write_bytes(retained)
        command(
            [compiler, "--object", "-o", native_output, "--cflag", "-not-a-gcc-flag", valid],
            expected=1,
        )
        assert native_output.read_bytes() == retained
        command([compiler, "-o", native_output, "--ldflag", "-not-a-gcc-flag", valid], expected=1)
        assert native_output.read_bytes() == retained
        missing_tools = os.environ.copy()
        missing_tools["PATH"] = str(work / "missing-tools")
        command([compiler, "--object", "-o", native_output, valid], expected=127, env=missing_tools)
        assert native_output.read_bytes() == retained
        fake_tools = work / "failed-tools"
        fake_tools.mkdir(exist_ok=True)
        failed_objcopy = fake_tools / "objcopy"
        failed_objcopy.write_text(f"#!{sys.executable}\nraise SystemExit(23)\n")
        failed_objcopy.chmod(0o755)
        failed_environment = os.environ.copy()
        failed_environment["PATH"] = str(fake_tools) + os.pathsep + os.environ["PATH"]
        command(
            [compiler, "--object", "-o", native_output, valid], expected=23, env=failed_environment
        )
        assert native_output.read_bytes() == retained
        for destination in ("/dev/null", "/dev/full", link):
            before = Path(destination).lstat()
            command([compiler, "--object", "-o", destination, valid], expected=1)
            after = Path(destination).lstat()
            assert (before.st_mode, before.st_dev, before.st_ino) == (
                after.st_mode,
                after.st_dev,
                after.st_ino,
            )
        assert link.is_symlink() and target.read_bytes() == expected_c
        spaced_source = work / "source with spaces.crs"
        spaced_source.write_bytes(valid.read_bytes())
        spaced_executable = work / "output with spaces"
        command([compiler, "-o", spaced_executable, *c_options, *c_link_options, spaced_source])
        command([spaced_executable])
        for prefix in ("-", "@"):
            name = prefix + "relative-output"
            command([compiler, "-o", name, *c_options, *c_link_options, valid], cwd=work)
            command([work / name])
        assert not list(
            work.glob(".crust-*")
        ), "driver left temporary files after a completed command"

        check_c_runtime(command, compiler, work, cc)
        library_source, library_object = work / "library.crs", work / "library.o"
        library_source.write_text("fn answer()->i32{return 42i32;}")
        command(
            [
                compiler,
                "--library",
                "--object",
                "--export",
                "answer",
                "-o",
                library_object,
                *c_options,
                library_source,
            ]
        )
        library_main = work / "library-main.c"
        library_main.write_text(
            "#include <stdint.h>\nextern int32_t answer(void);\n"
            "int main(void){return answer();}\n"
        )
        command(
            [
                *cc,
                *STRICT,
                "-no-pie",
                library_object,
                library_main,
                *ldflags,
                "-o",
                work / "library-main",
            ]
        )
        command([work / "library-main"], expected=42)

        stage_sources = [
            "api/crust0.crs",
            "api/crust0_host.crs",
            "api/crust0_stage.crs",
            *[
                f"stages/c/{name}.crs"
                for name in ("model", "base", "types", "emit", "driver", "program", "main")
            ],
        ]
        seed = build / "crust-c-seed"
        generations = [("seed", seed), ("current", compiler)]
        generated = []
        for name, stage_compiler in generations:
            c_path, response = work / f"self-{name}.c", work / f"self-{name}.rsp"
            command(
                [stage_compiler, "--emit-c", "-o", c_path, "--symbols", response, *stage_sources]
            )
            generated.append((c_path.read_bytes(), response.read_bytes()))
        assert (
            generated[0] == generated[1]
        ), "seed and self-compiled C stages emit different artifacts"
        stage_object = work / "self-backend.o"
        command([compiler, "--object", "-o", stage_object, *c_options, *stage_sources])
        references = command(["nm", "-u", stage_object]).stdout.decode()
        allowed_frontend = {
            "crust_context_init",
            "crust_context_destroy",
            "crust_read",
            "crust_read_range",
            "crust_collect",
            "crust_resolve",
            "crust_check",
            "crust_try_alloc",
            "crust_try_copy_string",
        }
        for name in re.findall(r"\bU\s+(\S+)", references):
            if name.startswith("crust_") and name not in allowed_frontend:
                raise AssertionError(f"C stage calls a forbidden native compiler helper: {name}")
        next_compiler = work / "crust-c-next"
        command(
            [
                *cc,
                "-no-pie",
                stage_object,
                build / "libcrust0.a",
                build / "libcrust0_host.a",
                *ldflags,
                "-o",
                next_compiler,
            ]
        )
        next_c, next_response = work / "self-next.c", work / "self-next.rsp"
        command(
            [next_compiler, "--emit-c", "-o", next_c, "--symbols", next_response, *stage_sources]
        )
        assert generated[1] == (
            next_c.read_bytes(),
            next_response.read_bytes(),
        ), "self-translation changed emitted artifacts"
        for stage_compiler in (seed, compiler, next_compiler):
            names = command(["nm", stage_compiler]).stdout
            assert not re.search(
                rb"\bcrust_x64_", names
            ), "C stage contains a native x64 backend dependency"
        next_object = work / "self-intrusive.o"
        command(
            [
                next_compiler,
                "--object",
                "-o",
                next_object,
                *c_options,
                "examples/intrusive/program.crs",
            ]
        )
        next_program = work / "self-intrusive"
        command(
            [*cc, "-no-pie", next_object, build / "libcrust0_host.a", *ldflags, "-o", next_program]
        )
        assert command([next_program]).stdout == b"intrusive: ok\n"
        print(
            "C stage: seed, self, and next generations emit identical C and exact-symbol response files"
        )
    print(f"integration ({args.backend}): {checks} process checks passed")


if __name__ == "__main__":
    main()
