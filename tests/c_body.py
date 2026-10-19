# SPDX-License-Identifier: Apache-2.0

"""Check an external C body emitter and its failure contract."""

import argparse
import re
import shlex
import shutil
import tempfile
from pathlib import Path

from host import run
from prepare import link_library

ROOT = Path(__file__).resolve().parents[1]


def wasm_check(harness, work, clang):
    source = work / "wasm32.c"
    run([harness, "wasm32", ROOT / "tests/wasm32.crs", source], check=True, cwd=ROOT)
    script = work / "wasm32.mjs"
    script.write_text(
        "const {instance}=await WebAssembly.instantiate("
        "await Bun.file(process.argv[2]).arrayBuffer(),"
        "{env:{wasm_roundtrip:x=>x^0x55}});"
        "const status=instance.exports.wasm_probe();"
        "if(status!==0)throw new Error('wasm32 contract failed: '+status);\n"
    )
    for level in (0, 2):
        output = work / f"wasm32-O{level}.wasm"
        run(
            [
                clang,
                "--target=wasm32",
                "-ffreestanding",
                "-nostdlib",
                f"-O{level}",
                "-Werror",
                "-Wl,--no-entry",
                "-Wl,--export=wasm_probe",
                "-Wl,--allow-undefined",
                source,
                "-o",
                output,
            ],
            check=True,
        )
        run(["bun", script, output], check=True, timeout=10)
    print("wasm32: layouts, callbacks, pointer round trips, wrapping and imports passed at O0/O2")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cflags", default="-O2 -g")
    parser.add_argument("--ldflags", default="")
    parser.add_argument("--wasm-clang", type=Path)
    args = parser.parse_args()
    build = args.build.resolve()
    with tempfile.TemporaryDirectory(prefix="crust-c-body-", dir=build) as directory:
        work = Path(directory)
        harness = work / "harness"
        output = work / "program"
        library = work / "ordinary-backend.so"
        shutil.copyfile(build / "crust-c-library.so", library)
        linked = link_library(build, library, "c/package.crs")
        sources = [
            "api/crust0.crs",
            "api/crust0_host.crs",
            "api/crust0_stage.crs",
            "stages/c/model.crs",
            "stages/c/api.crs",
            "stages/c/extension.crs",
            "tests/c_body.crs",
            "tests/c_wasm.crs",
        ]
        run(
            [
                str(build / "crust-c"),
                "-o",
                str(harness),
                *sources,
                *("--cflag=" + flag for flag in shlex.split(args.cflags)),
                "--ldflag=" + str(linked),
                "--ldflag=" + str(build / "libcrust0.a"),
                "--ldflag=" + str(build / "libcrust0_host.a"),
                *("--ldflag=" + flag for flag in shlex.split(args.ldflags)),
            ],
            cwd=ROOT,
            check=True,
        )
        dag_output = work / "type-dag"
        statement_output = work / "statements"
        run(
            [str(harness), str(output), str(dag_output), str(statement_output)],
            cwd=ROOT,
            check=True,
            timeout=30,
        )
        run([str(dag_output)], cwd=ROOT, check=True, timeout=10)
        run([str(statement_output)], cwd=ROOT, check=True, timeout=10)
        if args.wasm_clang:
            wasm_check(harness, work, args.wasm_clang.resolve())
        result = run([str(output)], cwd=ROOT, check=False)
        if result.returncode != 42:
            raise RuntimeError(f"external body returned {result.returncode}, expected 42")
        symbols = run(["nm", "--defined-only", str(output)], check=True, capture_output=True).stdout
        if not re.search(rb"\bt r_g[0-9]+\b", symbols) or not re.search(
            rb"\br r_g[0-9]+\b", symbols
        ):
            raise RuntimeError(f"private function and constant symbols are missing: {symbols!r}")
        public = run(
            ["nm", "-g", "--defined-only", str(output)], check=True, capture_output=True
        ).stdout
        if re.search(rb"\br_g[0-9]+\b", public) or b"body_entry" not in public:
            raise RuntimeError(f"private symbols escaped native visibility: {public!r}")
    print(
        "C body extension: native results, non-block statements, shared type DAGs, private linkage, and failure paths passed"
    )


if __name__ == "__main__":
    main()
