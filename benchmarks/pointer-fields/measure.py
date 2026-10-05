#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Count seed tokens saved by pointer-field syntax in compiler stages."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STRICT = "-std=c99 -pedantic-errors -Wall -Wextra -Werror -Wstrict-prototypes -Wmissing-prototypes -Wshadow -Wvla".split()


def run(command):
    result = subprocess.run(list(map(str, command)), cwd=ROOT, capture_output=True, timeout=120)
    if result.returncode or result.stderr:
        raise RuntimeError(f"{command}: status {result.returncode}\n{result.stderr.decode()}")
    return result.stdout


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        parser.error("use a new output directory under build/")
    output.mkdir(parents=True)
    binary = output / "rewrite"
    command = [
        "gcc",
        *STRICT,
        "-O2",
        "-g",
        "-I.",
        "-Iinclude",
        "-Isrc",
        "benchmarks/pointer-fields/rewrite.c",
        "src/profile_linux_x64.c",
        "-o",
        binary,
    ]
    run(command)
    hashes = {
        str(path): digest(path)
        for path in [
            ROOT / "crust0_amalg.c",
            ROOT / "include/crust0.h",
            ROOT / "src/profile_linux_x64.c",
            ROOT / "benchmarks/pointer-fields/rewrite.c",
            Path(__file__),
            ROOT / "build/crust0",
        ]
    }
    rows = {}
    for source in sorted((ROOT / "stages").rglob("*.crs")):
        target = output / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows[str(source.relative_to(ROOT))] = json.loads(run([binary, source, target]))
        hashes[str(source)] = digest(source)
        check = json.loads(run([binary, target, output / "verify.crs"]))
        if check["tokens"] != rows[str(source.relative_to(ROOT))]["after"] or check["arrows"] != 0:
            raise RuntimeError(f"rewrite or token count differs: {source}")
    packages = {
        "c-stage": run(
            [
                "make",
                "-s",
                "--no-print-directory",
                "--eval",
                'pointer-inputs:;@printf "%s\\n" $(C_STAGE)',
                "pointer-inputs",
            ]
        )
        .decode()
        .splitlines(),
        "reader": [
            "api/crust0.crs",
            "api/crust0_host.crs",
            "stages/reader/model.crs",
            "stages/reader/lex.crs",
            "stages/reader/parse.crs",
        ],
    }
    checks = {}
    for name, sources in packages.items():
        hashes.update({str(ROOT / path): digest(ROOT / path) for path in sources})
        baseline = run(["build/crust0", "--library", "-S", *sources])
        rewritten = [
            output / path if path.startswith("stages/") else ROOT / path for path in sources
        ]
        candidate = run(["build/crust0", "--library", "-S", *rewritten])
        if candidate != baseline:
            raise RuntimeError(f"assembly differs after source rewrite: {name}")
        checks[name] = hashlib.sha256(candidate).hexdigest()
    if any(digest(Path(path)) != expected for path, expected in hashes.items()):
        raise RuntimeError("an input changed during measurement")
    for path in (Path(__file__), ROOT / "benchmarks/pointer-fields/rewrite.c"):
        shutil.copyfile(path, output / path.name)
    report = {
        "revision": run(["git", "rev-parse", "HEAD"]).decode().strip(),
        "command": list(map(str, command)),
        "hashes": hashes,
        "rows": rows,
        "identical_assembly": checks,
        "totals": {
            key: sum(row[key] for row in rows.values()) for key in ("tokens", "arrows", "after")
        },
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["totals"]))


if __name__ == "__main__":
    main()
