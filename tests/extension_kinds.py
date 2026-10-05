#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compose independent type extensions and execute their lowered program."""

import argparse
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build"))
    args = parser.parse_args()
    build = args.build.resolve()
    with tempfile.TemporaryDirectory(dir=build, prefix="extension-kinds-") as directory:
        target = Path(directory) / "target"
        for order in ("forward", "reverse"):
            subprocess.run(
                [str(build / "kind_composition"), str(target), order],
                check=True,
                timeout=60,
            )
            result = subprocess.run([str(target)], capture_output=True, check=True, timeout=10)
            if result.stdout != b"BA":
                raise SystemExit(
                    f"{order}: expected defer then resource cleanup, got {result.stdout!r}"
                )
    print("Extension kinds: independent readers, both allocation orders, and cleanup passed")


if __name__ == "__main__":
    main()
