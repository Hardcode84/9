#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail every allocation through checked clients and explicit trusted providers."""

import argparse
import tempfile
from pathlib import Path

from host import WINDOWS, host_sources, sanitizer_compiler, sanitizer_environment, sanitizer_flags
from host import run as host_run
from ownership import RUNTIME_TREE
from ownership_arrays import PROGRAM as ARRAYS
from ownership_leases import EMBEDDED, PROVIDER, embedded_client
from ownership_loops import LOOPS
from ownership_origins import RECORDS
from ownership_transfers import PROVIDER as TRANSFER_PROVIDER
from ownership_transfers import VALID as TRANSFER_CLIENT
from prepare import sources

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default=sanitizer_compiler())
    parser.add_argument("--amalgamation", type=int, choices=(0, 1), default=1)
    parser.add_argument("--sources", nargs="+")
    args = parser.parse_args()
    args.build = args.build.resolve()
    if args.sources is None:
        args.sources = [
            *sources(args.build, "ownership/package.crs"),
            ROOT / "tests/ownership_input.crs",
            ROOT / "tests/ownership_alloc.crs",
        ]
    environment = sanitizer_environment()

    def run(argv):
        result = host_run(
            [str(x) for x in argv],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode:
            raise RuntimeError(f"{argv}\n{result.stdout}{result.stderr}")
        return result.stdout

    with tempfile.TemporaryDirectory(prefix="ownership-alloc-", dir=args.build) as tmp:
        work = Path(tmp).resolve()
        generated = work / "stage.c"
        symbols = work / "stage.rsp"
        run(
            [
                args.build / "crust-c",
                "--library",
                "--emit",
                "--export",
                "ownership_alloc_verify",
                "--symbols",
                symbols,
                "-o",
                generated,
                *args.sources,
            ]
        )
        flags = ["-std=c99", "-pedantic-errors", *sanitizer_flags()]
        run([args.cc, *flags, "-c", generated, "-o", work / "input.o"])
        run(["objcopy", f"@{symbols}", work / "input.o", work / "stage.o"])
        run(
            [
                args.cc,
                *flags,
                "-Wall",
                "-Wextra",
                "-Werror",
                "-Wstrict-prototypes",
                "-Wmissing-prototypes",
                "-Wshadow",
                "-Wvla",
                "-Iinclude",
                "-Isrc",
                *([] if WINDOWS else ["-no-pie"]),
                *host_sources(args.amalgamation),
                "tests/ownership_alloc.c",
                work / "stage.o",
                "-Wl,--wrap=crust0_host_alloc",
                "-Wl,--wrap=crust0_host_free",
                *(["-lbcrypt"] if WINDOWS else []),
                "-o",
                work / "sweep",
            ]
        )
        arrays = work / "arrays.crs"
        arrays.write_text(ARRAYS)
        runtime_tree = work / "runtime-tree.crs"
        runtime_tree.write_text(RUNTIME_TREE)
        loops = work / "loops.crs"
        loops.write_text(LOOPS)
        origins = work / "origins.crs"
        origins.write_text(RECORDS)
        leases = work / "leases.crs"
        leases.write_text(embedded_client(EMBEDDED["nested"]))
        lease_provider = work / "lease-provider.crs"
        lease_provider.write_text(PROVIDER)
        transfers = work / "transfers.crs"
        transfers.write_text(TRANSFER_CLIENT)
        transfer_provider = work / "transfer-provider.crs"
        transfer_provider.write_text(TRANSFER_PROVIDER)
        for source, trusted in [
            (transfers, transfer_provider),
            (leases, lease_provider),
            (arrays, ""),
            (origins, ""),
            (loops, ""),
            ("examples/ownership-basics/origins.crs", ""),
            ("examples/ownership-basics/last-use.crs", ""),
            (runtime_tree, "examples/ownership-graphs/provider.crs"),
            ("examples/intrusive/program.crs", "examples/intrusive/links.crs"),
            ("examples/ownership-graphs/program.crs", "examples/ownership-graphs/provider.crs"),
            ("examples/ownership-index/program.crs", "examples/ownership-index/provider.crs"),
            ("examples/ownership-basics/handles.crs", ""),
            ("examples/ownership-basics/views.crs", ""),
            ("examples/ownership-basics/heap.crs", ""),
        ]:
            print(source, run([work / "sweep", source, trusted]).strip())


if __name__ == "__main__":
    main()
