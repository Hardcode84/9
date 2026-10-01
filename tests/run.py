#!/usr/bin/env python3
"""Compile, link, and execute the RMD0 semantic and native interface cases."""

import argparse
import os
from pathlib import Path
import random
import re
import resource
import shlex
import signal
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TYPES = {f"{sign}{bits}": (bits, sign == "i") for bits in (8, 16, 32, 64) for sign in "iu"}
TYPES.update({"isize": (64, True), "usize": (64, False)})
STRICT = ["-std=c99", "-pedantic-errors", "-Wall", "-Wextra", "-Werror",
          "-Wstrict-prototypes", "-Wmissing-prototypes", "-Wshadow", "-Wvla"]


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
    literal = lambda value: f"{value}{kind}"
    for a in values:
        for op, value in [("-", -a), ("~", ~a)]:
            cases.append((f"{op}({literal(a)})", literal(wrapped(value, bits, signed))))
        for b in [low, high, 1, rng.randint(low, high)]:
            for op, value in [("+", a + b), ("-", a - b), ("*", a * b),
                              ("&", a & b), ("|", a | b), ("^", a ^ b)]:
                cases.append((f"({literal(a)}) {op} ({literal(b)})", literal(wrapped(value, bits, signed))))
            for op, value in [("<", a < b), ("<=", a <= b), (">", a > b), (">=", a >= b),
                              ("==", a == b), ("!=", a != b)]:
                cases.append((f"({literal(a)}) {op} ({literal(b)})", str(value).lower()))
            if b != 0 and not (signed and a == low and b == -1):
                quotient = abs(a) // abs(b) * (-1 if (a < 0) != (b < 0) else 1)
                cases.append((f"({literal(a)}) / ({literal(b)})", literal(quotient)))
                cases.append((f"({literal(a)}) % ({literal(b)})", literal(a - quotient * b)))
        for shift in (0, 1, bits - 1):
            for op, value in [("<<", a << shift), (">>", a >> shift)]:
                cases.append((f"({literal(a)}) {op} {literal(shift)}", literal(wrapped(value, bits, signed))))
        for target, (width, sign) in TYPES.items():
            cases.append((f"({literal(a)}) as {target}", f"{wrapped(a, width, sign)}{target}"))
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--assembler", default="as --64")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    build = compiler.parent
    work = build / "tests"
    work.mkdir(exist_ok=True)
    cc = shlex.split(args.cc)
    assembler = shlex.split(args.assembler)
    ldflags = shlex.split(args.ldflags)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    checks = 0

    def command(argv, expected=0, **options):
        nonlocal checks
        result = subprocess.run([str(arg) for arg in argv], cwd=ROOT, capture_output=True, timeout=30, **options)
        checks += 1
        if result.returncode != expected:
            raise AssertionError(f"{shlex.join(map(str, argv))}: status {result.returncode}, expected {expected}\n"
                                 f"{result.stdout.decode(errors='replace')}\n{result.stderr.decode(errors='replace')}")
        return result

    def assemble(source):
        output = source.with_suffix(".s.o")
        command([*assembler, source, "-o", output])
        return output

    def executable(name, source=None, inputs=None, libraries=()):
        if source is not None:
            path = work / f"{name}.rmd"
            path.write_text(source)
            inputs = [path]
        assembly = work / f"{name}.s"
        output = work / name
        command([compiler, "-S", "-o", assembly, *inputs])
        command([*cc, "-no-pie", assemble(assembly), *libraries, build / "librmd0_host.a", *ldflags, "-o", output])
        return output

    native = work / "native.o"
    command([*cc, *STRICT, "-O2", "-c", "tests/native.c", "-o", native])
    command([executable("runtime", inputs=["tests/runtime.rmd"], libraries=[native])])
    intrusive = executable("intrusive", inputs=["examples/intrusive.rmd"])
    assert command([intrusive]).stdout == b"intrusive: ok\n"

    native_names = [".Lrmd_0_string_1", ".Lrmd_1_label_1", "line\nbreak", 'quote"back\\name',
                    "1", ".", "\x7fend"]
    native_source = work / "native-names.c"
    native_source.write_text("#include <stdint.h>\n" + "\n".join(
        f"int32_t native_{index}(void);\nint32_t native_{index}(void) {{return {index + 10};}}"
        for index in range(len(native_names))) + "\n")
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
    named_source = "\n".join(declarations) + "\nfn main(argc:i32,argv:**u8)->i32{" + "".join(calls) + "return 0i32;}\n"
    command([executable("native-names", named_source, libraries=[native_renamed])])

    specification = (ROOT / "docs" / "rmd0-spec.md").read_text()
    example_section = specification.split("## 13 Complete seed examples\n", 1)[1].split("\n## 14 ", 1)[0]
    examples = re.findall(r"^~~~text\n(.*?)^~~~\s*$", example_section, re.M | re.S)
    if len(examples) != 2:
        raise AssertionError(f"expected two complete specification examples, found {len(examples)}")
    assert command([executable("spec-list", examples[0])]).stdout == b"ok\n"
    example_main = "\nfn main(argc:i32,argv:**u8)->i32{if apply()!=18u32{return 1i32;}return 0i32;}\n"
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
    stack_outgoing = (f"fn sum({parameters})->i64{{return {total};}}\n"
                      f"fn main(argc:i32,argv:**u8)->i32{{if sum({arguments})!={expected_total}i64"
                      "{return 1i32;}return 0i32;}\n")
    command([executable("stack-outgoing", stack_outgoing)])
    stack_limit = executable("stack-limit", """
fn exhaust()->unit {var large:[u8;1048576]=uninit;}
fn main(argc:i32,argv:**u8)->i32 {exhaust();return 0i32;}
""")
    stack_environment = os.environ.copy()
    # This child must expose the native guard-page signal, including in sanitizer runs.
    stack_environment["ASAN_OPTIONS"] = ":".join(filter(None, [stack_environment.get("ASAN_OPTIONS"), "handle_segv=0"]))
    for program, expected_status in ((stack_arguments_executable, 0), (stack_limit, -signal.SIGSEGV)):
        command([program], expected=expected_status,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_STACK, (131072, 131072)),
                env=stack_environment)

    arithmetic_checks = 0
    for kind, (bits, signed) in TYPES.items():
        cases = integer_cases(kind, bits, signed)
        arithmetic_checks += len(cases)
        functions = []
        for start in range(0, len(cases), 200):
            function = f"case_{start}"
            body = [f"fn {function}() -> i32 {{"]
            for index, (expression, value) in enumerate(cases[start:start + 200], 1):
                body.append(f"if ({expression}) != ({value}) {{ return {index}i32; }}")
            body.append("return 0i32; }")
            functions.append((function, "\n".join(body)))
        main_body = "\n".join(f"var status_{index}:i32={name}(); if status_{index}!=0i32 {{return status_{index};}}"
                              for index, (name, _) in enumerate(functions))
        source = "\n".join(body for _, body in functions) + "\nfn main(argc:i32,argv:**u8)->i32{\n" + main_body + "\nreturn 0i32;}\n"
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
    print(f"required traps: {len(traps)} processes passed")

    for name, source in {
        "flat-depth": "fn f()->u32{return " + "+".join(["1u32"] * 10000) + ";}",
        "record-depth": "".join(f"record R{i}{{field:R{i + 1};}}" for i in range(2000)) + "record R2000{field:u8;}",
        "unknown-value": "fn f()->u32{return absent;}",
        "native-conflict": 'extern fn a()->u8="shared"; extern fn b()->u64="shared";',
        "wrong-entry": "fn main()->u32{return 0u32;}",
    }.items():
        path = work / f"reject-{name}.rmd"
        path.write_text(source)
        result = command([compiler, "--prepare", path], expected=1)
        if not result.stderr or b"error" not in result.stderr and b"entry" not in result.stderr:
            raise AssertionError(f"missing diagnostic for {name}: {result.stderr!r}")

    api_paths = [ROOT / "api" / f"{stem}.rmd" for stem in ("rmd0", "rmd0_host", "rmd0_x64")]
    probe = ['#include "rmd0.h"', '#include "rmd0_x64.h"', '#include <stdio.h>', 'int main(void) {']
    for path in api_paths:
        for record, body in re.findall(r"record (\w+) \{(.*?)\}", path.read_text(), re.S):
            for query, expression in [(f"sizeof({record})", f"sizeof({record})"),
                                      (f"alignof({record})", f"RMD_ALIGNOF({record})")]:
                probe.append(f'printf("if {query} != %zuusize {{return 1i32;}}\\n", {expression});')
            for field in re.findall(r"^    (\w+):", body, re.M):
                probe.append(f'printf("if offsetof({record},{field}) != %zuusize {{return 2i32;}}\\n", offsetof({record},{field}));')
    probe.append("return 0; }")
    probe_path = work / "layout.c"
    probe_path.write_text("\n".join(probe) + "\n")
    command([*cc, *STRICT, "-Iinclude", probe_path, "-o", work / "layout-probe"])
    layout_checks = command([work / "layout-probe"]).stdout.decode()
    layout_path = work / "layout.rmd"
    layout_path.write_text("fn main(argc:i32,argv:**u8)->i32{\n" + layout_checks + "return 0i32;}\n")
    command([executable("api-layout", inputs=[*api_paths, layout_path], libraries=[build / "librmd0.a"])])
    print(f"public layouts: {len(layout_checks.splitlines())} C/RMD0 comparisons passed")

    if (ROOT / "examples" / "stage.rmd").exists():
        stage = executable("stage", inputs=[*api_paths, "examples/stage.rmd"], libraries=[build / "librmd0.a"])
        custom_input = work / "answer.txt"
        custom_input.write_text("42\n")
        custom_assembly = work / "answer.s"
        command([stage, custom_input, custom_assembly])
        if "stage: add zero" not in custom_assembly.read_text():
            raise AssertionError("custom backend lowering did not run")
        custom_object = assemble(custom_assembly)
        command([*cc, *STRICT, "-no-pie", custom_object, "examples/answer_main.c",
                 *ldflags, "-o", work / "answer"])
        command([work / "answer"], expected=42)
        saved_registers = [("rbp", 0x3141592653589793), ("rbx", 0x2718281828459045),
                           ("r12", 0x123456789ABCDEF0), ("r13", 0xFEDCBA9876543210),
                           ("r14", 0x1122334455667788), ("r15", 0x8877665544332211)]
        register_probe = [".text", ".globl _start", ".type _start,@function", "_start:",
                          "\tandq $-16, %rsp"]
        register_probe += [f"\tmovabsq $0x{value:016x}, %{register}"
                           for register, value in saved_registers]
        register_probe += ["\txorl %edi, %edi", "\txorl %esi, %esi", "\tcall rmd_stage_answer",
                           "\tcmpl $42, %eax", "\tjne .Lregister_failure"]
        for register, value in saved_registers:
            register_probe += [f"\tmovabsq $0x{value:016x}, %r10", f"\tcmpq %r10, %{register}",
                               "\tjne .Lregister_failure"]
        register_probe += ["\txorl %edi, %edi", "\tjmp .Lregister_exit", ".Lregister_failure:",
                           "\tmovl $1, %edi", ".Lregister_exit:", "\tmovl $60, %eax", "\tsyscall",
                           '.section .note.GNU-stack,"",@progbits']
        register_source = work / "stage-registers.s"
        register_source.write_text("\n".join(register_probe) + "\n")
        register_executable = work / "stage-registers"
        command([*cc, "-nostdlib", "-no-pie", custom_object, assemble(register_source),
                 "-Wl,-e,_start", "-o", register_executable])
        command([register_executable])
        custom_input.write_text("not a number\n")
        command([stage, custom_input, custom_assembly], expected=1)
        custom_input.write_text("42\n")
        command([stage, custom_input, "/dev/full"], expected=1)
    else:
        raise AssertionError("missing ordinary RMD0 stage example")

    valid = work / "valid.rmd"
    invalid = work / "invalid.rmd"
    output = work / "atomic.s"
    valid.write_text("fn main(argc:i32,argv:**u8)->i32{return 0i32;}")
    invalid.write_bytes(b"fn\x00")
    output.write_text("retained output\n")
    command([compiler, "-o", output, invalid], expected=1)
    assert output.read_text() == "retained output\n"
    command([compiler, "-o", work / "absent-directory" / "output.s", valid], expected=1)
    command([compiler, "--check", work / "absent.rmd"], expected=1)
    for arguments in ([valid], ["--help"], ["--version"]):
        with open("/dev/full", "wb") as failed_output:
            result = subprocess.run([str(compiler), *map(str, arguments)], stdout=failed_output,
                                    stderr=subprocess.PIPE, timeout=30)
            checks += 1
            assert result.returncode == 1 and result.stderr, (arguments, result.returncode, result.stderr)
    for device, expected_status in (("/dev/null", 0), ("/dev/full", 1)):
        before = Path(device).stat()
        assert stat.S_ISCHR(before.st_mode)
        result = command([compiler, "-o", device, valid], expected=expected_status)
        after = Path(device).stat()
        assert stat.S_ISCHR(after.st_mode)
        assert (after.st_dev, after.st_ino, after.st_rdev) == (before.st_dev, before.st_ino, before.st_rdev)
        if expected_status != 0:
            assert result.stderr
    target = work / "symlink-target.s"
    link = work / "symlink-output.s"
    target.write_text("replace this output\n")
    link.unlink(missing_ok=True)
    link.symlink_to(target.name)
    command([compiler, "-o", output, valid])
    command([compiler, "-o", link, valid])
    assert link.is_symlink() and link.readlink() == Path(target.name)
    assert target.read_bytes() == output.read_bytes()
    print(f"integration: {checks} process checks passed")


if __name__ == "__main__":
    main()
