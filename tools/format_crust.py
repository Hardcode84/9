# SPDX-License-Identifier: Apache-2.0

"""Format repository Crust files with their selected source grammar."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SOURCE = ROOT / "examples/reader-switch/main.crs"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    paths = [Path(os.path.abspath(path)) for path in args.files]
    build = "build/windows" if os.name == "nt" else "build"
    profile = "windows_x64" if os.name == "nt" else "linux_x64"
    launcher = ROOT / build / ("crust.exe" if os.name == "nt" else "crust")
    try:
        subprocess.run(
            ["make", "--no-print-directory", "-s", f"BUILD={build}", f"PROFILE={profile}", "all"],
            cwd=ROOT,
            check=True,
        )
        mode = "--check" if args.check else "--write"
        ordinary = [str(path) for path in paths if path != TEXT_SOURCE]
        if ordinary:
            subprocess.run(
                [
                    launcher,
                    "stages/build/run.crs",
                    "stages/format/tool.crs",
                    mode,
                    "--",
                    *ordinary,
                ],
                cwd=ROOT,
                check=True,
            )
        if TEXT_SOURCE in paths:
            subprocess.run(
                [
                    launcher,
                    "examples/format/reader-switch.crs",
                    mode,
                    "--",
                    TEXT_SOURCE,
                ],
                cwd=ROOT,
                check=True,
            )
    except subprocess.CalledProcessError as error:
        return error.returncode
    except OSError as error:
        print(f"Crust formatter: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
