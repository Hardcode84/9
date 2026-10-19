#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise the native Windows seed, including cross-built executables under WSL."""

import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def native_path(path):
    path = Path(path).resolve()
    if os.name == "nt":
        return path.as_posix()
    return (
        subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip().replace("\\", "/")
    )


def literal(text):
    return json.dumps(str(text), ensure_ascii=False)


def execute(command):
    command = list(map(str, command))
    executable = Path(command[0])
    if executable.suffix == ".exe" and executable.name != "windows_limit.exe":
        limiter = executable.parent / "windows_limit.exe"
        command = [str(limiter), native_path(executable), *command[1:]]
    return subprocess.run(command, cwd=ROOT, capture_output=True, timeout=90)


def checked(command, expected=0):
    result = execute(command)
    if result.returncode != expected:
        raise AssertionError(
            f"{command}: {result.returncode}\n{result.stdout!r}\n{result.stderr!r}"
        )
    return result


def fixtures(build, cc):
    directory = build / "windows-tests"
    directory.mkdir(exist_ok=True)
    marker = '#include "crust0_abi.h"\nCRUST_ABI_EXPORT;\n'
    sources = {
        "bad": 'const char *const CRUST_ABI_crust0 = "wrong";\n',
        "missing": "int unrelated(void);\nint unrelated(void) { return 0; }\n",
        "forwarded": marker,
        "forwarded-marker": "int unrelated(void);\nint unrelated(void) { return 0; }\n",
    }
    for name, body in sources.items():
        source = directory / f"{name}.c"
        source.write_text("/* SPDX-License-Identifier: Apache-2.0 */\n" + body)
        inputs = [str(source)]
        if name.startswith("forwarded"):
            symbol = "seed_i8" if name == "forwarded" else "CRUST_ABI_crust0"
            definition = directory / f"{name}.def"
            definition.write_text(
                f"; SPDX-License-Identifier: Apache-2.0\nEXPORTS\n{symbol}=windows_library.{symbol}\n"
            )
            inputs.append(str(definition))
        checked(
            [
                *shlex.split(cc),
                *STRICT,
                "-shared",
                "-Wl,--export-all-symbols",
                f"-I{build / 'profile/include'}",
                *inputs,
                "-o",
                str(build / f"{name}.dll"),
            ]
        )
    return directory


def root_case(seed, directory, name, text, diagnostic=None, arguments=()):
    root = directory / f"{name}.crs"
    root.write_text("// SPDX-License-Identifier: Apache-2.0\n" + text, encoding="utf-8")
    result = execute([seed, native_path(root), *arguments])
    if diagnostic is None:
        assert result.returncode == 0, (name, result.returncode, result.stderr)
    else:
        assert result.returncode != 0 and diagnostic.encode() in result.stderr, (
            name,
            result.stderr,
        )
    return result


def library_checks(seed, build, directory):
    good = native_path(build / "windows_library.dll")
    calls = native_path(ROOT / "tests/windows_calls.crs")
    root_case(
        seed,
        directory,
        "calls",
        f"""
var library:*u8 = host_open(run,{literal(good)});
if library == null(*u8) {{ return 90i32; }};
if !host_import(run,library,{literal(calls)}) {{ return 91i32; }};
return test_calls();
""",
    )
    for name, diagnostic in [
        ("bad", "native API digest mismatch"),
        ("missing", "missing native API digest"),
        ("forwarded-marker", "missing native API digest"),
        ("absent", "cannot load native input"),
    ]:
        root_case(
            seed,
            directory,
            name,
            f"host_open(run,{literal(native_path(build / (name + '.dll')))});",
            diagnostic,
        )
    forwarded = native_path(build / "forwarded.dll")
    root_case(
        seed,
        directory,
        "forwarded-symbol",
        f"""
extern fn value(x:i8)->i8="seed_i8";
host_bind(run,host_open(run,{literal(forwarded)}),"value");
""",
        "library does not export",
    )
    root_case(
        seed,
        directory,
        "missing-symbol",
        f"""
extern fn value()->i32="absent";
host_bind(run,host_open(run,{literal(good)}),"value");
""",
        "library does not export",
    )
    root_case(
        seed,
        directory,
        "no-global-exports",
        f"""
host_open(run,{literal(good)});
extern fn value(x:i8)->i8="seed_i8";
return value(0i8) as i32;
""",
        "unresolved host symbol",
    )
    root_case(
        seed,
        directory,
        "bare-library",
        'crust_run_open(run,"windows_library.dll");',
        "directory separator",
    )
    root_case(
        seed,
        directory,
        "linux-api",
        f"host_source(run,{literal(native_path(ROOT / 'api/crust0_stage.crs'))});",
        "API digest",
    )


