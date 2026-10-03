#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail each arena backing allocation in plain and resource overload preparation."""

import argparse
import fnmatch
import os
import re
import resource
import shutil
import subprocess
import tempfile
from pathlib import Path

import overload
import overload_resources

ROOT = Path(__file__).resolve().parents[1]
STAGE = [
    "api/crust0.crs",
    "api/crust0_host.crs",
    "stages/c/model.crs",
    "stages/c/base.crs",
    *[f"stages/reader/{name}.crs" for name in ("model", "lex", "parse")],
    *[
        f"stages/resources/{name}.crs"
        for name in (
            "model",
            "base",
            "read",
            "types",
            "constants",
            "state",
            "cleanup",
            "drop",
            "places",
            "expr",
            "control",
        )
    ],
    *[
        f"stages/overload/{name}.crs"
        for name in ("model", "base", "types", "collect", "read", "resolve", "resources")
    ],
    "tests/overload_alloc.crs",
]


def cases():
    yield "plain-c-backend", "plain", [path.read_text() for path in overload.c_backend_sources()]
    yield "plain-format-provider", "plain", [overload.FORMAT_INTERFACE, overload.FORMAT_PROVIDER]
    yield "plain-format-consumer", "plain", [overload.FORMAT_INTERFACE, overload.FORMAT_CALLER]
    yield "plain-format-merged", "plain", [
        overload.FORMAT_PROVIDER,
        overload.FORMAT_INTERFACE,
        overload.FORMAT_CALLER,
    ]
    for name, source, _ in overload.runtime_cases():
        if name in {
            "long-nominal-type-keys",
            "scalar-types-and-native-width-aliases",
            "function-values-expected-contexts",
            "function-values-in-constant-and-field",
            "source-prototypes-coalesce",
            "arity",
        }:
            yield "plain-" + name, "plain", [source]
    for name, source, _ in overload_resources.runtime_cases():
        if name in {
            "move-defer-and-borrow-overloads",
            "overloaded-drop-selection",
            "typed-projection-callbacks",
            "matching-unsafe-prototype-and-definition",
        }:
            yield "resources-" + name, "resources", [source]
    interface = """
extern fn putchar(code:i32)->i32="putchar";
resource Token {id:i32;} drop cleanup;
fn cleanup(item:mut Token)->unit;
fn create(code:i32)->Token; fn create(code:u64)->Token;
fn consume(item:Token)->unit;
fn show(item:read Token)->unit; fn show(item:mut Token)->unit;
"""
    provider = """
fn cleanup(item:mut Token)->unit {unsafe {putchar(item.id);}}
fn create(code:i32)->Token {unsafe {return make Token {id:code};}}
fn create(code:u64)->Token {return create(code as i32);}
fn consume(item:Token)->unit {unsafe {putchar(33i32);}}
fn show(item:read Token)->unit {unsafe {putchar(item.id+32i32);}}
fn show(item:mut Token)->unit {unsafe {item.id=item.id+1i32;}}
"""
    consumer = overload_resources.program(
        "var first:Token=create(65i32); var second:Token=create(66u64); "
        "show(read first); show(mut second); var callback:fn(read Token)->unit=show; "
        "defer callback(read second); unsafe {putchar(88i32);} consume(create(68i32));",
        common=False,
    )
    yield "resources-provider", "resources", [interface, provider]
    yield "resources-consumer", "resources", [interface, consumer]
    yield "resources-merged", "resources", [provider, interface, consumer]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--amalgamation", type=int, choices=(0, 1), default=1)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--no-sanitize", action="store_true")
    parser.add_argument("--work", type=Path)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    selected = [
        item
        for item in cases()
        if not args.case or any(fnmatch.fnmatchcase(item[0], pattern) for pattern in args.case)
    ]
    if not selected:
        parser.error("no test cases selected")
    if args.list:
        for name, mode, _ in selected:
            print(f"{mode}: {name}")
        return 0
    compiler = args.build.resolve() / "crust-c"
    if not compiler.is_file():
        parser.error(f"compiler does not exist: {compiler}")
    work = (
        args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix="crust-overload-alloc-"))
    )
    work.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def run(command, timeout=120):
        result = subprocess.run(
            list(map(str, command)),
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError(
                f"command failed ({result.returncode}): {command}\n"
                f"{result.stdout.decode(errors='replace')}{result.stderr.decode(errors='replace')}"
            )
        return result

    completed = False
    try:
        generated = work / "fixture.c"
        response = work / "fixture.rsp"
        run([compiler, "--emit-c", "-o", generated, "--symbols", response, *STAGE])
        flags = ["-std=c99", "-pedantic-errors", "-g", "-O1", "-fno-omit-frame-pointer"]
        if not args.no_sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        run([args.cc, *flags, "-c", generated, "-o", work / "fixture.input.o"])
        run(["objcopy", f"@{response}", work / "fixture.input.o", work / "fixture.o"])
        strict = [
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wstrict-prototypes",
            "-Wmissing-prototypes",
            "-Wshadow",
            "-Wvla",
        ]
        executable = work / "fixture"
        run(
            [
                args.cc,
                *flags,
                *strict,
                "-Iinclude",
                "-Isrc",
                "-no-pie",
                work / "fixture.o",
                *(
                    ["crust0_amalg.c"]
                    if args.amalgamation
                    else ["src/core.c", "src/read.c", "src/check.c"]
                ),
                "src/profile_linux_x64.c",
                "runtime/host.c",
                "runtime/host_posix.c",
                "-o",
                executable,
            ]
        )
        totals = [0, 0, 0]
        for name, mode, sources in selected:
            inputs = []
            for index, source in enumerate(sources):
                path = work / f"{name}-{index}.crs"
                path.write_text(source)
                inputs.append(path)
            result = run([executable, mode, *inputs])
            match = re.fullmatch(
                rb"overload allocation: ([0-9]+) failure points checked "
                rb"\(read ([0-9]+), overload ([0-9]+), final ([0-9]+)\)\n",
                result.stdout,
            )
            if match is None or result.stderr:
                raise RuntimeError(
                    f"unexpected output for {name}: {result.stdout!r} {result.stderr!r}"
                )
            count = int(match.group(1))
            phases = [int(value) for value in match.groups()[1:]]
            if count == 0 or sum(phases) != count:
                raise RuntimeError(
                    f"invalid allocation failure counts for {name}: {result.stdout!r}"
                )
            totals = [old + new for old, new in zip(totals, phases, strict=False)]
            print(
                f"{name}: {count} arena failures "
                f"(read {phases[0]}, overload {phases[1]}, final {phases[2]})",
                flush=True,
            )
        if not args.case and min(totals) == 0:
            raise RuntimeError(f"full suite did not exercise every preparation phase: {totals}")
        print(
            f"Overload allocation suite: {len(selected)} inputs; {sum(totals)} arena failure points "
            f"(read {totals[0]}, overload {totals[1]}, final {totals[2]}); "
            f"{'native' if args.no_sanitize else 'ASan and UBSan'}"
        )
        completed = True
    finally:
        if completed and args.work is None:
            shutil.rmtree(work)
        else:
            print(f"Allocation test artifacts: {work}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
