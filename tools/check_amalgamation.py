#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check frontend linkage in split and amalgamated builds."""

import argparse
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from amalgamate import ROOT, SOURCES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--cflags", required=True)
    args = parser.parse_args()
    subprocess.run([sys.executable, "tools/amalgamate.py", "--check"], cwd=ROOT, check=True)
    header = (ROOT / "include/crust0.h").read_text()
    header = re.sub(r"/\*.*?\*/", "", header, flags=re.S)
    public = set(re.findall(r"\b(crust_\w+)\s*\(", header))
    # These helpers connect the core to separately compiled platform adapters.
    bridges = {"crust_profile_allocate", "crust_type_compare_reset", "crust_type_compare_seen"}
    builds = {"split": SOURCES, "amalgamated": ("crust0_amalg.c",)}
    with tempfile.TemporaryDirectory(prefix="crust-amalgamation-") as work:
        for mode, sources in builds.items():
            library = Path(work) / f"{mode}.so"
            subprocess.run(
                [
                    *shlex.split(args.cc),
                    *shlex.split(args.cflags),
                    "-fPIC",
                    "-shared",
                    "-Wl,--no-undefined",
                    "-Iinclude",
                    "-Isrc",
                    *sources,
                    "src/profile_linux_x64.c",
                    "-o",
                    str(library),
                ],
                cwd=ROOT,
                check=True,
            )
            symbols = subprocess.check_output(
                ["nm", "-D", "--defined-only", "--format=posix", str(library)], text=True
            )
            actual = {line.split()[0] for line in symbols.splitlines()}
            expected = public | bridges
            if mode == "split":
                expected = expected | {"crust_map_reserve"}
            if actual != expected:
                print(f"{mode}: missing symbols: {sorted(expected - actual)}")
                print(f"{mode}: unexpected symbols: {sorted(actual - expected)}")
                return 1
            print(f"{mode}: frontend exports match the public API and private bridges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