def path_checks(seed, directory):
    result = root_case(
        seed,
        directory,
        "binary-stream",
        r"""
return crust0_host_write_stream(1u32,"\n\r\n",3usize);
""",
    )
    assert result.stdout == b"\n\r\n", result.stdout
    unicode = directory / "space and café 日本"
    unicode.mkdir(exist_ok=True)
    (unicode / "input.bin").write_bytes(b"\x00\xff\r\n")
    root_case(
        seed,
        unicode,
        "root 日本",
        """
var input:*CrustSource=host_input(run,"input.bin",100u64);
if input == null(*CrustSource) { return 1i32; };
if input -> size != 4usize || input -> bytes[1usize] != 255u8 { return 2i32; };
if run -> argc != 1i32 { return 3i32; };
var output:*u8=host_path(run,run -> argv[0usize]);
return crust0_host_write_file(output,input -> bytes,input -> size);
""",
        arguments=("output café.bin",),
    )
    assert (unicode / "output café.bin").read_bytes() == b"\x00\xff\r\n"
    root_case(seed, directory, "drive-relative", 'host_path(run,"C:input");', "drive-relative")
    root_case(
        seed,
        directory,
        "unc-path",
        r"""
extern fn compare(a:*u8,b:*u8)->i32="strcmp";
var result:*u8=host_path(run,"\\\\server\\share\\file");
return compare(result,"//server/share/file");
""",
    )
    drive = native_path(directory)[:2]
    root_case(
        seed,
        directory,
        "rooted-path",
        f"""
extern fn compare(a:*u8,b:*u8)->i32="strcmp";
return compare(host_path(run,"/input"),{literal(drive + '/input')});
""",
    )
    checked([seed, native_path(unicode / "root 日本.crs").replace("/", "\\"), "output café.bin"])


def float_checks(seed, directory):
    # Both sides of the midpoint collapse to the same binary64 value.
    for index, (decimal, bits) in enumerate(
        [
            ("1.0000000596046447753906251", 0x3F800001),
            ("1.0000000596046447753906249", 0x3F800000),
            ("1.000000059604644775390625", 0x3F800000),
            ("1e-45", 1),
            ("1e-100", 0),
        ]
    ):
        root_case(
            seed,
            directory,
            f"float-{index}",
            f"""
var value:f32={decimal}f32;
if *(&value as *u32) != {bits}u32 {{ return 1i32; }};
return 0i32;
""",
        )
    root_case(seed, directory, "float-overflow", "var value:f32=1e100f32;", "f32")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    build = args.build.resolve()
    directory = fixtures(build, args.cc)
    seed = build / "crust.exe"
    checked(
        [
            build / "windows_seed.exe",
            native_path(build / "windows_library.dll"),
            native_path(directory / "host.bin"),
        ]
    )
    library_checks(seed, build, directory)
    path_checks(seed, directory)
    float_checks(seed, directory)
    reader = directory / "reader-switch.crs"
    text = (ROOT / "examples/reader-switch/main.crs").read_text()
    for ending in ("\n", "\r\n"):
        reader.write_bytes(text.replace("\n", ending).encode())
        result = checked([seed, native_path(reader)])
        assert result.stdout == (
            b"Hello from a reader written in CRUST!\nThese lines use the new grammar.\n"
        )
    assert not list(directory.glob("*.crust-*")), "output temporary leaked"
    # Windows refuses replacement while an image remains loaded in this process.
    # The C lifetime test runs many loads and destroys before returning.
    for name in ("bad", "missing", "forwarded", "forwarded-marker"):
        (build / f"{name}.dll").unlink()
    print("Windows seed: calls, callbacks, DLL rejection, paths, and cleanup passed")


if __name__ == "__main__":
    main()
